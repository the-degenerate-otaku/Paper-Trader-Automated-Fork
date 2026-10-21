from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from paper_trader.config import InstrumentRule, Settings

if TYPE_CHECKING:
    from paper_trader.trading import Order, RiskContext, Side


@dataclass(frozen=True)
class EntryEconomics:
    gross_target_profit_inr: Decimal
    target_cost_inr: Decimal
    stop_cost_inr: Decimal
    net_target_profit_inr: Decimal
    net_stop_loss_inr: Decimal
    target_cost_multiple: Decimal | None
    net_reward_risk: Decimal | None
    break_even_win_rate: Decimal | None
    assumed_fills_per_side: int
    charge_schedule: str
    entry_charges_inr: Decimal
    target_exit_charges_inr: Decimal
    stop_exit_charges_inr: Decimal
    target_slippage_inr: Decimal
    stop_slippage_inr: Decimal

    def payload(self) -> dict[str, str | int | None]:
        return {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in asdict(self).items()
        }


def estimate_entry(
    settings: Settings,
    order: Order,
    reference_price: Decimal,
    context: RiskContext,
    day: date,
    *,
    entry_already_slipped: bool = False,
    previous_entry_turnover: Decimal = Decimal(0),
    previous_entry_brokerage: Decimal = Decimal(0),
) -> EntryEconomics:
    from paper_trader.trading import ChargesCalculator, tick_round

    prices = (reference_price, order.stop_price, order.target_price)
    if (
        order.reduce_only
        or any(value is None or not value.is_finite() or value <= 0 for value in prices)
        or context.bar_volume <= 0
        or not context.atr.is_finite()
        or context.atr < 0
        or (context.atr == 0 and settings.execution.atr_slippage_fraction > 0)
    ):
        raise ValueError("Entry economics requires valid prices and liquidity")
    if order.stop_price is None or order.target_price is None:
        raise ValueError("Entry economics requires a stop and target")
    direction = Decimal(1 if order.side == "BUY" else -1)
    tick = (
        settings.instrument_rules.get(order.symbol, InstrumentRule()).tick_size
        or settings.execution.tick_size
    )
    stop = tick_round(order.stop_price, tick)
    target = tick_round(order.target_price, tick)
    if (reference_price - stop) * direction <= 0 or (target - reference_price) * direction <= 0:
        raise ValueError("Entry economics requires directional stop and target")
    capacity = int(Decimal(context.bar_volume) * settings.execution.max_bar_volume_fill_pct / 100)
    if capacity <= 0:
        raise ValueError("No estimated fill capacity")
    fills = (order.quantity + capacity - 1) // capacity
    if fills > settings.entry_economics.max_assumed_fills:
        raise ValueError("Estimated fill count exceeds budget")
    calc = ChargesCalculator(settings.charges)
    schedule = calc.schedule(day).id
    exit_side: Side = "SELL" if order.side == "BUY" else "BUY"
    target_net = stop_net = Decimal(0)
    turnover = {key: Decimal(0) for key in ("entry", "target", "stop")}
    brokerage = turnover.copy()
    fees_by_path = turnover.copy()
    remaining = order.quantity
    for part in range(fills):
        quantity = min(capacity, remaining)
        remaining -= quantity
        impact = Decimal(quantity) / context.bar_volume * settings.execution.impact_volume_pct / 100
        rate = settings.execution.slippage_bps / 10000 + impact
        atr_slip = context.atr * settings.execution.atr_slippage_fraction
        entry = reference_price
        if not entry_already_slipped:
            entry = tick_round(entry + direction * (entry * rate + atr_slip), tick, order.side)
            if order.limit_price is not None and order.order_type in {"LIMIT", "SL"}:
                limit = tick_round(order.limit_price, tick)
                entry = min(entry, limit) if direction > 0 else max(entry, limit)
        entry_fee = calc.calculate(
            entry * quantity,
            order.side,
            order.product,
            day,
            previous_entry_turnover + turnover["entry"],
            previous_entry_brokerage + brokerage["entry"],
        )
        turnover["entry"] += entry * quantity
        brokerage["entry"] += entry_fee.items["brokerage"]
        fees_by_path["entry"] += entry_fee.total
        for key, planned in (("target", target), ("stop", stop)):
            exit_price = tick_round(
                planned - direction * (planned * rate + atr_slip), tick, exit_side
            )
            if min(entry, exit_price) <= 0:
                raise ValueError("Estimated slippage consumes the price")
            fees = calc.calculate(
                exit_price * quantity,
                exit_side,
                order.product,
                day,
                turnover[key],
                brokerage[key],
                dp_already_charged=part > 0,
            )
            turnover[key] += exit_price * quantity
            brokerage[key] += fees.items["brokerage"]
            fees_by_path[key] += fees.total
            net = (exit_price - entry) * direction * quantity - entry_fee.total - fees.total
            if key == "target":
                target_net += net
            else:
                stop_net += net
    gross = (target - reference_price) * direction * order.quantity
    stop_gross = (reference_price - stop) * direction * order.quantity
    target_cost, stop_loss = gross - target_net, -stop_net
    return EntryEconomics(
        gross,
        target_cost,
        stop_loss - stop_gross,
        target_net,
        stop_loss,
        gross / target_cost if target_cost > 0 else None,
        target_net / stop_loss if stop_loss > 0 else None,
        stop_loss / (target_net + stop_loss) if target_net > 0 and stop_loss > 0 else None,
        fills,
        schedule,
        fees_by_path["entry"],
        fees_by_path["target"],
        fees_by_path["stop"],
        target_cost - fees_by_path["entry"] - fees_by_path["target"],
        stop_loss - stop_gross - fees_by_path["entry"] - fees_by_path["stop"],
    )
