from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import Field

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Section, Settings
from paper_trader.data import CandleStore, YFinanceProvider, quality
from paper_trader.features import FeatureEngine
from paper_trader.market import Timeframe
from paper_trader.storage import Database
from paper_trader.universe import UniverseService, UniverseUnavailable


class ChartRequest(Section):
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9&_.-]{0,39}$")
    timeframe: Timeframe = "5m"
    days: Literal[5, 30, 90, 365] = 5
    refresh: bool = False
    version: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def chart_data(settings: Settings, database: Database, request: ChartRequest) -> dict[str, object]:
    calendar = TradingCalendar.load(settings)
    store = CandleStore(database, calendar)
    now = datetime.now(UTC)
    start = now - timedelta(days=request.days)
    if request.symbol.endswith(".NS") or request.symbol == "DEMO":
        raise HTTPException(422, "Use an NSE symbol without a provider suffix; DEMO is replay-only")
    if request.timeframe != "1d" and request.days > 30:
        raise HTTPException(422, "Use daily candles for history longer than 30 days")
    if request.timeframe == "1m" and request.days != 5:
        raise HTTPException(422, "One-minute history is limited to five days")
    with database.connect() as connection:
        row = connection.execute(
            "SELECT b.version, b.fetched_at, b.warnings_json FROM data_batches b "
            "JOIN candle_versions c ON c.data_version=b.version "
            "WHERE c.symbol=? AND c.timeframe=? AND (? IS NULL OR b.version=?) "
            "GROUP BY b.version ORDER BY b.fetched_at DESC LIMIT 1",
            (request.symbol, request.timeframe, request.version, request.version),
        ).fetchone()
    if request.version and row is None:
        raise HTTPException(404, "No matching stored dataset")
    if request.version and request.refresh:
        raise HTTPException(422, "A pinned dataset cannot be refreshed")
    if request.refresh or row is None:
        bounded = settings.model_copy(deep=True)
        bounded.data.max_fetch_bars = min(settings.data.max_fetch_bars, 6000)
        try:
            batch = YFinanceProvider(bounded, calendar).history(
                request.symbol, request.timeframe, start, now
            )
        except Exception as exc:
            raise HTTPException(
                502, "Market history unavailable; no synthetic fallback used"
            ) from exc
        if not batch.candles:
            raise HTTPException(422, "Provider returned no closed session candles")
        with database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO instruments "
                "(symbol, name, instrument_type, lot_size, tick_size, provider_symbol) "
                "VALUES (?, ?, 'EQUITY', 1, ?, ?)",
                (
                    request.symbol,
                    request.symbol,
                    str(settings.execution.tick_size),
                    request.symbol + ".NS",
                ),
            )
        version = store.save(batch)
        fetched_at, warnings = batch.fetched_at.isoformat(), list(batch.warnings)
    else:
        version, fetched_at = row["version"], row["fetched_at"]
        warnings = json.loads(row["warnings_json"])
    candles = tuple(
        c
        for c in store.read(version, request.symbol, request.timeframe, now)
        if c.opened_at >= start
    )
    if not candles:
        raise HTTPException(422, "No stored candles in this date range; refresh history")
    if len(candles) > 1500:
        candles = candles[-1500:]
        warnings.append("CHART_CALCULATION_WINDOW_LIMITED_TO_1500_BARS")
    features = FeatureEngine(settings, calendar)
    indicators = []
    latest = None
    for index in range(max(0, len(candles) - 300), len(candles)):
        latest = features.calculate(candles[: index + 1], candles[index].closed_at)
        indicators.append(
            {"at": latest.at.isoformat(), "symbol": latest.symbol, "values": latest.values}
        )
    return {
        "symbol": request.symbol,
        "timeframe": request.timeframe,
        "version": version,
        "fetched_at": fetched_at,
        "as_of": now.isoformat(),
        "source": "stored history",
        "live": False,
        "warnings": warnings,
        "health": asdict(quality(candles, calendar, now)),
        "candles": [c.model_dump(mode="json") for c in candles[-300:]],
        "indicators": indicators,
        "feature": asdict(latest) if latest else None,
    }


def install_chart_routes(app: FastAPI, settings: Settings, database: Database) -> None:
    lock = asyncio.Lock()

    @app.get("/api/market/symbols")
    async def symbols() -> list[dict[str, object]]:
        with database.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT symbol, name, sector, instrument_type FROM instruments "
                    "WHERE symbol != 'DEMO' ORDER BY symbol LIMIT 2000"
                ).fetchall()
            ]

    @app.post("/api/market/universe")
    async def refresh_universe() -> dict[str, object]:
        if lock.locked():
            raise HTTPException(409, "A market data operation is already running")

        def refresh() -> dict[str, object]:
            results: dict[str, object] = {}
            with httpx.Client(trust_env=False, follow_redirects=False) as client:
                service = UniverseService(settings, database, client)
                for index in settings.universe.indices:
                    try:
                        snapshot = service.refresh(index)
                        results[index] = {
                            "count": len(snapshot.symbols),
                            "observed_at": snapshot.observed_at.isoformat(),
                            "stale": snapshot.stale,
                            "error": snapshot.error,
                        }
                    except UniverseUnavailable:
                        results[index] = {"error": "Official membership download unavailable"}
            return results

        async with lock:
            return await asyncio.to_thread(refresh)

    @app.post("/api/market/chart")
    async def chart(request: ChartRequest) -> dict[str, object]:
        if lock.locked():
            raise HTTPException(409, "A market data operation is already running")
        async with lock:
            return await asyncio.to_thread(chart_data, settings, database, request)
