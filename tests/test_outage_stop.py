import asyncio
from datetime import datetime

import httpx

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import CandleStore
from paper_trader.demo import synthetic
from paper_trader.engine import EmaStrategy, ReplayEngine
from paper_trader.inference import SystemOneStrategy
from paper_trader.storage import Database


def test_existing_stop_executes_during_inference_outage(
    settings: Settings, database: Database
) -> None:
    settings.data.warmup_bars = 20
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO instruments VALUES "
            "('DEMO', 'Synthetic', 'EQUITY', 'SYNTHETIC', NULL, 'EQ', "
            "1, '0.05', NULL, NULL, 'DEMO')"
        )
    calendar = TradingCalendar.load(settings)
    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 2)
    version = CandleStore(database, calendar).save(batch)
    engine = ReplayEngine(
        settings, calendar, database, batch.candles, {"DEMO": version}, EmaStrategy(settings)
    )

    async def enter_position():
        while engine.cursor < len(engine.events) and not engine.exchange.portfolio.positions:
            await engine.step()

    asyncio.run(enter_position())
    assert engine.exchange.portfolio.positions
    position = next(iter(engine.exchange.portfolio.positions.values()))
    candle = engine.events[engine.cursor]
    stressed = candle.model_copy(
        update={
            "low": min(candle.low, position.stop_price - settings.execution.tick_size),
            "high": max(candle.high, position.stop_price + settings.execution.tick_size),
        }
    )
    engine.events = (
        engine.events[: engine.cursor] + (stressed,) + engine.events[engine.cursor + 1 :]
    )

    def outage(request):
        raise httpx.ConnectError("test outage", request=request)

    engine.strategy = SystemOneStrategy(settings, httpx.MockTransport(outage))
    asyncio.run(engine.step())
    assert not engine.exchange.portfolio.positions
    assert "STOP" in str(engine.exchange.portfolio.closed_trades[-1]["reason"])
    assert any(
        event.payload.get("reason") == "INFERENCE_UNAVAILABLE_OR_INVALID" for event in engine.log
    )
