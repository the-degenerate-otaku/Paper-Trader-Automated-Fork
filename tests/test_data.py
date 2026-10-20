from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import (
    CandleStore,
    ClosedCandleFeeder,
    CsvProvider,
    YFinanceProvider,
    adjusted,
    quality,
)
from paper_trader.market import Candle, CorporateAction, DataBatch
from paper_trader.storage import Database


def bar(minute: int = 15, day: int = 19, close: str = "101") -> Candle:
    opened = datetime.fromisoformat(f"2026-10-{day:02d}T09:{minute:02d}:00+05:30")
    return Candle(
        symbol="NIFTY50",
        timeframe="5m",
        opened_at=opened,
        closed_at=opened + timedelta(minutes=5),
        open=Decimal("100"),
        high=Decimal("103"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=1000,
        source="fixture",
    )


def batch(*candles: Candle, actions: tuple[CorporateAction, ...] = ()) -> DataBatch:
    return DataBatch(
        candles=candles,
        actions=actions,
        fetched_at=datetime.fromisoformat("2026-10-21T15:30:00+05:30"),
    )


def test_feeder_cannot_access_current_or_future_candle(
    settings: Settings, database: Database
) -> None:
    store = CandleStore(database, TradingCalendar.load(settings))
    a, b = bar(), bar(20)
    version = store.save(batch(a, b))
    clock = [a.closed_at - timedelta(microseconds=1)]
    feeder = ClosedCandleFeeder(store, version, "NIFTY50", "5m", lambda: clock[0])
    assert feeder.history() == ()
    with pytest.raises(ValueError, match="Lookahead"):
        feeder.history(a.closed_at)
    clock[0] = a.closed_at
    assert feeder.history() == (a,)
    clock[0] = b.closed_at
    assert feeder.history() == (a, b)
    assert feeder.history(a.closed_at) == (a,)


def test_data_revisions_preserve_prior_version(settings: Settings, database: Database) -> None:
    store = CandleStore(database, TradingCalendar.load(settings))
    first = store.save(batch(bar()))
    second = store.save(batch(bar(close="102")))
    at = datetime(2026, 10, 21, tzinfo=UTC)
    assert store.read(first, "NIFTY50", "5m", at)[0].close == 101
    assert store.read(second, "NIFTY50", "5m", at)[0].close == 102
    assert first != second


def test_duplicates_and_unclosed_data_rejected(settings: Settings, database: Database) -> None:
    store = CandleStore(database, TradingCalendar.load(settings))
    with pytest.raises(ValueError, match="Duplicate"):
        store.save(batch(bar(), bar()))
    with pytest.raises(ValueError, match="Unclosed"):
        store.save(DataBatch(candles=(bar(),), fetched_at=bar().opened_at))
    with pytest.raises(ValueError, match="Out-of-session"):
        store.save(batch(bar(day=20)))


def test_invalid_prices_and_naive_times_rejected() -> None:
    payload = bar().model_dump()
    for updates in (
        {"high": "90"},
        {"open": "NaN"},
        {"volume": -1},
        {"closed_at": datetime(2026, 10, 19)},
    ):
        with pytest.raises(ValidationError):
            Candle.model_validate({**payload, **updates})


def test_actions_are_exdate_and_knowledge_gated(settings: Settings, database: Database) -> None:
    calendar = TradingCalendar.load(settings)
    store = CandleStore(database, calendar)
    before = bar(day=16)
    ex = datetime.fromisoformat("2026-10-19T09:15:00+05:30")
    action = CorporateAction(
        symbol="NIFTY50",
        ex_date=ex.date(),
        kind="split",
        factor=Decimal(2),
        known_at=ex,
        source="fixture",
    )
    version = store.save(batch(before, actions=(action,)))
    assert store.actions(version, "NIFTY50", before.closed_at) == ()
    assert adjusted((before,), (action,), before.closed_at, calendar)[0].close == 101
    changed = adjusted((before,), store.actions(version, "NIFTY50", ex), ex, calendar)[0]
    assert changed.close == Decimal("50.5") and changed.volume == 2000
    provider_basis = before.model_copy(update={"price_basis": "provider_split_adjusted"})
    assert adjusted((provider_basis,), (action,), ex, calendar)[0].close == 101
    late = action.model_copy(update={"known_at": ex + timedelta(days=1)})
    assert adjusted((before,), (late,), ex, calendar)[0].close == 101


def test_dividend_and_bonus_adjustments(settings: Settings) -> None:
    calendar = TradingCalendar.load(settings)
    before = bar(day=16)
    now = datetime.fromisoformat("2026-10-19T10:00:00+05:30")
    dividend = CorporateAction(
        symbol="NIFTY50",
        ex_date=now.date(),
        kind="dividend",
        cash=Decimal(1),
        known_at=now,
        source="fixture",
    )
    result = adjusted((before,), (dividend,), now, calendar)[0]
    assert result.close == 100
    bonus = dividend.model_copy(update={"kind": "bonus", "factor": Decimal(2), "cash": Decimal(0)})
    assert adjusted((before,), (bonus,), now, calendar)[0].close == Decimal("50.5")


def test_gap_stale_and_zero_volume_detection(settings: Settings) -> None:
    calendar = TradingCalendar.load(settings)
    bars = (bar(), bar(25).model_copy(update={"volume": 0}))
    health = quality(bars, calendar, bars[-1].closed_at)
    assert health.status == "gaps" and len(health.gaps) == 1 and health.zero_volume_bars == 1
    assert quality(bars, calendar, bars[-1].closed_at + timedelta(hours=1)).status == "stale"


def test_csv_incremental_update_and_limits(
    settings: Settings, database: Database, tmp_path: Path
) -> None:
    path = tmp_path / "bars.csv"
    a, b = bar(), bar(20)
    header = "opened_at,closed_at,open,high,low,close,volume\n"

    def row(c: Candle) -> str:
        return f"{c.opened_at.isoformat()},{c.closed_at.isoformat()},100,103,99,{c.close},1000\n"

    path.write_text(header + row(a))
    calendar = TradingCalendar.load(settings)
    provider = CsvProvider(path, settings, calendar)
    store = CandleStore(database, calendar)
    end = b.closed_at + timedelta(minutes=5)
    first = store.update(provider, "NIFTY50", "5m", a.opened_at, end)
    path.write_text(header + row(a) + row(b))
    second = store.update(provider, "NIFTY50", "5m", a.opened_at, end)
    assert len(store.read(first, "NIFTY50", "5m", end)) == 1
    assert len(store.read(second, "NIFTY50", "5m", end)) == 2
    settings.data.max_import_bytes = 1
    with pytest.raises(ValueError, match="size"):
        provider.history("NIFTY50", "5m", a.opened_at, end)


def test_yfinance_contract_and_daily_session_normalization(settings: Settings) -> None:
    seen = {}

    class FakeTicker:
        def history(self, **kwargs: object) -> pd.DataFrame:
            seen.update(kwargs)
            return pd.DataFrame(
                {
                    "Open": [100],
                    "High": [103],
                    "Low": [99],
                    "Close": [101],
                    "Volume": [1000],
                    "Dividends": [1],
                    "Stock Splits": [0],
                },
                index=pd.DatetimeIndex(["2026-10-19"], tz="Asia/Kolkata"),
            )

    provider = YFinanceProvider(settings, TradingCalendar.load(settings), lambda _: FakeTicker())
    result = provider.history(
        "NIFTY50", "1d", datetime(2026, 10, 18, tzinfo=UTC), datetime(2026, 10, 21, tzinfo=UTC)
    )
    assert seen["auto_adjust"] is False and seen["back_adjust"] is False
    assert result.candles[0].closed_at.astimezone(provider.calendar.zone).hour == 15
    assert result.candles[0].price_basis == "provider_split_adjusted"
    assert result.actions[0].kind == "dividend"
