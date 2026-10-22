from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import numpy as np
from pydantic import Field

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Section, Settings
from paper_trader.data import quality
from paper_trader.features import FeatureEngine, FeatureSnapshot
from paper_trader.inference import QUESTIONS, SystemOneStrategy, distribution
from paper_trader.market import Candle
from paper_trader.trading import Order, PaperExchange, Portfolio, RiskContext


class Movement(Section):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    drift_bps: float = Field(ge=-100, le=100, allow_inf_nan=False)
    noise_bps: float = Field(ge=0, le=100, allow_inf_nan=False)
    shock_bps: float = Field(default=0, ge=-1000, le=1000, allow_inf_nan=False)
    reverse_after_shock: bool = False
    volume: int = Field(default=10000, ge=1, le=10000000)
    missing_bar: bool = False
    inference_outage: bool = False
    slippage_factor: Decimal = Field(default=Decimal(1), ge=1, le=10)


class LabConfig(Section):
    warmup: int = Field(default=220, ge=200, le=240)
    probe_offsets: list[int] = Field(default_factory=lambda: [0, 20], min_length=1, max_length=5)
    horizon: int = Field(default=30, ge=20, le=60)
    initial_price: Decimal = Field(default=Decimal(1000), gt=100, le=10000)
    inference_timeout_ms: int = Field(default=30000, ge=5000, le=60000)
    candidate_net_reward_risk: Decimal = Field(default=Decimal(1), ge=0, le=5)
    candidate_target_cost_multiple: Decimal = Field(default=Decimal(2), ge=1, le=10)
    candidate_port: int = Field(default=2084, ge=1024, le=65535)
    folds: dict[str, date]
    seeds: dict[str, int]
    movements: list[Movement] = Field(min_length=1, max_length=30)


@dataclass(frozen=True)
class Probe:
    fold: str
    scenario: str
    offset: int
    history: tuple[Candle, ...]
    future: tuple[Candle, ...]
    movement: Movement


def generate(
    settings: Settings, lab: LabConfig, movement: Movement, fold: str
) -> tuple[Candle, ...]:
    day = lab.folds[fold]
    calendar = TradingCalendar.load(settings)
    start = datetime.combine(day, time(9, 15), calendar.zone)
    if calendar.status(start + timedelta(minutes=lab.warmup)).phase != "open":
        raise ValueError("Lab fold must be an open configured trading day")
    digest = hashlib.sha256(f"{lab.seeds[fold]}:{movement.name}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8]))
    price = lab.initial_price
    bars = []
    count = lab.warmup + max(lab.probe_offsets) + lab.horizon
    for i in range(count):
        shock = movement.shock_bps if i == lab.warmup - 3 else 0
        opened = price * (1 + Decimal(str(shock)) / 10000)
        drift = movement.drift_bps
        if movement.reverse_after_shock and i >= lab.warmup - 3:
            drift = -drift
        change = Decimal(str(drift + rng.normal(0, movement.noise_bps))) / 10000
        price = opened * (1 + change)
        wick = Decimal(str(abs(rng.normal(0, movement.noise_bps / 2)))) / 10000
        at = start + timedelta(minutes=i)
        if movement.missing_bar and i == lab.warmup - 2:
            continue
        bars.append(
            Candle(
                symbol="LAB",
                timeframe="1m",
                opened_at=at,
                closed_at=at + timedelta(minutes=1),
                open=opened,
                high=max(opened, price) * (1 + wick),
                low=min(opened, price) * (1 - wick),
                close=price,
                volume=max(1, int(movement.volume * rng.uniform(0.8, 1.2))),
                source="synthetic_scenario_lab_v1",
            )
        )
    return tuple(bars)


def probes(settings: Settings, lab: LabConfig) -> list[Probe]:
    if set(lab.folds) != {"train", "validation", "test"} or set(lab.seeds) != set(lab.folds):
        raise ValueError("Lab requires train, validation and untouched test folds")
    if not lab.folds["train"] < lab.folds["validation"] < lab.folds["test"]:
        raise ValueError("Lab folds must be chronological")
    if len({m.name for m in lab.movements}) != len(lab.movements):
        raise ValueError("Scenario names must be unique")
    if any(offset < 0 or offset > 40 for offset in lab.probe_offsets):
        raise ValueError("Probe offsets exceed bounded session window")
    result = []
    calendar = TradingCalendar.load(settings)
    for fold in lab.folds:
        for movement in lab.movements:
            bars = generate(settings, lab, movement, fold)
            for offset in lab.probe_offsets:
                at = datetime.combine(lab.folds[fold], time(9, 15), calendar.zone) + timedelta(
                    minutes=lab.warmup + offset
                )
                result.append(
                    Probe(
                        fold,
                        movement.name,
                        offset,
                        tuple(b for b in bars if b.closed_at <= at),
                        tuple(b for b in bars if b.opened_at >= at),
                        movement,
                    )
                )
    return result


def snapshot(settings: Settings, probe: Probe) -> FeatureSnapshot | None:
    calendar = TradingCalendar.load(settings)
    recent = probe.history[-settings.data.warmup_bars :]
    if (
        len(recent) < settings.data.warmup_bars
        or quality(recent, calendar, probe.history[-1].closed_at).status != "healthy"
    ):
        return None
    return FeatureEngine(settings, calendar).calculate(
        probe.history, probe.history[-1].closed_at, cash=settings.account.starting_capital_inr
    )


def simulate(
    settings: Settings,
    probe: Probe,
    features: FeatureSnapshot,
    direction: str,
    decision_at: datetime | None = None,
) -> dict[str, Any]:
    config = settings.model_copy(deep=True)
    config.execution.slippage_bps *= probe.movement.slippage_factor
    calendar = TradingCalendar.load(config)
    book = Portfolio(config.account.starting_capital_inr)
    exchange = PaperExchange(config, calendar, book)
    atr = Decimal(str(features.values["atr"]))
    price = Decimal(str(features.values["ltp"]))
    symbol = features.symbol
    long = direction == "LONG"
    sign = Decimal(1 if long else -1)
    context = RiskContext(
        sector="SYNTHETIC",
        average_turnover=Decimal(1000000000),
        bar_volume=probe.history[-1].volume,
        atr=atr,
    )
    size = exchange.risk.size(book, price, atr)
    if direction == "HOLD" or size <= 0:
        return {
            "entered": False,
            "net_inr": "0",
            "gross_inr": "0",
            "charges_inr": "0",
            "remaining": 0,
            "vetoes": [],
        }
    distance = atr * config.risk.atr_stop_multiple
    request = Order(
        symbol=symbol,
        side="BUY" if long else "SELL",
        product="MIS",
        quantity=size,
        signal_at=decision_at or features.at,
        stop_price=price - sign * distance,
        target_price=price + sign * distance * config.risk.reward_risk_ratio,
    )
    vetoes = exchange.submit(request, price, context)
    if vetoes:
        return {
            "entered": False,
            "net_inr": "0",
            "gross_inr": "0",
            "charges_inr": "0",
            "remaining": 0,
            "vetoes": vetoes,
        }
    hold = timedelta(minutes=config.auto_paper.max_hold_minutes)
    for bar in probe.future:
        if decision_at is not None and bar.opened_at < decision_at:
            continue
        position = book.positions.get((symbol, "MIS"))
        if position is not None and bar.opened_at >= position.opened_at + hold:
            exchange.cancel(request.id)
            if not any(
                p.order.reduce_only and p.status in {"OPEN", "PARTIAL"}
                for p in exchange.orders.values()
            ):
                exchange.submit(
                    Order(
                        symbol=symbol,
                        side="SELL" if position.quantity > 0 else "BUY",
                        product="MIS",
                        quantity=abs(position.quantity),
                        signal_at=bar.opened_at,
                        reduce_only=True,
                    ),
                    bar.open,
                    context,
                )
        exchange.process(bar, atr)
        if not book.positions and book.fills:
            exchange.cancel(request.id)
            break
    remaining = sum(abs(p.quantity) for p in book.positions.values())
    net = book.realized_pnl if not remaining else None
    return {
        "entered": bool(book.fills),
        "net_inr": str(net) if net is not None else None,
        "gross_inr": str(net + book.total_charges) if net is not None else None,
        "charges_inr": str(book.total_charges),
        "remaining": remaining,
        "vetoes": [
            str(r)
            for event in exchange.veto_log
            if isinstance(event.get("reasons"), list)
            for r in cast(list[object], event["reasons"])
        ],
        "partial_fills": len(book.fills),
        "exit_reasons": [f.reason for f in book.fills if f.reason != "ENTRY"],
    }


@dataclass
class LabRunner:
    baseline: Settings
    candidates: dict[str, Settings]
    config: LabConfig
    cache_dir: Path
    results: list[dict[str, Any]] = field(default_factory=list)

    async def run(self) -> list[dict[str, Any]]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        inference = self.baseline.model_copy(deep=True)
        inference.system_one.timeout_ms = self.config.inference_timeout_ms
        strategy = SystemOneStrategy(inference)
        for index, probe in enumerate(probes(self.baseline, self.config)):
            features = snapshot(self.baseline, probe)
            row: dict[str, Any] = {
                "fold": probe.fold,
                "scenario": probe.scenario,
                "offset": probe.offset,
                "synthetic": True,
                "weights_trained": False,
                "profiles": {},
            }
            if features is None or probe.movement.inference_outage:
                row["reason"] = "DATA_GAP" if features is None else "INJECTED_INFERENCE_OUTAGE"
                self.results.append(row)
                continue
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "state": features.state,
                        "questions": QUESTIONS,
                        "checkpoint": inference.system_one.model_dump(mode="json"),
                        "at": features.at.isoformat(),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            cache = self.cache_dir / f"{fingerprint}.json"
            if cache.exists():
                raw = json.loads(cache.read_text(encoding="utf-8"))
                response = raw.get("response")
            else:
                signal = await strategy.decide(
                    features, Portfolio(inference.account.starting_capital_inr)
                )
                raw = signal.raw
                response = raw.get("response")
                if strategy.healthy and response is not None:
                    cache.write_text(json.dumps(raw, allow_nan=False), encoding="utf-8")
                elif not strategy.healthy:
                    response = None
            row.update(
                at=features.at.isoformat(),
                known_at=probe.future[-1].closed_at.isoformat(),
                state=features.state,
                feature_hash=hashlib.sha256(
                    json.dumps(features.values, sort_keys=True).encode()
                ).hexdigest(),
                cache_key=fingerprint,
                response=response,
                latency_ms=raw.get("latency_ms"),
            )
            if not isinstance(response, dict):
                row["reason"] = "INFERENCE_UNAVAILABLE_OR_INVALID"
                self.results.append(row)
                print(
                    f"{index + 1}: {probe.fold}/{probe.scenario}: inference unavailable", flush=True
                )
                continue
            try:
                strategy.policy(response, {})
                if response.get("model") not in {
                    inference.system_one.checkpoint,
                    *inference.system_one.accepted_response_models,
                }:
                    raise ValueError("Cached checkpoint mismatch")
                row["probabilities"] = distribution(
                    response["answers"]["direction"], {"LONG", "SHORT", "NEUTRAL"}, 1
                )
            except (KeyError, ValueError, TypeError):
                row["reason"] = "INFERENCE_UNAVAILABLE_OR_INVALID"
                self.results.append(row)
                continue
            for name, profile in {"baseline": self.baseline, **self.candidates}.items():
                signal = SystemOneStrategy(profile).policy(response, {})
                row["profiles"][name] = {
                    "direction": signal.direction,
                    "reason": signal.reason,
                    **simulate(profile, probe, features, signal.direction),
                }
            labels = {
                direction: simulate(self.baseline, probe, features, direction)
                for direction in ("LONG", "SHORT")
            }
            if all(r["net_inr"] is not None for r in labels.values()):
                best = max(labels, key=lambda direction: Decimal(labels[direction]["net_inr"]))
                row["label"] = best if Decimal(labels[best]["net_inr"]) > 0 else "NEUTRAL"
                row["label_outcomes"] = labels
            else:
                row["label"] = None
            self.results.append(row)
            print(
                f"{index + 1}: {probe.fold}/{probe.scenario}: "
                f"{row['profiles']['baseline']['direction']}",
                flush=True,
            )
            (self.cache_dir.parent / "progress.json").write_text(
                json.dumps(self.results, allow_nan=False), encoding="utf-8"
            )
        return self.results
