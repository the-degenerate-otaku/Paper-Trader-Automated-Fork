import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from paper_trader.arena import BotArena
from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import CandleStore
from paper_trader.demo import synthetic
from paper_trader.features import FeatureSnapshot
from paper_trader.storage import Database
from paper_trader.trading import Order, PendingOrder, RiskContext


def make_arena(settings: Settings, database: Database) -> BotArena:
    settings.data.warmup_bars = 20
    settings.arena.bots[1].strategy = "hold"
    calendar = TradingCalendar.load(settings)
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO instruments VALUES "
            "('DEMO', 'Synthetic', 'EQUITY', 'SYNTHETIC', NULL, 'EQ', "
            "1, '0.05', NULL, NULL, 'DEMO')"
        )
    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 2)
    version = CandleStore(database, calendar).save(batch)
    return BotArena(settings, calendar, database, batch.candles, {"DEMO": version})


def test_bankrolls_cannot_exceed_total_or_duplicate_ids(settings: Settings) -> None:
    content = settings.model_dump()
    content["arena"]["bots"][0]["bankroll_inr"] = Decimal(1000001)
    with pytest.raises(ValidationError):
        Settings.model_validate(content)
    content = settings.model_dump()
    content["arena"]["bots"][1]["id"] = content["arena"]["bots"][0]["id"]
    with pytest.raises(ValidationError):
        Settings.model_validate(content)


def test_scheduler_closed_clock_isolation_and_no_duplicate_tick(
    settings: Settings, database: Database
) -> None:
    arena = make_arena(settings, database)
    first = next(iter(arena.engines.values())).events[0]
    assert asyncio.run(arena.tick(first.closed_at - timedelta(seconds=1))) == 0
    assert asyncio.run(arena.tick(first.closed_at)) == 2
    assert asyncio.run(arena.tick(first.closed_at)) == 0
    engines = tuple(arena.engines.values())
    assert engines[0].account_id != engines[1].account_id
    assert all(e.exchange.portfolio.starting_capital == Decimal(500000) for e in engines)
    assert all(not e.exchange.orders for e in engines)
    assert all(Settings.model_validate_json(e.settings.model_dump_json()) for e in engines)
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM decisions WHERE bot_id IS NOT NULL"
            ).fetchone()[0]
            == 2
        )


def test_shadow_never_fills_and_stop_cancels_pending_entries(
    settings: Settings, database: Database
) -> None:
    arena = make_arena(settings, database)
    key = settings.arena.bots[0].id
    engine = arena.engines[key]
    asyncio.run(arena.configure(key, "shadow", True))
    assert engine.shadow and arena.gates[key].enabled

    async def replay():
        for _ in engine.events:
            await arena.tick(engine.events[-1].closed_at)

    asyncio.run(replay())
    assert not engine.exchange.portfolio.fills
    assert not engine.exchange.orders
    assert any(
        e.payload.get("direction") == "LONG" for e in engine.log if e.kind == "DecisionEvent"
    )
    order = Order(
        symbol="DEMO",
        side="BUY",
        product="MIS",
        quantity=1,
        signal_at=engine.events[-1].closed_at,
        stop_price=90,
    )
    engine.exchange.orders[order.id] = PendingOrder(order, RiskContext(), 1)
    with pytest.raises(ValueError):
        asyncio.run(arena.configure(key, "autopilot", True))
    asyncio.run(arena.configure(key, "shadow", False))
    assert engine.exchange.orders[order.id].status == "CANCELLED"
    assert not arena.gates[key].enabled


def test_future_duplicate_and_late_append_rejected(settings: Settings, database: Database) -> None:
    arena = make_arena(settings, database)
    first = next(iter(arena.engines.values())).events[0]
    with pytest.raises(ValueError, match="Future"):
        asyncio.run(arena.append_closed((first,), {}, first.closed_at - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="Duplicate"):
        asyncio.run(arena.append_closed((first, first), {}, first.closed_at))
    assert asyncio.run(arena.append_closed((first,), {}, first.closed_at)) == 0
    with pytest.raises(ValueError, match="Late historical"):
        asyncio.run(
            arena.append_closed(
                (first.model_copy(update={"symbol": "OTHER"}),), {}, first.closed_at
            )
        )


def test_live_stale_gate_holds_even_if_model_would_trade(
    settings: Settings, database: Database
) -> None:
    arena = make_arena(settings, database)
    key = settings.arena.bots[0].id
    gate, engine = arena.gates[key], arena.engines[key]
    gate.enabled, gate.mode = True, "autopilot"
    at = engine.events[0].closed_at
    gate.wall_clock = at + timedelta(seconds=settings.data.stale_after_seconds + 1)
    gate.max_age_seconds = settings.data.stale_after_seconds
    snapshot = FeatureSnapshot("DEMO", at, {"ema_9": 110.0, "ema_20": 100.0}, "TRENDING", "test")
    assert asyncio.run(gate.decide(snapshot, engine.exchange.portfolio)).reason == "FEED_STALE"
    gate.block_reason = "FEED_REFRESH_FAILED"
    assert (
        asyncio.run(gate.decide(snapshot, engine.exchange.portfolio)).reason
        == "FEED_REFRESH_FAILED"
    )
