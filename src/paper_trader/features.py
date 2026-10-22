from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import numpy as np
import pandas as pd

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import session_bounds
from paper_trader.market import Candle, aware

FeatureValue = float | str | None


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    at: datetime
    values: dict[str, FeatureValue]
    regime: str
    state: str


def finite(value: object) -> float | None:
    try:
        number = float(str(value))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def closed_atr(candles: tuple[Candle, ...], period: int) -> Decimal:
    if period < 1 or len(candles) < period:
        return Decimal(0)
    alpha = Decimal(1) / period
    average = candles[0].high - candles[0].low
    for previous, current in zip(candles, candles[1:], strict=False):
        value = max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        average = alpha * value + (1 - alpha) * average
    return average


class FeatureEngine:
    def __init__(self, settings: Settings, calendar: TradingCalendar) -> None:
        self.settings = settings
        self.calendar = calendar

    def calculate(
        self,
        candles: tuple[Candle, ...],
        at: datetime,
        benchmark: tuple[Candle, ...] = (),
        bank_benchmark: tuple[Candle, ...] = (),
        sector_benchmark: tuple[Candle, ...] = (),
        vix: tuple[Candle, ...] = (),
        expiry_dates: tuple[date, ...] = (),
        position: str = "FLAT",
        cash: Decimal = Decimal(0),
    ) -> FeatureSnapshot:
        at = aware(at)
        for series in (candles, benchmark, bank_benchmark, sector_benchmark, vix):
            if any(c.closed_at > at for c in series):
                raise ValueError("Feature lookahead rejected")
            if any(a.closed_at > b.closed_at for a, b in pairwise(series)):
                raise ValueError("Feature input must be chronological")
        if not candles:
            raise ValueError("Feature engine requires closed candles")
        if len({(c.symbol, c.timeframe) for c in candles}) != 1:
            raise ValueError("Mixed instrument or timeframe in feature input")
        if len({c.identity for c in candles}) != len(candles):
            raise ValueError("Duplicate feature input")
        cfg = self.settings.features
        frame = pd.DataFrame(
            [
                {key: float(getattr(c, key)) for key in ("open", "high", "low", "close", "volume")}
                for c in candles
            ]
        )
        close = frame["close"]
        delta = close.diff()
        gains = (
            delta.clip(lower=0)
            .ewm(alpha=1 / cfg.rsi_period, adjust=False, min_periods=cfg.rsi_period)
            .mean()
        )
        losses = (
            (-delta.clip(upper=0))
            .ewm(alpha=1 / cfg.rsi_period, adjust=False, min_periods=cfg.rsi_period)
            .mean()
        )
        rsi = 100 - 100 / (1 + gains / losses.replace(0, np.nan))
        rsi = rsi.mask((losses == 0) & (gains > 0), 100).mask((losses == 0) & (gains == 0), 50)
        true_range = pd.concat(
            [
                frame.high - frame.low,
                (frame.high - close.shift()).abs(),
                (frame.low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = true_range.ewm(
            alpha=1 / cfg.atr_period, adjust=False, min_periods=cfg.atr_period
        ).mean()
        upward, downward = frame.high.diff(), -frame.low.diff()
        plus = upward.where((upward > downward) & (upward > 0), 0.0)
        minus = downward.where((downward > upward) & (downward > 0), 0.0)
        adx_atr = true_range.ewm(
            alpha=1 / cfg.adx_period, adjust=False, min_periods=cfg.adx_period
        ).mean()
        plus_di = 100 * plus.ewm(alpha=1 / cfg.adx_period, adjust=False).mean() / adx_atr
        minus_di = 100 * minus.ewm(alpha=1 / cfg.adx_period, adjust=False).mean() / adx_atr
        denominator = (plus_di + minus_di).replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / denominator
        adx = dx.ewm(alpha=1 / cfg.adx_period, adjust=False, min_periods=cfg.adx_period).mean()
        fast = close.ewm(span=cfg.macd_fast, adjust=False, min_periods=cfg.macd_fast).mean()
        slow = close.ewm(span=cfg.macd_slow, adjust=False, min_periods=cfg.macd_slow).mean()
        macd = fast - slow
        signal = macd.ewm(span=cfg.macd_signal, adjust=False, min_periods=cfg.macd_signal).mean()
        center = close.rolling(cfg.bollinger_period).mean()
        width = close.rolling(cfg.bollinger_period).std(ddof=0) * cfg.bollinger_std
        days = pd.Series([c.opened_at.astimezone(self.calendar.zone).date() for c in candles])
        typical = (frame.high + frame.low + close) / 3
        cumulative_volume = frame.volume.groupby(days).cumsum()
        vwap = (typical * frame.volume).groupby(days).cumsum() / cumulative_volume.replace(
            0, np.nan
        )
        volume_mean = frame.volume.shift(1).rolling(cfg.volume_period).mean()
        values: dict[str, FeatureValue] = {
            "ltp": float(close.iloc[-1]),
            "rsi": finite(rsi.iloc[-1]),
            "sma": finite(close.rolling(cfg.sma_period).mean().iloc[-1]),
            "atr": finite(atr.iloc[-1]),
            "atr_pct": finite(100 * atr.iloc[-1] / close.iloc[-1]),
            "adx": finite(adx.iloc[-1]),
            "macd": finite(macd.iloc[-1]),
            "macd_signal": finite(signal.iloc[-1]),
            "macd_hist": finite((macd - signal).iloc[-1]),
            "bb_mid": finite(center.iloc[-1]),
            "bb_high": finite((center + width).iloc[-1]),
            "bb_low": finite((center - width).iloc[-1]),
            "vwap": finite(vwap.iloc[-1]),
            "obv": finite((np.sign(delta.fillna(0)) * frame.volume).cumsum().iloc[-1]),
            "volume_ratio": finite(frame.volume.iloc[-1] / volume_mean.replace(0, np.nan).iloc[-1]),
            "realized_volatility": finite(
                pd.Series(np.log(close / close.shift()), index=close.index)
                .rolling(cfg.volatility_period)
                .std(ddof=0)
                .iloc[-1]
                * 100
            ),
        }
        for period in cfg.ema_periods:
            values[f"ema_{period}"] = finite(
                close.ewm(span=period, adjust=False, min_periods=period).mean().iloc[-1]
            )
        for period in cfg.return_periods:
            values[f"return_{period}"] = finite((close / close.shift(period) - 1).iloc[-1] * 100)
        today = candles[-1].opened_at.astimezone(self.calendar.zone).date()
        prior = [c for c in candles if c.opened_at.astimezone(self.calendar.zone).date() < today]
        previous_day = prior[-1].opened_at.astimezone(self.calendar.zone).date() if prior else None
        previous = [
            c for c in prior if c.opened_at.astimezone(self.calendar.zone).date() == previous_day
        ]
        for key in (
            "previous_high",
            "previous_low",
            "previous_close",
            "gap_pct",
            "pivot",
            "r1",
            "s1",
        ):
            values[key] = None
        if previous:
            high, low, prev_close = (
                max(c.high for c in previous),
                min(c.low for c in previous),
                previous[-1].close,
            )
            pivot = (high + low + prev_close) / 3
            first_today = next(
                c for c in candles if c.opened_at.astimezone(self.calendar.zone).date() == today
            )
            values.update(
                previous_high=float(high),
                previous_low=float(low),
                previous_close=float(prev_close),
                gap_pct=float((first_today.open / prev_close - 1) * 100),
                pivot=float(pivot),
                r1=float(2 * pivot - low),
                s1=float(2 * pivot - high),
            )
        bounds = session_bounds(self.calendar, today)
        values.update(opening_range_high=None, opening_range_low=None, time_bucket="UNKNOWN")
        if bounds:
            range_end = bounds[0] + timedelta(minutes=cfg.opening_range_minutes)
            opening_bars = [
                c for c in candles if bounds[0] <= c.opened_at and c.closed_at <= range_end
            ]
            complete_range = bool(
                opening_bars
                and opening_bars[0].opened_at == bounds[0]
                and opening_bars[-1].closed_at == range_end
                and all(
                    a.closed_at == b.opened_at
                    for a, b in zip(opening_bars, opening_bars[1:], strict=False)
                )
            )
            if at >= range_end and complete_range and candles[-1].timeframe != "1d":
                values.update(
                    opening_range_high=float(max(c.high for c in opening_bars)),
                    opening_range_low=float(min(c.low for c in opening_bars)),
                )
            bucket = (
                "OPEN"
                if at < bounds[0] + timedelta(minutes=cfg.open_bucket_minutes)
                else (
                    "LATE"
                    if at >= bounds[1] - timedelta(minutes=cfg.late_bucket_minutes)
                    else "MID"
                )
            )
            values["time_bucket"] = bucket
        rolling = [
            c
            for c in candles
            if c.opened_at.astimezone(self.calendar.zone).date()
            >= today - timedelta(days=cfg.high_low_days)
        ]
        values["high_52w_distance_pct"] = float(
            (candles[-1].close / max(c.high for c in rolling) - 1) * 100
        )
        values["low_52w_distance_pct"] = float(
            (candles[-1].close / min(c.low for c in rolling) - 1) * 100
        )
        values["high_low_coverage_days"] = float(
            (today - rolling[0].opened_at.astimezone(self.calendar.zone).date()).days
        )
        values["relative_strength_nifty"] = self.relative(candles, benchmark)
        values["relative_strength_bank"] = self.relative(candles, bank_benchmark)
        values["sector_relative_strength"] = self.relative(candles, sector_benchmark)
        values["vix"] = float(vix[-1].close) if vix else None
        values["vix_change_pct"] = (
            float((vix[-1].close / vix[-2].close - 1) * 100) if len(vix) > 1 else None
        )
        values["days_to_expiry"] = (
            float(min((d - today).days for d in expiry_dates if d >= today))
            if any(d >= today for d in expiry_dates)
            else None
        )
        values["index_trend"] = self.trend(benchmark)
        values["sector_trend"] = self.trend(sector_benchmark)
        values["supertrend"] = self.supertrend(frame, atr)
        atr_pct, adx_now = values["atr_pct"], values["adx"]
        regime = "WARMUP"
        if isinstance(atr_pct, float) and isinstance(adx_now, float):
            regime = (
                "HIGH_VOLATILITY"
                if atr_pct >= cfg.high_volatility_atr_pct
                else (
                    "CHOPPY"
                    if adx_now < cfg.trend_adx_min
                    else "TRENDING_UP"
                    if close.iloc[-1] >= slow.iloc[-1]
                    else "TRENDING_DOWN"
                )
            )
        state = self.state(candles[-1].symbol, values, regime, position, cash)
        return FeatureSnapshot(candles[-1].symbol, at, values, regime, state)

    @staticmethod
    def trend(candles: tuple[Candle, ...]) -> str | None:
        if len(candles) < 2:
            return None
        return (
            "UP"
            if candles[-1].close > candles[0].close
            else "DOWN"
            if candles[-1].close < candles[0].close
            else "FLAT"
        )

    @staticmethod
    def relative(candles: tuple[Candle, ...], benchmark: tuple[Candle, ...]) -> float | None:
        by_time = {c.closed_at: c for c in benchmark}
        common = [(c, by_time[c.closed_at]) for c in candles if c.closed_at in by_time]
        if len(common) < 2:
            return None
        return float(
            (
                (common[-1][0].close / common[0][0].close - 1)
                - (common[-1][1].close / common[0][1].close - 1)
            )
            * 100
        )

    def supertrend(self, frame: pd.DataFrame, atr: pd.Series[float]) -> float | None:
        previous_upper = previous_lower = previous_close = 0.0
        line = None
        bullish = True
        atr_values = atr.to_numpy(copy=False)
        for i, (high, low, close) in enumerate(
            zip(frame.high, frame.low, frame.close, strict=True)
        ):
            atr_value = float(atr_values[i])
            if not math.isfinite(atr_value):
                continue
            mid = (float(high) + float(low)) / 2
            spread = self.settings.features.supertrend_multiple * atr_value
            upper, lower = mid + spread, mid - spread
            if line is not None:
                upper = (
                    upper
                    if upper < previous_upper or previous_close > previous_upper
                    else previous_upper
                )
                lower = (
                    lower
                    if lower > previous_lower or previous_close < previous_lower
                    else previous_lower
                )
                bullish = (
                    float(close) >= previous_lower if bullish else float(close) > previous_upper
                )
            line = lower if bullish else upper
            previous_upper, previous_lower, previous_close = (
                upper,
                lower,
                float(close),
            )
        return line

    def state(
        self,
        symbol: str,
        values: dict[str, FeatureValue],
        regime: str,
        position: str,
        cash: Decimal,
    ) -> str:
        def number(key: str) -> str:
            value = values.get(key)
            return f"{value:.2f}" if isinstance(value, float) else "NA"

        state = (
            f"Asset:{symbol}|LTP:{number('ltp')}|Regime:{regime}|RSI:{number('rsi')}"
            f"|VWAP:{number('vwap')}|VolRatio:{number('volume_ratio')}|ATR%:{number('atr_pct')}"
            f"|RSNifty:{number('relative_strength_nifty')}|RSBank:{number('relative_strength_bank')}"
            f"|VIX:{number('vix')}|Time:{values['time_bucket']}|Position:{position}|CashINR:{cash:.2f}"
        )
        if len(state.encode()) > self.settings.features.state_max_bytes:
            raise ValueError("Compact state exceeds configured byte/token bound")
        return state
