from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal, Self
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from paper_trader.calendar import TradingCalendar
from paper_trader.config import ChargesConfig, InstrumentRule, Section, Settings
from paper_trader.market import Candle, aware

Product = Literal["MIS", "CNC"]
Side = Literal["BUY", "SELL"]


def tick_round(price: Decimal, tick: Decimal, side: Side | None = None) -> Decimal:
    mode = ROUND_CEILING if side == "BUY" else ROUND_FLOOR if side == "SELL" else ROUND_HALF_UP
    return (price / tick).to_integral_value(rounding=mode) * tick


class Order(Section):
    id: str = Field(default_factory=lambda: uuid4().hex, max_length=128)
    symbol: str = Field(pattern=r"^[A-Z0-9&_.-]+$", max_length=40)
    side: Side
    product: Product
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M", "BRACKET"] = "MARKET"
    quantity: int = Field(gt=0, le=1000000000)
    signal_at: datetime
    limit_price: Decimal | None = Field(default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False)
    trigger_price: Decimal | None = Field(
        default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False
    )
    stop_price: Decimal | None = Field(default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False)
    target_price: Decimal | None = Field(
        default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False
    )
    trailing_distance: Decimal | None = Field(
        default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False
    )
    reduce_only: bool = False
    validity: Literal["DAY", "GTC"] = "DAY"

    @field_validator("signal_at")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        return aware(value)

    @model_validator(mode="after")
    def required_fields(self) -> Self:
        if self.order_type in {"LIMIT", "SL"} and self.limit_price is None:
            raise ValueError("Limit price is required")
        if self.order_type in {"SL", "SL-M"} and self.trigger_price is None:
            raise ValueError("Trigger price is required")
        if not self.reduce_only and self.stop_price is None:
            raise ValueError("Every entry needs a stop")
        if self.order_type == "BRACKET" and self.target_price is None:
            raise ValueError("Bracket entries need a target")
        if self.product == "MIS" and self.validity != "DAY":
            raise ValueError("MIS orders have DAY validity")
        return self


@dataclass(frozen=True)
class ChargeBreakdown:
    schedule_id: str
    items: dict[str, Decimal]

    @property
    def total(self) -> Decimal:
        return sum(self.items.values(), Decimal(0))


class ChargesCalculator:
    def __init__(self, schedules: list[ChargesConfig]) -> None:
        self.schedules = schedules

    def schedule(self, day: date) -> ChargesConfig:
        eligible = [s for s in self.schedules if s.effective_date <= day]
        if not eligible:
            raise ValueError("No verified charge schedule covers this date")
        return max(eligible, key=lambda s: s.effective_date)

    def calculate(
        self,
        turnover: Decimal,
        side: Side,
        product: Product,
        day: date,
        previous_turnover: Decimal = Decimal(0),
        previous_brokerage: Decimal = Decimal(0),
        dp_already_charged: bool = False,
    ) -> ChargeBreakdown:
        if not turnover.is_finite() or turnover <= 0:
            raise ValueError("Turnover must be positive and finite")
        cfg = self.schedule(day)
        rate = cfg.brokerage_intraday_rate if product == "MIS" else cfg.brokerage_delivery_rate
        brokerage = max(
            Decimal(0),
            min((turnover + previous_turnover) * rate, cfg.brokerage_cap_inr) - previous_brokerage,
        )
        stt_rate = (
            cfg.stt_delivery_rate
            if product == "CNC"
            else (cfg.stt_intraday_sell_rate if side == "SELL" else Decimal(0))
        )
        stamp_rate = (
            (cfg.stamp_delivery_buy_rate if product == "CNC" else cfg.stamp_intraday_buy_rate)
            if side == "BUY"
            else Decimal(0)
        )
        raw = {
            "brokerage": brokerage,
            "stt": (turnover * stt_rate / cfg.stt_quantum).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
            * cfg.stt_quantum,
            "exchange": turnover * cfg.transaction_rate,
            "ipft": turnover * cfg.ipft_rate,
            "sebi": turnover * cfg.sebi_rate,
            "stamp": turnover * stamp_rate,
            "dp": cfg.dp_charge_inr
            if product == "CNC" and side == "SELL" and not dp_already_charged
            else Decimal(0),
        }
        raw["gst"] = (raw["brokerage"] + raw["exchange"] + raw["ipft"] + raw["sebi"]) * cfg.gst_rate
        raw["dp_gst"] = raw["dp"] * cfg.gst_rate
        return ChargeBreakdown(
            cfg.id,
            {k: v.quantize(cfg.money_quantum, rounding=ROUND_HALF_UP) for k, v in raw.items()},
        )


@dataclass
class Position:
    symbol: str
    product: Product
    quantity: int
    average_price: Decimal
    stop_price: Decimal
    target_price: Decimal | None
    opened_at: datetime
    sector: str
    entry_charges: Decimal
    leverage: Decimal
    entry_order_id: str
    trailing_distance: Decimal | None = None


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: Side
    product: Product
    quantity: int
    price: Decimal
    at: datetime
    charges: ChargeBreakdown
    reason: str


@dataclass
class Portfolio:
    starting_capital: Decimal
    cash: Decimal = field(init=False)
    positions: dict[tuple[str, Product], Position] = field(default_factory=dict)
    marks: dict[str, Decimal] = field(default_factory=dict)
    realized_pnl: Decimal = Decimal(0)
    total_charges: Decimal = Decimal(0)
    peak_equity: Decimal = field(init=False)
    daily_start: Decimal = field(init=False)
    weekly_start: Decimal = field(init=False)
    current_day: date | None = None
    current_week: date | None = None
    consecutive_losses: int = 0
    last_loss_at: datetime | None = None
    entry_times: dict[str, list[datetime]] = field(default_factory=dict)
    kill_switch: bool = False
    fills: list[Fill] = field(default_factory=list)
    closed_trades: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = self.starting_capital
        self.peak_equity = self.daily_start = self.weekly_start = self.starting_capital

    @property
    def equity(self) -> Decimal:
        equity = self.cash
        for p in self.positions.values():
            mark = self.marks.get(p.symbol, p.average_price)
            equity += (
                mark * p.quantity if p.product == "CNC" else (mark - p.average_price) * p.quantity
            )
        return equity

    @property
    def exposure(self) -> Decimal:
        return sum(
            (
                abs(p.quantity) * self.marks.get(p.symbol, p.average_price)
                for p in self.positions.values()
            ),
            Decimal(0),
        )

    @property
    def used_margin(self) -> Decimal:
        return sum(
            (
                abs(p.quantity)
                * max(p.average_price, self.marks.get(p.symbol, p.average_price))
                / p.leverage
                for p in self.positions.values()
                if p.product == "MIS"
            ),
            Decimal(0),
        )

    @property
    def available_cash(self) -> Decimal:
        return self.cash - self.used_margin

    def checkpoint(self, at: datetime, calendar: TradingCalendar) -> None:
        day = aware(at).astimezone(calendar.zone).date()
        week = day - timedelta(days=day.weekday())
        if self.current_day != day:
            self.current_day, self.daily_start = day, self.equity
        if self.current_week != week:
            self.current_week, self.weekly_start = week, self.equity
        self.peak_equity = max(self.peak_equity, self.equity)

    def apply(self, fill: Fill, order: Order, sector: str, leverage: Decimal) -> None:
        key = (fill.symbol, fill.product)
        sign = 1 if fill.side == "BUY" else -1
        if order.reduce_only:
            position = self.positions[key]
            if sign * position.quantity >= 0 or fill.quantity > abs(position.quantity):
                raise ValueError("Invalid position reduction")
            allocation = position.entry_charges * Decimal(fill.quantity) / abs(position.quantity)
            gross = (
                (fill.price - position.average_price)
                * fill.quantity
                * (1 if position.quantity > 0 else -1)
            )
            pnl = gross - fill.charges.total - allocation
            self.cash += (
                fill.price * fill.quantity - fill.charges.total
                if fill.product == "CNC"
                else gross - fill.charges.total
            )
            self.realized_pnl += pnl
            self.closed_trades.append(
                {
                    "entry_order_id": position.entry_order_id,
                    "symbol": fill.symbol,
                    "quantity": fill.quantity,
                    "pnl": str(pnl),
                    "opened_at": position.opened_at.isoformat(),
                    "closed_at": fill.at.isoformat(),
                    "reason": fill.reason,
                    "charges": str(allocation + fill.charges.total),
                }
            )
            self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
            if pnl < 0:
                self.last_loss_at = fill.at
            position.quantity += sign * fill.quantity
            position.entry_charges -= allocation
            if position.quantity == 0:
                del self.positions[key]
        else:
            if order.stop_price is None:
                raise ValueError("Stop is missing")
            existing = self.positions.get(key)
            if existing and existing.entry_order_id != order.id:
                raise ValueError("Position already exists")
            self.cash -= (
                fill.price * fill.quantity if fill.product == "CNC" else Decimal(0)
            ) + fill.charges.total
            if existing:
                total = abs(existing.quantity) + fill.quantity
                existing.average_price = (
                    existing.average_price * abs(existing.quantity) + fill.price * fill.quantity
                ) / total
                existing.quantity += sign * fill.quantity
                existing.entry_charges += fill.charges.total
            else:
                self.positions[key] = Position(
                    fill.symbol,
                    fill.product,
                    sign * fill.quantity,
                    fill.price,
                    order.stop_price,
                    order.target_price,
                    fill.at,
                    sector,
                    fill.charges.total,
                    leverage,
                    order.id,
                    order.trailing_distance,
                )
                self.entry_times.setdefault(fill.symbol, []).append(fill.at)
        self.total_charges += fill.charges.total
        self.fills.append(fill)
        self.marks[fill.symbol] = fill.price
        self.peak_equity = max(self.peak_equity, self.equity)


@dataclass(frozen=True)
class RiskContext:
    sector: str = "UNKNOWN"
    instrument_type: str = "EQUITY"
    average_turnover: Decimal | None = None
    bar_volume: int = 0
    correlations: dict[str, float] = field(default_factory=dict)
    expiry_blackout: bool = False
    feed_healthy: bool = True


class RiskEngine:
    def __init__(self, settings: Settings, calendar: TradingCalendar) -> None:
        self.settings = settings
        self.calendar = calendar

    def size(self, portfolio: Portfolio, price: Decimal, atr: Decimal) -> int:
        if atr <= 0 or price <= 0 or not atr.is_finite() or not price.is_finite():
            return 0
        cfg = self.settings.risk
        budget = portfolio.equity * cfg.risk_per_trade_pct / 100
        return max(
            0,
            int(
                min(
                    budget / (atr * cfg.atr_stop_multiple),
                    portfolio.equity
                    * cfg.max_position_pct
                    / 100
                    / (price * (1 + cfg.sizing_buffer_bps / 10000)),
                )
            ),
        )

    def vetoes(
        self, order: Order, price: Decimal, portfolio: Portfolio, at: datetime, context: RiskContext
    ) -> list[str]:
        if not price.is_finite() or price <= 0:
            return ["INVALID_PRICE"]
        cfg = self.settings.risk
        portfolio.checkpoint(at, self.calendar)
        key = (order.symbol, order.product)
        current = portfolio.positions.get(key)
        continuing = current is not None and current.entry_order_id == order.id
        rule = self.settings.instrument_rules.get(order.symbol, InstrumentRule())
        reasons = []
        if context.instrument_type != "EQUITY":
            reasons.append("REFERENCE_INSTRUMENT")
        if rule.halted or order.symbol in cfg.banned_symbols:
            reasons.append("HALTED_OR_BANNED")
        if (rule.lower_circuit and price <= rule.lower_circuit) or (
            rule.upper_circuit and price >= rule.upper_circuit
        ):
            reasons.append("CIRCUIT")
        if not self.calendar.status(at).phase == "open":
            reasons.append("OUTSIDE_SESSION")
        if not context.feed_healthy:
            reasons.append("UNHEALTHY_FEED")
        if order.reduce_only:
            if (
                current is None
                or order.quantity > abs(current.quantity)
                or ((order.side == "BUY") == (current.quantity > 0))
            ):
                reasons.append("INVALID_REDUCTION")
            return reasons
        if portfolio.equity <= portfolio.peak_equity * (1 - cfg.max_drawdown_kill_pct / 100):
            portfolio.kill_switch = True
        if portfolio.kill_switch:
            reasons.append("DRAWDOWN_KILL")
        if portfolio.equity <= portfolio.daily_start * (1 - cfg.daily_loss_limit_pct / 100):
            reasons.append("DAILY_LOSS_LIMIT")
        if portfolio.equity <= portfolio.weekly_start * (1 - cfg.weekly_loss_limit_pct / 100):
            reasons.append("WEEKLY_LOSS_LIMIT")
        if portfolio.consecutive_losses >= cfg.max_consecutive_losses and portfolio.last_loss_at:
            if at < portfolio.last_loss_at + timedelta(minutes=cfg.cooldown_minutes):
                reasons.append("LOSS_COOLDOWN")
            else:
                portfolio.consecutive_losses = 0
        if order.product == "CNC" and order.side == "SELL":
            reasons.append("CNC_LONG_ONLY")
        session = self.calendar.status(at)
        if not session.can_decide or (order.product == "MIS" and not session.can_enter_mis):
            reasons.append("ENTRY_WINDOW")
        if current and not continuing:
            reasons.append("POSITION_EXISTS")
        if not continuing and len(portfolio.positions) >= cfg.max_open_positions:
            reasons.append("MAX_POSITIONS")
        if (
            not continuing
            and sum(p.sector == context.sector for p in portfolio.positions.values())
            >= cfg.max_per_sector
        ):
            reasons.append("SECTOR_LIMIT")
        notional = price * order.quantity
        equity = max(portfolio.equity, Decimal(0))
        existing_notional = abs(current.quantity) * price if continuing and current else Decimal(0)
        if notional + existing_notional > equity * cfg.max_position_pct / 100:
            reasons.append("POSITION_LIMIT")
        if portfolio.exposure + notional > equity * cfg.max_exposure_pct / 100:
            reasons.append("EXPOSURE_LIMIT")
        if (
            order.stop_price is None
            or order.stop_price <= 0
            or (order.side == "BUY" and order.stop_price >= price)
            or (order.side == "SELL" and order.stop_price <= price)
        ):
            reasons.append("INVALID_STOP")
        elif (
            abs(price - order.stop_price)
            * (order.quantity + (abs(current.quantity) if continuing and current else 0))
            > equity * cfg.risk_per_trade_pct / 100
        ):
            reasons.append("TRADE_RISK_LIMIT")
        if order.target_price and (
            (order.side == "BUY" and order.target_price <= price)
            or (order.side == "SELL" and order.target_price >= price)
        ):
            reasons.append("INVALID_TARGET")
        leverage = rule.mis_leverage or self.settings.execution.mis_leverage
        margin = notional if order.product == "CNC" else notional / leverage
        fees = (
            ChargesCalculator(self.settings.charges)
            .calculate(
                notional, order.side, order.product, at.astimezone(self.calendar.zone).date()
            )
            .total
        )
        if margin + fees > portfolio.available_cash:
            reasons.append("INSUFFICIENT_CASH_OR_MARGIN")
        day = at.astimezone(self.calendar.zone).date()
        entries = [
            t
            for times in portfolio.entry_times.values()
            for t in times
            if t.astimezone(self.calendar.zone).date() == day
        ]
        symbol_entries = [
            t
            for t in portfolio.entry_times.get(order.symbol, [])
            if t.astimezone(self.calendar.zone).date() == day
        ]
        if not continuing and len(entries) >= cfg.max_trades_per_day:
            reasons.append("DAILY_TRADE_LIMIT")
        if not continuing and len(symbol_entries) >= cfg.max_trades_per_symbol:
            reasons.append("SYMBOL_TRADE_LIMIT")
        if (
            not continuing
            and symbol_entries
            and at < symbol_entries[-1] + timedelta(minutes=cfg.minimum_trade_gap_minutes)
        ):
            reasons.append("TRADE_SPACING")
        if context.average_turnover is None or context.average_turnover < cfg.min_avg_turnover_inr:
            reasons.append("TURNOVER_FILTER")
        if context.bar_volume < cfg.minimum_bar_volume:
            reasons.append("BAR_VOLUME_FILTER")
        if (
            sum(
                abs(v) >= cfg.correlation_threshold
                for s, v in context.correlations.items()
                if any(p.symbol == s for p in portfolio.positions.values())
            )
            >= cfg.max_correlated_positions
        ):
            reasons.append("CORRELATION_LIMIT")
        blackouts = cfg.event_blackouts.get(order.symbol, [])
        if context.expiry_blackout or any(
            abs((d - day).days) <= cfg.event_blackout_days for d in blackouts
        ):
            reasons.append("EVENT_BLACKOUT")
        return reasons


@dataclass
class PendingOrder:
    order: Order
    context: RiskContext
    remaining: int
    status: str = "OPEN"
    turnover: Decimal = Decimal(0)
    brokerage: Decimal = Decimal(0)
    triggered: bool = False


class PaperExchange:
    def __init__(self, settings: Settings, calendar: TradingCalendar, portfolio: Portfolio) -> None:
        self.settings = settings
        self.calendar = calendar
        self.portfolio = portfolio
        self.risk = RiskEngine(settings, calendar)
        self.charges = ChargesCalculator(settings.charges)
        self.orders: dict[str, PendingOrder] = {}
        self.veto_log: list[dict[str, object]] = []
        self.dp_days: set[tuple[str, date]] = set()

    def submit(self, order: Order, price: Decimal, context: RiskContext) -> list[str]:
        if order.id in self.orders:
            return ["DUPLICATE_ORDER"]
        rule = self.settings.instrument_rules.get(order.symbol, InstrumentRule())
        tick = rule.tick_size or self.settings.execution.tick_size
        order = order.model_copy(
            update={
                key: tick_round(value, tick)
                for key in (
                    "stop_price",
                    "target_price",
                    "limit_price",
                    "trigger_price",
                    "trailing_distance",
                )
                if (value := getattr(order, key)) is not None
            }
        )
        reasons = (
            ["INVALID_ROUNDED_PRICE"]
            if any(
                value is not None and value <= 0
                for value in (
                    order.stop_price,
                    order.target_price,
                    order.limit_price,
                    order.trigger_price,
                    order.trailing_distance,
                )
            )
            else self.risk.vetoes(order, price, self.portfolio, order.signal_at, context)
        )
        if any(
            p.status in {"OPEN", "PARTIAL"}
            and p.order.symbol == order.symbol
            and p.order.product == order.product
            for p in self.orders.values()
        ):
            reasons.append("PENDING_ORDER_EXISTS")
        if reasons:
            self.veto_log.append(
                {
                    "order_id": order.id,
                    "symbol": order.symbol,
                    "at": order.signal_at.isoformat(),
                    "reasons": reasons,
                }
            )
            return reasons
        self.orders[order.id] = PendingOrder(order, context, order.quantity)
        return []

    def cancel(self, order_id: str) -> None:
        pending = self.orders[order_id]
        if pending.status in {"OPEN", "PARTIAL"}:
            pending.status = "CANCELLED"

    def process(self, candle: Candle, atr: Decimal = Decimal(0)) -> list[Fill]:
        self.portfolio.checkpoint(candle.opened_at, self.calendar)
        before = len(self.portfolio.fills)
        cfg = self.settings.execution
        rule = self.settings.instrument_rules.get(candle.symbol, InstrumentRule())
        tick = rule.tick_size or cfg.tick_size
        capacity = int(Decimal(candle.volume) * cfg.max_bar_volume_fill_pct / 100)
        for pending in list(self.orders.values()):
            order = pending.order
            if pending.status not in {"OPEN", "PARTIAL"} or order.symbol != candle.symbol:
                continue
            if (
                order.validity == "DAY"
                and order.signal_at.astimezone(self.calendar.zone).date()
                < candle.opened_at.astimezone(self.calendar.zone).date()
            ):
                pending.status = "EXPIRED"
                continue
            eligible = order.signal_at + timedelta(milliseconds=cfg.latency_ms)
            if candle.opened_at < eligible or candle.closed_at <= order.signal_at or capacity <= 0:
                continue
            price = candle.open
            if order.order_type in {"SL", "SL-M"}:
                if order.trigger_price is None:
                    continue
                pending.triggered = pending.triggered or (
                    candle.high >= order.trigger_price
                    if order.side == "BUY"
                    else candle.low <= order.trigger_price
                )
                if not pending.triggered:
                    continue
                price = (
                    max(candle.open, order.trigger_price)
                    if order.side == "BUY"
                    else min(candle.open, order.trigger_price)
                )
            if order.order_type in {"LIMIT", "SL"}:
                if order.limit_price is None:
                    continue
                through = tick * cfg.limit_trade_through_ticks
                if not (
                    candle.low <= order.limit_price - through
                    if order.side == "BUY"
                    else candle.high >= order.limit_price + through
                ):
                    continue
                price = (
                    min(candle.open, order.limit_price)
                    if order.side == "BUY"
                    else max(candle.open, order.limit_price)
                )
            quantity = min(capacity, pending.remaining)
            impact = Decimal(quantity) / max(candle.volume, 1) * cfg.impact_volume_pct / 100
            slip = price * (cfg.slippage_bps / 10000 + impact) + atr * cfg.atr_slippage_fraction
            price = tick_round(price + (slip if order.side == "BUY" else -slip), tick, order.side)
            if order.limit_price is not None and order.order_type in {"LIMIT", "SL"}:
                price = (
                    min(price, tick_round(order.limit_price, tick, "SELL"))
                    if order.side == "BUY"
                    else max(price, tick_round(order.limit_price, tick, "BUY"))
                )
            effective = order.model_copy(update={"quantity": quantity})
            reasons = self.risk.vetoes(
                effective, price, self.portfolio, candle.opened_at, pending.context
            )
            if reasons:
                pending.status = "REJECTED"
                self.veto_log.append(
                    {
                        "order_id": order.id,
                        "symbol": order.symbol,
                        "at": candle.opened_at.isoformat(),
                        "reasons": reasons,
                    }
                )
                continue
            day = candle.opened_at.astimezone(self.calendar.zone).date()
            fees = self.charges.calculate(
                price * quantity,
                order.side,
                order.product,
                day,
                pending.turnover,
                pending.brokerage,
                (order.symbol, day) in self.dp_days,
            )
            fill = Fill(
                order.id,
                order.symbol,
                order.side,
                order.product,
                quantity,
                price,
                candle.opened_at,
                fees,
                "MANUAL_EXIT" if order.reduce_only else "ENTRY",
            )
            self.portfolio.apply(
                fill, effective, pending.context.sector, rule.mis_leverage or cfg.mis_leverage
            )
            if fees.items["dp"]:
                self.dp_days.add((order.symbol, day))
            pending.turnover += price * quantity
            pending.brokerage += fees.items["brokerage"]
            pending.remaining -= quantity
            pending.status = "FILLED" if pending.remaining == 0 else "PARTIAL"
            capacity -= quantity
        self.reflex(candle, capacity)
        self.portfolio.marks[candle.symbol] = candle.close
        self.portfolio.peak_equity = max(self.portfolio.peak_equity, self.portfolio.equity)
        return self.portfolio.fills[before:]

    def reflex(self, candle: Candle, capacity: int | None = None) -> None:
        rule = self.settings.instrument_rules.get(candle.symbol, InstrumentRule())
        if rule.halted or candle.volume <= 0:
            return
        if (rule.lower_circuit and candle.low <= rule.lower_circuit == candle.high) or (
            rule.upper_circuit and candle.low == rule.upper_circuit <= candle.high
        ):
            return
        tick = rule.tick_size or self.settings.execution.tick_size
        if capacity is None:
            capacity = int(
                Decimal(candle.volume) * self.settings.execution.max_bar_volume_fill_pct / 100
            )
        for position in list(self.portfolio.positions.values()):
            if position.symbol != candle.symbol:
                continue
            long = position.quantity > 0
            stopped = (
                candle.low <= position.stop_price if long else candle.high >= position.stop_price
            )
            targeted = position.target_price is not None and (
                candle.high >= position.target_price
                if long
                else candle.low <= position.target_price
            )
            squareoff = (
                position.product == "MIS"
                and self.calendar.status(candle.closed_at).must_squareoff_mis
            )
            if stopped or targeted or squareoff:
                if capacity <= 0:
                    self.veto_log.append(
                        {
                            "symbol": position.symbol,
                            "at": candle.closed_at.isoformat(),
                            "reasons": ["EXIT_VOLUME_CAP"],
                        }
                    )
                    continue
                side: Side = "SELL" if long else "BUY"
                if stopped:
                    price = (
                        min(candle.open, position.stop_price)
                        if long
                        else max(candle.open, position.stop_price)
                    )
                    reason = "STOP"
                elif targeted and position.target_price is not None:
                    price = (
                        max(candle.open, position.target_price)
                        if long
                        else min(candle.open, position.target_price)
                    )
                    reason = "TARGET"
                else:
                    price, reason = candle.close, "MIS_SQUAREOFF"
                slip = price * self.settings.execution.slippage_bps / 10000
                price = tick_round(price + (-slip if long else slip), tick, side)
                order = Order(
                    symbol=position.symbol,
                    side=side,
                    product=position.product,
                    quantity=min(abs(position.quantity), capacity),
                    signal_at=candle.closed_at,
                    reduce_only=True,
                )
                day = candle.closed_at.astimezone(self.calendar.zone).date()
                fees = self.charges.calculate(
                    price * order.quantity,
                    side,
                    position.product,
                    day,
                    dp_already_charged=(position.symbol, day) in self.dp_days,
                )
                self.portfolio.apply(
                    Fill(
                        order.id,
                        order.symbol,
                        side,
                        order.product,
                        order.quantity,
                        price,
                        candle.closed_at,
                        fees,
                        reason,
                    ),
                    order,
                    position.sector,
                    position.leverage,
                )
                if fees.items["dp"]:
                    self.dp_days.add((position.symbol, day))
                capacity -= order.quantity
                for pending in self.orders.values():
                    if pending.order.symbol == position.symbol and pending.status in {
                        "OPEN",
                        "PARTIAL",
                    }:
                        pending.status = "CANCELLED"
            elif position.trailing_distance:
                candidate = (
                    candle.high - position.trailing_distance
                    if long
                    else candle.low + position.trailing_distance
                )
                position.stop_price = tick_round(
                    max(position.stop_price, candidate)
                    if long
                    else min(position.stop_price, candidate),
                    tick,
                )
