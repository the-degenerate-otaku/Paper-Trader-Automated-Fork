from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from paper_trader.config import Settings
from paper_trader.live_paper import SavedPaper
from paper_trader.trading import ChargesCalculator


def read_ledger(path: Path) -> SavedPaper:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT payload_json FROM live_paper_state WHERE id='main'"
        ).fetchone()
    if row is None:
        raise ValueError("No saved paper account")
    return SavedPaper.model_validate_json(row[0])


def trade_reviews(
    path: Path, state: SavedPaper, settings: Settings, day: date
) -> list[dict[str, Any]]:
    from paper_trader.calendar import TradingCalendar

    zone = TradingCalendar.load(settings).zone
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in state.closed_trades:
        if datetime.fromisoformat(trade["closed_at"]).astimezone(zone).date() == day:
            groups[trade["entry_order_id"]].append(trade)
    matched = {}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM live_paper_events WHERE event='auto_decision' "
            "ORDER BY id DESC LIMIT ?",
            (settings.research.max_samples,),
        )
        for (payload,) in rows:
            event = json.loads(payload)
            identifier = event.get("order_id")
            if identifier in groups and identifier not in matched:
                matched[identifier] = event
    result = []
    for identifier, chunks in groups.items():
        decision = matched.get(identifier)
        if not decision or not decision.get("raw", {}).get("request"):
            continue
        net = sum((Decimal(t["pnl"]) for t in chunks), Decimal(0))
        result.append(
            {
                "entry_order_id": identifier,
                "symbol": chunks[0]["symbol"],
                "decision_at": decision["at"],
                "known_at": max(datetime.fromisoformat(t["closed_at"]) for t in chunks).isoformat(),
                "request": decision["raw"]["request"],
                "response": decision["raw"].get("response"),
                "checkpoint_revision": decision.get("model_revision"),
                "config_hash": decision.get("config_hash"),
                "candle_hash": decision.get("candle_hash"),
                "net_inr": str(net),
                "charges_inr": str(sum((Decimal(t["charges"]) for t in chunks), Decimal(0))),
                "taken_trade_profitable": net > 0,
                "opposite_direction_outcome": "unknown",
                "direction_gold_label": None,
                "weight_training_approved": False,
                "source": "recorded_paper_trade_outcome",
                "limitations": "One observed action; recorded fees; opposite outcome unknown.",
            }
        )
    return result


def audit_account(state: SavedPaper, settings: Settings, day: date) -> dict[str, Any]:
    from paper_trader.calendar import TradingCalendar

    zone = TradingCalendar.load(settings).zone
    zero = Decimal(0)

    def money(value: Decimal) -> str:
        return str(value.quantize(Decimal("0.01")))

    closed = state.closed_trades
    checks: dict[str, bool] = {}
    checks["realized_matches_closed_allocations"] = abs(
        sum((Decimal(t["pnl"]) for t in closed), zero) - state.realized_pnl
    ) < Decimal("0.01")
    checks["total_charges_match_fills"] = abs(
        sum((f.charges.total for f in state.fills), zero) - state.total_charges
    ) < Decimal("0.01")
    checks["charges_allocated_exactly_once"] = abs(
        sum((Decimal(t["charges"]) for t in closed), zero)
        + sum((p.entry_charges for p in state.positions), zero)
        - state.total_charges
    ) < Decimal("0.01")
    if not state.positions:
        checks["flat_cash_reconciles"] = abs(
            state.cash - state.starting_capital - state.realized_pnl
        ) < Decimal("0.01")
    by_entry: dict[str, list[dict[str, Any]]] = defaultdict(list)
    close_lookup = {}
    for trade in closed:
        by_entry[trade["entry_order_id"]].append(trade)
        close_lookup[(trade["symbol"], datetime.fromisoformat(trade["closed_at"]))] = trade[
            "entry_order_id"
        ]
    remaining = {p.entry_order_id: abs(p.quantity) for p in state.positions}
    entries: dict[str, int] = defaultdict(int)
    for fill in state.fills:
        if fill.reason == "ENTRY":
            entries[fill.order_id] += fill.quantity
    checks["entry_exit_quantities_reconcile"] = all(
        entries[identifier]
        == sum(t["quantity"] for t in by_entry.get(identifier, [])) + remaining.get(identifier, 0)
        for identifier in set(entries) | set(by_entry) | set(remaining)
    )
    daily = [
        t for t in closed if datetime.fromisoformat(t["closed_at"]).astimezone(zone).date() == day
    ]
    net = sum((Decimal(t["pnl"]) for t in daily), zero)
    charges = sum((Decimal(t["charges"]) for t in daily), zero)
    calculator = ChargesCalculator(settings.charges)
    protection: dict[tuple[str, str, date], tuple[Decimal, Decimal]] = {}
    savings = zero
    corrected_fills = 0
    for fill in state.fills:
        if fill.reason not in {"STOP", "TARGET", "MIS_SQUAREOFF"}:
            continue
        identifier = close_lookup.get((fill.symbol, fill.at))
        if identifier is None:
            raise ValueError("Protective exit cannot be linked to its entry")
        fill_day = fill.at.astimezone(zone).date()
        key = (identifier, fill.reason, fill_day)
        turnover, brokerage = protection.get(key, (zero, zero))
        recalculated = calculator.calculate(
            fill.price * fill.quantity, fill.side, fill.product, fill_day, turnover, brokerage, True
        )
        protection[key] = (
            turnover + fill.price * fill.quantity,
            brokerage + recalculated.items["brokerage"],
        )
        schedule = calculator.schedule(fill_day)
        corrected_gst = (
            recalculated.items["brokerage"]
            + fill.charges.items["exchange"]
            + fill.charges.items["ipft"]
            + fill.charges.items["sebi"]
        ) * schedule.gst_rate
        corrected_gst = corrected_gst.quantize(schedule.money_quantum, rounding=ROUND_HALF_UP)
        delta = (
            fill.charges.items["brokerage"]
            - recalculated.items["brokerage"]
            + fill.charges.items["gst"]
            - corrected_gst
        )
        if fill_day == day:
            savings += delta
            corrected_fills += int(delta != 0)
    groups = [trades for trades in by_entry.values() if any(t in daily for t in trades)]
    outcomes = [sum((Decimal(t["pnl"]) for t in trades), zero) for trades in groups]
    return {
        "day": str(day),
        "checks": checks,
        "passed": all(checks.values()),
        "recorded_net_inr": money(net),
        "recorded_charges_inr": money(charges),
        "recorded_gross_inr": money(net + charges),
        "closed_positions": len(groups),
        "profitable_positions": sum(p > 0 for p in outcomes),
        "losing_positions": sum(p < 0 for p in outcomes),
        "protective_brokerage_gst_difference_inr": money(savings),
        "affected_exit_fills": corrected_fills,
        "fixed_fill_path_counterfactual_net_inr": money(net + savings),
        "counterfactual_is_strategy_replay": False,
        "ledger_modified": False,
        "rounding_policy": "Other taxes retain per-fill rounding; not a broker contract note.",
        "scope": "Same recorded fills, corrected protective-order brokerage and related GST only.",
    }
