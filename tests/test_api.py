from datetime import datetime

from fastapi.testclient import TestClient

from paper_trader.api import create_app
from paper_trader.config import Settings


def test_local_boundary_rejects_cross_origin_host_csrf_and_oversized_body(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings), base_url="http://127.0.0.1:2080") as client:
        assert client.get("/api/terminal", headers={"Host": "evil.example"}).status_code == 403
        assert client.post("/api/run", json={}).status_code == 403
        assert (
            client.post(
                "/api/run",
                json={},
                headers={"X-Paper-Request": "1", "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/run", content=b"x" * 65537, headers={"X-Paper-Request": "1"}
            ).status_code
            == 413
        )
        bad = client.post(
            "/api/run",
            json={"symbol": "secret credential marker", "strategy": "live"},
            headers={"X-Paper-Request": "1"},
        )
        assert bad.status_code == 422 and "secret" not in bad.text
        assert client.get("/api/../../config.yaml").status_code == 404


def test_replay_api_smoke_and_websocket_only_reveal_closed_bars(settings: Settings) -> None:
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:2080", headers={"X-Paper-Request": "1"}
    ) as client:
        assert client.post("/api/step").status_code == 409
        created = client.post("/api/run", json={"strategy": "hold"})
        assert created.status_code == 200
        assert created.json()["run"]["cursor"] == 0
        assert created.json()["candles"] == []
        state = client.post("/api/step").json()
        assert state["run"]["cursor"] == 1 and len(state["candles"]) == 1
        assert datetime.fromisoformat(state["candles"][0]["closed_at"]) == datetime.fromisoformat(
            state["run"]["clock"]
        )
        with client.websocket_connect(
            "ws://127.0.0.1:2080/api/ws", headers={"Origin": "http://127.0.0.1:2080"}
        ) as socket:
            assert socket.receive_json()["run"]["cursor"] == 1
        assert client.get("/api/v1/trading/positions").json() == {"positions": []}
        assert client.get("/api/v1/trading/accounts").json()["accounts"]
        assert client.get("/api/v1/trading/portfolio/summary").json()["summary"][
            "total_value"
        ] == float(settings.account.starting_capital_inr)


def test_api_shadow_and_manual_order_timestamp_veto(settings: Settings) -> None:
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:2080", headers={"X-Paper-Request": "1"}
    ) as client:
        client.post("/api/run", json={"shadow": True})
        clock = client.post("/api/step").json()["run"]["clock"]
        order = {
            "symbol": "DEMO",
            "quantity": 1,
            "side": "BUY",
            "product": "MIS",
            "signal_at": clock,
            "stop_price": 90,
        }
        assert client.post("/api/orders", json=order).status_code == 409
        client.post("/api/run", json={"shadow": False})
        client.post("/api/step")
        order["signal_at"] = "2026-09-01T10:00:00+05:30"
        assert client.post("/api/orders", json=order).status_code == 422
