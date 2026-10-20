from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Section, Settings, load_settings
from paper_trader.data import CandleStore
from paper_trader.demo import synthetic
from paper_trader.engine import EmaStrategy, HoldStrategy, ReplayEngine, Strategy
from paper_trader.inference import SystemOneStrategy
from paper_trader.storage import Database
from paper_trader.trading import Order


class LocalBoundary:
    def __init__(
        self,
        app: ASGIApp,
        port: int = 2080,
        max_request_bytes: int = 65536,
        development_origins: list[str] | None = None,
    ) -> None:
        self.app, self.port, self.max_request_bytes = app, port, max_request_bytes
        self.development_origins = development_origins or []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode()
        allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        allowed_origins = {f"http://{host}" for host in allowed_hosts}
        allowed_origins.update(self.development_origins)
        origin = headers.get(b"origin", b"").decode()
        invalid = host not in allowed_hosts or (bool(origin) and origin not in allowed_origins)
        if scope["type"] == "websocket":
            if invalid or not origin:
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        mutation = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        if invalid or (mutation and headers.get(b"x-paper-request") != b"1"):
            await JSONResponse({"detail": "Local request boundary rejected"}, 403)(
                scope, receive, send
            )
            return
        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            total += len(message.get("body", b""))
            if total > self.max_request_bytes:
                await JSONResponse({"detail": "Request too large"}, 413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        index = 0

        async def replay() -> Message:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay, send)


class RunRequest(Section):
    strategy: Literal["hold", "ema", "systemone"] = "hold"
    source: Literal["synthetic", "stored"] = "synthetic"
    start: datetime = datetime.fromisoformat("2026-09-01T09:15:00+05:30")
    sessions: int = Field(default=3, ge=1, le=30)
    symbol: str = Field(default="DEMO", pattern=r"^[A-Z0-9&_.-]+$", max_length=40)
    version: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    timeframe: Literal["1m", "5m", "15m", "1h", "1d"] = "5m"
    shadow: bool = False


class Terminal:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calendar = TradingCalendar.load(settings)
        self.database = Database(settings.storage.database_path, settings.storage.busy_timeout_ms)
        self.database.migrate()
        self.database.seed(settings, self.calendar)
        self.engine: ReplayEngine | None = None
        self.task: asyncio.Task[None] | None = None
        self.lock = asyncio.Lock()
        self.source = "none"

    def require_engine(self) -> ReplayEngine:
        if self.engine is None:
            raise HTTPException(409, "Create a replay run first")
        return self.engine

    def create(self, request: RunRequest) -> None:
        if self.task and not self.task.done():
            raise HTTPException(409, "Pause playback before creating a run")
        if self.engine and self.engine.exchange.portfolio.positions:
            raise HTTPException(409, "Open positions remain; finish this run before replacing it")
        store = CandleStore(self.database, self.calendar)
        if request.source == "synthetic":
            batch = synthetic(self.settings, request.start, request.sessions)
            with self.database.connect() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO instruments VALUES "
                    "('DEMO', 'Synthetic demo', 'EQUITY', 'SYNTHETIC', NULL, "
                    "'EQ', 1, ?, NULL, NULL, 'DEMO')",
                    (str(self.settings.execution.tick_size),),
                )
            version = store.save(batch)
            candles = batch.candles
            symbol = "DEMO"
        else:
            if not request.version:
                raise HTTPException(422, "Stored runs require an immutable data version")
            version, symbol = request.version, request.symbol
            candles = store.read(version, symbol, request.timeframe, datetime.now(UTC))
        if not candles:
            raise HTTPException(422, "No closed candles in dataset")
        strategy: Strategy = (
            SystemOneStrategy(self.settings)
            if request.strategy == "systemone"
            else EmaStrategy(self.settings)
            if request.strategy == "ema"
            else HoldStrategy()
        )
        self.engine = ReplayEngine(
            self.settings,
            self.calendar,
            self.database,
            candles,
            {symbol: version},
            strategy,
            shadow=request.shadow,
        )
        self.source = request.source

    async def step(self) -> None:
        async with self.lock:
            engine = self.require_engine()
            if await engine.step() is None:
                engine.finish()

    async def play(self) -> None:
        engine = self.require_engine()
        engine.playing = True
        try:
            while engine.playing and engine.cursor < len(engine.events):
                await self.step()
                await asyncio.sleep(self.settings.server.replay_interval_seconds)
            if engine.cursor == len(engine.events):
                engine.finish()
        finally:
            engine.playing = False

    def positions(self) -> list[dict[str, object]]:
        if not self.engine:
            return []
        portfolio = self.engine.exchange.portfolio
        return [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_price": float(p.average_price),
                "current_price": float(portfolio.marks.get(p.symbol, p.average_price)),
                "market_value": float(
                    abs(p.quantity) * portfolio.marks.get(p.symbol, p.average_price)
                ),
                "unrealized_pnl": float(
                    (portfolio.marks.get(p.symbol, p.average_price) - p.average_price) * p.quantity
                ),
                "asset_type": p.product,
                "option_type": None,
                "strike": None,
                "expiration_date": None,
                "underlying_symbol": None,
            }
            for p in portfolio.positions.values()
        ]

    def snapshot(self) -> dict[str, object]:
        engine = self.engine
        if not engine:
            return {
                "mode": "paper",
                "source": self.source,
                "run": None,
                "positions": [],
                "curve": [],
                "candles": [],
                "decisions": [],
                "orders": [],
                "features": {},
                "trades": [],
                "metrics": {},
            }
        from paper_trader.engine import metrics

        return {
            "mode": "paper",
            "source": self.source,
            "run": {
                "id": engine.run_id,
                "account_id": engine.account_id,
                "cursor": engine.cursor,
                "total": len(engine.events),
                "clock": engine.clock.isoformat() if engine.clock else None,
                "playing": engine.playing,
                "shadow": engine.shadow,
            },
            "positions": self.positions(),
            "curve": engine.curve[-1000:],
            "candles": [
                c.model_dump(mode="json")
                for bars in engine.history.values()
                for c in tuple(bars)[-300:]
            ],
            "decisions": [
                {**asdict(e), "at": e.at.isoformat()}
                for e in tuple(engine.log)[-100:]
                if e.kind == "DecisionEvent"
            ],
            "orders": [
                {"order": pending.order.model_dump(mode="json"), "status": pending.status}
                for pending in engine.exchange.orders.values()
            ],
            "features": {
                symbol: {"state": state.state, "regime": state.regime, "values": state.values}
                for symbol, state in engine.latest_features.items()
            },
            "indicators": [
                {"at": e.at.isoformat(), "symbol": e.symbol, "values": e.payload.get("values", {})}
                for e in engine.log
                if e.kind == "FeatureEvent"
            ],
            "fills": [
                {
                    "at": fill.at.isoformat(),
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "price": str(fill.price),
                    "quantity": fill.quantity,
                    "reason": fill.reason,
                }
                for fill in engine.exchange.portfolio.fills[-100:]
            ],
            "trades": engine.exchange.portfolio.closed_trades[-100:],
            "metrics": metrics(engine.curve, engine.exchange.portfolio, self.settings),
            "equity": str(engine.exchange.portfolio.equity),
            "cash": str(engine.exchange.portfolio.cash),
            "exposure": str(engine.exchange.portfolio.exposure),
            "charges": str(engine.exchange.portfolio.total_charges),
        }


def create_app(settings: Settings | None = None) -> FastAPI:
    terminal = Terminal(settings or load_settings(Path("config.yaml"), Path(".env")))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if terminal.task:
            terminal.task.cancel()
            await asyncio.gather(terminal.task, return_exceptions=True)

    app = FastAPI(title="NSE Paper Terminal", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.terminal = terminal
    app.add_middleware(
        LocalBoundary,
        port=terminal.settings.server.port,
        max_request_bytes=terminal.settings.server.max_request_bytes,
        development_origins=terminal.settings.server.development_origins,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Invalid request", "fields": [list(e["loc"]) for e in exc.errors()]}, 422
        )

    @app.exception_handler(ValueError)
    async def bad_value(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": "Operation rejected: invalid data or state"}, 422)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        strategy = (
            terminal.engine.strategy if terminal.engine else SystemOneStrategy(terminal.settings)
        )
        return {
            "mode": "paper",
            "database_bytes": terminal.database.path.stat().st_size,
            "inference_ready": await strategy.health()
            if isinstance(strategy, SystemOneStrategy)
            else False,
            "calendar": asdict(terminal.calendar.status(datetime.now(UTC))),
            "source": terminal.source,
        }

    @app.get("/api/terminal")
    async def snapshot() -> dict[str, object]:
        return terminal.snapshot()

    @app.get("/api/settings")
    async def settings_view() -> dict[str, object]:
        result = terminal.settings.model_dump(mode="json", exclude={"storage"})
        result["session"].pop("calendar_path", None)
        return result

    @app.get("/api/watchlist/{index_symbol}")
    async def watchlist(index_symbol: Literal["NIFTY50", "NIFTYBANK"]) -> dict[str, object]:
        at = (
            terminal.engine.clock
            if terminal.engine and terminal.engine.clock
            else datetime.now(UTC)
        )
        with terminal.database.connect() as connection:
            row = connection.execute(
                "SELECT id, observed_at FROM universe_snapshots "
                "WHERE index_symbol=? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1",
                (index_symbol, at.isoformat()),
            ).fetchone()
            members = (
                []
                if row is None
                else [
                    dict(r)
                    for r in connection.execute(
                        "SELECT symbol, company_name, sector FROM constituents_history "
                        "WHERE snapshot_id=? ORDER BY symbol",
                        (row["id"],),
                    ).fetchall()
                ]
            )
        return {
            "as_of": at.isoformat(),
            "observed_at": row["observed_at"] if row else None,
            "members": members,
            "message": "No observation-time universe snapshot available"
            if not row
            else "Observed membership; prices require an imported dataset",
        }

    @app.post("/api/run")
    async def create_run(request: RunRequest) -> dict[str, object]:
        async with terminal.lock:
            terminal.create(request)
        return terminal.snapshot()

    @app.post("/api/step")
    async def step() -> dict[str, object]:
        if terminal.task and not terminal.task.done():
            raise HTTPException(409, "Pause playback before manual stepping")
        await terminal.step()
        return terminal.snapshot()

    @app.post("/api/play")
    async def play() -> dict[str, object]:
        terminal.require_engine()
        if terminal.task and not terminal.task.done():
            raise HTTPException(409, "Playback already running")
        terminal.task = asyncio.create_task(terminal.play())
        return {"status": "playing"}

    @app.post("/api/pause")
    async def pause() -> dict[str, object]:
        terminal.require_engine().pause()
        if terminal.task:
            await terminal.task
        return terminal.snapshot()

    @app.post("/api/orders")
    async def order(request: Order) -> dict[str, object]:
        async with terminal.lock:
            engine = terminal.require_engine()
            if engine.shadow:
                raise HTTPException(409, "Shadow run cannot place orders")
            bars = engine.history.get(request.symbol)
            if not bars or not engine.clock:
                raise HTTPException(409, "Step until this instrument has a closed candle")
            if request.signal_at != engine.clock:
                raise HTTPException(422, "Order timestamp must equal replay clock")
            with terminal.database.connect() as connection:
                if connection.execute("SELECT 1 FROM orders WHERE id=?", (request.id,)).fetchone():
                    raise HTTPException(409, "Order identifier already used")
            vetoes = engine.exchange.submit(
                request, bars[-1].close, engine.risk_context(request.symbol)
            )
            with terminal.database.connect() as connection:
                connection.execute(
                    "INSERT INTO orders VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        request.id,
                        engine.account_id,
                        request.symbol,
                        request.side,
                        request.product,
                        request.order_type,
                        request.quantity,
                        "REJECTED" if vetoes else "OPEN",
                        request.model_dump_json(),
                        request.signal_at.isoformat(),
                    ),
                )
            return {"order_id": request.id, "vetoes": vetoes, "accepted": not vetoes}

    @app.delete("/api/orders/{order_id}")
    async def cancel(order_id: str) -> dict[str, str]:
        async with terminal.lock:
            pending = terminal.require_engine().exchange.orders.get(order_id)
            if not pending or pending.status not in {"OPEN", "PARTIAL"}:
                raise HTTPException(409, "No cancellable order")
            pending.status = "CANCELLED"
            with terminal.database.connect() as connection:
                connection.execute("UPDATE orders SET status='CANCELLED' WHERE id=?", (order_id,))
        return {"status": "CANCELLED"}

    @app.get("/api/trades/{entry_order_id}")
    async def inspect_trade(entry_order_id: str) -> dict[str, object]:
        engine = terminal.require_engine()
        with terminal.database.connect() as connection:
            row = connection.execute(
                "SELECT o.payload_json AS order_json, d.state_text, d.features_json, "
                "d.policy_outcome, d.veto_reasons_json, d.checkpoint_id, j.body AS rationale, "
                "m.request_json, m.response_json, m.latency_ms, m.error "
                "FROM orders o LEFT JOIN decisions d ON o.decision_id=d.id "
                "LEFT JOIN journal j ON j.decision_id=d.id "
                "LEFT JOIN model_outputs m ON m.decision_id=d.id "
                "WHERE o.id=? AND o.account_id=?",
                (entry_order_id, engine.account_id),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "No entry journal for this run")
        return dict(row)

    @app.get("/api/v1/trading/accounts")
    async def accounts() -> dict[str, object]:
        engine = terminal.engine
        capital = float(terminal.settings.account.starting_capital_inr)
        return {
            "success": True,
            "accounts": [
                {
                    "id": engine.account_id if engine else "personal",
                    "owner": "Local paper account",
                    "created_at": "",
                    "starting_balance": capital,
                    "current_balance": float(engine.exchange.portfolio.cash) if engine else capital,
                    "balance_change": 0,
                    "balance_change_percent": 0,
                }
            ],
        }

    @app.get("/api/v1/trading/accounts/{account_id}/balance")
    async def balance(account_id: str) -> dict[str, object]:
        expected = terminal.engine.account_id if terminal.engine else "personal"
        if account_id != expected:
            raise HTTPException(404, "Unknown account")
        return {
            "success": True,
            "account_id": account_id,
            "cash_balance": float(terminal.engine.exchange.portfolio.cash)
            if terminal.engine
            else float(terminal.settings.account.starting_capital_inr),
        }

    @app.get("/api/v1/trading/positions")
    async def positions() -> dict[str, object]:
        return {"positions": terminal.positions()}

    @app.get("/api/v1/trading/portfolio/summary")
    async def portfolio_summary() -> dict[str, object]:
        capital = float(terminal.settings.account.starting_capital_inr)
        equity = float(terminal.engine.exchange.portfolio.equity) if terminal.engine else capital
        cash = float(terminal.engine.exchange.portfolio.cash) if terminal.engine else capital
        pnl = equity - capital
        return {
            "success": True,
            "summary": {
                "total_value": equity,
                "cash_balance": cash,
                "invested_value": equity - cash,
                "daily_pnl": equity - float(terminal.engine.exchange.portfolio.daily_start)
                if terminal.engine and terminal.engine.clock
                else None,
                "daily_pnl_percent": (
                    equity / float(terminal.engine.exchange.portfolio.daily_start) - 1
                )
                * 100
                if terminal.engine
                and terminal.engine.clock
                and terminal.engine.exchange.portfolio.daily_start > 0
                else None,
                "total_pnl": pnl,
                "total_pnl_percent": pnl / capital * 100,
            },
        }

    @app.websocket("/api/ws")
    async def events(socket: WebSocket) -> None:
        await socket.accept()
        try:
            while True:
                await socket.send_json(terminal.snapshot())
                await asyncio.sleep(terminal.settings.server.websocket_interval_seconds)
        except (WebSocketDisconnect, RuntimeError):
            return

    dist = Path("frontend/dist").resolve()
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
