from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from paper_trader import charting
from paper_trader.api import create_app
from paper_trader.config import Settings
from paper_trader.demo import synthetic
from paper_trader.market import DataBatch


@pytest.fixture
def chart_client(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 4, 12, tzinfo=UTC)

    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 2)
    market_batch = DataBatch(
        candles=tuple(c.model_copy(update={"symbol": "RELIANCE"}) for c in batch.candles),
        fetched_at=Clock.now(),
        warnings=("HISTORICAL_REVISION_NOT_POINT_IN_TIME",),
    )
    monkeypatch.setattr(charting, "datetime", Clock)
    monkeypatch.setattr(charting.YFinanceProvider, "history", lambda *args: market_batch)
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:2080", headers={"X-Paper-Request": "1"}
    ) as client:
        yield client


def test_chart_download_cache_and_replay_isolation(chart_client: TestClient, monkeypatch):
    chart_client.post("/api/run", json={})
    before = chart_client.post("/api/step").json()
    result = chart_client.post("/api/market/chart", json={"symbol": "RELIANCE"})
    assert result.status_code == 200
    data = result.json()
    assert data["live"] is False and len(data["candles"]) == 150
    assert len(data["indicators"]) == len(data["candles"])
    assert data["indicators"][-1]["values"]["ema_50"] is not None
    assert data["indicators"][0]["values"]["ema_50"] is None
    assert max(c["closed_at"] for c in data["candles"]) <= data["as_of"]

    def unavailable(*args):
        raise RuntimeError("private credential marker")

    monkeypatch.setattr(charting.YFinanceProvider, "history", unavailable)
    cached = chart_client.post("/api/market/chart", json={"symbol": "RELIANCE"})
    assert cached.status_code == 200 and cached.json()["version"] == data["version"]
    failed = chart_client.post("/api/market/chart", json={"symbol": "RELIANCE", "refresh": True})
    assert failed.status_code == 502 and "private" not in failed.text
    after = chart_client.get("/api/terminal").json()
    assert before["run"] == after["run"]
    assert before["candles"] == after["candles"]
    assert before["orders"] == after["orders"]
    catalog = chart_client.get("/api/market/symbols").json()
    assert any(s["symbol"] == "RELIANCE" for s in catalog)
    assert not any(s["symbol"] == "DEMO" for s in catalog)


@pytest.mark.parametrize(
    "payload",
    [
        {"symbol": "https://evil.example"},
        {"symbol": "RELIANCE", "timeframe": "../../config.yaml"},
        {"symbol": "RELIANCE", "days": 999999},
        {"symbol": "RELIANCE.NS"},
        {"symbol": "DEMO"},
        {"symbol": "RELIANCE", "timeframe": "1m", "days": 30},
        {"symbol": "RELIANCE", "timeframe": "5m", "days": 365},
    ],
)
def test_chart_rejects_unsafe_or_unbounded_requests(chart_client, payload):
    assert chart_client.post("/api/market/chart", json=payload).status_code == 422


def test_pinned_chart_dataset_cannot_silently_change(chart_client):
    first = chart_client.post("/api/market/chart", json={"symbol": "RELIANCE"}).json()
    version = first["version"]
    assert (
        chart_client.post(
            "/api/market/chart", json={"symbol": "RELIANCE", "version": version}
        ).json()["version"]
        == version
    )
    assert (
        chart_client.post(
            "/api/market/chart", json={"symbol": "RELIANCE", "version": version, "refresh": True}
        ).status_code
        == 422
    )
    assert (
        chart_client.post(
            "/api/market/chart", json={"symbol": "RELIANCE", "version": "a" * 64}
        ).status_code
        == 404
    )
