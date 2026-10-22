from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import quality, session_bounds
from paper_trader.features import FeatureEngine, FeatureSnapshot
from paper_trader.market import Candle


def mis_history(bars: tuple[Candle, ...], settings: Settings, at: datetime) -> tuple[Candle, ...]:
    calendar = TradingCalendar.load(settings)
    result = []
    for bar in bars:
        if bar.timeframe != "1m":
            raise ValueError("Expected original one-minute input")
        day = bar.opened_at.astimezone(calendar.zone).date()
        bounds = session_bounds(calendar, day)
        special = next((s for s in calendar.calendar.special_sessions if s.date == day), None)
        cutoff = datetime.combine(day, (special or settings.session).mis_squareoff, calendar.zone)
        if bounds and bounds[0] <= bar.opened_at < bar.closed_at <= min(bounds[1], cutoff, at):
            result.append(bar)
    ordered = tuple(sorted(result, key=lambda bar: bar.opened_at))
    if len({bar.identity for bar in ordered}) != len(ordered):
        raise ValueError("Duplicate minute in timeframe history")
    if len({bar.symbol for bar in ordered}) > 1:
        raise ValueError("Mixed symbol timeframe history")
    return ordered


def aggregate_five(bars: tuple[Candle, ...], calendar: TradingCalendar) -> tuple[Candle, ...]:
    buckets: dict[datetime, list[Candle]] = defaultdict(list)
    if len({bar.identity for bar in bars}) != len(bars):
        raise ValueError("Duplicate minute in aggregation")
    if len({(bar.symbol, bar.price_basis) for bar in bars}) > 1:
        raise ValueError("Mixed symbol or price basis in aggregation")
    for bar in bars:
        if bar.timeframe != "1m" or bar.closed_at - bar.opened_at != timedelta(minutes=1):
            raise ValueError("Aggregation needs full one-minute candles")
        bounds = session_bounds(calendar, bar.opened_at.astimezone(calendar.zone).date())
        if bounds is None:
            raise ValueError("Unknown input session")
        if not bounds[0] <= bar.opened_at < bar.closed_at <= bounds[1]:
            raise ValueError("Aggregation input lies outside its session")
        offset = int((bar.opened_at - bounds[0]).total_seconds())
        opened = bounds[0] + timedelta(minutes=5 * (offset // 300))
        buckets[opened].append(bar)
    result = []
    for opened, group in sorted(buckets.items()):
        group.sort(key=lambda bar: bar.opened_at)
        if len(group) != 5 or any(
            bar.opened_at != opened + timedelta(minutes=index) for index, bar in enumerate(group)
        ):
            continue
        result.append(
            Candle(
                symbol=group[0].symbol,
                timeframe="5m",
                opened_at=opened,
                closed_at=group[-1].closed_at,
                open=group[0].open,
                high=max(bar.high for bar in group),
                low=min(bar.low for bar in group),
                close=group[-1].close,
                volume=sum(bar.volume for bar in group),
                source="research_5m_from_saved_1m",
                price_basis=group[0].price_basis,
            )
        )
    return tuple(result)


def paired_inputs(
    bars: tuple[Candle, ...], settings: Settings, at: datetime
) -> tuple[dict[str, FeatureSnapshot], dict[str, object]]:
    calendar = TradingCalendar.load(settings)
    minutes = mis_history(bars, settings, at)
    fives = aggregate_five(minutes, calendar)
    result = {}
    provenance: dict[str, object] = {}
    for name, series in (("1m", minutes), ("5m", fives)):
        if len(series) < settings.data.warmup_bars:
            raise ValueError(f"Insufficient {name} warmup")
        if series[-1].closed_at != at:
            raise ValueError(f"Unclosed or missing {name} signal candle")
        if quality(series[-settings.data.warmup_bars :], calendar, at).status != "healthy":
            raise ValueError(f"Unhealthy {name} history")
        visible = series[-settings.simulation.history_bars :]
        features = FeatureEngine(settings, calendar).calculate(
            visible, at, cash=settings.account.starting_capital_inr
        )
        result[name] = replace(features, state=f"Timeframe:{name}|{features.state}")
        provenance[name] = {
            "bars": len(visible),
            "first_open": visible[0].opened_at.isoformat(),
            "last_close": visible[-1].closed_at.isoformat(),
            "history_hash": hashlib.sha256(
                json.dumps(
                    [bar.model_dump(mode="json") for bar in visible], sort_keys=True
                ).encode()
            ).hexdigest(),
        }
    return result, provenance
