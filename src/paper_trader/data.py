from __future__ import annotations

import csv
import importlib
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

import pandas as pd

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.market import (
    Candle,
    CorporateAction,
    DataBatch,
    Timeframe,
    aware,
    duration,
    stamp,
)
from paper_trader.storage import Database


def session_bounds(calendar: TradingCalendar, day: date) -> tuple[datetime, datetime] | None:
    if not calendar.is_covered(day):
        return None
    special = next((s for s in calendar.calendar.special_sessions if s.date == day), None)
    if special is None and (
        day in calendar.calendar.holidays or day.weekday() not in calendar.settings.session.weekdays
    ):
        return None
    session = special or calendar.settings.session
    return (
        datetime.combine(day, session.open, calendar.zone),
        datetime.combine(day, session.close, calendar.zone),
    )


def in_session(candle: Candle, calendar: TradingCalendar) -> bool:
    day = candle.opened_at.astimezone(calendar.zone).date()
    bounds = session_bounds(calendar, day)
    return bool(bounds and bounds[0] <= candle.opened_at < candle.closed_at <= bounds[1])


class Provider(Protocol):
    def history(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> DataBatch: ...


class HistoryTicker(Protocol):
    def history(self, **kwargs: object) -> pd.DataFrame: ...


class CsvProvider:
    def __init__(self, path: Path, settings: Settings, calendar: TradingCalendar) -> None:
        self.path = path
        self.settings = settings
        self.calendar = calendar

    def history(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> DataBatch:
        start, end = aware(start), aware(end)
        if self.path.stat().st_size > self.settings.data.max_import_bytes:
            raise ValueError("CSV exceeds configured import size")
        candles = []
        warnings = []
        for row in csv.DictReader(io.StringIO(self.path.read_text(encoding="utf-8-sig"))):
            candle = Candle.model_validate(
                {**row, "symbol": symbol, "timeframe": timeframe, "source": "csv"}
            )
            if start <= candle.opened_at < end:
                if in_session(candle, self.calendar):
                    candles.append(candle)
                else:
                    warnings.append("OUTSIDE_SESSION")
            if len(candles) > self.settings.data.max_fetch_bars:
                raise ValueError("CSV exceeds configured bar limit")
        return DataBatch(
            candles=tuple(candles),
            fetched_at=datetime.now(UTC),
            warnings=tuple(sorted(set(warnings))),
        )


class YFinanceProvider:
    def __init__(
        self,
        settings: Settings,
        calendar: TradingCalendar,
        ticker_factory: Callable[[str], object] | None = None,
    ) -> None:
        self.settings = settings
        self.calendar = calendar
        self.factory = ticker_factory

    def history(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> DataBatch:
        start, end = aware(start), aware(end)
        if start >= end:
            raise ValueError("History start must precede end")
        yf = importlib.import_module("yfinance")
        yf.set_tz_cache_location(str(self.settings.storage.database_path.parent / "yfinance-cache"))
        mapped = self.settings.universe.indices.get(symbol)
        provider_symbol = mapped.provider_symbol if mapped else symbol + ".NS"
        ticker = cast(
            HistoryTicker,
            self.factory(provider_symbol) if self.factory else yf.Ticker(provider_symbol),
        )
        history = ticker.history
        frame = history(
            start=start,
            end=end,
            interval=timeframe,
            auto_adjust=False,
            back_adjust=False,
            actions=True,
            prepost=False,
            repair=False,
            raise_errors=True,
            timeout=self.settings.universe.timeout_seconds,
        )
        if len(frame) > self.settings.data.max_fetch_bars:
            raise ValueError("Provider exceeded configured bar limit")
        fetched = datetime.now(UTC)
        candles = []
        actions = []
        warnings = {"PROVIDER_SPLIT_ADJUSTED_HISTORY", "HISTORICAL_REVISION_NOT_POINT_IN_TIME"}
        for index, row in frame.iterrows():
            if not isinstance(index, pd.Timestamp):
                raise ValueError("Provider index is not a timestamp")
            opened = aware(index.to_pydatetime())
            day = opened.astimezone(self.calendar.zone).date()
            bounds = session_bounds(self.calendar, day)
            if not bounds:
                warnings.add("OUTSIDE_SESSION")
                continue
            if timeframe == "1d":
                opened, closed = bounds
            else:
                closed = min(opened + duration(timeframe), bounds[1])
            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                opened_at=opened,
                closed_at=closed,
                open=Decimal(str(row["Open"])),
                high=Decimal(str(row["High"])),
                low=Decimal(str(row["Low"])),
                close=Decimal(str(row["Close"])),
                volume=int(row["Volume"]),
                source="yfinance",
                price_basis="provider_split_adjusted",
            )
            if candle.closed_at > fetched:
                warnings.add("UNCLOSED_CANDLE")
                continue
            if in_session(candle, self.calendar) and start <= candle.opened_at < end:
                candles.append(candle)
            else:
                warnings.add("OUTSIDE_SESSION")
            split = Decimal(str(row.get("Stock Splits", 0)))
            cash = Decimal(str(row.get("Dividends", 0)))
            if split > 0:
                actions.append(
                    CorporateAction(
                        symbol=symbol,
                        ex_date=day,
                        kind="split",
                        factor=split,
                        known_at=fetched,
                        source="yfinance",
                    )
                )
            if cash > 0:
                actions.append(
                    CorporateAction(
                        symbol=symbol,
                        ex_date=day,
                        kind="dividend",
                        cash=cash,
                        known_at=fetched,
                        source="yfinance",
                    )
                )
        return DataBatch(
            candles=tuple(candles),
            actions=tuple(actions),
            fetched_at=fetched,
            warnings=tuple(sorted(warnings)),
        )


@dataclass(frozen=True)
class FeedHealth:
    status: str
    zero_volume_bars: int
    gaps: tuple[str, ...]
    latest_close: str | None
    age_seconds: float | None


def quality(candles: tuple[Candle, ...], calendar: TradingCalendar, now: datetime) -> FeedHealth:
    now = aware(now)
    visible = sorted((c for c in candles if c.closed_at <= now), key=lambda c: c.opened_at)
    gaps = []
    for previous, current in zip(visible, visible[1:], strict=False):
        day = previous.opened_at.astimezone(calendar.zone).date()
        next_day = current.opened_at.astimezone(calendar.zone).date()
        if day == next_day and current.opened_at > previous.closed_at:
            gaps.append(stamp(previous.closed_at))
    latest = visible[-1].closed_at if visible else None
    age = (now - latest).total_seconds() if latest else None
    stale = age is None or age > calendar.settings.data.stale_after_seconds
    status = "empty" if not visible else "stale" if stale else "gaps" if gaps else "healthy"
    return FeedHealth(
        status,
        sum(c.volume == 0 for c in visible),
        tuple(gaps),
        stamp(latest) if latest else None,
        age,
    )


class CandleStore:
    def __init__(self, database: Database, calendar: TradingCalendar) -> None:
        self.database = database
        self.calendar = calendar

    def save(self, batch: DataBatch) -> str:
        keys = [c.identity for c in batch.candles]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate candle identities in batch")
        if any(not in_session(c, self.calendar) for c in batch.candles):
            raise ValueError("Out-of-session candle cannot be stored")
        if any(c.closed_at > batch.fetched_at for c in batch.candles):
            raise ValueError("Unclosed candle cannot be persisted")
        version = batch.version
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO data_batches VALUES (?, ?, ?)",
                (version, stamp(batch.fetched_at), json.dumps(batch.warnings)),
            )
            for candle in batch.candles:
                connection.execute(
                    "INSERT OR IGNORE INTO candle_versions VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        version,
                        candle.symbol,
                        candle.timeframe,
                        stamp(candle.opened_at),
                        stamp(candle.closed_at),
                        candle.model_dump_json(),
                    ),
                )
                connection.execute(
                    "INSERT INTO candles (symbol, timeframe, opened_at, closed_at, "
                    "open, high, low, "
                    "close, volume, source, data_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(symbol, timeframe, opened_at) DO UPDATE SET "
                    "closed_at=excluded.closed_at, open=excluded.open, high=excluded.high, "
                    "low=excluded.low, close=excluded.close, volume=excluded.volume, "
                    "source=excluded.source, data_version=excluded.data_version",
                    (
                        candle.symbol,
                        candle.timeframe,
                        stamp(candle.opened_at),
                        stamp(candle.closed_at),
                        str(candle.open),
                        str(candle.high),
                        str(candle.low),
                        str(candle.close),
                        candle.volume,
                        candle.source,
                        version,
                    ),
                )
            for action in batch.actions:
                connection.execute(
                    "INSERT OR IGNORE INTO action_versions VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        version,
                        action.symbol,
                        str(action.ex_date),
                        stamp(action.known_at),
                        action.kind,
                        action.model_dump_json(),
                    ),
                )
        return version

    def read(
        self, version: str, symbol: str, timeframe: Timeframe, at: datetime
    ) -> tuple[Candle, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM candle_versions WHERE data_version=? AND symbol=? "
                "AND timeframe=? AND closed_at<=? ORDER BY opened_at",
                (version, symbol, timeframe, stamp(at)),
            ).fetchall()
        return tuple(Candle.model_validate_json(row[0]) for row in rows)

    def actions(self, version: str, symbol: str, at: datetime) -> tuple[CorporateAction, ...]:
        day = aware(at).astimezone(self.calendar.zone).date()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM action_versions WHERE data_version=? AND symbol=? "
                "AND ex_date<=? AND known_at<=? ORDER BY ex_date",
                (version, symbol, str(day), stamp(at)),
            ).fetchall()
        return tuple(CorporateAction.model_validate_json(row[0]) for row in rows)

    def incremental_start(self, symbol: str, timeframe: Timeframe, fallback: datetime) -> datetime:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT MAX(opened_at) FROM candles WHERE symbol=? AND timeframe=?",
                (symbol, timeframe),
            ).fetchone()[0]
        return datetime.fromisoformat(row) if row else aware(fallback)

    def update(
        self, provider: Provider, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> str:
        batch = provider.history(
            symbol,
            timeframe,
            max(aware(start), self.incremental_start(symbol, timeframe, start)),
            aware(end),
        )
        with self.database.connect() as connection:
            previous = connection.execute(
                "SELECT v.payload_json FROM candle_versions v JOIN candles c "
                "ON v.symbol=c.symbol AND v.timeframe=c.timeframe AND v.opened_at=c.opened_at "
                "AND v.data_version=c.data_version WHERE c.symbol=? AND c.timeframe=? "
                "AND c.closed_at<=? ORDER BY c.opened_at",
                (symbol, timeframe, stamp(end)),
            ).fetchall()
            previous_actions = connection.execute(
                "SELECT DISTINCT payload_json FROM action_versions WHERE symbol=?",
                (symbol,),
            ).fetchall()
        merged = {c.identity: c for c in (Candle.model_validate_json(row[0]) for row in previous)}
        merged.update({c.identity: c for c in batch.candles})
        actions: dict[tuple[date, str], CorporateAction] = {}
        for action in [
            CorporateAction.model_validate_json(row[0]) for row in previous_actions
        ] + list(batch.actions):
            key = (action.ex_date, action.kind)
            existing = actions.get(key)
            if existing is None or action.known_at < existing.known_at:
                actions[key] = action
        return self.save(
            batch.model_copy(
                update={
                    "candles": tuple(sorted(merged.values(), key=lambda c: c.opened_at)),
                    "actions": tuple(sorted(actions.values(), key=lambda a: (a.ex_date, a.kind))),
                }
            )
        )


def adjusted(
    candles: tuple[Candle, ...],
    actions: tuple[CorporateAction, ...],
    at: datetime,
    calendar: TradingCalendar,
) -> tuple[Candle, ...]:
    now = aware(at)
    result = []
    for candle in candles:
        if candle.closed_at > now:
            raise ValueError("Cannot adjust future candles")
        prices = {key: getattr(candle, key) for key in ("open", "high", "low", "close")}
        volume = Decimal(candle.volume)
        candle_day = candle.opened_at.astimezone(calendar.zone).date()
        for action in sorted(actions, key=lambda a: a.ex_date):
            if action.symbol != candle.symbol or not (
                candle_day < action.ex_date <= now.astimezone(calendar.zone).date()
                and action.known_at <= now
            ):
                continue
            if action.kind in {"split", "bonus"} and candle.price_basis == "as_traded":
                prices = {key: value / action.factor for key, value in prices.items()}
                volume *= action.factor
            elif action.kind == "dividend":
                previous = max(
                    (
                        c
                        for c in candles
                        if c.symbol == candle.symbol
                        and c.opened_at.astimezone(calendar.zone).date() < action.ex_date
                    ),
                    key=lambda c: c.closed_at,
                    default=None,
                )
                if previous is None or action.cash >= previous.close:
                    raise ValueError("Dividend adjustment needs a valid previous close")
                factor = (previous.close - action.cash) / previous.close
                prices = {key: value * factor for key, value in prices.items()}
        result.append(candle.model_copy(update={**prices, "volume": int(volume)}))
    return tuple(result)


class ClosedCandleFeeder:
    def __init__(
        self,
        store: CandleStore,
        version: str,
        symbol: str,
        timeframe: Timeframe,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.version = version
        self.symbol = symbol
        self.timeframe = timeframe
        self.clock = clock

    def history(self, at: datetime | None = None) -> tuple[Candle, ...]:
        now = aware(self.clock())
        requested = aware(at) if at else now
        if requested > now:
            raise ValueError("Lookahead access rejected")
        return self.store.read(self.version, self.symbol, self.timeframe, requested)
