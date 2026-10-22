from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from paper_trader.calendar import TradingCalendar
from paper_trader.config import ResearchConfig, Settings
from paper_trader.data import CandleStore, quality
from paper_trader.inference import QUESTIONS, distribution
from paper_trader.market import Candle, aware
from paper_trader.storage import Database

LABELS = {"LONG", "SHORT", "NEUTRAL"}


@dataclass(frozen=True)
class Outcome:
    decision_id: str
    at: datetime
    known_at: datetime
    symbol: str
    state: str
    probabilities: dict[str, float]
    label: str
    checkpoint: str
    revision: str
    versions: tuple[str, ...]
    label_spec: dict[str, object] = field(default_factory=dict)
    data_sources: tuple[str, ...] = ()


def path_wins(
    bars: tuple[Candle, ...], entry: Decimal, distance: Decimal, rr: Decimal, long: bool
) -> bool:
    stop, target = (
        (entry - distance, entry + distance * rr)
        if long
        else (entry + distance, entry - distance * rr)
    )
    for bar in bars:
        if bar.low <= stop if long else bar.high >= stop:
            return False
        if bar.high >= target if long else bar.low <= target:
            return True
    return False


def label_path(bars: tuple[Candle, ...], distance: Decimal, rr: Decimal) -> str:
    if not bars or distance <= 0 or rr <= 0:
        raise ValueError("Labeling requires a positive distance and future horizon")
    entry = bars[0].open
    long = path_wins(bars, entry, distance, rr, True)
    short = path_wins(bars, entry, distance, rr, False)
    return "LONG" if long and not short else "SHORT" if short and not long else "NEUTRAL"


def outcomes(database: Database, run_id: str, as_of: datetime, settings: Settings) -> list[Outcome]:
    cutoff = aware(as_of)
    with database.connect() as connection:
        run = connection.execute(
            "SELECT config_json, data_version FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        rows = connection.execute(
            "SELECT d.id, d.created_at, d.symbol, d.state_text, d.features_json, "
            "d.checkpoint_id, m.response_json, m.checkpoint_revision FROM decisions d "
            "JOIN model_outputs m ON m.decision_id=d.id WHERE d.run_id=? "
            "AND m.error IS NULL ORDER BY d.created_at, d.id LIMIT ?",
            (run_id, settings.research.max_samples),
        ).fetchall()
    if run is None:
        raise ValueError("Unknown run")
    recorded = Settings.model_validate_json(run["config_json"])
    versions = tuple(dict.fromkeys(json.loads(run["data_version"]).values()))
    calendar = TradingCalendar.load(recorded)
    store = CandleStore(database, calendar)
    series: dict[str, tuple[Candle, ...]] = {}
    for symbol in {row["symbol"] for row in rows}:
        collected: dict[tuple[str, str, datetime], Candle] = {}
        for version in versions:
            for timeframe in recorded.data.timeframes:
                for bar in store.read(version, symbol, timeframe, cutoff):
                    collected.setdefault(bar.identity, bar)
        series[symbol] = tuple(sorted(collected.values(), key=lambda c: c.closed_at))
    result = []
    opened = {symbol: [bar.opened_at for bar in bars] for symbol, bars in series.items()}
    for row in rows:
        at = aware(datetime.fromisoformat(row["created_at"]))
        offset = bisect_left(opened[row["symbol"]], at)
        future = series[row["symbol"]][offset : offset + settings.research.horizon_bars]
        if len(future) != settings.research.horizon_bars or future[-1].closed_at > cutoff:
            continue
        if (
            future[0].opened_at != at
            or quality(future, calendar, future[-1].closed_at).status != "healthy"
        ):
            continue
        features = json.loads(row["features_json"])
        atr = features.get("atr")
        if type(atr) not in {int, float} or not math.isfinite(atr) or atr <= 0:
            continue
        try:
            answer = json.loads(row["response_json"])["answers"]["direction"]
            probabilities = distribution(answer, LABELS, 1)
        except (KeyError, ValueError, TypeError):
            continue
        result.append(
            Outcome(
                row["id"],
                at,
                future[-1].closed_at,
                row["symbol"],
                row["state_text"],
                probabilities,
                label_path(
                    future,
                    Decimal(str(atr)) * recorded.risk.atr_stop_multiple,
                    recorded.risk.reward_risk_ratio,
                ),
                row["checkpoint_id"],
                row["checkpoint_revision"],
                versions,
                {
                    "horizon_bars": settings.research.horizon_bars,
                    "atr_stop_multiple": str(recorded.risk.atr_stop_multiple),
                    "reward_risk_ratio": str(recorded.risk.reward_risk_ratio),
                },
                tuple(
                    sorted(
                        {
                            "synthetic"
                            if c.source.startswith("synthetic")
                            else "yfinance"
                            if c.source.startswith("yfinance")
                            else "csv"
                            if c.source.startswith("csv")
                            else "other"
                            for c in future
                        }
                    )
                ),
            )
        )
    return result


def nll(rows: list[Outcome], temperature: float) -> float:
    if not rows:
        raise ValueError("No calibration samples")
    return sum(
        -math.log(
            max(
                distribution({"probabilities": row.probabilities}, LABELS, temperature)[row.label],
                1e-12,
            )
        )
        for row in rows
    ) / len(rows)


def reliability(rows: list[Outcome], temperature: float, bins: int) -> list[dict[str, object]]:
    groups: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for row in rows:
        probs = distribution({"probabilities": row.probabilities}, LABELS, temperature)
        chosen = max(probs, key=lambda key: probs[key])
        confidence = probs[chosen]
        groups[min(int(confidence * bins), bins - 1)].append((confidence, chosen == row.label))
    return [
        {
            "lower": i / bins,
            "upper": (i + 1) / bins,
            "count": len(group),
            "mean_probability": sum(p for p, _ in group) / len(group) if group else None,
            "observed_accuracy": sum(hit for _, hit in group) / len(group) if group else None,
        }
        for i, group in enumerate(groups)
    ]


def fit(rows: list[Outcome], config: ResearchConfig, as_of: datetime) -> dict[str, object]:
    cutoff = aware(as_of)
    available = sorted((row for row in rows if row.known_at <= cutoff), key=lambda row: row.at)
    if len(available) < config.min_train_samples + config.min_validation_samples:
        raise ValueError("Insufficient realized model outcomes for calibration")
    identities = {(row.checkpoint, row.revision) for row in available}
    if len(identities) != 1 or next(iter(identities))[1] == "unverified":
        raise ValueError("Calibration requires one explicitly versioned checkpoint")
    if len({json.dumps(row.label_spec, sort_keys=True) for row in available}) != 1:
        raise ValueError("Calibration samples use incompatible label rules")
    split = min(len(available) - 1, int(len(available) * config.train_fraction))
    validation_start = available[split].at
    training = [
        row for row in available if row.at < validation_start and row.known_at < validation_start
    ]
    validation = [row for row in available if row.at >= validation_start]
    if len(training) < config.min_train_samples or len(validation) < config.min_validation_samples:
        raise ValueError("Insufficient samples after chronological purge")
    best = min(config.temperature_grid, key=lambda temperature: nll(training, temperature))
    calibrated = reliability(validation, best, config.reliability_bins)
    ece = sum(
        int(str(point["count"]))
        / len(validation)
        * abs(float(str(point["mean_probability"])) - float(str(point["observed_accuracy"])))
        for point in calibrated
        if point["count"]
    )
    checkpoint, revision = next(iter(identities))
    return {
        "checkpoint": checkpoint,
        "revision": revision,
        "temperature": best,
        "as_of": cutoff.isoformat(),
        "validation_start": validation_start.isoformat(),
        "train_samples": len(training),
        "validation_samples": len(validation),
        "purged_samples": len(available) - len(training) - len(validation),
        "train_nll_before": nll(training, 1),
        "train_nll_after": nll(training, best),
        "validation_nll_before": nll(validation, 1),
        "validation_nll_after": nll(validation, best),
        "validation_ece": ece,
        "reliability_before": reliability(validation, 1, config.reliability_bins),
        "reliability_after": calibrated,
        "versions": sorted({v for row in available for v in row.versions}),
        "label_spec": available[0].label_spec,
        "data_sources": sorted({source for row in available for source in row.data_sources}),
        "revision_status": "operator_declared",
        "applied": False,
    }


def save_artifact(database: Database, report: dict[str, object]) -> str:
    payload = json.dumps(report, sort_keys=True, allow_nan=False)
    identifier = hashlib.sha256(payload.encode()).hexdigest()
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO calibration_artifacts VALUES (?, ?, ?, ?, ?)",
            (
                identifier,
                report["checkpoint"],
                report["revision"],
                datetime.now(UTC).isoformat(),
                payload,
            ),
        )
    return identifier


def export_rows(rows: list[Outcome], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            record = {
                "state": {"body": row.state},
                "questions": {"direction": QUESTIONS["direction"]},
                "gold": {
                    "direction": {
                        "label": row.label,
                        "probabilities": {
                            label: int(label == row.label) for label in sorted(LABELS)
                        },
                    }
                },
                "meta": {
                    "decision_id": row.decision_id,
                    "at": row.at.isoformat(),
                    "known_at": row.known_at.isoformat(),
                    "symbol": row.symbol,
                    "checkpoint": row.checkpoint,
                    "revision": row.revision,
                    "versions": row.versions,
                    "label_spec": row.label_spec,
                    "data_sources": row.data_sources,
                    "label_rule": "Next-open entry; ATR stop and reward/risk target; "
                    "stop first on ambiguous bars; neutral if no target wins within horizon",
                },
            }
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    return len(rows)
