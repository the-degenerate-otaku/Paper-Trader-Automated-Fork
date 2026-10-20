from datetime import datetime
from decimal import Decimal

import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.trading import Order, PaperExchange, Portfolio, RiskContext


@pytest.mark.parametrize(
    ("field", "kind"),
    [
        ("stop_price", "MARKET"),
        ("limit_price", "LIMIT"),
        ("trigger_price", "SL-M"),
        ("target_price", "BRACKET"),
        ("trailing_distance", "MARKET"),
    ],
)
def test_subtick_price_cannot_become_zero_after_validation(
    settings: Settings, field: str, kind: str
) -> None:
    exchange = PaperExchange(settings, TradingCalendar.load(settings), Portfolio(Decimal(1000000)))
    values = {
        "symbol": "RELIANCE",
        "side": "BUY",
        "product": "MIS",
        "quantity": 1,
        "signal_at": datetime.fromisoformat("2026-09-01T10:00:00+05:30"),
        "order_type": kind,
        "stop_price": Decimal(90),
        "target_price": Decimal(120),
        field: Decimal("0.001"),
    }
    order = Order.model_validate(values)
    vetoes = exchange.submit(
        order,
        Decimal(100),
        RiskContext(sector="TEST", average_turnover=Decimal(1000000000), bar_volume=1000000),
    )
    assert "INVALID_ROUNDED_PRICE" in vetoes
    assert not exchange.orders
