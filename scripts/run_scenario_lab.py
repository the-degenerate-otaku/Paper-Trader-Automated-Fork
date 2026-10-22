from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from paper_trader.accounting import audit_account, read_ledger, trade_reviews
from paper_trader.calibration import Outcome, export_rows, fit, nll
from paper_trader.config import Settings, load_settings
from paper_trader.scenario_lab import LabConfig, LabRunner

ROOT = Path(__file__).resolve().parents[1]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for fold in ("train", "validation", "test"):
        selected = [r for r in rows if r["fold"] == fold]
        names = {name for row in selected for name in row["profiles"]}
        groups = {}
        for name in sorted(names):
            trades = [r["profiles"][name] for r in selected if name in r["profiles"]]
            resolved = [t for t in trades if t["entered"] and t["net_inr"] is not None]
            groups[name] = {
                "independent_trials": len(trades),
                "entered": sum(t["entered"] for t in trades),
                "wins": sum(Decimal(t["net_inr"]) > 0 for t in resolved),
                "trial_net_sum_inr": str(
                    sum((Decimal(t["net_inr"]) for t in resolved), Decimal(0))
                ),
                "charges_sum_inr": str(
                    sum((Decimal(t["charges_inr"]) for t in trades), Decimal(0))
                ),
                "unresolved_positions": sum(t["remaining"] > 0 for t in trades),
                "vetoes": dict(Counter(v for t in trades for v in t["vetoes"])),
            }
        summary[fold] = {
            "profiles": groups,
            "failures": dict(Counter(r["reason"] for r in selected if r.get("reason"))),
            "raw_choices": dict(
                Counter(
                    max(r["probabilities"], key=r["probabilities"].get)
                    for r in selected
                    if r.get("probabilities")
                )
            ),
        }
    return summary


def training_rows(rows: list[dict[str, Any]], settings: Settings) -> list[Outcome]:
    result = []
    for row in rows:
        if row.get("label") is None or row["fold"] == "test":
            continue
        result.append(
            Outcome(
                row["cache_key"],
                datetime.fromisoformat(row["at"]),
                datetime.fromisoformat(row["known_at"]),
                "LAB",
                row["state"],
                row["probabilities"],
                row["label"],
                settings.system_one.checkpoint,
                settings.system_one.checkpoint_revision,
                (row["feature_hash"],),
                {
                    "definition": "Net-positive best direction after costs; next eligible fill; "
                    "stop first; time exit; rejected entries flat; unresolved omitted.",
                    "hold_minutes": settings.auto_paper.max_hold_minutes,
                    "stop_atr": str(settings.risk.atr_stop_multiple),
                    "target_rr": str(settings.risk.reward_risk_ratio),
                },
                ("synthetic_scenario_lab_v1",),
            )
        )
    return result


async def run(output: Path, config_path: Path) -> None:
    if not output.resolve().is_relative_to((ROOT / "work").resolve()):
        raise ValueError("Lab outputs must stay in the private work directory")
    baseline = load_settings(ROOT / "profiles/baseline.yaml", ROOT / "profiles/.unused-env")
    balanced = load_settings(
        ROOT / "profiles/research-balanced.yaml", ROOT / "profiles/.unused-env"
    )
    config = LabConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    cost_only = baseline.model_copy(deep=True)
    cost_only.entry_economics = balanced.entry_economics.model_copy(deep=True)
    cost_covered = balanced.model_copy(deep=True)
    cost_covered.entry_economics.minimum_net_reward_risk = config.candidate_net_reward_risk
    cost_covered.entry_economics.minimum_target_cost_multiple = (
        config.candidate_target_cost_multiple
    )
    if config.candidate_port in {2080, 2081, 2082, 2083, 8000}:
        raise ValueError("Candidate port must remain separate from existing services")
    cost_covered.server.port = config.candidate_port
    cost_covered.storage.database_path = ROOT / "data/comparison-cost-covered.sqlite3"
    cost_covered.system_one.timeout_ms = config.inference_timeout_ms
    runner = LabRunner(
        baseline,
        {"cost-only": cost_only, "research-balanced": balanced, "cost-covered": cost_covered},
        config,
        output / "cache",
    )
    rows = await runner.run()
    output.mkdir(parents=True, exist_ok=True)
    samples = training_rows(rows, baseline)
    calibration: dict[str, Any]
    experiment = baseline.research.model_copy(deep=True)
    experiment.train_fraction = 0.5
    test_samples = training_rows(
        [{**row, "fold": "validation"} for row in rows if row["fold"] == "test"], baseline
    )
    try:
        calibration = fit(samples, experiment, datetime.now(UTC))
        calibration["untouched_test_nll_raw"] = nll(test_samples, 1) if test_samples else None
        calibration["untouched_test_nll_fitted"] = (
            nll(test_samples, float(calibration["temperature"])) if test_samples else None
        )
        training_labels = Counter(
            row.label for row in samples if row.at.date() == config.folds["train"]
        )
        prior = {
            label: (training_labels[label] + 1) / (sum(training_labels.values()) + 3)
            for label in ("LONG", "SHORT", "NEUTRAL")
        }
        calibration["test_nll_uniform_baseline"] = math.log(3)
        calibration["test_nll_training_prior_baseline"] = (
            -sum(math.log(prior[row.label]) for row in test_samples) / len(test_samples)
            if test_samples
            else None
        )
        calibration["training_label_counts"] = dict(training_labels)
    except ValueError as exc:
        calibration = {"fitted": False, "reason": str(exc)}
    calibration.update(synthetic_only=True, promoted=False, model_weights_trained=False)
    count = export_rows(
        [row for row in samples if row.at.date() == config.folds["train"]],
        output / "synthetic-training.jsonl",
    )
    validation_count = export_rows(
        [row for row in samples if row.at.date() == config.folds["validation"]],
        output / "synthetic-validation.jsonl",
    )
    test_count = export_rows(test_samples, output / "synthetic-test.jsonl")
    (output / "candidate.yaml").write_text(
        yaml.safe_dump(cost_covered.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    report = {
        "suite": config.model_dump(mode="json"),
        "summary": summarize(rows),
        "calibration_experiment": calibration,
        "training_examples_exported": count,
        "validation_examples_exported": validation_count,
        "test_examples_exported": test_count,
        "profiles": {
            name: profile.model_dump(mode="json")
            for name, profile in {"baseline": baseline, **runner.candidates}.items()
        },
        "source_hashes": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                ROOT / "src/paper_trader/scenario_lab.py",
                ROOT / "src/paper_trader/trading.py",
                config_path,
            ]
        },
        "notices": [
            "Independent one-position trials; aggregate sums are not a portfolio backtest.",
            "Price-impact scenarios supply no actual news, depth, benchmark or VIX data.",
            "Synthetic seeds test sensitivity, not evidence of real NSE profitability.",
            "Active profile and original ledger are unchanged; no weights were fine-tuned.",
        ],
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    (output / "observations.json").write_text(
        json.dumps(rows, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"profiles", "suite"}},
            indent=2,
            allow_nan=False,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated accounting audit and Laya scenario lab")
    parser.add_argument("command", choices=["audit", "simulate"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=ROOT / "profiles/scenario-lab.yaml")
    parser.add_argument("--day", type=date.fromisoformat, default=date(2026, 10, 22))
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / "work").resolve()):
        parser.error("Outputs must stay in the private work directory")
    if args.command == "audit":
        settings = load_settings(ROOT / "config.yaml", ROOT / ".env")
        state = read_ledger(settings.storage.database_path)
        report = audit_account(state, settings, args.day)
        reviews = trade_reviews(settings.storage.database_path, state, settings, args.day)
        report["real_trade_reviews_exported"] = len(reviews)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.with_name("trade-reviews.jsonl").write_text(
            "".join(json.dumps(review, allow_nan=False) + "\n" for review in reviews),
            encoding="utf-8",
        )
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            raise SystemExit(1)
    else:
        asyncio.run(run(args.output, args.suite))


if __name__ == "__main__":
    main()
