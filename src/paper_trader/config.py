from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Percent = Annotated[Decimal, Field(ge=0, le=100, allow_inf_nan=False)]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountConfig(Section):
    name: str = Field(min_length=1)
    starting_capital_inr: PositiveDecimal
    currency: Literal["INR"]
    timezone: str

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown timezone") from exc
        if value not in {"Asia/Kolkata", "Asia/Calcutta"}:
            raise ValueError("NSE session rules require Asia/Kolkata")
        return value


class IndexConfig(Section):
    name: str
    provider_symbol: str
    constituents_url: str


class UniverseConfig(Section):
    indices: dict[str, IndexConfig]
    include_constituents: bool
    custom_symbols: list[str]
    refresh_days: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0)
    user_agent: str
    allowed_series: list[str]
    allowed_hosts: list[str]
    max_csv_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def safe_sources(self) -> Self:
        for index in self.indices.values():
            parsed = urlparse(index.constituents_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in self.allowed_hosts
                or parsed.port not in {None, 443}
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Constituent source must use an approved HTTPS host without secrets"
                )
        return self

    @field_validator("custom_symbols")
    @classmethod
    def valid_symbols(cls, values: list[str]) -> list[str]:
        symbols = [v.strip().upper() for v in values]
        if any(not s or any(c.isspace() for c in s) or s.endswith(".NS") for s in symbols):
            raise ValueError("Use NSE symbols without provider suffixes or whitespace")
        return list(dict.fromkeys(symbols))


class SessionConfig(Section):
    pre_open: time
    open: time
    close: time
    mis_squareoff: time
    last_entry: time
    weekdays: list[int]
    skip_first_minutes: int = Field(ge=0)
    skip_last_minutes: int = Field(ge=0)
    calendar_path: Path

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.pre_open <= self.open < self.last_entry <= self.mis_squareoff < self.close:
            raise ValueError("Require pre_open <= open < last_entry <= squareoff < close")
        if not self.weekdays or any(v < 0 or v > 6 for v in self.weekdays):
            raise ValueError("weekdays must contain values 0 through 6")
        for value in (self.pre_open, self.open, self.close, self.last_entry, self.mis_squareoff):
            if value.tzinfo is not None:
                raise ValueError("Session times are local wall-clock times without offsets")
        span = (self.close.hour * 60 + self.close.minute) - (self.open.hour * 60 + self.open.minute)
        if self.skip_first_minutes + self.skip_last_minutes >= span:
            raise ValueError("Avoidance windows consume the entire session")
        return self


class StorageConfig(Section):
    database_path: Path
    busy_timeout_ms: int = Field(ge=0)


class ExecutionConfig(Section):
    tick_size: PositiveDecimal
    latency_ms: int = Field(ge=0)
    fill_on: Literal["next_bar_open"]
    slippage_bps: Decimal = Field(ge=0, allow_inf_nan=False)
    impact_volume_pct: Percent
    max_bar_volume_fill_pct: Percent
    mis_leverage: PositiveDecimal
    limit_trade_through_ticks: int = Field(ge=0)
    atr_slippage_fraction: Decimal = Field(ge=0, allow_inf_nan=False)


class InstrumentRule(Section):
    tick_size: PositiveDecimal | None = None
    mis_leverage: PositiveDecimal | None = None
    lower_circuit: PositiveDecimal | None = None
    upper_circuit: PositiveDecimal | None = None
    halted: bool = False


class ChargesConfig(Section):
    id: str
    effective_date: date
    verified_on: date
    sources: list[str]
    brokerage_intraday_rate: Decimal = Field(ge=0, le=1)
    brokerage_delivery_rate: Decimal = Field(ge=0, le=1)
    brokerage_cap_inr: Decimal = Field(ge=0)
    stt_delivery_rate: Decimal = Field(ge=0, le=1)
    stt_intraday_sell_rate: Decimal = Field(ge=0, le=1)
    transaction_rate: Decimal = Field(ge=0, le=1)
    ipft_rate: Decimal = Field(ge=0, le=1)
    sebi_rate: Decimal = Field(ge=0, le=1)
    gst_rate: Decimal = Field(ge=0, le=1)
    stamp_delivery_buy_rate: Decimal = Field(ge=0, le=1)
    stamp_intraday_buy_rate: Decimal = Field(ge=0, le=1)
    dp_charge_inr: Decimal = Field(ge=0)
    money_quantum: PositiveDecimal
    stt_quantum: PositiveDecimal


class RiskConfig(Section):
    risk_per_trade_pct: Percent
    max_position_pct: Percent
    max_exposure_pct: Percent
    max_open_positions: int = Field(ge=1)
    max_per_sector: int = Field(ge=1)
    daily_loss_limit_pct: Percent
    weekly_loss_limit_pct: Percent
    max_drawdown_kill_pct: Percent
    max_consecutive_losses: int = Field(ge=1)
    cooldown_minutes: int = Field(ge=0)
    min_avg_turnover_inr: PositiveDecimal
    atr_stop_multiple: PositiveDecimal
    reward_risk_ratio: PositiveDecimal
    max_trades_per_day: int = Field(ge=1)
    max_trades_per_symbol: int = Field(ge=1)
    minimum_trade_gap_minutes: int = Field(ge=0)
    minimum_bar_volume: int = Field(ge=0)
    max_correlated_positions: int = Field(ge=1)
    correlation_threshold: float = Field(ge=0, le=1)
    event_blackouts: dict[str, list[date]]
    event_blackout_days: int = Field(ge=0)
    banned_symbols: list[str]
    sizing_buffer_bps: Decimal = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.risk_per_trade_pct > self.max_position_pct:
            raise ValueError("Per-trade risk exceeds position limit")
        if self.max_position_pct > self.max_exposure_pct:
            raise ValueError("Position limit exceeds total exposure limit")
        return self


class SystemOneConfig(Section):
    endpoint: str
    checkpoint: str
    checkpoint_repo: str
    checkpoint_subfolder: str
    timeout_ms: int = Field(gt=0)
    min_direction_prob: float = Field(ge=0, le=1)
    min_conviction: Literal["LOW", "MEDIUM", "HIGH"]
    max_reversal_risk: float = Field(ge=0, le=1)
    temperature_scalar: PositiveDecimal
    retries: int = Field(default=1, ge=0, le=3)
    max_response_bytes: int = Field(default=65536, gt=0)

    @field_validator("endpoint")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("System One must use a loopback HTTP endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("System One URL cannot contain credentials, query or fragment")
        if parsed.path != "/v1/systemone":
            raise ValueError("Expected /v1/systemone")
        return value


class DataConfig(Section):
    provider: Literal["yfinance"]
    timeframes: list[Literal["1m", "5m", "15m", "1h", "1d"]]
    warmup_bars: int = Field(ge=1)
    adjust_corporate_actions: bool
    stale_after_seconds: int = Field(gt=0)
    max_fetch_bars: int = Field(gt=0)
    max_import_bytes: int = Field(gt=0)


class FeatureConfig(Section):
    ema_periods: list[int] = Field(min_length=1)
    sma_period: int = Field(ge=2)
    rsi_period: int = Field(ge=2)
    atr_period: int = Field(ge=2)
    adx_period: int = Field(ge=2)
    macd_fast: int = Field(ge=2)
    macd_slow: int = Field(ge=3)
    macd_signal: int = Field(ge=2)
    bollinger_period: int = Field(ge=2)
    bollinger_std: float = Field(gt=0, allow_inf_nan=False)
    supertrend_multiple: float = Field(gt=0, allow_inf_nan=False)
    volume_period: int = Field(ge=2)
    volatility_period: int = Field(ge=2)
    return_periods: list[int] = Field(min_length=1)
    opening_range_minutes: int = Field(gt=0)
    high_low_days: int = Field(gt=0)
    trend_adx_min: float = Field(ge=0, le=100)
    high_volatility_atr_pct: float = Field(gt=0)
    open_bucket_minutes: int = Field(gt=0)
    late_bucket_minutes: int = Field(gt=0)
    state_max_bytes: int = Field(gt=0, le=380)

    @model_validator(mode="after")
    def valid_periods(self) -> Self:
        if any(p < 1 for p in self.ema_periods + self.return_periods):
            raise ValueError("Indicator periods must be positive")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("MACD fast period must be below slow period")
        return self


class SimulationConfig(Section):
    random_seed: int
    history_bars: int = Field(ge=200)
    max_log_events: int = Field(gt=0)
    strategy: Literal["hold", "ema", "systemone"]
    product: Literal["MIS", "CNC"]
    ema_fast: int = Field(gt=0)
    ema_slow: int = Field(gt=0)
    trading_days_per_year: int = Field(gt=0)
    calendar_days_per_year: float = Field(gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="forbid",
        env_prefix="PAPER_TRADER__",
        env_nested_delimiter="__",
        env_file_encoding="utf-8",
    )

    mode: Literal["paper"]
    account: AccountConfig
    storage: StorageConfig
    universe: UniverseConfig
    session: SessionConfig
    data: DataConfig
    features: FeatureConfig
    simulation: SimulationConfig
    execution: ExecutionConfig
    instrument_rules: dict[str, InstrumentRule]
    charges: list[ChargesConfig] = Field(min_length=1)
    risk: RiskConfig
    system_one: SystemOneConfig
    benchmarks: list[str]
    risk_free_rate_pct: Percent


def load_settings(path: Path, env_file: Path | None = None) -> Settings:
    resolved = path.resolve()
    content = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("Config must be a YAML mapping")

    class LoadedSettings(Settings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return env_settings, dotenv_settings, init_settings, file_secret_settings

    settings = LoadedSettings(**{"_env_file": env_file, **content})
    for section, key in ((settings.storage, "database_path"), (settings.session, "calendar_path")):
        value = getattr(section, key)
        if not value.is_absolute():
            setattr(section, key, (resolved.parent / value).resolve())
    return settings


class SpecialSession(Section):
    date: date
    open: time
    close: time
    last_entry: time
    mis_squareoff: time
    name: str

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if any(
            t.tzinfo is not None
            for t in (self.open, self.close, self.last_entry, self.mis_squareoff)
        ):
            raise ValueError("Special session times cannot have offsets")
        if not self.open < self.last_entry <= self.mis_squareoff < self.close:
            raise ValueError("Invalid special session times")
        return self


class CalendarFile(Section):
    source: str
    verified_on: date
    covered_years: list[int]
    holidays: dict[date, str]
    special_sessions: list[SpecialSession]

    @model_validator(mode="after")
    def coverage(self) -> Self:
        if any(d.year not in self.covered_years for d in self.holidays):
            raise ValueError("Holiday falls outside covered years")
        dates = [s.date for s in self.special_sessions]
        if len(dates) != len(set(dates)):
            raise ValueError("Duplicate special session date")
        if any(d.year not in self.covered_years for d in dates):
            raise ValueError("Special session falls outside covered years")
        return self
