from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import session_bounds
from paper_trader.market import Candle, DataBatch, aware


def synthetic(
    settings: Settings, start: datetime, sessions: int, symbol: str = "DEMO"
) -> DataBatch:
    calendar = TradingCalendar.load(settings)
    day = aware(start).astimezone(calendar.zone).date()
    rng = np.random.default_rng(settings.simulation.random_seed)
    bars = []
    price = Decimal(100)
    completed = 0
    while completed < sessions:
        if not calendar.is_covered(day):
            raise ValueError("Synthetic demo falls outside verified calendar coverage")
        bounds = session_bounds(calendar, day)
        if bounds:
            opened = bounds[0]
            while opened + timedelta(minutes=5) <= bounds[1]:
                change = Decimal(str(float(rng.normal(0.015, 0.15))))
                close = max(Decimal(1), price + change)
                bars.append(
                    Candle(
                        symbol=symbol,
                        timeframe="5m",
                        opened_at=opened,
                        closed_at=opened + timedelta(minutes=5),
                        open=price,
                        high=max(price, close) + Decimal("0.2"),
                        low=max(Decimal("0.01"), min(price, close) - Decimal("0.2")),
                        close=close,
                        volume=1000000,
                        source="synthetic",
                    )
                )
                price = close
                opened += timedelta(minutes=5)
            completed += 1
        day += timedelta(days=1)
    return DataBatch(
        candles=tuple(bars),
        fetched_at=bars[-1].closed_at,
        warnings=("SYNTHETIC_DEMONSTRATION_ONLY",),
    )
