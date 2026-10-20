from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from paper_trader.config import Section

Timeframe = Literal["1m", "5m", "15m", "1h", "1d"]
PriceBasis = Literal["as_traded", "provider_split_adjusted"]
FRAME_SECONDS: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return value.astimezone(UTC)


def stamp(value: datetime) -> str:
    return aware(value).isoformat(timespec="microseconds")


def duration(timeframe: Timeframe) -> timedelta:
    return timedelta(seconds=FRAME_SECONDS[timeframe])


class Candle(Section):
    model_config = {"extra": "forbid", "frozen": True}
    symbol: str = Field(pattern=r"^[A-Z0-9&_.-]+$", max_length=40)
    timeframe: Timeframe
    opened_at: datetime
    closed_at: datetime
    open: Decimal = Field(gt=0, allow_inf_nan=False)
    high: Decimal = Field(gt=0, allow_inf_nan=False)
    low: Decimal = Field(gt=0, allow_inf_nan=False)
    close: Decimal = Field(gt=0, allow_inf_nan=False)
    volume: int = Field(ge=0)
    source: str = Field(min_length=1, max_length=80)
    price_basis: PriceBasis = "as_traded"

    @field_validator("opened_at", "closed_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return aware(value)

    @model_validator(mode="after")
    def valid_bar(self) -> Self:
        if self.opened_at >= self.closed_at:
            raise ValueError("Candle must close after it opens")
        if self.closed_at - self.opened_at > duration(self.timeframe):
            raise ValueError("Candle exceeds timeframe duration")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Inconsistent OHLC range")
        return self

    @property
    def identity(self) -> tuple[str, str, datetime]:
        return self.symbol, self.timeframe, self.opened_at


class CorporateAction(Section):
    symbol: str
    ex_date: date
    kind: Literal["split", "bonus", "dividend"]
    factor: Decimal = Field(default=Decimal(1), gt=0, allow_inf_nan=False)
    cash: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    known_at: datetime
    source: str

    @field_validator("known_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return aware(value)


class DataBatch(Section):
    candles: tuple[Candle, ...]
    actions: tuple[CorporateAction, ...] = ()
    fetched_at: datetime
    warnings: tuple[str, ...] = ()

    @field_validator("fetched_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return aware(value)

    @property
    def version(self) -> str:
        payload = "\n".join(c.model_dump_json() for c in self.candles)
        payload += "\n" + "\n".join(a.model_dump_json() for a in self.actions)
        return hashlib.sha256(payload.encode()).hexdigest()
