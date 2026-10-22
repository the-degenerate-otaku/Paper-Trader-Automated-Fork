from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any

import numpy as np
from pydantic import Field, model_validator

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Section, Settings
from paper_trader.data import quality
from paper_trader.features import FeatureEngine, FeatureSnapshot
from paper_trader.market import Candle
from paper_trader.timeframe_lab import aggregate_five, mis_history
from paper_trader.trading import Fill, Order, PaperExchange, Portfolio, RiskContext


class Shock(Section):
    start: time
    end: time
    jump_bps: float = Field(default=0, ge=-1000, le=1000, allow_inf_nan=False)
    drift_bps: float = Field(default=0, ge=-100, le=100, allow_inf_nan=False)
    noise_bps: float = Field(default=0, ge=0, le=200, allow_inf_nan=False)
    volume_multiplier: Decimal = Field(default=Decimal(1), ge=0, le=10)
    slippage_multiplier: Decimal = Field(default=Decimal(1), ge=1, le=10)
    inference_outage: bool = False
    missing_data: bool = False
    halted: bool = False

    @model_validator(mode="after")
    def ordered(self) -> Shock:
        if self.start.tzinfo or self.end.tzinfo or self.start >= self.end:
            raise ValueError("Stress windows require ordered local times")
        return self


class Scenario(Section):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    decisions: list[time] = Field(min_length=1, max_length=10)
    shocks: list[Shock] = Field(min_length=1, max_length=5)


class SessionProtocol(Section):
    historical_days: list[date] = Field(min_length=1, max_length=15)
    stress_day: date
    symbols: list[Annotated[str, Field(pattern=r"^[A-Z0-9&_.-]+$", max_length=40)]] = Field(
        min_length=1, max_length=10
    )
    decision_times: list[time] = Field(min_length=1, max_length=20)
    new_hold_minutes: int = Field(ge=1, le=60)
    entry_expiry_minutes: int = Field(ge=1, le=30)
    decision_delay_seconds: int = Field(ge=1, le=60)
    inference_timeout_ms: int = Field(ge=5000, le=60000)
    max_new_inferences: int = Field(ge=1, le=1000)
    random_seed: int = Field(ge=0, le=4294967295)
    scenarios: list[Scenario] = Field(max_length=20)


def active_shocks(
    scenario: Scenario | None, at: datetime, calendar: TradingCalendar
) -> list[Shock]:
    local = at.astimezone(calendar.zone).time()
    return (
        [shock for shock in scenario.shocks if shock.start <= local < shock.end] if scenario else []
    )


def stressed(
    bars: tuple[Candle, ...],
    scenario: Scenario,
    day: date,
    calendar: TradingCalendar,
    seed: int,
) -> tuple[Candle, ...]:
    if len({bar.symbol for bar in bars}) > 1:
        raise ValueError("Stress each symbol independently")
    salt = f"{seed}:{scenario.name}:{bars[0].symbol if bars else ''}"
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(salt.encode()).digest()[:8]))
    factor = Decimal(1)
    result = []
    applied: set[int] = set()
    if any(a.opened_at >= b.opened_at for a, b in zip(bars, bars[1:], strict=False)):
        raise ValueError("Stress input must be chronological")
    for bar in bars:
        if bar.opened_at.astimezone(calendar.zone).date() != day:
            result.append(bar)
            continue
        shocks = active_shocks(scenario, bar.opened_at, calendar)
        for index, shock in enumerate(scenario.shocks):
            if (
                index not in applied
                and bar.opened_at.astimezone(calendar.zone).time() >= shock.start
            ):
                factor *= 1 + Decimal(str(shock.jump_bps)) / 10000
                applied.add(index)
        opened = bar.open * factor
        change = sum(
            (
                Decimal(str(shock.drift_bps + rng.normal(0, shock.noise_bps))) / 10000
                for shock in shocks
            ),
            Decimal(0),
        )
        closed = bar.close * factor * (1 + change)
        wick = abs(change) / 2
        volume = Decimal(bar.volume)
        for shock in shocks:
            volume *= shock.volume_multiplier
        value = Candle(
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            opened_at=bar.opened_at,
            closed_at=bar.closed_at,
            open=opened,
            high=max(bar.high * factor, opened, closed) * (1 + wick),
            low=min(bar.low * factor, opened, closed) * (1 - wick),
            close=closed,
            volume=max(0, int(volume)),
            source="historically_anchored_stress",
            price_basis=bar.price_basis,
        )
        if any(shock.halted for shock in shocks):
            mark = result[-1].close if result else bar.open
            value = value.model_copy(
                update={"open": mark, "high": mark, "low": mark, "close": mark, "volume": 0}
            )
        factor *= 1 + change
        if not any(shock.missing_data for shock in shocks):
            result.append(value)
    return tuple(result)


def frame_history(
    minutes: tuple[Candle, ...],
    native_fives: tuple[Candle, ...],
    settings: Settings,
    at: datetime,
    frame: str,
) -> tuple[Candle, ...]:
    recent = mis_history(minutes, settings, at)
    if frame == "1m":
        return recent
    if frame != "5m":
        raise ValueError("Only one/five-minute research signals are supported")
    calendar = TradingCalendar.load(settings)
    start = min((bar.opened_at for bar in minutes), default=at)
    older = []
    for bar in native_fives:
        day = bar.opened_at.astimezone(calendar.zone).date()
        special = next((s for s in calendar.calendar.special_sessions if s.date == day), None)
        cutoff = datetime.combine(day, (special or settings.session).mis_squareoff, calendar.zone)
        if bar.closed_at <= min(start, at, cutoff):
            older.append(bar)
    return tuple(sorted((*older, *aggregate_five(recent, calendar)), key=lambda bar: bar.opened_at))


def market_features(
    minutes: tuple[Candle, ...],
    native_fives: tuple[Candle, ...],
    settings: Settings,
    at: datetime,
    frame: str,
) -> FeatureSnapshot:
    history = frame_history(minutes, native_fives, settings, at, frame)
    calendar = TradingCalendar.load(settings)
    if len(history) < settings.data.warmup_bars:
        raise ValueError("WARMUP")
    if history[-1].closed_at != at:
        raise ValueError("MISSING_CLOSED_SIGNAL")
    if quality(history[-settings.data.warmup_bars :], calendar, at).status != "healthy":
        raise ValueError("UNHEALTHY_SIGNAL_HISTORY")
    return FeatureEngine(settings, calendar).calculate(
        history[-settings.simulation.history_bars :], at
    )


class SessionExchange(PaperExchange):
    def begin_batch(self, candles: tuple[Candle, ...]) -> None:
        if getattr(self, "batch_active", False):
            raise ValueError("Previous minute batch is unfinished")
        if not candles or len({(b.opened_at, b.closed_at) for b in candles}) != 1:
            raise ValueError("Minute batch must share one clock")
        if len({b.symbol for b in candles}) != len(candles):
            raise ValueError("Minute batch has duplicate symbols")
        self.batch_active = True
        self.deferred: list[tuple[Candle, int | None]] = []
        self.batch_candles = candles
        for candle in candles:
            self.portfolio.marks[candle.symbol] = candle.open
        self.portfolio.checkpoint(candles[0].opened_at, self.calendar)

    def process(self, candle: Candle, atr: Decimal = Decimal(0)) -> list[Fill]:
        if not getattr(self, "batch_active", False):
            return super().process(candle, atr)
        if candle not in self.batch_candles:
            raise ValueError("Candle outside active minute batch")
        peak = self.portfolio.peak_equity
        fills = super().process(candle, atr)
        self.portfolio.marks[candle.symbol] = candle.open
        self.portfolio.peak_equity = max(peak, self.portfolio.equity)
        return fills

    def reflex(self, candle: Candle, capacity: int | None = None) -> None:
        if getattr(self, "batch_active", False):
            self.deferred.append((candle, capacity))
        else:
            super().reflex(candle, capacity)

    def end_batch(self) -> list[Fill]:
        if not getattr(self, "batch_active", False):
            raise ValueError("No active minute batch")
        if {b.symbol for b, _ in self.deferred} != {b.symbol for b in self.batch_candles}:
            raise ValueError("Minute batch is incomplete")
        self.batch_active = False
        before = len(self.portfolio.fills)
        for candle, capacity in self.deferred:
            super().reflex(candle, capacity)
        for candle in self.batch_candles:
            self.portfolio.marks[candle.symbol] = candle.close
        self.portfolio.peak_equity = max(self.portfolio.peak_equity, self.portfolio.equity)
        return self.portfolio.fills[before:]


@dataclass
class ReplayBook:
    settings: Settings
    frame: str
    calendar: TradingCalendar = field(init=False)
    exchange: SessionExchange = field(init=False)
    latest: dict[str, FeatureSnapshot] = field(default_factory=dict)
    curve: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    closes: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.settings = self.settings.model_copy(deep=True)
        self.calendar = TradingCalendar.load(self.settings)
        self.exchange = SessionExchange(
            self.settings, self.calendar, Portfolio(self.settings.account.starting_capital_inr)
        )

    def context(
        self,
        symbol: str,
        bars: tuple[Candle, ...],
        sector: str,
        atr: Decimal,
        histories: dict[str, tuple[Candle, ...]] | None = None,
        at: datetime | None = None,
    ) -> RiskContext:
        totals: dict[date, Decimal] = defaultdict(Decimal)
        today = (at or bars[-1].closed_at).astimezone(self.calendar.zone).date()
        for bar in bars:
            day = bar.opened_at.astimezone(self.calendar.zone).date()
            if day < today:
                totals[day] += bar.close * bar.volume
        correlations = {}
        for position in self.exchange.portfolio.positions.values():
            if position.symbol == symbol:
                continue
            other = (histories or {}).get(position.symbol, ())
            aligned = {bar.closed_at: float(bar.close) for bar in other}
            pairs = [
                (float(bar.close), aligned[bar.closed_at])
                for bar in bars
                if bar.closed_at in aligned
            ]
            if len(pairs) >= self.settings.features.volatility_period:
                left, right = np.array(pairs).T
                a, b = np.diff(np.log(left)), np.diff(np.log(right))
                if np.std(a) > 0 and np.std(b) > 0:
                    correlations[position.symbol] = float(np.corrcoef(a, b)[0, 1])
        return RiskContext(
            sector=sector,
            average_turnover=sum(totals.values(), Decimal(0)) / len(totals) if totals else None,
            bar_volume=bars[-1].volume if bars else 0,
            atr=atr,
            correlations=correlations,
            feed_healthy=bool(bars),
        )

    def close(
        self, symbol: str, at: datetime, price: Decimal, context: RiskContext, reason: str
    ) -> None:
        position = self.exchange.portfolio.positions.get((symbol, "MIS"))
        if position is None:
            return
        for pending in self.exchange.orders.values():
            if pending.order.symbol == symbol and pending.status in {"OPEN", "PARTIAL"}:
                if pending.order.reduce_only:
                    return
                self.exchange.cancel(pending.order.id)
        vetoes = self.exchange.submit(
            Order(
                symbol=symbol,
                side="SELL" if position.quantity > 0 else "BUY",
                product="MIS",
                quantity=abs(position.quantity),
                signal_at=at,
                reduce_only=True,
            ),
            price,
            context,
        )
        self.closes.append(
            {"symbol": symbol, "at": at.isoformat(), "reason": reason, "vetoes": vetoes}
        )

    def advance(self, bar: Candle, context: RiskContext, expiry_minutes: int) -> None:
        for pending in self.exchange.orders.values():
            if (
                not pending.order.reduce_only
                and pending.status in {"OPEN", "PARTIAL"}
                and (bar.opened_at - pending.order.signal_at >= timedelta(minutes=expiry_minutes))
            ):
                self.exchange.cancel(pending.order.id)
        position = self.exchange.portfolio.positions.get((bar.symbol, "MIS"))
        if position and bar.opened_at >= position.opened_at + timedelta(
            minutes=self.settings.auto_paper.max_hold_minutes
        ):
            self.close(bar.symbol, bar.opened_at, bar.open, context, "MAX_HOLD_EXIT")
        fills = self.exchange.process(bar, context.atr)
        if (
            any(fill.reason != "ENTRY" for fill in fills)
            and (bar.symbol, "MIS") not in self.exchange.portfolio.positions
        ):
            for pending in self.exchange.orders.values():
                if pending.order.symbol == bar.symbol and pending.status in {"OPEN", "PARTIAL"}:
                    self.exchange.cancel(pending.order.id)

    def end_batch(self) -> None:
        fills = self.exchange.end_batch()
        closed = {fill.symbol for fill in fills if fill.reason != "ENTRY"}
        for pending in self.exchange.orders.values():
            symbol = pending.order.symbol
            if (
                symbol in closed
                and (symbol, "MIS") not in self.exchange.portfolio.positions
                and pending.status in {"OPEN", "PARTIAL"}
            ):
                self.exchange.cancel(pending.order.id)

    def act(
        self,
        snapshot: FeatureSnapshot,
        direction: str,
        context: RiskContext,
        at: datetime,
        reason: str,
    ) -> None:
        p = self.exchange.portfolio
        position = p.positions.get((snapshot.symbol, "MIS"))
        event: dict[str, Any] = {
            "symbol": snapshot.symbol,
            "at": at.isoformat(),
            "direction": direction,
            "reason": reason,
            "vetoes": [],
        }
        if direction != "HOLD":
            long = direction == "LONG"
            price = Decimal(str(snapshot.values["ltp"]))
            if position:
                if long != (position.quantity > 0):
                    self.close(snapshot.symbol, at, price, context, "OPPOSITE_SIGNAL")
                    event["action"] = "OPPOSITE_EXIT"
                else:
                    event["action"] = "KEEP_POSITION"
            else:
                atr = Decimal(str(snapshot.values["atr"]))
                size = self.exchange.risk.size(p, price, atr)
                if size > 0:
                    distance = atr * self.settings.risk.atr_stop_multiple
                    sign = Decimal(1 if long else -1)
                    request = Order(
                        symbol=snapshot.symbol,
                        side="BUY" if long else "SELL",
                        product="MIS",
                        quantity=size,
                        signal_at=at,
                        stop_price=price - sign * distance,
                        target_price=price + sign * distance * self.settings.risk.reward_risk_ratio,
                    )
                    event["vetoes"] = self.exchange.submit(request, price, context)
        self.decisions.append(event)

    def portfolio_features(self, snapshot: FeatureSnapshot) -> FeatureSnapshot:
        p = self.exchange.portfolio
        position = p.positions.get((snapshot.symbol, "MIS"))
        state = FeatureEngine(self.settings, self.calendar).state(
            snapshot.symbol,
            snapshot.values,
            snapshot.regime,
            ("LONG" if position.quantity > 0 else "SHORT") if position else "FLAT",
            p.available_cash,
        )
        return replace(snapshot, state=f"Timeframe:{self.frame}|{state}")

    def record(self, at: datetime) -> None:
        p = self.exchange.portfolio
        self.curve.append(
            {
                "at": at.isoformat(),
                "equity": str(p.equity),
                "cash": str(p.cash),
                "realized": str(p.realized_pnl),
                "positions": len(p.positions),
                "exposure": str(p.exposure),
            }
        )

    def report(self) -> dict[str, Any]:
        p = self.exchange.portfolio
        closed: dict[str, Decimal] = defaultdict(Decimal)
        active = {position.entry_order_id for position in p.positions.values()}
        for trade in p.closed_trades:
            closed[str(trade["entry_order_id"])] += Decimal(str(trade["pnl"]))
        outcomes = [net for identifier, net in closed.items() if identifier not in active]
        peak = p.starting_capital
        drawdown = Decimal(0)
        for point in self.curve:
            value = Decimal(point["equity"])
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak * 100)
        checks = {
            "charges": sum((fill.charges.total for fill in p.fills), Decimal(0)) == p.total_charges,
            "realized": abs(
                sum((Decimal(str(t["pnl"])) for t in p.closed_trades), Decimal(0)) - p.realized_pnl
            )
            < Decimal("0.01"),
            "allocated_fees": abs(
                sum((Decimal(str(t["charges"])) for t in p.closed_trades), Decimal(0))
                + sum((pos.entry_charges for pos in p.positions.values()), Decimal(0))
                - p.total_charges
            )
            < Decimal("0.01"),
        }
        if not p.positions:
            checks["flat_cash"] = abs(p.cash - p.starting_capital - p.realized_pnl) < Decimal(
                "0.01"
            )
        return {
            "realized_net_inr": str(p.realized_pnl),
            "marked_net_inr": str(p.equity - p.starting_capital),
            "charges_inr": str(p.total_charges),
            "entries": len({f.order_id for f in p.fills if f.reason == "ENTRY"}),
            "completed_positions": len(outcomes),
            "wins": sum(net > 0 for net in outcomes),
            "max_drawdown_pct": str(drawdown),
            "unresolved_positions": len(p.positions),
            "open_orders": sum(
                v.status in {"OPEN", "PARTIAL"} for v in self.exchange.orders.values()
            ),
            "checks": checks,
            "accounting_passed": all(checks.values()),
            "kill_switch": p.kill_switch,
        }
