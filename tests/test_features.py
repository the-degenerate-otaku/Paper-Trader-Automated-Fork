import json
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import session_bounds
from paper_trader.features import FeatureEngine
from paper_trader.market import Candle


def series(settings: Settings, count: int = 220, flat: bool = False) -> tuple[Candle, ...]:
    calendar = TradingCalendar.load(settings)
    day = datetime.fromisoformat("2026-09-01T09:15:00+05:30").date()
    result = []
    while len(result) < count:
        bounds = session_bounds(calendar, day)
        if bounds:
            opened = bounds[0]
            while opened + timedelta(minutes=5) <= bounds[1] and len(result) < count:
                price = Decimal(100 if flat else 100 + len(result))
                result.append(
                    Candle(
                        symbol="NIFTY50",
                        timeframe="5m",
                        opened_at=opened,
                        closed_at=opened + timedelta(minutes=5),
                        open=price,
                        high=price + 1,
                        low=price - 1,
                        close=price,
                        volume=1000,
                        source="fixture",
                    )
                )
                opened += timedelta(minutes=5)
        day += timedelta(days=1)
    return tuple(result)


def test_indicators_and_state_are_finite_and_deterministic(settings: Settings) -> None:
    bars = series(settings)
    engine = FeatureEngine(settings, TradingCalendar.load(settings))
    snapshot = engine.calculate(bars, bars[-1].closed_at)
    expected = pd.Series([float(c.close) for c in bars]).ewm(span=20, adjust=False).mean().iloc[-1]
    assert snapshot.values["ema_20"] == pytest.approx(expected)
    assert snapshot.values["rsi"] == 100
    assert snapshot.values["volume_ratio"] == 1
    assert snapshot.values["obv"] == 219000
    assert snapshot.regime == "TRENDING_UP"
    assert snapshot.values["supertrend"] is not None
    assert len(snapshot.state.encode()) <= 380
    assert engine.calculate(bars, bars[-1].closed_at) == snapshot
    json.dumps(snapshot.values, allow_nan=False)


def test_future_data_and_context_are_rejected(settings: Settings) -> None:
    bars = series(settings, 40)
    engine = FeatureEngine(settings, TradingCalendar.load(settings))
    at = bars[-2].closed_at
    prefix = engine.calculate(bars[:-1], at)
    changed = bars[-1].model_copy(update={"close": Decimal(999999)})
    with pytest.raises(ValueError, match="lookahead"):
        engine.calculate((*bars[:-1], changed), at)
    with pytest.raises(ValueError, match="lookahead"):
        engine.calculate(bars[:-1], at, benchmark=bars)
    assert engine.calculate(bars[:-1], at) == prefix


def test_vwap_resets_each_session_and_opening_range_is_gated(settings: Settings) -> None:
    bars = series(settings, 80)
    engine = FeatureEngine(settings, TradingCalendar.load(settings))
    snapshot = engine.calculate(bars, bars[-1].closed_at)
    assert snapshot.values["vwap"] == pytest.approx(sum(float(c.close) for c in bars[75:]) / 5)
    early = engine.calculate(bars[:2], bars[1].closed_at)
    assert early.values["opening_range_high"] is None
    ready = engine.calculate(bars[:3], bars[2].closed_at)
    assert ready.values["opening_range_high"] == 103
    assert snapshot.values["previous_close"] == 174


def test_flat_and_warmup_values_are_explicit(settings: Settings) -> None:
    engine = FeatureEngine(settings, TradingCalendar.load(settings))
    bars = series(settings, 50, flat=True)
    assert engine.calculate(bars, bars[-1].closed_at).values["rsi"] == 50
    warmup = engine.calculate(bars[:1], bars[0].closed_at)
    assert warmup.regime == "WARMUP" and warmup.values["ema_200"] is None
    assert warmup.values["vix"] is None and warmup.values["days_to_expiry"] is None


def test_relative_strength_uses_matching_closed_timestamps(settings: Settings) -> None:
    bars = series(settings, 40)
    benchmark = tuple(
        c.model_copy(update={"symbol": "NIFTYBANK", "close": Decimal(100)}) for c in bars
    )
    snapshot = FeatureEngine(settings, TradingCalendar.load(settings)).calculate(
        bars, bars[-1].closed_at, benchmark=benchmark
    )
    assert snapshot.values["relative_strength_nifty"] == 39
