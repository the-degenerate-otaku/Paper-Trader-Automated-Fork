from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from paper_trader.ablation import compare, directions, frequency_controls, summary
from paper_trader.calendar import TradingCalendar
from paper_trader.config import Section, Settings, load_settings
from paper_trader.features import FeatureSnapshot
from paper_trader.inference import QUESTIONS, SystemOneStrategy
from paper_trader.market import Candle, stamp
from paper_trader.scenario_lab import Movement, Probe
from paper_trader.timeframe_lab import paired_inputs
from paper_trader.trading import Portfolio

ROOT = Path(__file__).resolve().parents[1]


class Protocol(Section):
    day: date
    signal_times: list[time] = Field(min_length=1, max_length=10)
    history_days: int = Field(ge=3, le=30)
    future_minutes: int = Field(ge=10, le=60)
    new_hold_minutes: int = Field(ge=1, le=60)
    decision_delay_seconds: int = Field(ge=1, le=60)
    inference_timeout_ms: int = Field(ge=5000, le=60000)
    matched_count_resamples: int = Field(ge=100, le=10000)
    random_seed: int = Field(ge=0, le=4294967295)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare(
    connection: sqlite3.Connection, settings: Settings, protocol: Protocol
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    calendar = TradingCalendar.load(settings)
    times = sorted(
        datetime.combine(protocol.day, value, calendar.zone) for value in protocol.signal_times
    )
    if len(set(times)) != len(times) or any(
        at.minute % 5 or at.second or at.microsecond or not calendar.status(at).can_enter_mis
        for at in times
    ):
        raise ValueError("Signals require distinct eligible closed five-minute boundaries")
    if any(
        (b - a).total_seconds() < protocol.future_minutes * 60
        for a, b in zip(times, times[1:], strict=False)
    ):
        raise ValueError("Signal outcome windows must not overlap")
    membership = connection.execute(
        "SELECT id,observed_at FROM universe_snapshots WHERE index_symbol='NIFTY50' "
        "AND observed_at<=? ORDER BY observed_at DESC LIMIT 1",
        (stamp(times[0]),),
    ).fetchone()
    if membership is None:
        raise ValueError("No observed Nifty membership available before the first signal")
    symbols = [
        row[0]
        for row in connection.execute(
            "SELECT symbol FROM constituents_history WHERE snapshot_id=? ORDER BY symbol",
            (membership[0],),
        )
    ]
    if len(symbols) != 50:
        raise ValueError("Expected observed fifty-stock membership")
    cases = []
    excluded: Counter[str] = Counter()
    versions = set()
    for symbol in symbols:
        rows = connection.execute(
            "SELECT v.payload_json,c.data_version FROM candles c JOIN candle_versions v "
            "ON v.data_version=c.data_version AND v.symbol=c.symbol "
            "AND v.timeframe=c.timeframe AND v.opened_at=c.opened_at "
            "WHERE c.symbol=? AND c.timeframe='1m' AND c.opened_at>=? AND c.opened_at<? "
            "ORDER BY c.opened_at",
            (
                symbol,
                stamp(times[0] - timedelta(days=protocol.history_days)),
                stamp(times[-1] + timedelta(minutes=protocol.future_minutes)),
            ),
        ).fetchall()
        bars = tuple(Candle.model_validate_json(row[0]) for row in rows)
        versions.update(row[1] for row in rows)
        for at in times:
            try:
                inputs, provenance = paired_inputs(bars, settings, at)
            except ValueError as exc:
                excluded[str(exc)] += 1
                continue
            future = tuple(
                bar
                for bar in bars
                if at <= bar.opened_at < at + timedelta(minutes=protocol.future_minutes)
            )
            if len(future) != protocol.future_minutes or any(
                bar.opened_at != at + timedelta(minutes=index) for index, bar in enumerate(future)
            ):
                excluded["Incomplete one-minute outcome window"] += 1
                continue
            reference = next(bar for bar in bars if bar.closed_at == at)
            cases.append(
                {
                    "symbol": symbol,
                    "at": at.isoformat(),
                    "inputs": {
                        name: {**asdict(value), "at": value.at.isoformat()}
                        for name, value in inputs.items()
                    },
                    "history_provenance": provenance,
                    "reference": reference.model_dump(mode="json"),
                    "future": [bar.model_dump(mode="json") for bar in future],
                }
            )
    return cases, {
        "planned_pairs": len(symbols) * len(times),
        "eligible_pairs": len(cases),
        "symbols": len({case["symbol"] for case in cases}),
        "exclusions": dict(excluded),
        "membership_observed_at": membership[1],
        "data_versions": sorted(versions),
    }


async def run(output: Path, prepare_only: bool, resume_cases: bool = False) -> None:
    protocol_path = ROOT / "profiles/timeframe-comparison.yaml"
    protocol = Protocol.model_validate(yaml.safe_load(protocol_path.read_text()))
    profiles = {
        name: load_settings(ROOT / f"profiles/{name}.yaml", ROOT / "profiles/.unused-env")
        for name in ("baseline", "research-balanced")
    }
    if (
        protocol.future_minutes
        < max(
            protocol.new_hold_minutes, *(p.auto_paper.max_hold_minutes for p in profiles.values())
        )
        + 3
    ):
        raise ValueError("Outcome horizon must allow entry, timed exit and later fills")
    baseline = profiles["baseline"]
    resume_from = None
    if resume_cases:
        previous = json.loads((output / "report.json").read_text())
        cases = json.loads((output / "cases.json").read_text())
        coverage = json.loads((output / "coverage.json").read_text())
        if previous["protocol"] != protocol.model_dump(mode="json") or previous[
            "cases_hash"
        ] != digest(cases):
            raise ValueError("Frozen cases or protocol changed")
        for name, expected in previous["source_hashes"].items():
            if (
                name != str(Path(__file__).relative_to(ROOT))
                and hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected
            ):
                raise ValueError("Frozen experiment source or profile changed")
        resume_from = {
            "report_hash": digest(previous),
            "created_at": previous["created_at"],
            "common_valid_pairs": previous["common_valid_pairs"],
        }
    else:
        active = load_settings(ROOT / "config.yaml", ROOT / ".env")
        with sqlite3.connect(
            active.storage.database_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as connection:
            cases, coverage = prepare(connection, baseline, protocol)
    output.mkdir(parents=True, exist_ok=True)
    (output / "cases.json").write_text(json.dumps(cases, indent=2, allow_nan=False))
    (output / "coverage.json").write_text(json.dumps(coverage, indent=2))
    print(
        json.dumps({key: value for key, value in coverage.items() if key != "data_versions"}),
        flush=True,
    )
    if prepare_only:
        return
    if not cases:
        raise ValueError("No eligible paired inputs; no inference run produced")
    inference = baseline.model_copy(deep=True)
    inference.system_one.timeout_ms = protocol.inference_timeout_ms
    strategy = SystemOneStrategy(inference)
    if not await strategy.health():
        raise ValueError(
            "Local Laya server is unavailable; no synthetic model responses substituted"
        )
    cache_dir = output / "cache"
    cache_dir.mkdir(exist_ok=True)
    rows: dict[str, list[dict[str, Any]]] = {}
    paired_directions = []
    for index, case in enumerate(cases):
        at = datetime.fromisoformat(case["at"])
        probe = Probe(
            "recorded",
            case["symbol"],
            0,
            (Candle.model_validate(case["reference"]),),
            tuple(Candle.model_validate(bar) for bar in case["future"]),
            Movement(name="timeframe", drift_bps=0, noise_bps=0),
        )
        case_rows = []
        frame_signals = {}
        valid = True
        for frame, record in case["inputs"].items():
            features = FeatureSnapshot(**{**record, "at": at})
            cache_key = digest(
                {
                    "state": features.state,
                    "at": at.isoformat(),
                    "questions": QUESTIONS,
                    "checkpoint": inference.system_one.model_dump(mode="json"),
                }
            )
            cache = cache_dir / f"{cache_key}.json"
            if cache.exists():
                raw = json.loads(cache.read_text())
                response = raw.get("response")
            else:
                signal = await strategy.decide(
                    features, Portfolio(baseline.account.starting_capital_inr)
                )
                raw = signal.raw
                response = raw.get("response") if strategy.healthy else None
                with (output / "inference-attempts.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "cache_key": cache_key,
                                "symbol": case["symbol"],
                                "frame": frame,
                                "healthy": strategy.healthy,
                                "raw": raw,
                            },
                            allow_nan=False,
                        )
                        + "\n"
                    )
                if strategy.healthy:
                    cache.write_text(json.dumps(raw, allow_nan=False))
            chosen, reason = directions(inference, features, response)
            valid = valid and reason != "INFERENCE_UNAVAILABLE_OR_INVALID"
            frame_signals[frame] = chosen["laya"]
            for name, profile in profiles.items():
                for exit_name in ("current_exit", f"{protocol.new_hold_minutes}_minute_exit"):
                    variant = profile.model_copy(deep=True)
                    if exit_name != "current_exit":
                        variant.auto_paper.max_hold_minutes = protocol.new_hold_minutes
                    key = f"{name}/{frame}/{exit_name}"
                    row = {
                        "group": str(protocol.day),
                        "symbol": case["symbol"],
                        "at": case["at"],
                        "frame": frame,
                        "cache_key": cache_key,
                        "latency_ms": raw.get("latency_ms"),
                        **compare(
                            variant,
                            probe,
                            features,
                            response,
                            at + timedelta(seconds=protocol.decision_delay_seconds),
                        ),
                    }
                    case_rows.append((key, row))
        resolved = all(row["paired_resolved"] for _, row in case_rows)
        for key, row in case_rows:
            row["paired_resolved"] = resolved
            row["both_models_valid"] = valid
            rows.setdefault(key, []).append(row)
        paired_directions.append({"symbol": case["symbol"], "at": case["at"], **frame_signals})
        (output / "progress.json").write_text(json.dumps(rows, allow_nan=False))
        print(
            f"{index + 1}/{len(cases)} {case['symbol']} {at.strftime('%H:%M')} {frame_signals}",
            flush=True,
        )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol.model_dump(mode="json"),
        "coverage": coverage,
        "common_valid_pairs": sum(row["both_models_valid"] for row in next(iter(rows.values()))),
        "summaries": {
            key: {
                **summary(values),
                "both_models_valid_subset": summary(
                    [row for row in values if row["both_models_valid"]]
                ),
                "matched_count_control": frequency_controls(
                    values, protocol.matched_count_resamples, protocol.random_seed
                ),
            }
            for key, values in rows.items()
        },
        "direction_changes": sum(row["1m"] != row["5m"] for row in paired_directions),
        "profiles": {key: value.model_dump(mode="json") for key, value in profiles.items()},
        "source_hashes": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                protocol_path,
                ROOT / "src/paper_trader/timeframe_lab.py",
                ROOT / "src/paper_trader/scenario_lab.py",
                ROOT / "src/paper_trader/ablation.py",
                ROOT / "src/paper_trader/trading.py",
                ROOT / "src/paper_trader/features.py",
                ROOT / "src/paper_trader/inference.py",
                ROOT / "profiles/baseline.yaml",
                ROOT / "profiles/research-balanced.yaml",
            )
        },
        "cases_hash": digest(cases),
        "resume_from": resume_from,
        "weights_trained": False,
        "active_profile_changed": False,
        "limitations": [
            "Retrospective single-session trials, not account returns or an unseen holdout.",
            "Latest saved Yahoo minute revisions; no quote fills or full portfolio replay.",
            "Both histories exclude post-MIS-square-off bars; incomplete buckets are not padded.",
            "Indicator periods remain in bars, so five-minute lookbacks cover more clock time.",
            "Fresh inputs have a timeframe prefix and differ from the earlier journal test.",
            "Common decision delay and one-minute fills; no speed benefit assigned to EMA.",
            "Current and longer exits run at both timeframes; stops and targets remain active.",
            "Missing windows excluded before inference; responses shared across exit profiles.",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    (output / "observations.json").write_text(json.dumps(rows, indent=2, allow_nan=False))
    (output / "paired-directions.json").write_text(json.dumps(paired_directions, indent=2))
    print("Paired timeframe experiment complete", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Actual-model paired one/five-minute comparison")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume-cases", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "work").resolve()):
        parser.error("Outputs must stay in private work storage")
    if args.prepare_only and args.resume_cases:
        parser.error("Choose prepare-only or resume-cases")
    asyncio.run(run(output, args.prepare_only, args.resume_cases))


if __name__ == "__main__":
    main()
