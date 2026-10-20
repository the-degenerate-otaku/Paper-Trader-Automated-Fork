import asyncio
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from paper_trader.api import create_app
from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.data import CandleStore
from paper_trader.demo import synthetic
from paper_trader.research import slices, stress, walk_forward
from paper_trader.storage import Database


def dataset(settings: Settings, database: Database):
    with database.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO instruments VALUES "
            "('DEMO', 'Synthetic', 'EQUITY', 'SYNTHETIC', NULL, 'EQ', "
            "1, '0.05', NULL, NULL, 'DEMO')"
        )
    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 2)
    version = CandleStore(database, TradingCalendar.load(settings)).save(batch)
    return batch.candles, {"DEMO": version}


def test_walk_forward_seeds_only_prior_bars_and_reports_test_period(
    settings: Settings, database: Database
) -> None:
    settings.research.train_bars, settings.research.test_bars = 75, 50
    settings.data.warmup_bars = 20
    bars, versions = dataset(settings, database)
    folds = slices(bars, settings)
    assert len(folds) == 1
    assert folds[0][0][-1].closed_at <= folds[0][1][0].opened_at
    reports = asyncio.run(
        walk_forward(settings, TradingCalendar.load(settings), database, bars, versions, "hold")
    )
    assert len(reports) == 1 and not reports[0]["parameters_fitted"]
    run_id = reports[0]["run_id"]
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM decisions WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == 50
        )
        assert (
            connection.execute(
                "SELECT MIN(created_at) FROM decisions WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            > folds[0][0][-1].closed_at.isoformat()
        )
    json.dumps(reports, allow_nan=False)


def test_stress_scenarios_and_empty_windows_fail_honestly(
    settings: Settings, database: Database
) -> None:
    bars, versions = dataset(settings, database)
    settings.data.warmup_bars = 20
    reports = asyncio.run(
        stress(settings, TradingCalendar.load(settings), database, bars, versions)
    )
    assert {row["scenario"] for row in reports} == {
        "baseline",
        "missing_bars",
        "liquidity_drought",
        "high_slippage",
        "inference_outage",
    }
    assert next(row for row in reports if row["scenario"] == "missing_bars")["veto_count"] > 0
    assert (
        next(row for row in reports if row["scenario"] == "inference_outage")["open_positions"] == 0
    )
    json.dumps(reports, allow_nan=False)
    with pytest.raises(ValueError, match="Insufficient"):
        asyncio.run(
            walk_forward(
                settings, TradingCalendar.load(settings), database, bars[:5], versions, "hold"
            )
        )


def test_research_api_has_no_fake_calibration_or_future_export(settings: Settings) -> None:
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:2080", headers={"X-Paper-Request": "1"}
    ) as client:
        state = client.post("/api/run", json={}).json()
        run_id = state["run"]["id"]
        assert client.post("/api/research/calibrate", json={"run_id": run_id}).status_code == 409
        exported = client.post("/api/research/export", json={"run_id": run_id})
        assert exported.status_code == 200 and exported.content == b""
        assert client.get("/api/runs").json()
        assert client.get(f"/api/runs/{run_id}/report").status_code == 200
        assert (
            client.post("/api/research/export", json={"run_id": "../config.yaml"}).status_code
            == 422
        )
