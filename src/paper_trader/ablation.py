from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np

from paper_trader.config import Settings
from paper_trader.features import FeatureSnapshot
from paper_trader.inference import SystemOneStrategy
from paper_trader.scenario_lab import Probe, simulate

ARMS = ("no_trade", "ema", "laya", "ema_laya_filter")


def directions(
    settings: Settings, features: FeatureSnapshot, response: object
) -> tuple[dict[str, str], str]:
    fast = features.values.get(f"ema_{settings.simulation.ema_fast}")
    slow = features.values.get(f"ema_{settings.simulation.ema_slow}")
    ema = "HOLD"
    if (
        isinstance(fast, float)
        and isinstance(slow, float)
        and math.isfinite(fast)
        and math.isfinite(slow)
        and fast != slow
    ):
        ema = "LONG" if fast > slow else "SHORT"
    laya, reason = "HOLD", "INFERENCE_UNAVAILABLE_OR_INVALID"
    try:
        if not isinstance(response, dict) or response.get("model") not in {
            settings.system_one.checkpoint,
            *settings.system_one.accepted_response_models,
        }:
            raise ValueError("Missing or mismatched model response")
        routing = response.get("routing")
        if routing is not None and (
            not isinstance(routing, dict) or routing.get("model") != settings.system_one.checkpoint
        ):
            raise ValueError("Wrong routed checkpoint")
        signal = SystemOneStrategy(settings).policy(response, {})
        laya, reason = signal.direction, signal.reason
    except (KeyError, ValueError, TypeError, OverflowError):
        pass
    return {
        "no_trade": "HOLD",
        "ema": ema,
        "laya": laya,
        "ema_laya_filter": ema if ema == laya else "HOLD",
    }, reason


def compare(
    settings: Settings,
    probe: Probe,
    features: FeatureSnapshot,
    response: object,
    decision_at: datetime | None = None,
) -> dict[str, Any]:
    chosen, reason = directions(settings, features, response)
    outcomes = {
        name: {
            "direction": direction,
            **simulate(settings, probe, features, direction, decision_at),
        }
        for name, direction in chosen.items()
    }
    return {
        "arms": outcomes,
        "laya_reason": reason,
        "paired_resolved": all(result["net_inr"] is not None for result in outcomes.values()),
    }


def select_events(
    events: list[dict[str, Any]], separation: timedelta
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    latest = {}
    excluded: Counter[str] = Counter()
    for event in events:
        if event.get("reason") == "INFERENCE_PENDING":
            excluded["pending_records"] += 1
            continue
        if event.get("action") != "ENTRY_REVIEW" or "|Position:FLAT|" not in event.get("state", ""):
            excluded["non_entry_or_legacy_context"] += 1
            continue
        key = event["symbol"], event["bar_at"]
        if key in latest:
            excluded["duplicate_final_records"] += 1
        latest[key] = event
    selected = []
    next_at: dict[str, datetime] = {}
    for event in sorted(latest.values(), key=lambda item: (item["at"], item["symbol"])):
        at = datetime.fromisoformat(event["at"])
        symbol = event["symbol"]
        if symbol in next_at and at < next_at[symbol]:
            excluded["overlapping_symbol_window"] += 1
            continue
        selected.append(event)
        next_at[symbol] = at + separation
    return selected, dict(excluded)


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paired = [row for row in rows if row["paired_resolved"]]
    arms = {}
    for name in ARMS:
        results = [row["arms"][name] for row in paired]
        nets = [Decimal(result["net_inr"]) for result in results]
        gains = sum((net for net in nets if net > 0), Decimal(0))
        losses = -sum((net for net in nets if net < 0), Decimal(0))
        arms[name] = {
            "trials": len(paired),
            "entries": sum(result["entered"] for result in results),
            "wins": sum(net > 0 for net in nets),
            "net_sum_inr": str(sum(nets, Decimal(0))),
            "charges_inr": str(
                sum((Decimal(result["charges_inr"]) for result in results), Decimal(0))
            ),
            "profit_factor": float(gains / losses) if losses else None,
            "vetoes": dict(Counter(v for result in results for v in result["vetoes"])),
        }
    daily: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in paired:
        for name in ARMS:
            daily[row["group"]][name] += Decimal(row["arms"][name]["net_inr"])
    deltas = {}
    for name in ("laya", "ema_laya_filter"):
        differences = [
            Decimal(row["arms"][name]["net_inr"]) - Decimal(row["arms"]["ema"]["net_inr"])
            for row in paired
        ]
        deltas[name] = {
            "incremental_net_vs_ema_inr": str(sum(differences, Decimal(0))),
            "better_trials": sum(value > 0 for value in differences),
            "worse_trials": sum(value < 0 for value in differences),
            "tied_trials": sum(value == 0 for value in differences),
        }
    return {
        "paired_resolved_trials": len(paired),
        "unresolved_pairs_excluded": len(rows) - len(paired),
        "arms": arms,
        "paired_comparisons": deltas,
        "by_group": {
            group: {name: str(value) for name, value in values.items()}
            for group, values in daily.items()
        },
        "laya_reasons": dict(Counter(row["laya_reason"] for row in rows)),
        "interpretation": "Independent trials; not portfolio returns or a significance test.",
    }


def frequency_controls(rows: list[dict[str, Any]], resamples: int, seed: int) -> dict[str, Any]:
    paired = [row for row in rows if row["paired_resolved"]]
    candidates = [
        Decimal(row["arms"]["ema"]["net_inr"]) for row in paired if row["arms"]["ema"]["entered"]
    ]
    result = {}
    for name in ("laya", "ema_laya_filter"):
        trades = [row["arms"][name] for row in paired if row["arms"][name]["entered"]]
        n = len(trades)
        actual = sum((Decimal(trade["net_inr"]) for trade in trades), Decimal(0))
        if n == 0 or n > len(candidates):
            result[name] = {"matched_entries": n, "reason": "No comparable nonempty trade count"}
            continue
        rng = np.random.default_rng(seed)
        draws = np.array(
            [
                sum(
                    float(candidates[int(index)])
                    for index in rng.choice(len(candidates), n, replace=False)
                )
                for _ in range(resamples)
            ]
        )
        expected = sum(candidates, Decimal(0)) * n / len(candidates)
        result[name] = {
            "matched_entries": n,
            "ema_entry_pool": len(candidates),
            "actual_net_inr": str(actual.quantize(Decimal("0.01"))),
            "random_ema_expected_net_inr": str(expected.quantize(Decimal("0.01"))),
            "random_ema_net_p05_inr": round(float(np.percentile(draws, 5)), 2),
            "random_ema_net_p95_inr": round(float(np.percentile(draws, 95)), 2),
            "fraction_random_controls_at_least_as_good": float(np.mean(draws >= float(actual))),
            "resamples": resamples,
            "seed": seed,
        }
    return {
        "arms": result,
        "interpretation": "Exploratory thinning without replacement; not a significance test.",
    }
