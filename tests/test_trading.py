from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from paper_trader.calendar import TradingCalendar
from paper_trader.config import InstrumentRule, Settings
from paper_trader.market import Candle
from paper_trader.trading import (
    ChargesCalculator,
    Order,
    PaperExchange,
    Portfolio,
    RiskContext,
    RiskEngine,
    tick_round,
)

D = Decimal
AT = datetime.fromisoformat("2026-10-19T10:00:00+05:30")


def context() -> RiskContext:
    return RiskContext(sector="BANKING", average_turnover=D(1000000000), bar_volume=10000)


def order(**kwargs: object) -> Order:
    return Order.model_validate(
        {
            "symbol": "SAMPLE",
            "side": "BUY",
            "product": "MIS",
            "quantity": 10,
            "signal_at": AT,
            "stop_price": "98",
            "target_price": "110",
            **kwargs,
        }
    )


def candle(at: datetime = AT, **kwargs: object) -> Candle:
    return Candle.model_validate(
        {
            "symbol": "SAMPLE",
            "timeframe": "5m",
            "opened_at": at,
            "closed_at": at + timedelta(minutes=5),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": 10000,
            "source": "fixture",
            **kwargs,
        }
    )


def exchange(settings: Settings) -> PaperExchange:
    settings.execution.latency_ms = 0
    settings.execution.slippage_bps = D(0)
    settings.execution.impact_volume_pct = D(0)
    settings.execution.atr_slippage_fraction = D(0)
    return PaperExchange(settings, TradingCalendar.load(settings), Portfolio(D(100000)))


@pytest.mark.parametrize(
    ("side", "product", "total"),
    [
        ("BUY", "MIS", "30.34"),
        ("SELL", "MIS", "52.34"),
        ("BUY", "CNC", "118.74"),
        ("SELL", "CNC", "119.08"),
    ],
)
def test_charges_against_hand_computed_examples(
    settings: Settings, side: str, product: str, total: str
) -> None:
    fees = ChargesCalculator(settings.charges).calculate(D(100000), side, product, AT.date())
    assert fees.total == D(total)
    assert fees.items["exchange"] == D("3.07")
    assert fees.items["sebi"] == D("0.10")


def test_partial_brokerage_cap_and_dp_dedup(settings: Settings) -> None:
    calc = ChargesCalculator(settings.charges)
    first = calc.calculate(D(50000), "BUY", "MIS", AT.date())
    second = calc.calculate(D(50000), "BUY", "MIS", AT.date(), D(50000), first.items["brokerage"])
    assert first.items["brokerage"] + second.items["brokerage"] == 20
    fees = calc.calculate(D(100000), "SELL", "CNC", AT.date(), dp_already_charged=True)
    assert fees.items["dp"] == fees.items["dp_gst"] == 0
    with pytest.raises(ValueError, match="schedule"):
        calc.schedule(date(2026, 1, 1))


def test_same_signal_bar_cannot_fill(settings: Settings) -> None:
    sim = exchange(settings)
    assert sim.submit(order(), D(100), context()) == []
    assert sim.process(candle(AT - timedelta(minutes=5))) == []
    assert len(sim.process(candle())) == 1


def test_intraday_accounting_long_and_short(settings: Settings) -> None:
    for side in ("BUY", "SELL"):
        sim = exchange(settings)
        stop, target = ("98", "110") if side == "BUY" else ("102", "90")
        assert not sim.submit(
            order(side=side, stop_price=stop, target_price=target), D(100), context()
        )
        sim.process(candle())
        assert sim.portfolio.cash < 100000
        assert sim.portfolio.cash > 99000
        close_side = "SELL" if side == "BUY" else "BUY"
        close_order = order(side=close_side, reduce_only=True, signal_at=AT + timedelta(minutes=5))
        assert not sim.submit(close_order, D(100), context())
        sim.process(candle(AT + timedelta(minutes=5)))
        assert not sim.portfolio.positions
        assert sim.portfolio.equity == D(100000) - sim.portfolio.total_charges
        assert sim.portfolio.realized_pnl == -sim.portfolio.total_charges


def test_delivery_requires_cash_and_cnc_short_is_vetoed(settings: Settings) -> None:
    sim = exchange(settings)
    reasons = sim.submit(
        order(side="SELL", product="CNC", stop_price="102", target_price="90"), D(100), context()
    )
    assert "CNC_LONG_ONLY" in reasons
    assert not sim.submit(order(product="CNC"), D(100), context())
    sim.process(candle())
    assert sim.portfolio.cash < 99000
    assert sim.portfolio.equity == D(100000) - sim.portfolio.total_charges


def test_partial_fills_keep_one_position_and_trade_count(settings: Settings) -> None:
    sim = exchange(settings)
    entry = order(quantity=20)
    assert not sim.submit(entry, D(100), context())
    for i in range(2):
        fills = sim.process(candle(AT + timedelta(minutes=5 * i), volume=100))
        assert fills[0].quantity == 10
    assert sim.orders[entry.id].status == "FILLED"
    assert sim.portfolio.positions[("SAMPLE", "MIS")].quantity == 20
    assert len(sim.portfolio.entry_times["SAMPLE"]) == 1


def test_limit_requires_trade_through_and_triggered_orders(settings: Settings) -> None:
    sim = exchange(settings)
    entry = order(order_type="LIMIT", limit_price="99")
    assert not sim.submit(entry, D(100), context())
    assert not sim.process(candle(low="99"))
    fills = sim.process(candle(AT + timedelta(minutes=5), low="98.95"))
    assert fills[0].price <= 99
    sim = exchange(settings)
    entry = order(order_type="SL-M", trigger_price="101", stop_price="98", target_price="110")
    assert not sim.submit(entry, D(100), context())
    assert not sim.process(candle(high="100.5"))
    assert sim.process(candle(AT + timedelta(minutes=5), high="101.5"))[0].price == 101


def test_stop_wins_ambiguous_bar_and_gap_fills_adversely(settings: Settings) -> None:
    sim = exchange(settings)
    sim.submit(order(), D(100), context())
    sim.process(candle())
    fills = sim.process(
        candle(AT + timedelta(minutes=5), open="97", low="96", high="112", close="100")
    )
    assert fills[0].reason == "STOP" and fills[0].price == 97
    assert not sim.portfolio.positions


def test_mis_squareoff_and_trailing_stops(settings: Settings) -> None:
    sim = exchange(settings)
    sim.submit(order(trailing_distance="2"), D(100), context())
    sim.process(candle())
    sim.process(candle(AT + timedelta(minutes=5), open="103", high="104", low="102", close="103"))
    assert sim.portfolio.positions[("SAMPLE", "MIS")].stop_price == 102
    fills = sim.process(
        candle(AT.replace(hour=15, minute=10), open="105", high="106", low="104", close="105")
    )
    assert fills[0].reason == "MIS_SQUAREOFF"


def test_risk_limits_override_any_entry(settings: Settings) -> None:
    sim = exchange(settings)
    assert "POSITION_LIMIT" in sim.submit(order(quantity=1000), D(100), context())
    assert "TRADE_RISK_LIMIT" in sim.submit(order(stop_price="1", quantity=10), D(100), context())
    assert "TURNOVER_FILTER" in sim.submit(order(), D(100), RiskContext(bar_volume=10000))
    assert "REFERENCE_INSTRUMENT" in sim.submit(
        order(), D(100), RiskContext(instrument_type="INDEX")
    )
    sim.portfolio.kill_switch = True
    assert "DRAWDOWN_KILL" in sim.submit(order(), D(100), context())
    assert "INVALID_PRICE" in sim.submit(order(), D("NaN"), context())


def test_loss_limits_and_cooldown_are_account_wide(settings: Settings) -> None:
    sim = exchange(settings)
    sim.portfolio.checkpoint(AT, sim.calendar)
    sim.portfolio.cash = D(89000)
    reasons = sim.submit(order(), D(100), context())
    assert {"DAILY_LOSS_LIMIT", "WEEKLY_LOSS_LIMIT", "DRAWDOWN_KILL"}.issubset(reasons)
    sim = exchange(settings)
    sim.portfolio.consecutive_losses = settings.risk.max_consecutive_losses
    sim.portfolio.last_loss_at = AT
    assert "LOSS_COOLDOWN" in sim.submit(order(), D(100), context())


def test_halt_circuit_event_and_duplicate_guards(settings: Settings) -> None:
    sim = exchange(settings)
    settings.instrument_rules["SAMPLE"] = InstrumentRule(upper_circuit=D(100))
    assert "CIRCUIT" in sim.submit(order(), D(100), context())
    settings.instrument_rules["SAMPLE"] = InstrumentRule(halted=True)
    assert "HALTED_OR_BANNED" in sim.submit(order(), D(100), context())
    settings.instrument_rules.clear()
    settings.risk.event_blackouts["SAMPLE"] = [AT.date()]
    assert "EVENT_BLACKOUT" in sim.submit(order(), D(100), context())
    settings.risk.event_blackouts.clear()
    entry = order()
    assert not sim.submit(entry, D(100), context())
    assert sim.submit(entry, D(100), context()) == ["DUPLICATE_ORDER"]


def test_order_validation_and_tick_rounding() -> None:
    for updates in (
        {"quantity": 0},
        {"stop_price": None},
        {"quantity": -1},
        {"order_type": "LIMIT"},
        {"validity": "GTC"},
    ):
        with pytest.raises(ValidationError):
            order(**updates)
    assert tick_round(D("100.021"), D("0.05"), "BUY") == D("100.05")
    assert tick_round(D("100.021"), D("0.05"), "SELL") == D("100.00")
    assert RiskEngine.size
