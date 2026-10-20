from fastapi.testclient import TestClient

from paper_trader.api import create_app
from paper_trader.config import Settings


def test_arena_api_smoke_and_immediate_pause(settings: Settings) -> None:
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:2080", headers={"X-Paper-Request": "1"}
    ) as client:
        assert client.post("/api/arena/create").status_code == 409
        client.post("/api/run", json={})
        created = client.post("/api/arena/create").json()
        assert len(created["bots"]) == 2
        assert not any(b["enabled"] for b in created["bots"])
        key = settings.arena.bots[0].id
        assert (
            client.post(
                f"/api/arena/bots/{key}", json={"mode": "live", "enabled": True}
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/arena/bots/{key}", json={"mode": "shadow", "enabled": True}
            ).status_code
            == 200
        )
        assert client.post("/api/arena/play").status_code == 200
        paused = client.post("/api/arena/pause").json()
        assert not paused["running"]
