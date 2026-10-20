import asyncio

from fastapi.testclient import TestClient

from paper_trader.api import RunRequest, create_app
from paper_trader.config import Settings


def test_manual_order_persists_before_next_bar_and_cancels(settings: Settings) -> None:
    app = create_app(settings)
    terminal = app.state.terminal
    terminal.create(RunRequest())
    engine = terminal.engine
    asyncio.run(engine.jump(engine.events[75].closed_at))
    close = engine.events[75].close
    with TestClient(
        app, base_url="http://127.0.0.1:2080", headers={"X-Paper-Request": "1"}
    ) as client:
        response = client.post(
            "/api/orders",
            json={
                "symbol": "DEMO",
                "quantity": 1,
                "side": "BUY",
                "product": "MIS",
                "signal_at": engine.clock.isoformat(),
                "stop_price": str(close - 1),
            },
        )
        assert response.status_code == 200
        assert response.json()["accepted"], response.json()
        order_id = response.json()["order_id"]
        with terminal.database.connect() as connection:
            assert (
                connection.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()[
                    0
                ]
                == "OPEN"
            )
        assert client.delete(f"/api/orders/{order_id}").status_code == 200
        with terminal.database.connect() as connection:
            assert (
                connection.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()[
                    0
                ]
                == "CANCELLED"
            )
        assert not engine.exchange.portfolio.fills


def test_extreme_numeric_inputs_are_rejected_without_echo(settings: Settings) -> None:
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:2080", headers={"X-Paper-Request": "1"}
    ) as client:
        response = client.post(
            "/api/orders",
            json={
                "symbol": "DEMO",
                "quantity": 10**100,
                "side": "BUY",
                "product": "MIS",
                "signal_at": "2026-09-01T10:00:00+05:30",
                "stop_price": "1e99999",
            },
        )
        assert response.status_code == 422 and "99999" not in response.text
