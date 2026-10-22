from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydantic import Field

from paper_trader.ablation import compare, frequency_controls, select_events, summary
from paper_trader.calendar import TradingCalendar
from paper_trader.config import Section, Settings, load_settings
from paper_trader.features import FeatureSnapshot
from paper_trader.market import Candle, stamp
from paper_trader.scenario_lab import LabConfig, Movement, Probe, probes, snapshot

ROOT = Path(__file__).resolve().parents[1]


class Protocol(Section):
    journal_limit: int = Field(ge=100, le=100000)
    separation_minutes: int = Field(ge=10, le=120)
    future_minutes: int = Field(ge=10, le=60)
    real_days: list[date] = Field(min_length=1, max_length=30)
    matched_count_resamples: int = Field(ge=100, le=10000)
    random_seed: int = Field(ge=0, le=4294967295)


def evaluate(rows: list[dict[str, Any]], config: Protocol) -> dict[str, Any]:
    available = [row for row in rows if row["laya_reason"] != "INFERENCE_UNAVAILABLE_OR_INVALID"]
    return {
        **summary(rows),
        "model_available_subset": summary(available),
        "matched_trade_count_control": frequency_controls(
            rows, config.matched_count_resamples, config.random_seed
        ),
        "available_subset_count_control": frequency_controls(
            available, config.matched_count_resamples, config.random_seed
        ),
    }


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def historical(
    connection: sqlite3.Connection, config: Protocol, profiles: dict[str, Settings]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    settings = profiles["baseline"]
    zone = TradingCalendar.load(settings).zone
    loaded = connection.execute(
        "SELECT id,payload_json FROM live_paper_events WHERE event='auto_decision' "
        "ORDER BY id DESC LIMIT ?",
        (config.journal_limit,),
    ).fetchall()
    events = []
    for identifier, payload in reversed(loaded):
        event = json.loads(payload)
        event["journal_id"] = identifier
        if datetime.fromisoformat(event["at"]).astimezone(zone).date() in config.real_days:
            events.append(event)
    selected, excluded = select_events(events, timedelta(minutes=config.separation_minutes))
    coverage = Counter(excluded)
    results: dict[str, list[dict[str, Any]]] = {name: [] for name in profiles}
    stored: dict[tuple[str, date], tuple[Candle, ...]] = {}
    versions = set()
    latencies = []
    for event in selected:
        at, bar_at = (datetime.fromisoformat(event[key]) for key in ("at", "bar_at"))
        symbol = event["symbol"]
        day = at.astimezone(zone).date()
        if not 0 <= (at - bar_at).total_seconds() <= settings.auto_paper.max_candle_age_seconds:
            coverage["stale_or_future_signal"] += 1
            continue
        key = symbol, day
        if key not in stored:
            start = datetime.combine(day, time.min, zone)
            rows = connection.execute(
                "SELECT v.payload_json,c.data_version FROM candles c JOIN candle_versions v "
                "ON v.data_version=c.data_version AND v.symbol=c.symbol "
                "AND v.timeframe=c.timeframe AND v.opened_at=c.opened_at "
                "WHERE c.symbol=? AND c.timeframe='1m' AND c.opened_at>=? AND c.opened_at<? "
                "ORDER BY c.opened_at",
                (symbol, stamp(start), stamp(start + timedelta(days=1))),
            ).fetchall()
            stored[key] = tuple(Candle.model_validate_json(row[0]) for row in rows)
            versions.update(row[1] for row in rows)
        bars = stored[key]
        reference = next((bar for bar in bars if bar.closed_at == bar_at), None)
        opened = at.replace(second=0, microsecond=0)
        if opened < at:
            opened += timedelta(minutes=1)
        future = tuple(
            bar
            for bar in bars
            if opened <= bar.opened_at < opened + timedelta(minutes=config.future_minutes)
        )
        if reference is None:
            coverage["missing_reference_bar"] += 1
            continue
        if len(future) != config.future_minutes or any(
            bar.opened_at != opened + timedelta(minutes=index) for index, bar in enumerate(future)
        ):
            coverage["incomplete_future_window"] += 1
            continue
        raw = event.get("raw", {})
        response = raw.get("response")
        if event.get("model_revision") != settings.system_one.checkpoint_revision:
            response = None
            coverage["checkpoint_mismatch"] += 1
        latency = raw.get("latency_ms")
        if isinstance(latency, (int, float)) and np.isfinite(latency):
            latencies.append(latency)
        features = FeatureSnapshot(symbol, bar_at, event["features"], "RECORDED", event["state"])
        probe = Probe(
            "recorded",
            symbol,
            0,
            (reference,),
            future,
            Movement(name="recorded", drift_bps=0, noise_bps=0),
        )
        evidence = {
            "group": str(day),
            "symbol": symbol,
            "journal_id": event["journal_id"],
            "at": at.isoformat(),
            "bar_at": bar_at.isoformat(),
            "state_hash": digest(features.state),
            "features_hash": digest(features.values),
            "response_hash": digest(response),
            "future_hash": digest([bar.model_dump(mode="json") for bar in future]),
            "latency_ms": latency,
        }
        for name, profile in profiles.items():
            results[name].append({**evidence, **compare(profile, probe, features, response, at)})
    return results, {
        "journal_records_loaded": len(loaded),
        "journal_limit_reached": len(loaded) == config.journal_limit,
        "day_records": len(events),
        "selected_before_outcome_availability": len(selected),
        "evaluated": len(results["baseline"]),
        "exclusions": dict(coverage),
        "future_data_versions": sorted(versions),
        "latency_ms_p50": float(np.percentile(latencies, 50)) if latencies else None,
        "latency_ms_p95": float(np.percentile(latencies, 95)) if latencies else None,
    }


def synthetic(folder: Path, profiles: dict[str, Settings]) -> dict[str, list[dict[str, Any]]]:
    lab = LabConfig.model_validate(
        yaml.safe_load((ROOT / "profiles/scenario-lab.yaml").read_text())
    )
    observations = json.loads((folder / "observations.json").read_text())
    manifest = json.loads((folder / "report.json").read_text())
    if (
        manifest["profiles"]["baseline"]["system_one"]["checkpoint_revision"]
        != profiles["baseline"].system_one.checkpoint_revision
    ):
        raise ValueError("Synthetic checkpoint revision mismatch")
    cached = {(row["fold"], row["scenario"], row["offset"]): row for row in observations}
    results: dict[str, list[dict[str, Any]]] = {name: [] for name in profiles}
    for probe in probes(profiles["baseline"], lab):
        features = snapshot(profiles["baseline"], probe)
        if features is None:
            continue
        row = cached[(probe.fold, probe.scenario, probe.offset)]
        response = row.get("response")
        if not probe.movement.inference_outage:
            if row.get("state") != features.state or row.get("feature_hash") != digest(
                features.values
            ):
                raise ValueError("Synthetic input provenance mismatch")
        for name, profile in profiles.items():
            results[name].append(
                {
                    "group": probe.fold,
                    "scenario": probe.scenario,
                    "offset": probe.offset,
                    **compare(profile, probe, features, response),
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline paired Laya/EMA ablation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-cache", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / "work").resolve()):
        parser.error("Reports must remain in private work")
    if not args.synthetic_cache.resolve().is_relative_to((ROOT / "work").resolve()):
        parser.error("Synthetic cache must remain in private work")
    protocol_path = ROOT / "profiles/laya-ablation.yaml"
    config = Protocol.model_validate(yaml.safe_load(protocol_path.read_text()))
    profiles = {
        name: load_settings(ROOT / f"profiles/{name}.yaml", ROOT / "profiles/.unused-env")
        for name in ("baseline", "research-balanced")
    }
    if (
        config.separation_minutes < config.future_minutes
        or config.future_minutes
        < max(settings.auto_paper.max_hold_minutes for settings in profiles.values()) + 2
    ):
        raise ValueError("Require non-overlapping windows long enough for timed exits")
    active = load_settings(ROOT / "config.yaml", ROOT / ".env")
    with sqlite3.connect(
        active.storage.database_path.resolve().as_uri() + "?mode=ro", uri=True
    ) as c:
        real, coverage = historical(c, config, profiles)
    generated = synthetic(args.synthetic_cache, profiles)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": config.model_dump(mode="json"),
        "coverage": coverage,
        "real": {name: evaluate(rows, config) for name, rows in real.items()},
        "synthetic": {name: evaluate(rows, config) for name, rows in generated.items()},
        "profiles": {name: settings.model_dump(mode="json") for name, settings in profiles.items()},
        "source_hashes": {
            str(path.resolve().relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                Path(__file__),
                protocol_path,
                ROOT / "src/paper_trader/ablation.py",
                ROOT / "src/paper_trader/scenario_lab.py",
                ROOT / "src/paper_trader/trading.py",
                ROOT / "src/paper_trader/inference.py",
                ROOT / "profiles/baseline.yaml",
                ROOT / "profiles/research-balanced.yaml",
                args.synthetic_cache / "observations.json",
                args.synthetic_cache / "report.json",
            ]
        },
        "limitations": [
            "Retrospective selected entry-review opportunities, not a preregistered holdout.",
            "Recorded inputs are preserved; future Yahoo candles use latest saved revisions.",
            "Independent trial sums omit portfolio interaction, quote fills and AI exit reviews.",
            "Both arms wait for the recorded response time; EMA gets no speed advantage here.",
            "EMA uses recorded EMA features; Laya saw the existing compact text input.",
            "Missing outcome windows are excluded before scoring and may bias coverage.",
            "Opportunity selection reflects the original AI scheduler and account history.",
            "Only one real session has explicit entry/position context; older journals excluded.",
            "Synthetic cases were previously inspected and are not new unseen evidence.",
            "Random thinning controls are exploratory and do not adjust for market correlation.",
            "No new inference, parameter tuning, weight training, account mutation or promotion.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    (args.output / "observations.json").write_text(
        json.dumps({"real": real, "synthetic": generated}, indent=2, allow_nan=False)
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"profiles", "source_hashes", "coverage"}
            },
            indent=2,
            allow_nan=False,
        )
    )
    print(
        json.dumps(
            {
                "coverage": {
                    key: value for key, value in coverage.items() if key != "future_data_versions"
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
