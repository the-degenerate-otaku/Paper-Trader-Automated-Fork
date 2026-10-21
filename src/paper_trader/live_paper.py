from __future__ import annotations

import asyncio
import importlib
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import Field, field_validator

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Section, Settings
from paper_trader.data import CandleStore, YFinanceProvider, quality
from paper_trader.market import Candle, aware
from paper_trader.storage import Database
from paper_trader.trading import (
    Fill,
    Order,
    PaperExchange,
    PendingOrder,
    Portfolio,
    Position,
    RiskContext,
)
from paper_trader.universe import UniverseService, utc_iso


class Ticket(Section):
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9&_.-]{0,39}$")
    side: str = Field(pattern=r"^(BUY|SELL)$")
    product: str = Field(default="CNC", pattern=r"^(CNC|MIS)$")
    order_type: str = Field(default="MARKET", pattern=r"^(MARKET|LIMIT|SL|SL-M|BRACKET)$")
    quantity: int = Field(gt=0, le=1000000000)
    stop_price: Decimal | None = Field(default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False)
    target_price: Decimal | None = Field(
        default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False
    )
    limit_price: Decimal | None = Field(default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False)
    trigger_price: Decimal | None = Field(
        default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False
    )
    trailing_distance: Decimal | None = Field(
        default=None, gt=0, le=Decimal("1e12"), allow_inf_nan=False
    )
    reduce_only: bool = False


class Quote(Section):
    symbol: str
    price: Decimal = Field(gt=0, le=Decimal("1e12"), allow_inf_nan=False)
    at: datetime
    day_volume: int = Field(ge=0)
    regular: bool
    change_percent: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("at")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        return aware(value)


class SavedPaper(Section):
    starting_capital: Decimal
    cash: Decimal
    realized_pnl: Decimal
    total_charges: Decimal
    peak_equity: Decimal
    daily_start: Decimal
    weekly_start: Decimal
    current_day: date | None
    current_week: date | None
    consecutive_losses: int
    last_loss_at: datetime | None
    kill_switch: bool
    positions: list[Position]
    marks: dict[str, Decimal]
    entry_times: dict[str, list[datetime]]
    fills: list[Fill]
    closed_trades: list[dict[str, Any]]
    orders: list[PendingOrder]
    dp_days: list[tuple[str, date]]


class LivePaper:
    def __init__(
        self, settings: Settings, database: Database, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.settings, self.database = settings, database
        self.calendar = TradingCalendar.load(settings)
        self.now = clock or (lambda: datetime.now(UTC))
        self.exchange = PaperExchange(
            settings, self.calendar, Portfolio(settings.account.starting_capital_inr)
        )
        self.members: dict[str, dict[str, Any]] = {}
        self.observed_at: datetime | None = None
        self.quotes: dict[str, Quote] = {}
        self.bars: dict[str, tuple[Candle, ...]] = {}
        self.errors: dict[str, str] = {}
        self.feed = "disconnected"
        self.task: asyncio.Task[None] | None = None
        self.lock = asyncio.Lock()
        self.history_lock = asyncio.Lock()
        self.membership()
        with database.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM live_paper_state WHERE id='main'"
            ).fetchone()
        if row:
            self.restore(SavedPaper.model_validate_json(row[0]))

    def membership(self) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, observed_at FROM universe_snapshots WHERE index_symbol='NIFTY50' "
                "AND observed_at<=? ORDER BY observed_at DESC LIMIT 1",
                (utc_iso(self.now()),),
            ).fetchone()
            self.members = (
                {}
                if row is None
                else {
                    r["symbol"]: dict(r)
                    for r in connection.execute(
                        "SELECT symbol, company_name, sector FROM constituents_history "
                        "WHERE snapshot_id=? ORDER BY symbol",
                        (row["id"],),
                    ).fetchall()
                }
            )
            self.observed_at = datetime.fromisoformat(row["observed_at"]) if row else None

    def membership_fresh(self) -> bool:
        return bool(
            self.observed_at
            and len(self.members) == 50
            and self.now() - self.observed_at < timedelta(days=self.settings.universe.refresh_days)
        )

    def saved(self) -> SavedPaper:
        p = self.exchange.portfolio
        fields = {
            key: getattr(p, key)
            for key in SavedPaper.model_fields
            if key not in {"orders", "dp_days", "positions"}
        }
        return SavedPaper(
            **fields,
            positions=list(p.positions.values()),
            orders=list(self.exchange.orders.values()),
            dp_days=list(self.exchange.dp_days),
        )

    def restore(self, saved: SavedPaper) -> None:
        p = Portfolio(saved.starting_capital)
        for key in SavedPaper.model_fields:
            if key not in {"orders", "dp_days", "positions", "starting_capital"}:
                setattr(p, key, getattr(saved, key))
        p.positions = {
            (position.symbol, position.product): position for position in saved.positions
        }
        self.exchange = PaperExchange(self.settings, self.calendar, p)
        self.exchange.orders = {pending.order.id: pending for pending in saved.orders}
        self.exchange.dp_days = set(saved.dp_days)

    def persist(self, event: str, payload: dict[str, object]) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO live_paper_state VALUES ('main', ?, ?) ON CONFLICT(id) "
                "DO UPDATE SET updated_at=excluded.updated_at, "
                "payload_json=excluded.payload_json",
                (self.now().isoformat(), self.saved().model_dump_json()),
            )
            connection.execute(
                "INSERT INTO live_paper_events (created_at,event,payload_json) VALUES (?,?,?)",
                (
                    self.now().isoformat(),
                    event,
                    json.dumps(jsonable_encoder(payload), allow_nan=False),
                ),
            )

    def fresh(self, quote: Quote) -> bool:
        age = (self.now() - quote.at).total_seconds()
        return (
            -self.settings.live_paper.future_tolerance_seconds
            <= age
            <= self.settings.live_paper.quote_max_age_seconds
        )

    def context(self, symbol: str) -> RiskContext:
        bars = self.bars.get(symbol, ())
        totals: dict[date, Decimal] = defaultdict(Decimal)
        today = self.now().astimezone(self.calendar.zone).date()
        for bar in bars:
            day = bar.opened_at.astimezone(self.calendar.zone).date()
            if day < today:
                totals[day] += bar.close * bar.volume
        quote = self.quotes.get(symbol)
        correlations = {}
        for position in self.exchange.portfolio.positions.values():
            aligned = {c.closed_at: float(c.close) for c in self.bars.get(position.symbol, ())}
            pairs = [(float(c.close), aligned[c.closed_at]) for c in bars if c.closed_at in aligned]
            if len(pairs) >= self.settings.features.volatility_period:
                a, b = np.array(pairs).T
                ar, br = np.diff(np.log(a)), np.diff(np.log(b))
                if np.std(ar) > 0 and np.std(br) > 0:
                    correlations[position.symbol] = float(np.corrcoef(ar, br)[0, 1])
        return RiskContext(
            sector=str(self.members.get(symbol, {}).get("sector", "UNKNOWN")),
            average_turnover=sum(totals.values(), Decimal(0)) / len(totals) if totals else None,
            bar_volume=bars[-1].volume if bars else 0,
            correlations=correlations,
            feed_healthy=bool(
                quote
                and self.fresh(quote)
                and quote.regular
                and self.feed == "connected"
                and bars
                and quality(bars, self.calendar, self.now()).status in {"healthy", "gaps"}
            ),
        )

    def submit(self, ticket: Ticket) -> dict[str, object]:
        quote = self.quotes.get(ticket.symbol)
        if not quote or not self.fresh(quote) or not quote.regular or self.feed != "connected":
            raise HTTPException(409, "A fresh regular-session streaming quote is required")
        if not ticket.reduce_only and (
            ticket.symbol not in self.members or not self.membership_fresh()
        ):
            raise HTTPException(409, "A current 50-stock Nifty membership snapshot is required")
        context = self.context(ticket.symbol)
        if ticket.reduce_only:
            context = replace(context, feed_healthy=True)
        order = Order.model_validate(
            {**ticket.model_dump(), "id": uuid4().hex, "signal_at": self.now()}
        )
        previous = self.saved().model_copy(deep=True)
        reasons = self.exchange.submit(order, quote.price, context)
        try:
            self.persist(
                "order_rejected" if reasons else "order_submitted",
                {"order": order.model_dump(mode="json"), "vetoes": reasons},
            )
        except Exception:
            self.restore(previous)
            raise
        return {"id": order.id, "vetoes": reasons}

    def tick(self, data: dict[str, Any]) -> bool:
        if data.get("currency") not in {None, "INR"}:
            return False
        provider_id = str(data.get("id", ""))
        if not provider_id.endswith(".NS"):
            return False
        symbol = provider_id[:-3]
        held = {p.symbol for p in self.exchange.portfolio.positions.values()}
        if symbol not in self.members and symbol not in held:
            return False
        try:
            quote = Quote(
                symbol=symbol,
                price=data["price"],
                at=datetime.fromtimestamp(int(data["time"]) / 1000, UTC),
                day_volume=data.get("day_volume", 0),
                regular=data.get("market_hours") == 1,
                change_percent=data.get("change_percent"),
            )
        except (ValueError, TypeError, KeyError, OverflowError):
            return False
        if (
            quote.at - self.now()
        ).total_seconds() > self.settings.live_paper.future_tolerance_seconds:
            return False
        prior = self.quotes.get(symbol)
        if prior and quote.at <= prior.at:
            return False
        if (
            prior
            and prior.at.astimezone(self.calendar.zone).date()
            == quote.at.astimezone(self.calendar.zone).date()
            and quote.day_volume < prior.day_volume
        ):
            return False
        self.quotes[symbol] = quote
        self.exchange.portfolio.marks[symbol] = quote.price
        if (
            not prior
            or not self.fresh(prior)
            or not self.fresh(quote)
            or not quote.regular
            or self.calendar.status(self.now()).phase != "open"
            or self.feed != "connected"
        ):
            return True
        same_day = (
            prior.at.astimezone(self.calendar.zone).date()
            == quote.at.astimezone(self.calendar.zone).date()
        )
        volume = quote.day_volume - prior.day_volume if same_day else 0
        if volume <= 0:
            return True
        if not any(
            p.symbol == symbol for p in self.exchange.portfolio.positions.values()
        ) and not any(
            p.order.symbol == symbol and p.status in {"OPEN", "PARTIAL"}
            for p in self.exchange.orders.values()
        ):
            return True
        previous = self.saved().model_copy(deep=True)
        context = self.context(symbol)
        for pending in self.exchange.orders.values():
            if pending.order.symbol == symbol and pending.status in {"OPEN", "PARTIAL"}:
                pending.context = context
                if pending.order.reduce_only:
                    pending.context = replace(pending.context, feed_healthy=True)
        candle = Candle(
            symbol=symbol,
            timeframe="1m",
            opened_at=quote.at - timedelta(microseconds=1),
            closed_at=quote.at,
            open=quote.price,
            high=quote.price,
            low=quote.price,
            close=quote.price,
            volume=volume,
            source="yahoo_observed_quote",
        )
        self.exchange.process(candle)
        try:
            self.persist(
                "quote_execution",
                {
                    "symbol": symbol,
                    "price": str(quote.price),
                    "at": quote.at.isoformat(),
                    "volume_delta": volume,
                },
            )
        except Exception:
            self.restore(previous)
            raise
        return True

    async def prepare(self, symbol: str) -> None:
        if symbol not in self.members and not any(
            p.symbol == symbol for p in self.exchange.portfolio.positions.values()
        ):
            raise HTTPException(422, "Only Nifty 50 stocks can be prepared")
        if (
            symbol not in self.bars
            and len(self.bars) >= self.settings.live_paper.max_prepared_symbols
        ):
            raise HTTPException(409, "Prepared stock limit reached")
        if self.history_lock.locked():
            raise HTTPException(409, "Stock data is already loading")
        async with self.history_lock:
            now = self.now()

            def load() -> tuple[Candle, ...]:
                bounded = self.settings.model_copy(deep=True)
                bounded.data.max_fetch_bars = min(self.settings.data.max_fetch_bars, 6000)
                batch = YFinanceProvider(bounded, self.calendar).history(
                    symbol, "1m", now - timedelta(days=self.settings.live_paper.history_days), now
                )
                if not batch.candles:
                    raise ValueError("No closed liquidity history")
                CandleStore(self.database, self.calendar).save(batch)
                return batch.candles

            try:
                bars = await asyncio.to_thread(load)
                async with self.lock:
                    self.bars[symbol] = tuple(sorted(bars, key=lambda c: c.closed_at))
                    self.errors.pop(symbol, None)
            except Exception as exc:
                self.errors[symbol] = "Liquidity history unavailable"
                raise HTTPException(502, "Stock data unavailable; entries remain blocked") from exc

    async def start(self) -> None:
        if self.task and not self.task.done():
            return
        if self.history_lock.locked():
            raise HTTPException(409, "Stock data is already loading")
        async with self.history_lock:

            def refresh() -> None:
                with httpx.Client(trust_env=False, follow_redirects=False) as client:
                    UniverseService(self.settings, self.database, client).refresh("NIFTY50")

            try:
                await asyncio.to_thread(refresh)
            except Exception as exc:
                raise HTTPException(502, "Official Nifty membership download unavailable") from exc
            self.membership()
        if not self.membership_fresh():
            raise HTTPException(409, "Current 50-stock Nifty membership unavailable")
        self.feed = "connecting"
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self.feed = "disconnected"
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    async def run(self) -> None:
        async def receive(data: dict[str, Any]) -> None:
            async with self.lock:
                self.tick(data)

        async def refresh_history() -> None:
            while True:
                await asyncio.sleep(self.settings.live_paper.history_poll_seconds)
                for symbol in list(self.bars):
                    if self.calendar.status(self.now()).phase == "open":
                        try:
                            await self.prepare(symbol)
                        except HTTPException:
                            continue

        history_task = asyncio.create_task(refresh_history())
        try:
            while True:
                try:
                    module = importlib.import_module("yfinance")
                    async with module.AsyncWebSocket(verbose=False) as stream:
                        self.quotes.clear()
                        held = {p.symbol for p in self.exchange.portfolio.positions.values()}
                        await stream.subscribe(
                            [s + ".NS" for s in sorted(set(self.members) | held)]
                        )
                        self.feed = "connected"
                        await asyncio.wait_for(
                            stream.listen(receive),
                            timeout=self.settings.live_paper.stream_cycle_seconds,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.feed = "reconnecting"
                else:
                    self.feed = "reconnecting"
                await asyncio.sleep(self.settings.live_paper.reconnect_seconds)
        finally:
            self.feed = "disconnected"
            history_task.cancel()
            await asyncio.gather(history_task, return_exceptions=True)

    def snapshot(self) -> dict[str, object]:
        now = self.now()
        p = self.exchange.portfolio
        rejected = []
        with self.database.connect() as connection:
            for row in connection.execute(
                "SELECT payload_json FROM live_paper_events WHERE event='order_rejected' "
                "ORDER BY id DESC LIMIT 100"
            ).fetchall():
                payload = json.loads(row[0])
                rejected.append(
                    {
                        "order": payload["order"],
                        "status": "REJECTED",
                        "remaining": 0,
                        "reasons": payload["vetoes"],
                    }
                )
        positions = []
        for position in p.positions.values():
            quote = self.quotes.get(position.symbol)
            mark = p.marks.get(position.symbol, position.average_price)
            positions.append(
                {
                    **asdict(position),
                    "mark": mark,
                    "unrealized_pnl": (mark - position.average_price) * position.quantity,
                    "quote_fresh": bool(quote and self.fresh(quote)),
                }
            )
        return cast(
            dict[str, object],
            jsonable_encoder(
                {
                    "source": "Yahoo Finance streaming · best effort",
                    "feed": self.feed,
                    "session": asdict(self.calendar.status(now)),
                    "now": now.isoformat(),
                    "membership_observed_at": self.observed_at,
                    "membership_fresh": self.membership_fresh(),
                    "stocks": [
                        {
                            **member,
                            "quote": self.quotes.get(symbol),
                            "prepared": symbol in self.bars,
                            "error": self.errors.get(symbol),
                            "fresh": bool(
                                symbol in self.quotes and self.fresh(self.quotes[symbol])
                            ),
                        }
                        for symbol, member in self.members.items()
                    ],
                    "portfolio": {
                        "starting_capital": p.starting_capital,
                        "cash": p.cash,
                        "available_cash": p.available_cash,
                        "equity": p.equity,
                        "unrealized_pnl": sum(
                            (
                                (p.marks.get(v.symbol, v.average_price) - v.average_price)
                                * v.quantity
                                for v in p.positions.values()
                            ),
                            Decimal(0),
                        ),
                        "realized_pnl": p.realized_pnl,
                        "charges": p.total_charges,
                        "exposure": p.exposure,
                    },
                    "positions": positions,
                    "orders": rejected
                    + [
                        {"order": item.order, "status": item.status, "remaining": item.remaining}
                        for item in list(self.exchange.orders.values())[-500:]
                    ],
                    "closed_trades": p.closed_trades[-500:],
                    "fills": [asdict(fill) for fill in p.fills[-500:]],
                    "vetoes": self.exchange.veto_log[-20:],
                },
                custom_encoder={Decimal: str},
            ),
        )


def install_live_paper(app: FastAPI, paper: LivePaper) -> None:
    @app.get("/api/paper")
    async def snapshot() -> dict[str, object]:
        return paper.snapshot()

    @app.post("/api/paper/connect")
    async def connect() -> dict[str, object]:
        await paper.start()
        return paper.snapshot()

    @app.post("/api/paper/disconnect")
    async def disconnect() -> dict[str, object]:
        await paper.stop()
        return paper.snapshot()

    @app.post("/api/paper/prepare/{symbol}")
    async def prepare(symbol: str) -> dict[str, object]:
        await paper.prepare(symbol)
        return paper.snapshot()

    @app.post("/api/paper/orders")
    async def submit(ticket: Ticket) -> dict[str, object]:
        async with paper.lock:
            return paper.submit(ticket)

    @app.delete("/api/paper/orders/{order_id}")
    async def cancel(order_id: str) -> dict[str, object]:
        async with paper.lock:
            item = paper.exchange.orders.get(order_id)
            if not item or item.status not in {"OPEN", "PARTIAL"}:
                raise HTTPException(409, "No cancellable order found")
            previous = paper.saved().model_copy(deep=True)
            paper.exchange.cancel(order_id)
            try:
                paper.persist("order_cancelled", {"id": order_id})
            except Exception:
                paper.restore(previous)
                raise
        return paper.snapshot()

    @app.websocket("/api/paper/ws")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(paper.snapshot())
                await asyncio.sleep(paper.settings.server.websocket_interval_seconds)
        except (WebSocketDisconnect, RuntimeError):
            return
