import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.calibration import Outcome, export_rows, fit, label_path, outcomes, save_artifact
from paper_trader.config import Settings
from paper_trader.data import CandleStore
from paper_trader.demo import synthetic
from paper_trader.engine import HoldStrategy, ReplayEngine
from paper_trader.inference import distribution
from paper_trader.storage import Database


def test_label_ambiguous_bar_is_conservative_and_directional(settings: Settings) -> None:
    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 1)
    bar = batch.candles[0].model_copy(
        update={
            "open": Decimal(100),
            "high": Decimal(104),
            "low": Decimal(98),
            "close": Decimal(102),
        }
    )
    assert label_path((bar,), Decimal(1), Decimal(2)) == "NEUTRAL"
    long = bar.model_copy(update={"low": Decimal("99.5")})
    assert label_path((long,), Decimal(1), Decimal(2)) == "LONG"
    short = bar.model_copy(update={"high": Decimal("100.5"), "close": Decimal(99)})
    assert label_path((short,), Decimal(1), Decimal(2)) == "SHORT"


def sample_rows() -> list[Outcome]:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    return [
        Outcome(
            str(i),
            start + timedelta(days=i),
            start + timedelta(days=i, minutes=5),
            "DEMO",
            "compact state",
            {"LONG": 0.9, "SHORT": 0.05, "NEUTRAL": 0.05},
            "LONG" if i % 2 else "SHORT",
            "typed-decisions",
            "unit-revision",
            ("immutable-version",),
        )
        for i in range(12)
    ]


def test_temperature_fit_uses_only_realized_training_and_preserves_holdout(
    settings: Settings, database: Database
) -> None:
    config = settings.research
    config.min_train_samples = config.min_validation_samples = 2
    config.train_fraction = 0.5
    rows = sample_rows()
    as_of = rows[-1].known_at
    report = fit(rows, config, as_of)
    assert report["temperature"] > 1
    assert report["train_nll_after"] < report["train_nll_before"]
    assert report["validation_nll_after"] < report["validation_nll_before"]
    assert not report["applied"]
    malicious_future = replace(rows[0], known_at=as_of + timedelta(days=100), label="NEUTRAL")
    assert fit(rows + [malicious_future], config, as_of) == report
    purged = rows.copy()
    purged[5] = replace(rows[5], known_at=rows[7].at)
    assert fit(purged, config, as_of)["purged_samples"] == 1
    identifier = save_artifact(database, report)
    assert identifier == save_artifact(database, report)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM calibration_artifacts").fetchone()[0] == 1
    with pytest.raises(ValueError, match="versioned"):
        fit([replace(row, revision="unverified") for row in rows], config, as_of)


def test_laya_notebook_gold_export_and_extreme_temperature(tmp_path: Path) -> None:
    path = tmp_path / "training.jsonl"
    assert export_rows(sample_rows(), path) == 12
    record = json.loads(path.read_text().splitlines()[0])
    assert set(record) == {"state", "questions", "gold", "meta"}
    assert record["questions"]["direction"]["type"] == "choice"
    assert record["gold"]["direction"]["probabilities"][record["gold"]["direction"]["label"]] == 1
    assert "storage" not in record["meta"]
    custom = sample_rows()[0]
    custom.label_spec["definition"] = "Cost-aware counterfactual label"
    export_rows([custom], path)
    assert json.loads(path.read_text())["meta"]["label_rule"] == custom.label_spec["definition"]
    for temperature in (1e-320, 1e308):
        probabilities = distribution(
            {"probabilities": {"LONG": 0.9, "SHORT": 0.05, "NEUTRAL": 0.05}},
            {"LONG", "SHORT", "NEUTRAL"},
            temperature,
        )
        assert sum(probabilities.values()) == pytest.approx(1)


def test_outcomes_are_unavailable_until_horizon_is_closed(
    settings: Settings, database: Database
) -> None:
    settings.research.horizon_bars = 2
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO instruments VALUES "
            "('DEMO', 'Synthetic', 'EQUITY', 'SYNTHETIC', NULL, 'EQ', "
            "1, '0.05', NULL, NULL, 'DEMO')"
        )
    calendar = TradingCalendar.load(settings)
    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 1)
    version = CandleStore(database, calendar).save(batch)
    engine = ReplayEngine(
        settings, calendar, database, batch.candles[:5], {"DEMO": version}, HoldStrategy()
    )
    asyncio.run(engine.run())
    with database.connect() as connection:
        row = connection.execute(
            "SELECT id FROM decisions WHERE run_id=? ORDER BY created_at LIMIT 1", (engine.run_id,)
        ).fetchone()
        connection.execute(
            "UPDATE decisions SET features_json=? WHERE id=?", (json.dumps({"atr": 1.0}), row[0])
        )
        connection.execute(
            "INSERT INTO model_outputs "
            "(decision_id, request_json, response_json, checkpoint_revision) "
            "VALUES (?, '{}', ?, 'unit-revision')",
            (
                row[0],
                json.dumps(
                    {
                        "answers": {
                            "direction": {
                                "type": "choice",
                                "choice": "LONG",
                                "probabilities": {"LONG": 0.8, "SHORT": 0.1, "NEUTRAL": 0.1},
                            }
                        }
                    }
                ),
            ),
        )
    assert not outcomes(database, engine.run_id, batch.candles[1].closed_at, settings)
    realized = outcomes(database, engine.run_id, batch.candles[2].closed_at, settings)
    assert len(realized) == 1
    assert realized[0].known_at == batch.candles[2].closed_at
    assert realized[0].versions == (version,)
