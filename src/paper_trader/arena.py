from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from paper_trader.calendar import TradingCalendar
from paper_trader.config import BotSpec, Settings
from paper_trader.data import CandleStore, YFinanceProvider
from paper_trader.engine import EmaStrategy, HoldStrategy, ReplayEngine, Signal, Strategy
from paper_trader.features import FeatureSnapshot
from paper_trader.inference import SystemOneStrategy
from paper_trader.market import Candle, aware
from paper_trader.storage import Database
from paper_trader.trading import Portfolio

Mode = Literal["manual", "copilot", "autopilot", "shadow"]


class EntryGate:
    def __init__(self, delegate: Strategy, mode: Mode) -> None:
        self.delegate, self.mode = delegate, mode
        self.enabled = False
        self.wall_clock: datetime | None = None
        self.max_age_seconds: int | None = None
        self.block_reason: str | None = None

    async def decide(self, snapshot: FeatureSnapshot, portfolio: Portfolio) -> Signal:
        if not self.enabled or self.mode == "manual":
            return Signal("HOLD", "BOT_ENTRIES_DISABLED")
        if self.block_reason:
            return Signal("HOLD", self.block_reason)
        if (
            self.wall_clock
            and self.max_age_seconds is not None
            and (self.wall_clock - snapshot.at).total_seconds() > self.max_age_seconds
        ):
            return Signal("HOLD", "FEED_STALE")
        return await self.delegate.decide(snapshot, portfolio)


class BotArena:
    def __init__(
        self,
        settings: Settings,
        calendar: TradingCalendar,
        database: Database,
        candles: tuple[Candle, ...],
        versions: dict[str, str],
    ) -> None:
        self.settings, self.database = settings, database
        self.id = uuid4().hex
        self.engines: dict[str, ReplayEngine] = {}
        self.gates: dict[str, EntryGate] = {}
        self.specs: dict[str, BotSpec] = {}
        self.running = False
        self.feed_error: str | None = None
        self.last_refresh = -float("inf")
        self.calendar = calendar
        self.lock = asyncio.Lock()
        for spec in settings.arena.bots:
            config = settings.model_copy(deep=True)
            config.account.starting_capital_inr = spec.bankroll_inr
            config.simulation.strategy = spec.strategy
            config.arena.bots = []
            if spec.min_direction_prob is not None:
                config.system_one.min_direction_prob = spec.min_direction_prob
            if spec.risk_per_trade_pct is not None:
                config.risk.risk_per_trade_pct = spec.risk_per_trade_pct
            strategy: Strategy = (
                SystemOneStrategy(config)
                if spec.strategy == "systemone"
                else EmaStrategy(config)
                if spec.strategy == "ema"
                else HoldStrategy()
            )
            gate = EntryGate(strategy, spec.mode)
            identifier = f"{self.id}:{spec.id}"
            engine = ReplayEngine(
                config,
                calendar,
                database,
                candles,
                versions,
                gate,
                shadow=spec.mode in {"copilot", "shadow"},
                bot_id=identifier,
            )
            with database.connect() as connection:
                connection.execute(
                    "INSERT INTO bots VALUES (?, ?, ?, ?, 0)",
                    (identifier, spec.name, engine.account_id, spec.mode),
                )
                connection.execute(
                    "INSERT INTO bot_configs (bot_id, config_json, created_at) VALUES (?, ?, ?)",
                    (identifier, spec.model_dump_json(), datetime.now(UTC).isoformat()),
                )
            self.engines[spec.id], self.gates[spec.id], self.specs[spec.id] = engine, gate, spec

    async def configure(self, key: str, mode: Mode, enabled: bool) -> None:
        async with self.lock:
            engine, gate = self.engines[key], self.gates[key]
            pending = [
                p for p in engine.exchange.orders.values() if p.status in {"OPEN", "PARTIAL"}
            ]
            if (engine.exchange.portfolio.positions or pending) and mode != gate.mode:
                raise ValueError("Close positions before changing bot mode")
            if not enabled:
                with self.database.connect() as connection:
                    for item in pending:
                        if not item.order.reduce_only:
                            item.status = "CANCELLED"
                            connection.execute(
                                "UPDATE orders SET status='CANCELLED' WHERE id=?", (item.order.id,)
                            )
            gate.mode, gate.enabled = mode, enabled
            engine.shadow = mode in {"copilot", "shadow"}
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE bots SET mode=?, enabled=? WHERE id=?",
                    (mode, int(enabled), engine.bot_id),
                )

    async def tick(self, now: datetime) -> int:
        instant = aware(now)
        async with self.lock:
            advanced = 0
            for key, engine in self.engines.items():
                if (
                    engine.cursor < len(engine.events)
                    and engine.events[engine.cursor].closed_at <= instant
                ):
                    gate = self.gates[key]
                    gate.wall_clock = instant if self.settings.arena.live_refresh_enabled else None
                    gate.max_age_seconds = self.settings.data.stale_after_seconds
                    await engine.step()
                    advanced += 1
                    if (
                        engine.cursor == len(engine.events)
                        and not self.settings.arena.live_refresh_enabled
                    ):
                        engine.finish()
            return advanced

    async def append_closed(
        self, candles: tuple[Candle, ...], versions: dict[str, str], now: datetime
    ) -> int:
        instant = aware(now)
        if any(c.closed_at > instant for c in candles):
            raise ValueError("Future candle append rejected")
        if len({c.identity for c in candles}) != len(candles):
            raise ValueError("Duplicate appended candle")
        async with self.lock:
            added = 0
            for engine in self.engines.values():
                identities = {c.identity for c in engine.events}
                new = tuple(
                    sorted(
                        (c for c in candles if c.identity not in identities),
                        key=lambda c: (c.closed_at, c.symbol),
                    )
                )
                if len(new) + len(engine.events) > self.settings.data.max_fetch_bars:
                    raise ValueError("Live run reached configured data budget")
                if new and engine.events and new[0].closed_at < engine.events[-1].closed_at:
                    raise ValueError("Late historical append requires a new immutable replay")
                if not new:
                    continue
                engine.events += new
                added += len(new)
                engine.data_versions.update(versions)
                with self.database.connect() as connection:
                    connection.execute(
                        "UPDATE runs SET data_version=? WHERE id=?",
                        (json.dumps(engine.data_versions), engine.run_id),
                    )
            return added

    async def refresh(self, now: datetime) -> None:
        config = self.settings.arena
        store = CandleStore(self.database, self.calendar)
        provider = YFinanceProvider(self.settings, self.calendar)
        try:
            all_candles: list[Candle] = []
            versions = {}
            latest = max(
                (e.events[-1].closed_at for e in self.engines.values() if e.events), default=None
            )
            for symbol in config.live_symbols:
                version = await asyncio.to_thread(
                    store.update,
                    provider,
                    symbol,
                    config.live_timeframe,
                    now - timedelta(days=config.lookback_days),
                    now,
                )
                candles = store.read(version, symbol, config.live_timeframe, now)
                all_candles.extend(c for c in candles if latest is None or c.closed_at > latest)
                versions[f"{symbol}:{version}"] = version
            await self.append_closed(tuple(all_candles), versions, now)
            self.feed_error = None
        except (OSError, ValueError, sqlite3.Error):
            self.feed_error = "FEED_REFRESH_FAILED"
        for gate in self.gates.values():
            gate.block_reason = self.feed_error

    async def run(self) -> None:
        try:
            while self.running and (
                self.settings.arena.live_refresh_enabled
                or any(e.cursor < len(e.events) for e in self.engines.values())
            ):
                if (
                    self.settings.arena.live_refresh_enabled
                    and time.monotonic() - self.last_refresh >= self.settings.arena.refresh_seconds
                ):
                    await self.refresh(datetime.now(UTC))
                    self.last_refresh = time.monotonic()
                await self.tick(datetime.now(UTC))
                await asyncio.sleep(self.settings.arena.interval_seconds)
        finally:
            self.running = False

    def snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "id": key,
                "name": self.specs[key].name,
                "strategy": self.specs[key].strategy,
                "mode": self.gates[key].mode,
                "enabled": self.gates[key].enabled,
                "bankroll_inr": str(engine.exchange.portfolio.starting_capital),
                "equity": str(engine.exchange.portfolio.equity),
                "cash": str(engine.exchange.portfolio.cash),
                "exposure": str(engine.exchange.portfolio.exposure),
                "charges": str(engine.exchange.portfolio.total_charges),
                "positions": len(engine.exchange.portfolio.positions),
                "cursor": engine.cursor,
                "total": len(engine.events),
                "run_id": engine.run_id,
                "last_decision": next(
                    (e.payload for e in reversed(engine.log) if e.kind == "DecisionEvent"), None
                ),
            }
            for key, engine in self.engines.items()
        ]
