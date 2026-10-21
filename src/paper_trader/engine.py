from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import uuid4

import numpy as np

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import quality
from paper_trader.features import FeatureEngine, FeatureSnapshot, closed_atr
from paper_trader.market import Candle, aware
from paper_trader.storage import Database
from paper_trader.trading import Fill, Order, PaperExchange, Portfolio, RiskContext


@dataclass(frozen=True)
class Signal:
    direction: Literal["LONG", "SHORT", "HOLD"]
    reason: str
    model: str = "deterministic-baseline"
    raw: dict[str, object] = field(default_factory=dict)


class Strategy(Protocol):
    async def decide(self, snapshot: FeatureSnapshot, portfolio: Portfolio) -> Signal: ...


class HoldStrategy:
    async def decide(self, snapshot: FeatureSnapshot, portfolio: Portfolio) -> Signal:
        return Signal("HOLD", "HOLD_BASELINE")


class EmaStrategy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def decide(self, snapshot: FeatureSnapshot, portfolio: Portfolio) -> Signal:
        cfg = self.settings.simulation
        fast, slow = (
            snapshot.values.get(f"ema_{cfg.ema_fast}"),
            snapshot.values.get(f"ema_{cfg.ema_slow}"),
        )
        if not isinstance(fast, float) or not isinstance(slow, float) or fast == slow:
            return Signal("HOLD", "EMA_WARMUP")
        return Signal("LONG" if fast > slow else "SHORT", "EXPLICIT_EMA_BASELINE")


@dataclass(frozen=True)
class AppEvent:
    kind: str
    at: datetime
    symbol: str
    payload: dict[str, object]


class ReplayEngine:
    def __init__(
        self,
        settings: Settings,
        calendar: TradingCalendar,
        database: Database,
        candles: tuple[Candle, ...],
        data_versions: dict[str, str],
        strategy: Strategy,
        contexts: dict[str, tuple[str, str]] | None = None,
        shadow: bool = False,
        account_id: str | None = None,
        bot_id: str | None = None,
    ) -> None:
        self.settings, self.calendar, self.database = settings, calendar, database
        self.events = tuple(
            sorted(
                candles, key=lambda c: (c.closed_at, c.symbol not in settings.benchmarks, c.symbol)
            )
        )
        if len({c.identity for c in candles}) != len(candles):
            raise ValueError("Duplicate replay candle")
        self.data_versions = data_versions
        self.strategy = strategy
        with database.connect() as connection:
            instruments = connection.execute(
                "SELECT symbol, sector, instrument_type FROM instruments"
            ).fetchall()
        self.contexts = contexts or {
            row["symbol"]: (row["sector"] or "UNKNOWN", row["instrument_type"])
            for row in instruments
        }
        self.shadow = shadow
        self.run_id = uuid4().hex
        self.account_id = account_id or self.run_id
        self.bot_id = bot_id
        self.exchange = PaperExchange(
            settings, calendar, Portfolio(settings.account.starting_capital_inr)
        )
        self.features = FeatureEngine(settings, calendar)
        self.history: dict[str, deque[Candle]] = defaultdict(
            lambda: deque(maxlen=settings.simulation.history_bars)
        )
        self.log: deque[AppEvent] = deque(maxlen=settings.simulation.max_log_events)
        self.curve: list[dict[str, object]] = []
        self.benchmark_start: dict[str, Decimal] = {}
        self.cursor = 0
        self.clock: datetime | None = None
        self.playing = False
        self.listeners: list[Callable[[AppEvent], None]] = []
        self.entry_metadata: dict[str, dict[str, object]] = {}
        self.latest_features: dict[str, FeatureSnapshot] = {}
        self._start()

    def _start(self) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO accounts VALUES (?, ?, 'INR', ?, ?, ?)",
                (
                    self.account_id,
                    "Paper run",
                    int(self.settings.account.starting_capital_inr * 100),
                    int(self.settings.account.starting_capital_inr * 100),
                    self.events[0].opened_at.isoformat() if self.events else "",
                ),
            )
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (
                    self.run_id,
                    self.settings.model_dump_json(),
                    json.dumps(self.data_versions),
                    self.settings.system_one.checkpoint
                    if self.settings.simulation.strategy == "systemone"
                    else f"baseline:{self.settings.simulation.strategy}",
                    self.settings.simulation.random_seed,
                    self.events[0].opened_at.isoformat() if self.events else "",
                ),
            )
            for schedule in self.settings.charges:
                connection.execute(
                    "INSERT OR IGNORE INTO charges_config VALUES (?, ?, ?, ?)",
                    (
                        schedule.id,
                        str(schedule.effective_date),
                        schedule.model_dump_json(),
                        json.dumps(schedule.sources),
                    ),
                )

    def emit(self, kind: str, candle: Candle, payload: dict[str, object]) -> None:
        event = AppEvent(kind, candle.closed_at, candle.symbol, payload)
        self.log.append(event)
        for listener in self.listeners:
            listener(event)

    def risk_context(self, symbol: str) -> RiskContext:
        bars = tuple(self.history[symbol])
        daily: dict[object, Decimal] = defaultdict(Decimal)
        today = bars[-1].closed_at.astimezone(self.calendar.zone).date()
        for c in bars:
            day = c.opened_at.astimezone(self.calendar.zone).date()
            if day < today:
                daily[day] += c.close * c.volume
        turnover = sum(daily.values(), Decimal(0)) / len(daily) if daily else None
        sector, kind = self.contexts.get(symbol, ("UNKNOWN", "UNKNOWN"))
        correlations = {}
        for position in self.exchange.portfolio.positions.values():
            other = tuple(self.history[position.symbol])
            aligned = {c.closed_at: float(c.close) for c in other}
            pairs = [(float(c.close), aligned[c.closed_at]) for c in bars if c.closed_at in aligned]
            if len(pairs) >= self.settings.features.volatility_period:
                a, b = np.array(pairs).T
                ar, br = np.diff(np.log(a)), np.diff(np.log(b))
                if np.std(ar) > 0 and np.std(br) > 0:
                    correlations[position.symbol] = float(np.corrcoef(ar, br)[0, 1])
        return RiskContext(
            sector=sector,
            atr=closed_atr(bars, self.settings.features.atr_period)
            if self.settings.entry_economics.enabled
            else Decimal(0),
            instrument_type=kind,
            average_turnover=turnover,
            bar_volume=bars[-1].volume,
            correlations=correlations,
            feed_healthy=quality(bars, self.calendar, bars[-1].closed_at).status == "healthy",
        )

    async def step(self) -> AppEvent | None:
        if self.cursor >= len(self.events):
            return None
        candle = self.events[self.cursor]
        self.clock = candle.closed_at
        self.emit("MarketEvent", candle, {"candle": candle.model_dump(mode="json")})
        prior = tuple(self.history[candle.symbol])
        prior_atr = Decimal(0)
        if prior and candle.symbol in self.latest_features:
            snapshot = self.latest_features[candle.symbol]
            if isinstance(snapshot.values["atr"], float):
                prior_atr = Decimal(str(snapshot.values["atr"]))
        fills = self.exchange.process(candle, prior_atr)
        for fill in fills:
            self.emit(
                "FillEvent",
                candle,
                {
                    "order_id": fill.order_id,
                    "price": str(fill.price),
                    "quantity": fill.quantity,
                    "reason": fill.reason,
                },
            )
        self.history[candle.symbol].append(candle)
        benchmark = tuple(self.history.get("NIFTY50", ()))
        bank = tuple(self.history.get("NIFTYBANK", ()))
        state = self.features.calculate(
            tuple(self.history[candle.symbol]),
            candle.closed_at,
            benchmark=benchmark,
            bank_benchmark=bank,
            position="OPEN"
            if any(p.symbol == candle.symbol for p in self.exchange.portfolio.positions.values())
            else "FLAT",
            cash=self.exchange.portfolio.available_cash,
        )
        self.emit("FeatureEvent", candle, {"values": state.values, "state": state.state})
        self.latest_features[candle.symbol] = state
        if self.contexts.get(candle.symbol, ("UNKNOWN", "UNKNOWN"))[1] == "INDEX":
            signal = Signal("HOLD", "REFERENCE_ONLY")
        elif len(self.history[candle.symbol]) < self.settings.data.warmup_bars:
            signal = Signal("HOLD", "WARMUP")
        elif not self.calendar.status(candle.closed_at).can_decide:
            signal = Signal("HOLD", "OUTSIDE_DECISION_WINDOW")
        else:
            signal = await self.strategy.decide(state, self.exchange.portfolio)
        decision_id = uuid4().hex
        vetoes: list[str] = []
        new_order = None
        if signal.direction != "HOLD" and not self.shadow:
            atr_value = state.values["atr"]
            if not isinstance(atr_value, float) or atr_value <= 0:
                vetoes = ["ATR_WARMUP"]
            else:
                atr = Decimal(str(atr_value))
                quantity = self.exchange.risk.size(self.exchange.portfolio, candle.close, atr)
                distance = atr * self.settings.risk.atr_stop_multiple
                long = signal.direction == "LONG"
                stop = candle.close - distance if long else candle.close + distance
                target = candle.close + distance * self.settings.risk.reward_risk_ratio * (
                    1 if long else -1
                )
                if quantity <= 0 or stop <= 0 or target <= 0:
                    vetoes = ["SIZE_OR_PRICE_INVALID"]
                else:
                    new_order = Order(
                        symbol=candle.symbol,
                        side="BUY" if long else "SELL",
                        product=self.settings.simulation.product,
                        quantity=quantity,
                        signal_at=candle.closed_at,
                        stop_price=stop,
                        target_price=target,
                    )
                    vetoes = self.exchange.submit(
                        new_order, candle.close, self.risk_context(candle.symbol)
                    )
                    self.entry_metadata[new_order.id] = {
                        "regime": state.regime,
                        "hour": str(candle.closed_at.astimezone(self.calendar.zone).hour),
                    }
                    self.emit("OrderEvent", candle, {"order_id": new_order.id, "vetoes": vetoes})
        self.emit(
            "DecisionEvent",
            candle,
            {
                "id": decision_id,
                "direction": signal.direction,
                "reason": signal.reason,
                "vetoes": vetoes,
                "shadow": self.shadow,
            },
        )
        self._persist(candle, state, signal, decision_id, vetoes, new_order, fills)
        self.cursor += 1
        point: dict[str, object] = {
            "at": candle.closed_at.isoformat(),
            "equity": str(self.exchange.portfolio.equity),
            "exposure": str(self.exchange.portfolio.exposure),
            "benchmarks": {},
        }
        benchmark_values = {}
        for symbol in set(self.settings.benchmarks) | set(self.history):
            if self.history.get(symbol):
                close = self.history[symbol][-1].close
                self.benchmark_start.setdefault(symbol, close)
                benchmark_values[symbol] = str(
                    close
                    / self.benchmark_start[symbol]
                    * self.settings.account.starting_capital_inr
                )
        point["benchmarks"] = benchmark_values
        if self.curve and self.curve[-1]["at"] == point["at"]:
            self.curve[-1] = point
        else:
            self.curve.append(point)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO run_points VALUES (?, ?, ?, ?, ?)",
                (
                    self.run_id,
                    point["at"],
                    point["equity"],
                    point["exposure"],
                    json.dumps(benchmark_values),
                ),
            )
        return self.log[-1]

    def _persist(
        self,
        candle: Candle,
        state: FeatureSnapshot,
        signal: Signal,
        decision_id: str,
        vetoes: list[str],
        order: Order | None,
        fills: Sequence[Fill],
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    self.run_id,
                    self.bot_id,
                    candle.symbol,
                    candle.closed_at.isoformat(),
                    state.state,
                    json.dumps(state.values, allow_nan=False),
                    signal.direction if not vetoes else "VETO",
                    json.dumps(vetoes),
                    signal.model,
                ),
            )
            if signal.raw:
                connection.execute(
                    "INSERT INTO model_outputs "
                    "(decision_id, request_json, response_json, latency_ms, error, "
                    "checkpoint_revision) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        decision_id,
                        json.dumps(signal.raw.get("request", {})),
                        json.dumps(signal.raw.get("response", {})),
                        signal.raw.get("latency_ms"),
                        signal.raw.get("error"),
                        signal.raw.get("checkpoint_revision", "unverified"),
                    ),
                )
            connection.execute(
                "INSERT INTO journal (decision_id, created_at, body) VALUES (?, ?, ?)",
                (decision_id, candle.closed_at.isoformat(), signal.reason),
            )
            if order is not None and not vetoes:
                connection.execute(
                    "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        order.id,
                        self.account_id,
                        decision_id,
                        order.symbol,
                        order.side,
                        order.product,
                        order.order_type,
                        order.quantity,
                        "OPEN",
                        order.model_dump_json(),
                        order.signal_at.isoformat(),
                    ),
                )
            for fill in self.exchange.portfolio.fills[-len(fills) :] if fills else []:
                connection.execute(
                    "INSERT OR IGNORE INTO orders VALUES "
                    "(?, ?, NULL, ?, ?, ?, 'MARKET', ?, 'FILLED', '{}', ?)",
                    (
                        fill.order_id,
                        self.account_id,
                        fill.symbol,
                        fill.side,
                        fill.product,
                        fill.quantity,
                        fill.at.isoformat(),
                    ),
                )
                connection.execute(
                    "INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        uuid4().hex,
                        fill.order_id,
                        fill.at.isoformat(),
                        fill.quantity,
                        str(fill.price),
                        int(fill.charges.total * 100),
                        json.dumps({k: str(v) for k, v in fill.charges.items.items()}),
                        fill.charges.schedule_id,
                    ),
                )
            for pending in self.exchange.orders.values():
                connection.execute(
                    "UPDATE orders SET status=? WHERE id=?", (pending.status, pending.order.id)
                )
            connection.execute("DELETE FROM positions WHERE account_id=?", (self.account_id,))
            for p in self.exchange.portfolio.positions.values():
                connection.execute(
                    "INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        self.account_id,
                        p.symbol,
                        p.product,
                        p.quantity,
                        str(p.average_price),
                        str(p.stop_price),
                        str(p.target_price) if p.target_price else None,
                    ),
                )
            connection.execute(
                "UPDATE accounts SET cash_paise=? WHERE id=?",
                (int(self.exchange.portfolio.cash * 100), self.account_id),
            )

    async def run(self) -> dict[str, object]:
        while await self.step() is not None:
            pass
        return self.finish()

    async def play(self, speed: float = 1) -> None:
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("Replay speed must be finite and positive")
        self.playing = True
        while self.playing and await self.step() is not None:
            await asyncio.sleep(1 / speed)
        self.playing = False

    def pause(self) -> None:
        self.playing = False

    async def jump(self, at: datetime) -> None:
        target = aware(at)
        if self.clock and target < self.clock:
            raise ValueError("Rewind requires a fresh run to preserve ledger history")
        while self.cursor < len(self.events) and self.events[self.cursor].closed_at <= target:
            await self.step()

    def finish(self) -> dict[str, object]:
        for trade in self.exchange.portfolio.closed_trades:
            trade.update(self.entry_metadata.get(str(trade["entry_order_id"]), {}))
        result = metrics(self.curve, self.exchange.portfolio, self.settings)
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE runs SET ended_at=? WHERE id=?",
                (self.clock.isoformat() if self.clock else "", self.run_id),
            )
            connection.execute("DELETE FROM metrics WHERE run_id=?", (self.run_id,))
            for key, value in result.items():
                if value is None or isinstance(value, (int, float)):
                    connection.execute(
                        "INSERT INTO metrics VALUES (?, ?, '{}', ?)", (self.run_id, key, value)
                    )
            for trade in self.exchange.portfolio.closed_trades:
                connection.execute(
                    "INSERT OR REPLACE INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{self.run_id}:{trade['entry_order_id']}:{trade['closed_at']}",
                        self.account_id,
                        trade["symbol"],
                        trade["opened_at"],
                        trade["closed_at"],
                        int(Decimal(str(trade["pnl"])) * 100),
                        trade["reason"],
                        json.dumps(trade),
                    ),
                )
        return {
            "run_id": self.run_id,
            "metrics": result,
            "curve": self.curve,
            "trades": self.exchange.portfolio.closed_trades,
            "open_positions": len(self.exchange.portfolio.positions),
            "charges": str(self.exchange.portfolio.total_charges),
        }


def metrics(
    curve: list[dict[str, object]], portfolio: Portfolio, settings: Settings
) -> dict[str, object]:
    curve = list(
        {aware(datetime.fromisoformat(str(point["at"]))): point for point in curve}.values()
    )
    initial = float(portfolio.starting_capital)
    equity = np.array([initial, *[float(str(p["equity"])) for p in curve]])
    peaks = np.maximum.accumulate(equity)
    drawdowns = (peaks - equity) / peaks
    daily = {}
    for point in curve:
        day = (
            datetime.fromisoformat(str(point["at"]))
            .astimezone(TradingCalendar.load(settings).zone)
            .date()
        )
        daily[day] = float(str(point["equity"]))
    daily_equity = np.array([initial, *daily.values()])
    returns = np.diff(daily_equity) / daily_equity[:-1]
    days = (max(daily) - min(daily)).days + 1 if daily else 0
    years = days / settings.simulation.calendar_days_per_year if days else 0
    try:
        annual = (
            math.expm1(math.log(equity[-1] / initial) / years)
            if years > 0 and equity[-1] > 0
            else None
        )
    except OverflowError:
        annual = None
    rf = float(settings.risk_free_rate_pct) / 100 / settings.simulation.trading_days_per_year
    excess = returns - rf
    std = float(np.std(excess, ddof=1)) if len(excess) > 1 else 0
    downside = float(np.sqrt(np.mean(np.minimum(excess, 0) ** 2))) if len(excess) else 0
    annualizer = math.sqrt(settings.simulation.trading_days_per_year)
    pnl = np.array([float(str(t["pnl"])) for t in portfolio.closed_trades])
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gross = sum(
        (float(str(t["pnl"])) + float(str(t["charges"])) for t in portfolio.closed_trades), 0.0
    )
    duration = longest = 0
    for dd in drawdowns:
        duration = duration + 1 if dd > 0 else 0
        longest = max(longest, duration)
    breakdowns: dict[str, dict[str, dict[str, float]]] = {}
    for dimension in ("symbol", "regime", "hour"):
        grouped: dict[str, dict[str, float]] = {}
        for trade in portfolio.closed_trades:
            key = str(trade.get(dimension, "UNKNOWN"))
            group = grouped.setdefault(key, {"count": 0, "pnl_inr": 0})
            group["count"] += 1
            group["pnl_inr"] += float(str(trade["pnl"]))
        breakdowns[dimension] = grouped
    result: dict[str, object] = {
        "total_return_pct": (equity[-1] / initial - 1) * 100,
        "annualized_return_pct": annual * 100 if annual is not None else None,
        "cagr_pct": annual * 100 if annual is not None else None,
        "sharpe": float(excess.mean()) / std * annualizer if std else None,
        "sortino": float(excess.mean()) / downside * annualizer if downside else None,
        "calmar": annual / float(drawdowns.max())
        if annual is not None and drawdowns.max()
        else None,
        "max_drawdown_pct": float(drawdowns.max()) * 100,
        "drawdown_duration_bars": longest,
        "win_rate_pct": len(wins) / len(pnl) * 100 if len(pnl) else None,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) else None,
        "expectancy_inr": float(pnl.mean()) if len(pnl) else None,
        "average_win_inr": float(wins.mean()) if len(wins) else None,
        "average_loss_inr": float(losses.mean()) if len(losses) else None,
        "exposure_pct": float(
            np.mean(
                [
                    float(str(p["exposure"])) / float(str(p["equity"])) * 100
                    for p in curve
                    if float(str(p["equity"])) > 0
                ]
            )
        )
        if curve
        else 0,
        "turnover": float(
            sum((f.price * f.quantity for f in portfolio.fills), Decimal(0))
            / portfolio.starting_capital
        ),
        "total_charges_inr": float(portfolio.total_charges),
        "charges_pct_gross_pnl": float(portfolio.total_charges) / gross * 100
        if gross > 0
        else None,
        "closed_trade_count": len(pnl),
        "breakdowns": breakdowns,
    }
    return {
        key: None if isinstance(value, float) and not math.isfinite(value) else value
        for key, value in result.items()
    }
