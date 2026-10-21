from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from paper_trader.data import quality
from paper_trader.features import FeatureEngine
from paper_trader.inference import SystemOneStrategy

if TYPE_CHECKING:
    from paper_trader.live_paper import LivePaper


class AutoPaper:
    def __init__(self, paper: LivePaper) -> None:
        self.paper = paper
        settings = paper.settings.model_copy(deep=True)
        settings.simulation.product = "MIS"
        self.strategy = SystemOneStrategy(settings)
        self.features = FeatureEngine(settings, paper.calendar)
        self.task: asyncio.Task[None] | None = None
        self.enabled = False
        self.status = "Stopped"
        self.symbols: list[str] = []
        self.last_bars: dict[str, datetime] = {}
        self.events: deque[dict[str, Any]] = deque(maxlen=settings.auto_paper.max_events)
        self.order_ids: set[str] = set()
        self.holding_limits: dict[str, int] = {}
        self.priority_checked: dict[str, datetime] = {}
        self.priority_entry_ids: dict[str, str | None] = {}
        self.control = asyncio.Lock()
        with paper.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM live_paper_events WHERE event='auto_decision' "
                "ORDER BY id DESC LIMIT ?",
                (settings.auto_paper.max_events,),
            ).fetchall()
            for row in reversed(rows):
                event = json.loads(row[0])
                if event.get("reason") != "INFERENCE_PENDING":
                    self.events.append(event)
                if event.get("bar_at"):
                    self.last_bars[event["symbol"]] = datetime.fromisoformat(event["bar_at"])
            for row in connection.execute(
                "SELECT payload_json FROM live_paper_events WHERE event='order_submitted'"
            ).fetchall():
                payload = json.loads(row[0])
                if payload.get("automated"):
                    self.order_ids.add(payload["order"]["id"])
                    if payload.get("max_hold_minutes"):
                        self.holding_limits[payload["order"]["id"]] = payload["max_hold_minutes"]
        restarted = [
            identifier
            for identifier in self.order_ids
            if identifier in paper.exchange.orders
            and paper.exchange.orders[identifier].status in {"OPEN", "PARTIAL"}
        ]
        if restarted:
            for identifier in restarted:
                paper.exchange.cancel(identifier)
            paper.persist("auto_restart_paused", {"cancelled_entries": restarted})

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "status": self.status,
            "symbols": self.symbols,
            "model": self.strategy.settings.system_one.checkpoint,
            "model_healthy": self.strategy.healthy,
            "latency_ms": self.strategy.last_latency_ms,
            "product": "MIS",
            "mover_count": self.paper.settings.auto_paper.mover_count,
            "max_hold_minutes": self.paper.settings.auto_paper.max_hold_minutes,
            "events": [
                {
                    key: event[key]
                    for key in (
                        "symbol",
                        "at",
                        "bar_at",
                        "direction",
                        "reason",
                        "vetoes",
                        "order_id",
                        "action",
                    )
                    if key in event
                }
                for event in self.events
            ],
        }

    def movers(self) -> list[str]:
        paper = self.paper
        if not paper.membership_fresh() or paper.feed != "connected":
            return []
        if paper.settings.auto_paper.mover_count == 50:
            return sorted(paper.members)
        quotes = [paper.quotes.get(s) for s in paper.members]
        if any(
            q is None or not paper.fresh(q) or not q.regular or q.change_percent is None
            for q in quotes
        ):
            return []
        ranked = sorted(
            (q for q in quotes if q is not None),
            key=lambda q: (-abs(q.change_percent or 0), q.symbol),
        )
        return [q.symbol for q in ranked[: paper.settings.auto_paper.mover_count]]

    def priority(self, symbol: str) -> tuple[int, str]:
        paper = self.paper
        if any(p.symbol == symbol for p in paper.exchange.portfolio.positions.values()):
            return 0, symbol
        if any(
            p.order.symbol == symbol and p.status in {"OPEN", "PARTIAL"}
            for p in paper.exchange.orders.values()
        ):
            return 1, symbol
        return 2, symbol

    def close_position(self, symbol: str, reason: str) -> dict[str, object]:
        from paper_trader.live_paper import Ticket

        paper = self.paper
        position = paper.exchange.portfolio.positions.get((symbol, "MIS"))
        if position is None:
            return {"vetoes": ["POSITION_ALREADY_CLOSED"]}
        pending = [
            p
            for p in paper.exchange.orders.values()
            if p.order.symbol == symbol
            and p.order.product == "MIS"
            and p.status in {"OPEN", "PARTIAL"}
        ]
        if any(p.order.reduce_only for p in pending):
            return {"vetoes": ["EXIT_ALREADY_PENDING"]}
        previous = paper.saved().model_copy(deep=True)
        try:
            for item in pending:
                paper.exchange.cancel(item.order.id)
            result = paper.submit(
                Ticket(
                    symbol=symbol,
                    side="SELL" if position.quantity > 0 else "BUY",
                    product="MIS",
                    quantity=abs(position.quantity),
                    reduce_only=True,
                ),
                automated=True,
            )
        except Exception:
            paper.restore(previous)
            raise
        if result.get("id") and not result["vetoes"]:
            self.order_ids.add(str(result["id"]))
            paper.persist(
                "auto_exit_requested",
                {"symbol": symbol, "reason": reason, "order_id": result["id"]},
            )
        return result

    def time_exit(self, symbol: str) -> None:
        position = self.paper.exchange.portfolio.positions.get((symbol, "MIS"))
        if position is None:
            return
        minutes = self.holding_limits.get(position.entry_order_id)
        if minutes and self.paper.now() >= position.opened_at + timedelta(minutes=minutes):
            self.close_position(symbol, "MAX_HOLD_EXIT")

    async def start(self) -> None:
        async with self.control:
            await self._start()

    async def _start(self) -> None:
        if self.enabled:
            return
        if self.paper.feed != "connected":
            raise HTTPException(409, "Connect the market feed before starting AI paper trading")
        if not await self.strategy.health():
            raise HTTPException(
                409, "Local Laya server is unavailable; no automated entries enabled"
            )
        if self.enabled:
            return
        self.enabled = True
        self.status = "Waiting for fresh top-mover data"
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        async with self.control:
            await self._stop()

    async def _stop(self) -> None:
        if not self.enabled and self.task is None and not self.order_ids:
            return
        self.enabled = False
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        await self.cancel_entries()
        self.status = "Stopped; protective exits remain active while feed is connected"

    async def cancel_entries(self) -> None:
        async with self.paper.lock:
            previous = self.paper.saved().model_copy(deep=True)
            try:
                for identifier in self.order_ids:
                    pending = self.paper.exchange.orders.get(identifier)
                    if pending and not pending.order.reduce_only:
                        self.paper.exchange.cancel(identifier)
                self.paper.persist("auto_stopped", {})
            except Exception:
                self.paper.restore(previous)
                raise

    async def run(self) -> None:
        try:
            while self.enabled:
                await self.cycle()
                await asyncio.sleep(self.paper.settings.auto_paper.poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.enabled = False
            self.status = "Automation paused after a service error; review orders before restarting"
            await self.cancel_entries()

    async def cycle(self) -> None:
        paper = self.paper
        session = paper.calendar.status(paper.now())
        if session.phase != "open":
            self.status = "Waiting for an open trading session"
            return
        self.symbols = self.movers()
        remaining = set(self.symbols) if session.can_enter_mis else set()
        remaining.update(
            p.symbol for p in paper.exchange.portfolio.positions.values() if p.product == "MIS"
        )
        if not remaining:
            self.status = (
                "Waiting for fresh universe data"
                if session.can_enter_mis
                else "New intraday entries closed; no active MIS positions"
            )
            return
        self.status = f"Scanning {len(self.symbols)} stocks; active positions first"
        while remaining and self.enabled:
            held = {
                p.symbol: p.entry_order_id
                for p in paper.exchange.portfolio.positions.values()
                if p.product == "MIS"
            }
            urgent = {
                symbol
                for symbol in held
                if self.priority_entry_ids.get(symbol) != held[symbol]
                or symbol not in self.priority_checked
                or (paper.now() - self.priority_checked[symbol]).total_seconds()
                >= paper.settings.auto_paper.poll_seconds
            }
            symbol = min(remaining | urgent, key=self.priority)
            remaining.discard(symbol)
            self.priority_checked[symbol] = paper.now()
            self.priority_entry_ids[symbol] = held.get(symbol)
            await self.review(symbol)

    async def review(self, symbol: str) -> None:
        paper = self.paper
        if not self.enabled:
            return
        position = paper.exchange.portfolio.positions.get((symbol, "MIS"))
        quote = paper.quotes.get(symbol)
        if not quote or not paper.fresh(quote) or not quote.regular:
            return
        if position is None and (
            not paper.calendar.status(paper.now()).can_enter_mis
            or any(p.symbol == symbol for p in paper.exchange.portfolio.positions.values())
            or any(
                p.order.symbol == symbol and p.status in {"OPEN", "PARTIAL"}
                for p in paper.exchange.orders.values()
            )
        ):
            return
        review_entry_id = position.entry_order_id if position else None
        try:
            await paper.prepare(symbol)
        except HTTPException:
            self.status = f"Waiting for {symbol} closed-candle data"
            return
        bars = tuple(c for c in paper.bars.get(symbol, ()) if c.closed_at <= paper.now())
        bars = bars[-paper.settings.simulation.history_bars :]
        if not bars or self.last_bars.get(symbol) == bars[-1].closed_at:
            return
        recent = bars[-paper.settings.data.warmup_bars :]
        if (
            len(recent) < paper.settings.data.warmup_bars
            or quality(recent, paper.calendar, paper.now()).status != "healthy"
            or (paper.now() - bars[-1].closed_at).total_seconds()
            > paper.settings.auto_paper.max_candle_age_seconds
        ):
            self.status = f"Waiting for {symbol} complete, fresh closed candles"
            return
        async with paper.lock:
            portfolio = copy.deepcopy(paper.exchange.portfolio)
        snapshot = await asyncio.to_thread(
            self.features.calculate,
            bars,
            bars[-1].closed_at,
            cash=portfolio.available_cash,
            position=("LONG" if position.quantity > 0 else "SHORT") if position else "FLAT",
        )
        event: dict[str, Any] = {
            "symbol": symbol,
            "at": paper.now().isoformat(),
            "bar_at": snapshot.at.isoformat(),
            "direction": "HOLD",
            "reason": "INFERENCE_PENDING",
            "vetoes": [],
            "model": self.strategy.settings.system_one.checkpoint,
            "candle_hash": hashlib.sha256(
                "\n".join(c.model_dump_json() for c in bars).encode()
            ).hexdigest(),
            "state": snapshot.state,
            "features": snapshot.values,
            "action": "POSITION_REVIEW" if position else "ENTRY_REVIEW",
        }
        async with paper.lock:
            paper.persist("auto_decision", event)
            self.last_bars[symbol] = snapshot.at
        signal = await self.strategy.decide(snapshot, portfolio)
        if not self.enabled:
            return
        event.update(direction=signal.direction, reason=signal.reason, raw=signal.raw)
        async with paper.lock:
            if signal.direction != "HOLD":
                await self.submit(
                    symbol,
                    snapshot.at,
                    snapshot.values.get("atr"),
                    signal.direction == "LONG",
                    event,
                    review_entry_id=review_entry_id,
                )
            event["at"] = paper.now().isoformat()
            paper.persist("auto_decision", event)
            self.events.append(event)
        if not self.strategy.healthy:
            self.status = "Laya unavailable or invalid response; no new AI entries"

    async def submit(
        self,
        symbol: str,
        bar_at: datetime,
        atr_value: object,
        long: bool,
        event: dict[str, Any],
        review_entry_id: str | None = None,
    ) -> None:
        from paper_trader.live_paper import Ticket

        paper = self.paper
        if not self.enabled or (paper.now() - bar_at).total_seconds() > (
            paper.settings.auto_paper.max_candle_age_seconds
        ):
            event["vetoes"] = ["STALE_AI_DECISION"]
            return
        position = paper.exchange.portfolio.positions.get((symbol, "MIS"))
        if review_entry_id is not None:
            if not position or position.entry_order_id != review_entry_id:
                event["vetoes"] = ["POSITION_CHANGED_DURING_INFERENCE"]
            elif long == (position.quantity > 0):
                event["action"] = "KEEP_POSITION"
            else:
                try:
                    result = self.close_position(symbol, "AI_OPPOSITE_EXIT")
                    event["vetoes"] = result["vetoes"]
                    if result.get("id"):
                        event["order_id"] = result["id"]
                    event["action"] = "AI_OPPOSITE_EXIT"
                except HTTPException as exc:
                    event["vetoes"] = [str(exc.detail)]
            return
        if position:
            event["vetoes"] = ["POSITION_EXISTS"]
            return
        quote = paper.quotes.get(symbol)
        if not quote or not isinstance(atr_value, float) or atr_value <= 0:
            event["vetoes"] = ["ATR_OR_QUOTE_UNAVAILABLE"]
            return
        atr = Decimal(str(atr_value))
        quantity = paper.exchange.risk.size(paper.exchange.portfolio, quote.price, atr)
        distance = atr * paper.settings.risk.atr_stop_multiple
        stop = quote.price - distance if long else quote.price + distance
        target = quote.price + distance * paper.settings.risk.reward_risk_ratio * (
            1 if long else -1
        )
        if quantity <= 0 or stop <= 0 or target <= 0:
            event["vetoes"] = ["SIZE_OR_PRICE_INVALID"]
            return
        ticket = Ticket(
            symbol=symbol,
            side="BUY" if long else "SELL",
            product="MIS",
            quantity=quantity,
            stop_price=stop,
            target_price=target,
        )
        try:
            result = paper.submit(ticket, automated=True)
        except HTTPException as exc:
            event["vetoes"] = [str(exc.detail)]
            return
        event["vetoes"] = result["vetoes"]
        event["order_id"] = result["id"]
        if not result["vetoes"]:
            identifier = str(result["id"])
            self.order_ids.add(identifier)
            self.holding_limits[identifier] = paper.settings.auto_paper.max_hold_minutes
