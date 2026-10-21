import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from paper_trader.api import create_app
from paper_trader.config import Settings
from paper_trader.demo import synthetic
from paper_trader.engine import Signal
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


def test_stop_risk_rejection_explains_absolute_price_and_budget(live):
    paper, clock = live
    tick(paper, clock, price="925")
    result = paper.submit(ticket(quantity=20, stop_price="10.01"))
    assert "TRADE_RISK_LIMIT" in result["vetoes"]
    message = result["messages"][0]
    assert "18,299.80" in message
    budget = paper.exchange.portfolio.equity * paper.settings.risk.risk_per_trade_pct / 100
    assert f"{budget:,.2f}" in message
    assert "absolute stock price" in message
    assert paper.exchange.portfolio.positions == {}
    assert paper.submit(ticket(quantity=20, stop_price="915"))["vetoes"] == []


def test_cooldown_and_short_stop_messages_preserve_both_reasons(live):
    paper, clock = live
    tick(paper, clock)
    portfolio = paper.exchange.portfolio
    portfolio.consecutive_losses = paper.settings.risk.max_consecutive_losses
    portfolio.last_loss_at = clock[0]
    result = paper.submit(ticket(side="SELL", product="MIS", stop_price="90"))
    assert "LOSS_COOLDOWN" in result["vetoes"] and "INVALID_STOP" in result["vetoes"]
    message = " ".join(result["messages"])
    resume = (clock[0] + timedelta(minutes=paper.settings.risk.cooldown_minutes)).astimezone(
        paper.calendar.zone
    )
    assert f"{resume:%H:%M:%S} IST" in message
    assert "strictly above" in message
    assert "reduce-only closing orders remain available" in message
    assert "INVALID_STOP" not in paper.submit(ticket(stop_price="90"))["vetoes"]
    assert "strictly below" in " ".join(paper.submit(ticket(stop_price="110"))["messages"])
    clock[0] += timedelta(minutes=paper.settings.risk.cooldown_minutes)
    tick(paper, clock)
    assert "LOSS_COOLDOWN" not in paper.submit(ticket())["vetoes"]


def test_explained_rejection_does_not_hide_other_checks(live):
    paper, clock = live
    tick(paper, clock)
    result = paper.submit(ticket(side="SELL", product="CNC", stop_price="90"))
    assert "CNC_LONG_ONLY" in result["vetoes"]
    assert "CNC_LONG_ONLY" in result["messages"]


def test_automatic_history_coalesces_refresh_and_retries_failures(live, monkeypatch):
    paper, clock = live
    bars = paper.bars["RELIANCE"]
    calls = []

    def load(*args):
        calls.append(1)
        return SimpleNamespace(candles=bars)

    monkeypatch.setattr("paper_trader.live_paper.YFinanceProvider.history", load)
    monkeypatch.setattr("paper_trader.live_paper.CandleStore.save", lambda *args: None)

    async def refresh():
        await asyncio.gather(paper.prepare("RELIANCE"), paper.prepare("RELIANCE"))
        assert len(calls) == 1
        clock[0] += timedelta(seconds=paper.settings.live_paper.history_poll_seconds)
        await paper.prepare("RELIANCE")
        assert len(calls) == 2

    asyncio.run(refresh())
    clock[0] += timedelta(seconds=paper.settings.live_paper.history_poll_seconds)

    def fail(*args):
        raise ValueError("private provider failure")

    monkeypatch.setattr("paper_trader.live_paper.YFinanceProvider.history", fail)
    with pytest.raises(HTTPException) as error:
        asyncio.run(paper.prepare("RELIANCE"))
    assert error.value.status_code == 502
    assert "private" not in str(error.value.detail)
    monkeypatch.setattr("paper_trader.live_paper.YFinanceProvider.history", load)
    asyncio.run(paper.prepare("RELIANCE"))
    assert "RELIANCE" not in paper.errors


def test_history_cache_keeps_pending_order_context(live, monkeypatch):
    paper, clock = live
    paper.settings.live_paper.max_prepared_symbols = 1
    bars = paper.bars["RELIANCE"]
    monkeypatch.setattr(
        "paper_trader.live_paper.YFinanceProvider.history",
        lambda *args: SimpleNamespace(candles=bars),
    )
    monkeypatch.setattr("paper_trader.live_paper.CandleStore.save", lambda *args: None)
    tick(paper, clock)
    identifier = paper.submit(ticket())["id"]
    with pytest.raises(HTTPException) as error:
        asyncio.run(paper.prepare("TEST0"))
    assert error.value.status_code == 409 and "RELIANCE" in paper.bars
    paper.exchange.cancel(identifier)
    asyncio.run(paper.prepare("TEST0"))
    assert set(paper.bars) == {"TEST0"}
    with pytest.raises(HTTPException):
        asyncio.run(paper.prepare("OUTSIDE"))


def seed_movers(paper, clock):
    from paper_trader.live_paper import Quote

    for symbol in paper.members:
        paper.quotes[symbol] = Quote(
            symbol=symbol,
            price=100,
            at=clock[0],
            day_volume=10000,
            regular=True,
            change_percent=0,
        )
    paper.quotes["RELIANCE"].change_percent = -10
    paper.quotes["TEST0"].change_percent = 5


def test_auto_movers_rank_absolute_percent_and_require_all_fresh(live):
    paper, clock = live
    paper.settings.auto_paper.mover_count = 5
    seed_movers(paper, clock)
    assert paper.automation.movers()[:2] == ["RELIANCE", "TEST0"]
    assert len(paper.automation.movers()) == 5
    paper.quotes["TEST1"].at -= timedelta(seconds=60)
    assert paper.automation.movers() == []


def test_auto_model_unavailable_never_enables_entries(live, monkeypatch):
    paper, _ = live

    async def unavailable():
        return False

    monkeypatch.setattr(paper.automation.strategy, "health", unavailable)
    with pytest.raises(HTTPException):
        asyncio.run(paper.automation.start())
    assert not paper.automation.enabled and not paper.exchange.orders


def test_auto_sizes_mis_orders_and_stop_only_cancels_bot_entries(live):
    paper, clock = live
    tick(paper, clock)
    manual = paper.submit(ticket())["id"]
    paper.automation.enabled = True
    event = {}
    asyncio.run(paper.automation.submit("RELIANCE", clock[0], 1.0, True, event))
    assert event["vetoes"] == []
    bot = paper.exchange.orders[event["order_id"]]
    assert bot.order.product == "MIS" and bot.order.stop_price < Decimal(100)
    assert bot.order.target_price > Decimal(100) and bot.order.quantity > 0
    restored = LivePaper(paper.settings, paper.database, lambda: clock[0])
    assert not restored.automation.enabled
    assert event["order_id"] in restored.automation.order_ids
    assert restored.exchange.orders[event["order_id"]].status == "CANCELLED"
    assert restored.exchange.orders[manual].status == "OPEN"
    asyncio.run(paper.automation.stop())
    assert bot.status == "CANCELLED" and paper.exchange.orders[manual].status == "OPEN"


def test_auto_cannot_bypass_cooldown_stale_quote_or_stop_after_disable(live):
    paper, clock = live
    tick(paper, clock)
    paper.automation.enabled = True
    portfolio = paper.exchange.portfolio
    portfolio.last_loss_at = clock[0]
    portfolio.consecutive_losses = paper.settings.risk.max_consecutive_losses
    event = {}
    asyncio.run(paper.automation.submit("RELIANCE", clock[0], 1.0, True, event))
    assert "LOSS_COOLDOWN" in event["vetoes"]
    clock[0] += timedelta(seconds=60)
    asyncio.run(paper.automation.submit("RELIANCE", clock[0], 1.0, True, event))
    assert "fresh" in event["vetoes"][0]
    paper.automation.enabled = False
    asyncio.run(paper.automation.submit("RELIANCE", clock[0], 1.0, True, event))
    assert event["vetoes"] == ["STALE_AI_DECISION"]
    assert not paper.exchange.orders


def test_auto_closed_candle_once_and_restart_deduplication(live, monkeypatch):
    paper, clock = live
    seed_movers(paper, clock)
    paper.settings.auto_paper.mover_count = 1
    paper.automation.enabled = True
    calls = []
    future = paper.bars["RELIANCE"][-1].model_copy(
        update={
            "opened_at": clock[0] + timedelta(minutes=1),
            "closed_at": clock[0] + timedelta(minutes=2),
        }
    )
    paper.bars["RELIANCE"] += (future,)

    async def prepared(symbol):
        return None

    async def decide(snapshot, portfolio):
        calls.append(snapshot.at)
        paper.automation.strategy.healthy = True
        return Signal("HOLD", "MODEL_NEUTRAL")

    monkeypatch.setattr(paper, "prepare", prepared)
    monkeypatch.setattr(paper.automation.strategy, "decide", decide)

    async def cycle():
        await paper.automation.cycle()
        await paper.automation.cycle()

    asyncio.run(cycle())
    assert len(calls) == 1 and calls[0] <= clock[0]
    assert paper.automation.events[-1]["reason"] == "MODEL_NEUTRAL"
    restored = LivePaper(paper.settings, paper.database, lambda: clock[0])
    assert restored.automation.last_bars["RELIANCE"] == calls[0]
    assert len(restored.automation.events) == len(paper.automation.events)
    assert not restored.automation.enabled


def test_auto_rejects_gapped_or_old_candles_without_inference(live, monkeypatch):
    paper, clock = live
    seed_movers(paper, clock)
    paper.settings.auto_paper.mover_count = 1
    paper.automation.enabled = True
    paper.bars["RELIANCE"] = paper.bars["RELIANCE"][:-1]
    paper.bars["RELIANCE"] = paper.bars["RELIANCE"][:-20] + paper.bars["RELIANCE"][-19:]

    async def prepared(symbol):
        return None

    async def unexpected(*args):
        pytest.fail("Inference must not see gapped data")

    monkeypatch.setattr(paper, "prepare", prepared)
    monkeypatch.setattr(paper.automation.strategy, "decide", unexpected)
    asyncio.run(paper.automation.cycle())
    assert not paper.automation.events and not paper.exchange.orders


def test_auto_stop_during_inference_prevents_late_order(live, monkeypatch):
    paper, clock = live
    seed_movers(paper, clock)
    paper.settings.auto_paper.mover_count = 1
    paper.automation.enabled = True

    async def run():
        started = asyncio.Event()

        async def prepared(symbol):
            return None

        async def delayed(*args):
            started.set()
            await asyncio.Event().wait()
            return Signal("LONG", "ACCEPTED")

        monkeypatch.setattr(paper, "prepare", prepared)
        monkeypatch.setattr(paper.automation.strategy, "decide", delayed)
        paper.automation.task = asyncio.create_task(paper.automation.cycle())
        await started.wait()
        await paper.automation.stop()

    asyncio.run(run())
    assert not paper.automation.enabled and not paper.exchange.orders


def test_full_universe_is_not_blocked_by_one_missing_quote(live):
    paper, clock = live
    paper.settings.auto_paper.mover_count = 50
    seed_movers(paper, clock)
    paper.quotes.pop("TEST1")
    assert set(paper.automation.movers()) == set(paper.members)
    assert len(paper.automation.movers()) == 50


def test_active_positions_preempt_candidates_during_scan(live, monkeypatch):
    paper, clock = live
    seed_movers(paper, clock)
    paper.automation.enabled = True
    paper.settings.auto_paper.mover_count = 50
    visited = []

    async def review(symbol):
        visited.append(symbol)
        if len(visited) == 1:
            identifier = paper.submit(ticket(product="MIS"))["id"]
            assert identifier
            tick(paper, clock, volume=12000, seconds=2)

    monkeypatch.setattr(paper.automation, "review", review)
    asyncio.run(paper.automation.cycle())
    assert visited[:2] == ["RELIANCE", "RELIANCE"]
    assert set(visited) == set(paper.members)


def test_opposite_signal_closes_without_reversing_or_bypassing_fills(live):
    paper, clock = live
    tick(paper, clock)
    identifier = paper.submit(ticket(product="MIS"))["id"]
    tick(paper, clock, volume=12000, seconds=2)
    paper.automation.enabled = True
    event = {}
    asyncio.run(
        paper.automation.submit("RELIANCE", clock[0], 1.0, False, event, review_entry_id=identifier)
    )
    assert event["action"] == "AI_OPPOSITE_EXIT" and event["vetoes"] == []
    assert paper.exchange.portfolio.positions[("RELIANCE", "MIS")].quantity == 2
    closing = paper.exchange.orders[event["order_id"]]
    assert closing.order.reduce_only and closing.order.side == "SELL"
    tick(paper, clock, volume=14000, seconds=2)
    assert not paper.exchange.portfolio.positions


def test_active_review_sends_position_state_and_queues_opposite_exit(live, monkeypatch):
    paper, clock = live
    tick(paper, clock)
    paper.submit(ticket(product="MIS"))
    tick(paper, clock, volume=12000, seconds=2)
    paper.automation.enabled = True

    async def prepare(symbol):
        return None

    async def decide(snapshot, portfolio):
        assert "Position:LONG" in snapshot.state
        paper.automation.strategy.healthy = True
        return Signal("SHORT", "ACCEPTED")

    monkeypatch.setattr(paper, "prepare", prepare)
    monkeypatch.setattr(paper.automation.strategy, "decide", decide)
    asyncio.run(paper.automation.review("RELIANCE"))
    assert paper.automation.events[-1]["action"] == "AI_OPPOSITE_EXIT"
    assert any(p.order.reduce_only for p in paper.exchange.orders.values())


def test_position_review_cannot_reopen_closed_position(live):
    paper, clock = live
    tick(paper, clock)
    paper.automation.enabled = True
    event = {}
    asyncio.run(
        paper.automation.submit(
            "RELIANCE", clock[0], 1.0, False, event, review_entry_id="closed-entry"
        )
    )
    assert event["vetoes"] == ["POSITION_CHANGED_DURING_INFERENCE"]
    assert not paper.exchange.orders


def test_new_bot_holding_cap_queues_exit_with_ai_stopped_and_restores(live):
    paper, clock = live
    tick(paper, clock)
    paper.automation.enabled = True
    event = {}
    asyncio.run(paper.automation.submit("RELIANCE", clock[0], 1.0, True, event))
    tick(paper, clock, volume=50000, seconds=2)
    position = paper.exchange.portfolio.positions[("RELIANCE", "MIS")]
    identifier = position.entry_order_id
    restored = LivePaper(paper.settings, paper.database, lambda: clock[0])
    assert (
        restored.automation.holding_limits[identifier] == paper.settings.auto_paper.max_hold_minutes
    )
    paper.automation.enabled = False
    clock[0] = position.opened_at + timedelta(minutes=paper.settings.auto_paper.max_hold_minutes)
    paper.quotes["RELIANCE"].at = clock[0] - timedelta(seconds=1)
    tick(paper, clock, volume=51000)
    exits = [p for p in paper.exchange.orders.values() if p.order.reduce_only]
    assert len(exits) == 1 and exits[0].status == "OPEN"
    tick(paper, clock, volume=52000, seconds=2)
    assert exits[0].status == "PARTIAL"
    tick(paper, clock, volume=100000, seconds=2)
    assert not paper.exchange.portfolio.positions
