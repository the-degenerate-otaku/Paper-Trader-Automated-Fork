import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from paper_trader.engine import Signal
from paper_trader.inference import QUESTIONS
from paper_trader.scenario_lab import LabConfig, LabRunner, Movement, probes, simulate, snapshot


def config(movement=None):
    return LabConfig(
        folds={
            "train": date(2026, 10, 13),
            "validation": date(2026, 10, 14),
            "test": date(2026, 10, 15),
        },
        seeds={"train": 1, "validation": 2, "test": 3},
        probe_offsets=[0],
        movements=[movement or Movement(name="trend", drift_bps=2, noise_bps=0.5)],
    )


def test_lab_inputs_are_deterministic_and_cannot_see_future(settings):
    lab = config()
    case = probes(settings, lab)[0]
    assert probes(settings, lab)[0] == case
    before = snapshot(settings, case)
    future = tuple(
        c.model_copy(update={"high": c.high * 10, "close": c.close * 10}) for c in case.future
    )
    assert snapshot(settings, replace(case, future=future)) == before
    assert case.history[-1].closed_at <= case.future[0].opened_at


def test_gap_and_outage_cases_never_request_model_or_enter(settings, tmp_path, monkeypatch):
    lab = config(Movement(name="gap", drift_bps=1, noise_bps=1, missing_bar=True))
    assert snapshot(settings, probes(settings, lab)[0]) is None

    async def forbidden(*args):
        raise AssertionError("Fault case requested inference")

    monkeypatch.setattr("paper_trader.scenario_lab.SystemOneStrategy.decide", forbidden)
    result = asyncio.run(LabRunner(settings, {}, lab, tmp_path / "cache").run())
    assert all(r["reason"] == "DATA_GAP" and not r["profiles"] for r in result)
    lab = config(Movement(name="outage", drift_bps=1, noise_bps=1, inference_outage=True))
    result = asyncio.run(LabRunner(settings, {}, lab, tmp_path / "cache").run())
    assert all(r["reason"] == "INJECTED_INFERENCE_OUTAGE" and not r["profiles"] for r in result)


def test_laya_failure_is_honest_and_does_not_generate_training_labels(
    settings, tmp_path, monkeypatch
):
    async def failed(self, *args):
        self.healthy = False
        return Signal("HOLD", "INFERENCE_UNAVAILABLE_OR_INVALID", raw={"error": "failed"})

    monkeypatch.setattr("paper_trader.scenario_lab.SystemOneStrategy.decide", failed)
    rows = asyncio.run(LabRunner(settings, {}, config(), tmp_path / "cache").run())
    assert all(r["reason"] == "INFERENCE_UNAVAILABLE_OR_INVALID" and "label" not in r for r in rows)


def test_cost_filter_blocks_small_targets_and_simulation_keeps_money_finite(settings):
    case = probes(settings, config())[0]
    features = snapshot(settings, case)
    baseline = simulate(settings, case, features, "LONG")
    assert baseline["remaining"] == 0
    assert Decimal(baseline["net_inr"]).is_finite()
    filtered = settings.model_copy(deep=True)
    filtered.entry_economics.enabled = True
    result = simulate(filtered, case, features, "LONG")
    assert not result["entered"]
    assert "TARGET_CONSUMED_BY_COSTS" in result["vetoes"]


def test_folds_are_chronological(settings):
    lab = config()
    lab.folds["test"] = lab.folds["train"]
    with pytest.raises(ValueError, match="chronological"):
        probes(settings, lab)


def test_profiles_share_response_and_repeat_runs_reuse_cache(settings, tmp_path, monkeypatch):
    calls = []

    async def reply(self, features, portfolio):
        calls.append(features.state)
        answers = {}
        for name, question in QUESTIONS.items():
            kind = question["type"]
            if kind == "choice":
                labels = list(question["criteria"])
                answers[name] = {
                    "type": kind,
                    "choice": labels[0],
                    "probabilities": dict(zip(labels, [0.8, 0.1, 0.1], strict=True)),
                }
            elif kind == "score":
                answers[name] = {"type": kind, "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}}
            else:
                answers[name] = {"type": kind, "noul": 0.1}
        self.healthy = True
        return Signal(
            "LONG", "ACCEPTED", raw={"response": {"model": "typed-decisions", "answers": answers}}
        )

    monkeypatch.setattr("paper_trader.scenario_lab.SystemOneStrategy.decide", reply)
    candidates = {"same": settings.model_copy(deep=True)}
    rows = asyncio.run(LabRunner(settings, candidates, config(), tmp_path / "cache").run())
    assert len(calls) == 3
    assert all(
        r["profiles"]["baseline"]["net_inr"] == r["profiles"]["same"]["net_inr"] for r in rows
    )
    asyncio.run(LabRunner(settings, candidates, config(), tmp_path / "cache").run())
    assert len(calls) == 3
