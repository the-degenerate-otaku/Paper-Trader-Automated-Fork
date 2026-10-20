import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from importlib.resources import files

import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import CandleStore
from paper_trader.demo import synthetic
from paper_trader.engine import EmaStrategy, HoldStrategy, ReplayEngine, metrics
from paper_trader.storage import Database
from paper_trader.trading import Portfolio


def prepared(settings: Settings, database: Database, strategy: str = "ema") -> ReplayEngine:
    settings.data.warmup_bars = 20
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO instruments VALUES "
            "('DEMO', 'Synthetic demo', 'EQUITY', 'SYNTHETIC', NULL, 'EQ', "
            "1, '0.05', NULL, NULL, 'DEMO')"
        )
    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 2)
    version = CandleStore(database, TradingCalendar.load(settings)).save(batch)
    return ReplayEngine(
        settings,
        TradingCalendar.load(settings),
        database,
        batch.candles,
        {"DEMO": version},
        EmaStrategy(settings) if strategy == "ema" else HoldStrategy(),
    )


def test_shared_loop_persists_full_decision_and_fill_history(
    settings: Settings, database: Database
) -> None:
    engine = prepared(settings, database)
    result = asyncio.run(engine.run())
    assert engine.cursor == 150
    assert engine.exchange.portfolio.fills
    assert result["open_positions"] == 0
    kinds = {e.kind for e in engine.log}
    assert {"MarketEvent", "FeatureEvent", "DecisionEvent", "OrderEvent", "FillEvent"}.issubset(
        kinds
    )
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM decisions WHERE run_id=?", (engine.run_id,)
            ).fetchone()[0]
            == 150
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM run_points WHERE run_id=?", (engine.run_id,)
            ).fetchone()[0]
            == 150
        )
        assert connection.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == len(
            engine.exchange.portfolio.fills
        )
    json.dumps(result, allow_nan=False)


def test_step_jump_and_hold_never_place_orders(settings: Settings, database: Database) -> None:
    engine = prepared(settings, database, "hold")
    asyncio.run(engine.step())
    assert engine.cursor == 1
    asyncio.run(engine.jump(engine.events[4].closed_at))
    assert engine.cursor == 5
    with pytest.raises(ValueError, match="Rewind"):
        asyncio.run(engine.jump(engine.events[0].closed_at))
    assert not engine.exchange.orders
    with pytest.raises(ValueError):
        asyncio.run(engine.play(float("inf")))


def test_same_seed_repeats_financial_results(settings: Settings, database: Database) -> None:
    first = asyncio.run(prepared(settings, database).run())
    second = asyncio.run(prepared(settings, database).run())
    assert first["metrics"] == second["metrics"]
    assert first["curve"] == second["curve"]


def test_metrics_include_starting_capital_and_undefined_values(settings: Settings) -> None:
    portfolio = Portfolio(Decimal(100))
    start = datetime.fromisoformat("2026-10-19T10:00:00+05:30")
    curve = [
        {"at": start.isoformat(), "equity": "90", "exposure": "0", "benchmarks": {}},
        {
            "at": (start + timedelta(days=1)).isoformat(),
            "equity": "80",
            "exposure": "0",
            "benchmarks": {},
        },
    ]
    result = metrics(curve, portfolio, settings)
    assert result["max_drawdown_pct"] == pytest.approx(20)
    assert result["closed_trade_count"] == 0
    assert result["win_rate_pct"] is None
    assert result["total_return_pct"] == pytest.approx(-20)


def test_every_packaged_migration_applies(database: Database) -> None:
    expected = sum(
        p.name.endswith(".sql") for p in files("paper_trader").joinpath("migrations").iterdir()
    )
    assert database.migrate() == expected
