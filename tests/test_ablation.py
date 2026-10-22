from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from test_scenario_lab import config

from paper_trader.ablation import compare, directions, frequency_controls, select_events, summary
from paper_trader.engine import EmaStrategy
from paper_trader.scenario_lab import Movement, probes, simulate, snapshot
from paper_trader.trading import Portfolio


def test_ema_ablation_matches_existing_strategy_without_future_inputs(settings):
    import asyncio

    case = probes(settings, config())[0]
    features = snapshot(settings, case)
    chosen, reason = directions(settings, features, None)
    signal = asyncio.run(EmaStrategy(settings).decide(features, Portfolio(Decimal(1000000))))
    assert chosen["ema"] == signal.direction
    assert chosen["laya"] == chosen["ema_laya_filter"] == "HOLD"
    assert reason == "INFERENCE_UNAVAILABLE_OR_INVALID"
    altered = replace(features, values={**features.values, "ema_9": float("nan")})
    assert directions(settings, altered, None)[0]["ema"] == "HOLD"


def test_simulator_uses_real_symbol_and_does_not_fill_before_decision(settings):
    case = probes(settings, config(Movement(name="volatile", drift_bps=2, noise_bps=8)))[0]
    case = replace(
        case,
        history=tuple(bar.model_copy(update={"symbol": "SAMPLE"}) for bar in case.history),
        future=tuple(bar.model_copy(update={"symbol": "SAMPLE"}) for bar in case.future),
    )
    features = snapshot(settings, case)
    assert features.symbol == "SAMPLE"
    result = simulate(settings, case, features, "LONG")
    assert result["entered"]
    assert result["net_inr"] is not None
    delayed = simulate(settings, case, features, "LONG", case.future[-1].closed_at)
    assert not delayed["entered"]
    assert delayed["net_inr"] == "0"


def test_unavailable_model_does_not_block_rule_control_and_cannot_create_ai_trade(settings):
    case = probes(settings, config())[0]
    features = snapshot(settings, case)
    result = compare(settings, case, features, {"model": "wrong-model"})
    assert result["arms"]["ema"]["direction"] != "HOLD"
    for arm in ("laya", "ema_laya_filter", "no_trade"):
        assert not result["arms"][arm]["entered"]


def test_sample_selection_is_independent_of_model_response_and_future_pnl():
    from datetime import UTC, datetime

    at = datetime(2026, 10, 22, 8, tzinfo=UTC)
    events = [
        {
            "symbol": "SAMPLE",
            "at": (at + timedelta(minutes=i)).isoformat(),
            "bar_at": (at + timedelta(minutes=i)).isoformat(),
            "action": "ENTRY_REVIEW",
            "state": "Asset:SAMPLE|Position:FLAT|CashINR:100",
            "reason": reason,
        }
        for i, reason in ((0, "INFERENCE_PENDING"), (0, "ACCEPTED"), (1, "FAILED"), (30, "FAILED"))
    ]
    chosen, exclusions = select_events(events, timedelta(minutes=30))
    assert len(chosen) == 2
    assert exclusions == {"pending_records": 1, "overlapping_symbol_window": 1}
    changed = [{**event, "response": {"LONG": 0.99}, "future_pnl": 999} for event in events]
    assert [event["at"] for event in select_events(changed, timedelta(minutes=30))[0]] == [
        event["at"] for event in chosen
    ]


def test_unresolved_pairs_are_excluded_for_every_arm(settings):
    case = probes(settings, config())[0]
    features = snapshot(settings, case)
    result = {"group": "test", **compare(settings, case, features, None)}
    result["paired_resolved"] = False
    report = summary([result])
    assert report["unresolved_pairs_excluded"] == 1
    assert all(arm["trials"] == 0 for arm in report["arms"].values())


def test_filter_never_reverses_rule_direction(settings, monkeypatch):
    from paper_trader.engine import Signal

    case = probes(settings, config())[0]
    features = snapshot(settings, case)
    ema = directions(settings, features, None)[0]["ema"]
    response = {"model": settings.system_one.checkpoint}
    monkeypatch.setattr(
        "paper_trader.ablation.SystemOneStrategy.policy",
        lambda *args: Signal("SHORT" if ema == "LONG" else "LONG", "ACCEPTED"),
    )
    assert directions(settings, features, response)[0]["ema_laya_filter"] == "HOLD"
    monkeypatch.setattr(
        "paper_trader.ablation.SystemOneStrategy.policy", lambda *args: Signal(ema, "ACCEPTED")
    )
    assert directions(settings, features, response)[0]["ema_laya_filter"] == ema


def test_trade_count_control_does_not_reward_abstaining_as_an_edge():
    rows = []
    for i, net in enumerate(("-100", "-200", "-300")):
        arms = {
            "ema": {"entered": True, "net_inr": net},
            "laya": {"entered": i == 2, "net_inr": net if i == 2 else "0"},
            "ema_laya_filter": {"entered": False, "net_inr": "0"},
        }
        rows.append({"paired_resolved": True, "arms": arms})
    report = frequency_controls(rows, 100, 7)
    assert report == frequency_controls(rows, 100, 7)
    assert report["arms"]["laya"]["random_ema_expected_net_inr"] == "-200.00"
    assert report["arms"]["laya"]["fraction_random_controls_at_least_as_good"] == 1
    assert "reason" in report["arms"]["ema_laya_filter"]
