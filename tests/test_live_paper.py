from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from paper_trader.api import create_app
from paper_trader.config import Settings
from paper_trader.demo import synthetic
from paper_trader.live_paper import LivePaper, Ticket
from paper_trader.storage import Database


@pytest.fixture
def live(settings: Settings, database: Database):
    clock = [datetime.fromisoformat("2026-09-03T11:00:00+05:30").astimezone(UTC)]
    settings.risk.min_avg_turnover_inr = Decimal(1)
    paper = LivePaper(settings, database, lambda: clock[0])
    paper.members = {
        "RELIANCE": {"symbol": "RELIANCE", "company_name": "Test stock", "sector": "Energy"},
        **{f"TEST{i}": {"symbol": f"TEST{i}"} for i in range(49)},
    }
    paper.observed_at = clock[0] - timedelta(hours=1)
    paper.feed = "connected"
    batch = synthetic(settings, datetime.fromisoformat("2026-09-01T09:15:00+05:30"), 3)
    bars = []
    for bar in batch.candles:
        for minute in range(5):
            closed = bar.opened_at + timedelta(minutes=minute + 1)
            if closed <= clock[0]:
                bars.append(
                    bar.model_copy(
                        update={
                            "symbol": "RELIANCE",
                            "timeframe": "1m",
                            "opened_at": closed - timedelta(minutes=1),
                            "closed_at": closed,
                            "volume": bar.volume // 5,
                        }
                    )
                )
    paper.bars["RELIANCE"] = tuple(bars)
    return paper, clock


def tick(paper, clock, price="100", volume=10000, seconds=0, **extra):
    clock[0] += timedelta(seconds=seconds)
    return paper.tick(
        {
            "id": "RELIANCE.NS",
            "price": price,
            "time": str(int(clock[0].timestamp() * 1000)),
            "day_volume": volume,
            "market_hours": 1,
            **extra,
        }
    )


def ticket(**values):
    return Ticket.model_validate(
        {
            "symbol": "RELIANCE",
            "side": "BUY",
            "product": "CNC",
            "quantity": 2,
            "stop_price": "90",
            **values,
        }
    )


def test_observed_quote_entry_exit_and_restart_keep_cash_and_orders(live, settings, database):
    paper, clock = live
    assert tick(paper, clock)
    result = paper.submit(ticket())
    assert result["vetoes"] == [] and paper.exchange.portfolio.positions == {}
    assert tick(paper, clock, volume=12000, seconds=2)
    assert paper.exchange.portfolio.positions[("RELIANCE", "CNC")].quantity == 2
    restored = LivePaper(settings, database, lambda: clock[0])
    assert restored.exchange.portfolio.cash == paper.exchange.portfolio.cash
    assert restored.exchange.portfolio.total_charges == paper.exchange.portfolio.total_charges
    assert restored.exchange.portfolio.positions[("RELIANCE", "CNC")].stop_price == Decimal("90")
    assert restored.exchange.orders[result["id"]].status == "FILLED"
    assert restored.feed == "disconnected" and restored.quotes == {}
    with pytest.raises(HTTPException):
        restored.submit(ticket(side="SELL", reduce_only=True, stop_price=None))
    clock[0] += timedelta(seconds=1)
    assert paper.submit(ticket(side="SELL", reduce_only=True, stop_price=None))["vetoes"] == []
    tick(paper, clock, price="102", volume=14000, seconds=2)
    assert not paper.exchange.portfolio.positions
    assert len(paper.exchange.portfolio.closed_trades) == 1
    final = LivePaper(settings, database, lambda: clock[0])
    assert final.exchange.portfolio.cash == paper.exchange.portfolio.cash
    assert final.exchange.portfolio.closed_trades == paper.exchange.portfolio.closed_trades


def test_live_stale_duplicate_future_and_bad_volume_cannot_fill(live):
    paper, clock = live
    tick(paper, clock)
    assert paper.submit(ticket())["vetoes"] == []
    assert not tick(paper, clock, volume=11000)
    assert not tick(paper, clock, volume=9999, seconds=1)
    assert not tick(paper, clock, price="NaN", seconds=1)
    assert not tick(paper, clock, price="100", currency="USD", seconds=1)
    assert not paper.tick(
        {
            "id": "OTHER.NS",
            "price": 100,
            "time": int(clock[0].timestamp() * 1000),
            "market_hours": 1,
        }
    )
    future = {
        "id": "RELIANCE.NS",
        "price": 100,
        "time": int((clock[0] + timedelta(hours=1)).timestamp() * 1000),
        "market_hours": 1,
    }
    assert not paper.tick(future)
    assert not paper.exchange.portfolio.fills
    clock[0] += timedelta(minutes=1)
    with pytest.raises(HTTPException):
        paper.submit(ticket())


def test_live_stop_works_without_ai_or_liquidity_history(live):
    paper, clock = live
    tick(paper, clock)
    paper.submit(ticket())
    tick(paper, clock, volume=12000, seconds=2)
    paper.bars.clear()
    tick(paper, clock, price="89", volume=14000, seconds=2)
    assert not paper.exchange.portfolio.positions
    assert paper.exchange.portfolio.closed_trades[-1]["reason"] == "STOP"


def test_stream_gap_volume_is_not_invented_as_fill_liquidity(live):
    paper, clock = live
    tick(paper, clock)
    paper.submit(ticket())
    tick(paper, clock, volume=1000000, seconds=60)
    assert not paper.exchange.portfolio.fills
    tick(paper, clock, volume=1001000, seconds=2)
    assert len(paper.exchange.portfolio.fills) == 1


def test_live_failed_commit_rolls_back_fill_and_order_status(live, monkeypatch):
    paper, clock = live
    tick(paper, clock)
    identifier = paper.submit(ticket())["id"]
    before = paper.exchange.portfolio.cash

    def fail(*args):
        raise OSError("test storage failure")

    monkeypatch.setattr(paper, "persist", fail)
    with pytest.raises(OSError):
        tick(paper, clock, volume=12000, seconds=2)
    assert not paper.exchange.portfolio.positions
    assert paper.exchange.portfolio.cash == before
    assert paper.exchange.orders[identifier].status == "OPEN"
    assert not paper.exchange.portfolio.fills


def test_live_nifty_membership_and_session_vetoes(live):
    paper, clock = live
    tick(paper, clock)
    paper.observed_at = clock[0] - timedelta(days=100)
    with pytest.raises(HTTPException):
        paper.submit(ticket())
    paper.observed_at = clock[0]
    paper.bars.clear()
    assert "UNHEALTHY_FEED" in paper.submit(ticket())["vetoes"]
    paper.feed = "disconnected"
    with pytest.raises(HTTPException):
        paper.submit(ticket())


def test_manual_quotes_allow_old_history_gaps_but_not_stale_context(live):
    paper, clock = live
    bars = paper.bars["RELIANCE"]
    paper.bars["RELIANCE"] = bars[:10] + bars[11:]
    tick(paper, clock)
    assert paper.submit(ticket())["vetoes"] == []
    clock[0] += timedelta(minutes=30)
    tick(paper, clock, volume=12000)
    assert paper.context("RELIANCE").feed_healthy is False


def test_paper_http_boundary_and_offline_portfolio(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1:2080") as client:
        state = client.get("/api/paper").json()
        assert state["positions"] == [] and state["feed"] == "disconnected"
        assert state["portfolio"]["cash"] == str(settings.account.starting_capital_inr)
        assert client.post("/api/paper/orders", json={}).status_code == 403
        bad = client.post(
            "/api/paper/orders",
            headers={"X-Paper-Request": "1"},
            json={"symbol": "secret marker", "quantity": -1},
        )
        assert bad.status_code == 422 and "secret marker" not in bad.text
        no_feed = client.post(
            "/api/paper/orders",
            headers={"X-Paper-Request": "1"},
            json=ticket().model_dump(mode="json"),
        )
        assert no_feed.status_code == 409
        with client.websocket_connect(
            "ws://127.0.0.1:2080/api/paper/ws", headers={"Origin": "http://127.0.0.1:2080"}
        ) as stream:
            assert stream.receive_json()["orders"] == []
