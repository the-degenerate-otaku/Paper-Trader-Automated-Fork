from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.features import FeatureSnapshot
from paper_trader.market import Candle
from paper_trader.scenario_lab import Movement, Probe, simulate
from paper_trader.timeframe_lab import aggregate_five, mis_history, paired_inputs
from paper_trader.trading import PaperExchange


def minute(at, index=0):
    price = Decimal(100) + Decimal(index) / 100
    return Candle(
        symbol="SAMPLE",
        timeframe="1m",
        opened_at=at,
        closed_at=at + timedelta(minutes=1),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price + Decimal("0.25"),
        volume=1000 + index,
        source="synthetic_timeframe_test",
    )


def history(settings):
    calendar = TradingCalendar.load(settings)
    return tuple(
        minute(datetime.combine(day, time(9, 15), calendar.zone) + timedelta(minutes=i), i)
        for day in (date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 21))
        for i in range(360)
    )


def test_five_minute_ohlcv_is_session_aligned_and_partial_buckets_are_omitted(settings):
    calendar = TradingCalendar.load(settings)
    bars = history(settings)[:8]
    result = aggregate_five(bars, calendar)
    assert len(result) == 1
    five = result[0]
    assert five.opened_at == bars[0].opened_at
    assert five.closed_at == bars[4].closed_at
    assert (five.open, five.high, five.low, five.close, five.volume) == (
        bars[0].open,
        max(b.high for b in bars[:5]),
        min(b.low for b in bars[:5]),
        bars[4].close,
        sum(b.volume for b in bars[:5]),
    )
    assert aggregate_five(bars[:2] + bars[3:5], calendar) == ()


def test_aggregation_rejects_duplicates_and_mixed_price_bases(settings):
    calendar = TradingCalendar.load(settings)
    bars = history(settings)[:5]
    with pytest.raises(ValueError, match="Duplicate"):
        aggregate_five(bars + (bars[0],), calendar)
    with pytest.raises(ValueError, match="price basis"):
        aggregate_five(
            bars[:4] + (bars[4].model_copy(update={"price_basis": "provider_split_adjusted"}),),
            calendar,
        )


def test_paired_indicators_have_full_warmup_and_cannot_see_future(settings):
    calendar = TradingCalendar.load(settings)
    bars = history(settings)
    at = datetime(2026, 10, 21, 14, tzinfo=calendar.zone)
    inputs, provenance = paired_inputs(bars, settings, at)
    assert provenance["5m"]["bars"] >= settings.data.warmup_bars
    assert inputs["1m"].values["ltp"] == inputs["5m"].values["ltp"]
    assert inputs["1m"].values["atr"] != inputs["5m"].values["atr"]
    changed = tuple(
        b.model_copy(update={"close": b.close * 2, "high": b.high * 2}) if b.closed_at > at else b
        for b in bars
    )
    assert paired_inputs(changed, settings, at) == (inputs, provenance)
    assert inputs["5m"].state.startswith("Timeframe:5m|")
    with pytest.raises(ValueError, match="5m warmup"):
        paired_inputs(bars, settings, at - timedelta(minutes=30))


def test_signal_bucket_must_be_closed_and_gaps_are_not_padded(settings):
    calendar = TradingCalendar.load(settings)
    at = datetime(2026, 10, 21, 14, tzinfo=calendar.zone)
    bars = history(settings)
    with pytest.raises(ValueError, match="missing 5m"):
        paired_inputs(bars, settings, at + timedelta(minutes=1))
    missing = tuple(b for b in bars if b.opened_at != at - timedelta(minutes=8))
    with pytest.raises(ValueError, match="Unhealthy"):
        paired_inputs(missing, settings, at)


def test_both_histories_exclude_post_squareoff_bars(settings):
    calendar = TradingCalendar.load(settings)
    at = datetime(2026, 10, 21, 15, 30, tzinfo=calendar.zone)
    bars = history(settings)
    late = minute(at - timedelta(minutes=5))
    result = mis_history(bars + (late,), settings, at)
    assert late not in result
    assert result[-1].closed_at.astimezone(calendar.zone).time() == settings.session.mis_squareoff


def test_twenty_five_minute_exit_waits_longer_but_stop_still_exits_early(settings, monkeypatch):
    calendar = TradingCalendar.load(settings)
    at = datetime(2026, 10, 21, 14, tzinfo=calendar.zone)
    reference = minute(at - timedelta(minutes=1)).model_copy(
        update={
            "open": Decimal(100),
            "high": Decimal(100),
            "low": Decimal(100),
            "close": Decimal(100),
        }
    )
    future = tuple(
        reference.model_copy(
            update={
                "opened_at": at + timedelta(minutes=i),
                "closed_at": at + timedelta(minutes=i + 1),
                "volume": 100000,
            }
        )
        for i in range(35)
    )
    probe = Probe(
        "test", "flat", 0, (reference,), future, Movement(name="flat", drift_bps=0, noise_bps=0)
    )
    features = FeatureSnapshot("SAMPLE", at, {"atr": 1.0, "ltp": 100.0}, "CHOPPY", "test")
    exchanges = []

    def factory(*args):
        exchange = PaperExchange(*args)
        exchanges.append(exchange)
        return exchange

    monkeypatch.setattr("paper_trader.scenario_lab.PaperExchange", factory)
    short = settings.model_copy(deep=True)
    short.auto_paper.max_hold_minutes = 5
    long = settings.model_copy(deep=True)
    long.auto_paper.max_hold_minutes = 25
    first = simulate(short, probe, features, "LONG")
    second = simulate(long, probe, features, "LONG")
    assert first["remaining"] == second["remaining"] == 0
    durations = [
        (e.portfolio.fills[-1].at - e.portfolio.fills[0].at).total_seconds() / 60 for e in exchanges
    ]
    assert durations[0] < durations[1]
    assert durations[1] >= 25
    stopped = future[3].model_copy(update={"low": Decimal(97), "close": Decimal(98)})
    stopped_probe = replace(probe, future=future[:3] + (stopped,) + future[4:])
    result = simulate(long, stopped_probe, features, "LONG")
    assert "STOP" in result["exit_reasons"]
    last = exchanges[-1].portfolio.fills
    assert (last[-1].at - last[0].at).total_seconds() < 25 * 60
