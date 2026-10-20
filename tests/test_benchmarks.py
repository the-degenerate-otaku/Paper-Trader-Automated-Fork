import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import CandleStore
from paper_trader.demo import synthetic
from paper_trader.engine import ReplayEngine, Signal, metrics
from paper_trader.features import FeatureSnapshot
from paper_trader.storage import Database
from paper_trader.trading import Portfolio


def test_reference_closes_are_visible_before_equity_decisions_and_never_trade(
    settings: Settings, database: Database
) -> None:
    settings.data.warmup_bars = 1
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO instruments VALUES "
            "('DEMO', 'Synthetic', 'EQUITY', 'SYNTHETIC', NULL, 'EQ', "
            "1, '0.05', NULL, NULL, 'DEMO')"
        )
    calendar = TradingCalendar.load(settings)
    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 1)
    batch = batch.model_copy(update={"candles": batch.candles[:3]})
    benchmark = batch.model_copy(
        update={"candles": tuple(c.model_copy(update={"symbol": "NIFTY50"}) for c in batch.candles)}
    )
    store = CandleStore(database, calendar)
    versions = {"DEMO": store.save(batch), "NIFTY50": store.save(benchmark)}

    class Probe:
        async def decide(self, snapshot: FeatureSnapshot, portfolio: Portfolio) -> Signal:
            assert snapshot.symbol == "DEMO"
            assert engine.history["NIFTY50"][-1].closed_at == snapshot.at
            return Signal("HOLD", "PROBE")

    engine = ReplayEngine(
        settings, calendar, database, batch.candles + benchmark.candles, versions, Probe()
    )
    assert engine.events[0].symbol == "NIFTY50"
    asyncio.run(engine.run())
    assert not engine.exchange.orders
    assert any(
        e.payload.get("reason") == "REFERENCE_ONLY" for e in engine.log if e.symbol == "NIFTY50"
    )


def test_same_clock_cross_section_does_not_inflate_drawdown_duration(settings: Settings) -> None:
    start = datetime.fromisoformat("2026-09-01T10:00:00+05:30")
    curve = [
        {"at": start.isoformat(), "equity": "90", "exposure": "0"},
        {"at": start.isoformat(), "equity": "95", "exposure": "0"},
        {"at": (start + timedelta(days=1)).isoformat(), "equity": "80", "exposure": "0"},
    ]
    assert metrics(curve, Portfolio(Decimal(100)), settings)["drawdown_duration_bars"] == 2
