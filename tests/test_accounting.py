from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import TypeAdapter

from paper_trader.accounting import audit_account
from paper_trader.calendar import TradingCalendar
from paper_trader.live_paper import LivePaper
from paper_trader.market import Candle
from paper_trader.trading import ChargesCalculator, Fill, Order, PaperExchange, Portfolio, Position

D = Decimal
AT = datetime.fromisoformat("2026-10-22T13:30:00+05:30")


def opened(settings):
    settings.execution.slippage_bps = D(0)
    book = Portfolio(D(1000000))
    order = Order(
        symbol="SAMPLE",
        side="BUY",
        product="MIS",
        quantity=1000,
        signal_at=AT,
        stop_price=D(98),
        target_price=D(102),
    )
    charges = ChargesCalculator(settings.charges).calculate(D(100000), "BUY", "MIS", AT.date())
    book.apply(
        Fill(order.id, "SAMPLE", "BUY", "MIS", 1000, D(100), AT, charges, "ENTRY"),
        order,
        "TEST",
        D(1),
    )
    return PaperExchange(settings, TradingCalendar.load(settings), book)


def bar(price, minute):
    at = AT + timedelta(minutes=minute)
    return Candle(
        symbol="SAMPLE",
        timeframe="1m",
        opened_at=at,
        closed_at=at + timedelta(minutes=1),
        open=D(price),
        high=D(price),
        low=D(price),
        close=D(price),
        volume=10000,
        source="synthetic_accounting",
    )


def test_split_protective_fills_share_one_order_and_brokerage_cap(settings):
    sim = opened(settings)
    for i in range(10):
        sim.reflex(bar(102, i), capacity=100)
    exits = sim.portfolio.fills[1:]
    assert len({f.order_id for f in exits}) == 1
    assert sum(f.charges.items["brokerage"] for f in exits) == 20
    assert len(sim.portfolio.positions) == 0
    assert sim.portfolio.cash - sim.portfolio.starting_capital == sim.portfolio.realized_pnl
    assert sum(D(str(t["pnl"])) for t in sim.portfolio.closed_trades) == sim.portfolio.realized_pnl
    assert (
        sum(D(str(t["charges"])) for t in sim.portfolio.closed_trades)
        == sim.portfolio.total_charges
    )


def test_loss_streak_counts_complete_positions_and_aggregate_result(settings):
    sim = opened(settings)
    for i in range(9):
        sim.reflex(bar(98, i), capacity=100)
        assert sim.portfolio.consecutive_losses == 0
    sim.reflex(bar(98, 9), capacity=100)
    assert sim.portfolio.consecutive_losses == 1
    assert sim.portfolio.last_loss_at == bar(98, 9).closed_at
    mixed = opened(settings)
    mixed.reflex(bar(98, 0), capacity=900)
    mixed.reflex(bar(102, 1), capacity=100)
    assert mixed.portfolio.consecutive_losses == 1


def test_protective_fee_cap_survives_serialization(settings):
    sim = opened(settings)
    sim.reflex(bar(102, 0), capacity=500)
    position = sim.portfolio.positions[("SAMPLE", "MIS")]
    adapter = TypeAdapter(Position)
    restored = adapter.validate_json(adapter.dump_json(position))
    sim.portfolio.positions[("SAMPLE", "MIS")] = restored
    sim.reflex(bar(102, 1), capacity=500)
    assert len({f.order_id for f in sim.portfolio.fills[1:]}) == 1
    assert sum(f.charges.items["brokerage"] for f in sim.portfolio.fills[1:]) == 20


def test_legacy_position_without_protective_state_still_loads(settings):
    sim = opened(settings)
    adapter = TypeAdapter(Position)
    raw = adapter.dump_python(sim.portfolio.positions[("SAMPLE", "MIS")], mode="json")
    raw.pop("protective_exits")
    restored = adapter.validate_python(raw)
    assert restored.protective_exits == {}


def test_legacy_partial_exit_reconstructs_brokerage_without_refunding_history(settings):
    sim = opened(settings)
    sim.reflex(bar(102, 0), capacity=500)
    sim.portfolio.positions[("SAMPLE", "MIS")].protective_exits.clear()
    sim.reflex(bar(102, 1), capacity=500)
    assert sum(f.charges.items["brokerage"] for f in sim.portfolio.fills[1:]) == 20


def test_legacy_loss_streak_is_rebuilt_from_complete_position_totals(settings):
    sim = opened(settings)
    for i in range(10):
        sim.reflex(bar(98, i), capacity=100)
    sim.portfolio.consecutive_losses = 100
    before = sim.portfolio.cash
    sim.portfolio.reconcile_loss_streak()
    assert sim.portfolio.consecutive_losses == 1
    assert sim.portfolio.cash == before
    sim = opened(settings)
    sim.reflex(bar(102, 0), capacity=900)
    sim.reflex(bar(98, 1), capacity=100)
    assert sim.portfolio.consecutive_losses == 0


def test_audit_reconciles_without_mutating_account_and_detects_cash_error(settings, database):
    paper = LivePaper(settings, database)
    sim = opened(settings)
    for i in range(10):
        sim.reflex(bar(102, i), capacity=100)
    paper.exchange = sim
    state = paper.saved()
    before = state.model_dump_json()
    report = audit_account(state, settings, AT.date())
    assert report["passed"]
    assert report["protective_brokerage_gst_difference_inr"] == "0.00"
    assert state.model_dump_json() == before
    state.cash += 1
    assert not audit_account(state, settings, AT.date())["checks"]["flat_cash_reconciles"]
