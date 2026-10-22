from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.config import InstrumentRule, load_settings
from paper_trader.features import FeatureSnapshot
from paper_trader.market import Candle
from paper_trader.session_lab import ReplayBook, Scenario, frame_history, market_features, stressed
from paper_trader.timeframe_lab import aggregate_five
from paper_trader.trading import Order, RiskContext

D = Decimal
DAY = date(2026, 10, 22)


@pytest.fixture
def baseline():
    root = Path(__file__).resolve().parents[1]
    return load_settings(root / "profiles/baseline.yaml", root / "profiles/.unused-env")


def bars(settings, count=40, day=DAY):
    at = datetime.combine(day, time(10), TradingCalendar.load(settings).zone)
    return tuple(
        Candle(
            symbol="SAMPLE",
            timeframe="1m",
            opened_at=at + timedelta(minutes=i),
            closed_at=at + timedelta(minutes=i + 1),
            open=D(100),
            high=D("100.01"),
            low=D("99.99"),
            close=D(100),
            volume=1000000,
            source="synthetic_session_test",
        )
        for i in range(count)
    )


def scenario(**shock):
    return Scenario.model_validate(
        {
            "name": "test_case",
            "decisions": ["10:10"],
            "shocks": [{"start": "10:05", "end": "10:15", **shock}],
        }
    )


def context():
    return RiskContext(sector="TEST", average_turnover=D(100000000), bar_volume=1000000, atr=D(1))


def entered(settings, hold=25):
    settings.auto_paper.max_hold_minutes = hold
    book = ReplayBook(settings, "5m")
    source = bars(settings)
    request = Order(
        symbol="SAMPLE",
        side="BUY",
        product="MIS",
        quantity=10,
        signal_at=source[0].opened_at - timedelta(seconds=30),
        stop_price=D(98),
        target_price=D(110),
    )
    assert book.exchange.submit(request, D(100), context()) == []
    book.advance(source[0], context(), 5)
    assert ("SAMPLE", "MIS") in book.exchange.portfolio.positions
    return book, source


def test_stress_is_repeatable_and_future_changes_do_not_change_past(baseline):
    calendar = TradingCalendar.load(baseline)
    prior = bars(baseline, day=date(2026, 10, 21))
    current = bars(baseline)
    case = scenario(jump_bps=200, noise_bps=80)
    result = stressed(prior + current, case, DAY, calendar, 17)
    assert result == stressed(prior + current, case, DAY, calendar, 17)
    assert result[: len(prior)] == prior
    changed = current[:20] + tuple(
        b.model_copy(update={"open": D(200), "high": D(201), "low": D(199), "close": D(200)})
        for b in current[20:]
    )
    assert (
        stressed(prior + changed, case, DAY, calendar, 17)[: len(prior) + 20]
        == result[: len(prior) + 20]
    )
    for value in result:
        assert 0 < value.low <= min(value.open, value.close)
        assert value.high >= max(value.open, value.close)


def test_gap_drift_halt_and_missing_data_remain_distinct(baseline):
    calendar = TradingCalendar.load(baseline)
    source = bars(baseline)
    gap = stressed(source, scenario(jump_bps=200, drift_bps=-4), DAY, calendar, 1)
    assert gap[4].close == 100
    assert gap[5].open == 102
    assert gap[5].close < gap[5].open
    halted = stressed(source, scenario(halted=True), DAY, calendar, 1)
    assert all(b.volume == 0 and b.open == b.high == b.low == b.close for b in halted[5:15])
    missing = stressed(source, scenario(missing_data=True), DAY, calendar, 1)
    assert len(missing) == len(source) - 10
    assert not any(time(10, 5) <= b.opened_at.time() < time(10, 15) for b in missing)
    outage = stressed(source, scenario(inference_outage=True), DAY, calendar, 1)
    assert [(b.open, b.close, b.volume) for b in outage] == [
        (b.open, b.close, b.volume) for b in source
    ]


def test_invalid_stress_history_is_rejected(baseline):
    calendar = TradingCalendar.load(baseline)
    source = bars(baseline)
    with pytest.raises(ValueError, match="chronological"):
        stressed(source[::-1], scenario(), DAY, calendar, 1)
    with pytest.raises(ValueError, match="independently"):
        stressed(
            source + (source[-1].model_copy(update={"symbol": "OTHER"}),),
            scenario(),
            DAY,
            calendar,
            1,
        )


def test_native_warmup_cannot_override_derived_or_leak_future(baseline):
    calendar = TradingCalendar.load(baseline)
    source = bars(baseline)
    native = aggregate_five(bars(baseline, day=date(2026, 10, 21)), calendar)
    poisoned = aggregate_five(source, calendar)[0].model_copy(update={"close": D(1000)})
    at = source[9].closed_at
    result = frame_history(source, native + (poisoned,), baseline, at, "5m")
    assert len(result) == len(native) + 2
    assert result[-1].close == 100
    assert all(b.closed_at <= at for b in result)
    with pytest.raises(ValueError, match="WARMUP"):
        market_features(source, (), baseline, at, "5m")


@pytest.mark.parametrize("hold", [5, 25])
def test_max_hold_closes_on_observed_bar_after_eligibility_and_reconciles(baseline, hold):
    book, source = entered(baseline, hold)
    for bar in source[1 : hold + 2]:
        book.advance(bar, context(), 5)
        book.record(bar.closed_at)
    assert not book.exchange.portfolio.positions
    fills = book.exchange.portfolio.fills
    assert (fills[-1].at - fills[0].at).total_seconds() >= hold * 60
    assert book.closes[0]["reason"] == "MAX_HOLD_EXIT"
    assert book.report()["accounting_passed"]
    assert book.report()["completed_positions"] == 1


def test_protective_stop_runs_without_any_new_model_decisions(baseline):
    book, source = entered(baseline)
    stopped = source[2].model_copy(update={"low": D(97), "close": D(98)})
    book.advance(stopped, context(), 5)
    assert not book.exchange.portfolio.positions
    assert book.exchange.portfolio.fills[-1].reason == "STOP"
    assert not book.decisions
    assert book.report()["accounting_passed"]


def test_halt_and_zero_liquidity_do_not_fabricate_an_exit(baseline):
    book, source = entered(baseline, 5)
    book.settings.instrument_rules["SAMPLE"] = InstrumentRule(halted=True)
    book.advance(source[6].model_copy(update={"volume": 0}), context(), 5)
    assert book.report()["unresolved_positions"] == 1
    assert book.report()["completed_positions"] == 0
    assert book.report()["accounting_passed"]
    book.settings.instrument_rules["SAMPLE"] = InstrumentRule()
    book.advance(source[7], context(), 5)
    book.advance(source[8], context(), 5)
    assert book.report()["unresolved_positions"] == 0


def test_opposite_signal_requests_reduction_without_flipping_position(baseline):
    book, source = entered(baseline)
    snapshot = FeatureSnapshot(
        "SAMPLE", source[2].closed_at, {"atr": 1.0, "ltp": 100.0}, "CHOPPY", "test"
    )
    book.act(snapshot, "SHORT", context(), source[2].closed_at, "TEST")
    assert book.decisions[-1]["action"] == "OPPOSITE_EXIT"
    assert all(
        p.order.reduce_only
        for p in book.exchange.orders.values()
        if p.status in {"OPEN", "PARTIAL"}
    )
    book.advance(source[4], context(), 5)
    assert not book.exchange.portfolio.positions
    assert book.report()["entries"] == 1


def test_pending_entry_expires_and_cannot_fill_afterwards(baseline):
    book = ReplayBook(baseline, "1m")
    source = bars(baseline)
    request = Order(
        symbol="SAMPLE",
        side="BUY",
        product="MIS",
        quantity=10,
        signal_at=source[0].opened_at,
        stop_price=D(98),
        target_price=D(110),
    )
    assert book.exchange.submit(request, D(100), context()) == []
    book.advance(source[6], context(), 5)
    assert book.exchange.orders[request.id].status == "CANCELLED"
    assert not book.exchange.portfolio.fills


def test_shared_portfolio_limits_apply_across_symbols(baseline):
    baseline.risk.max_open_positions = 1
    book, source = entered(baseline)
    snapshot = FeatureSnapshot(
        "OTHER", source[2].closed_at, {"atr": 1.0, "ltp": 100.0}, "CHOPPY", "test"
    )
    book.act(snapshot, "LONG", context(), source[2].closed_at, "TEST")
    assert "MAX_POSITIONS" in book.decisions[-1]["vetoes"]
    assert len(book.exchange.portfolio.positions) == 1


def test_same_minute_profit_cannot_release_a_slot_for_an_earlier_open(baseline):
    baseline.risk.max_open_positions = 1
    book, source = entered(baseline)
    original = source[2]
    winner = original.model_copy(update={"high": D(115), "close": D(110)})
    other = original.model_copy(update={"symbol": "OTHER"})
    request = Order(
        symbol="OTHER",
        side="BUY",
        product="MIS",
        quantity=10,
        signal_at=source[1].opened_at,
        stop_price=D(98),
        target_price=D(110),
    )
    book.settings.risk.max_open_positions = 2
    assert book.exchange.submit(request, D(100), context()) == []
    book.settings.risk.max_open_positions = 1
    book.exchange.begin_batch((winner, other))
    book.advance(winner, context(), 5)
    assert ("SAMPLE", "MIS") in book.exchange.portfolio.positions
    assert book.exchange.portfolio.marks["SAMPLE"] == winner.open
    assert len(book.exchange.portfolio.closed_trades) == 0
    book.advance(other, context(), 5)
    assert book.exchange.orders[request.id].status == "REJECTED"
    assert "MAX_POSITIONS" in book.exchange.veto_log[-1]["reasons"]
    book.end_batch()
    assert not book.exchange.portfolio.positions
    assert book.exchange.portfolio.closed_trades[-1]["reason"] == "TARGET"
    assert book.report()["accounting_passed"]


def test_minute_batch_rejects_missing_duplicates_and_mixed_clocks(baseline):
    book = ReplayBook(baseline, "1m")
    source = bars(baseline)
    with pytest.raises(ValueError, match="share one clock"):
        book.exchange.begin_batch((source[0], source[1]))
    with pytest.raises(ValueError, match="duplicate"):
        book.exchange.begin_batch((source[0], source[0]))
    book.exchange.begin_batch((source[0],))
    with pytest.raises(ValueError, match="incomplete"):
        book.end_batch()
    with pytest.raises(ValueError, match="unfinished"):
        book.exchange.begin_batch((source[1],))
    book.advance(source[0], context(), 5)
    book.end_batch()
    assert book.exchange.portfolio.marks["SAMPLE"] == source[0].close
