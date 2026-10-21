import { useEffect, useState } from "react";
import {
    ChartNoAxesCombined,
    ArrowUpRight,
    Play,
    Square,
    Radio,
    Search,
} from "lucide-react";

type Quote = { price: string; at: string; change_percent: number | null };
type Stock = {
    symbol: string;
    company_name: string;
    sector: string;
    quote: Quote | null;
    fresh: boolean;
    prepared: boolean;
    error: string | null;
};
type Position = {
    symbol: string;
    product: string;
    quantity: number;
    average_price: string;
    stop_price: string;
    target_price: string | null;
    mark: string;
    unrealized_pnl: string;
    quote_fresh: boolean;
};
type Order = {
    order: {
        id: string;
        symbol: string;
        product: string;
        side: string;
        quantity: number;
        order_type: string;
        signal_at: string;
        limit_price: string | null;
        reduce_only: boolean;
    };
    status: string;
    remaining: number;
    reasons?: string[];
};
type State = {
    automation: {
        enabled: boolean;
        status: string;
        symbols: string[];
        model: string;
        model_healthy: boolean;
        latency_ms: number | null;
        mover_count: number;
        max_hold_minutes: number;
        events: {
            symbol: string;
            at: string;
            direction: string;
            reason: string;
            action?: string;
            vetoes: string[];
        }[];
    };
    feed: string;
    source: string;
    now: string;
    session: { phase: string; reason: string };
    membership_fresh: boolean;
    risk_per_trade_pct: string;
    history_poll_seconds: number;
    stocks: Stock[];
    portfolio: Record<string, string>;
    positions: Position[];
    orders: Order[];
    closed_trades: {
        symbol: string;
        quantity: number;
        pnl: string;
        charges: string;
        opened_at: string;
        closed_at: string;
        reason: string;
    }[];
    fills: {
        symbol: string;
        side: string;
        price: string;
        quantity: number;
        at: string;
        reason: string;
    }[];
};
const money = (value: unknown) =>
    value === undefined || value === null
        ? "—"
        : Number(value).toLocaleString("en-IN", {
              style: "currency",
              currency: "INR",
          });
const when = (value: string) =>
    new Date(value).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        hour12: false,
    });
const readable = (value: string) => value.replaceAll("_", " ").toLowerCase();

async function api(path = "", body?: unknown, method?: string) {
    const response = await fetch(`/api/paper${path}`, {
        method: method ?? (body === undefined ? "GET" : "POST"),
        headers: { "Content-Type": "application/json", "X-Paper-Request": "1" },
        body: body === undefined ? undefined : JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok)
        throw new Error(
            typeof result.detail === "string"
                ? result.detail
                : "Request rejected",
        );
    return result;
}

export default function PaperTerminal() {
    const [state, setState] = useState<State | null>(null);
    const [connected, setConnected] = useState(false);
    const [tab, setTab] = useState(0);
    const [search, setSearch] = useState("");
    const [symbol, setSymbol] = useState("RELIANCE");
    const [side, setSide] = useState("BUY");
    const [product, setProduct] = useState("CNC");
    const [kind, setKind] = useState("MARKET");
    const [quantity, setQuantity] = useState("1");
    const [stop, setStop] = useState("");
    const [target, setTarget] = useState("");
    const [limit, setLimit] = useState("");
    const [trigger, setTrigger] = useState("");
    const [trailing, setTrailing] = useState("");
    const [reduceOnly, setReduceOnly] = useState(false);
    const [busy, setBusy] = useState(false);
    const [showAllDecisions, setShowAllDecisions] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    const [dataStatus, setDataStatus] = useState("");
    const feed = state?.feed;
    const historyPoll = state?.history_poll_seconds ?? 60;
    useEffect(() => {
        if (tab !== 1 || feed !== "connected") return;
        let active = true;
        let timer: ReturnType<typeof setTimeout>;
        const refresh = async () => {
            setDataStatus("Updating stock data…");
            try {
                await api(`/prepare/${encodeURIComponent(symbol)}`, {});
                if (active) setDataStatus("Stock data refreshes automatically");
            } catch (e) {
                if (active)
                    setDataStatus(
                        `${e instanceof Error ? e.message : "Stock data unavailable"}. Retrying automatically.`,
                    );
            }
            if (active) timer = setTimeout(refresh, historyPoll * 1000);
        };
        timer = setTimeout(refresh, 300);
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [symbol, tab, feed, historyPoll]);
    useEffect(() => {
        let active = true;
        api()
            .then((data) => {
                if (active) setState(data);
            })
            .catch(() => {
                if (active) setError("Local paper service unavailable");
            });
        let socket: WebSocket | null = null;
        let retry: ReturnType<typeof setTimeout>;
        const open = () => {
            if (!active) return;
            socket = new WebSocket(
                `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/paper/ws`,
            );
            socket.onopen = () => setConnected(true);
            socket.onmessage = (event) => {
                if (active) setState(JSON.parse(event.data));
            };
            socket.onclose = () => {
                if (active) {
                    setConnected(false);
                    retry = setTimeout(open, 3000);
                }
            };
        };
        open();
        return () => {
            active = false;
            clearTimeout(retry);
            socket?.close();
        };
    }, []);
    async function act(path: string, body: unknown = {}, method?: string) {
        setBusy(true);
        setError("");
        setNotice("");
        try {
            const result = await api(path, body, method);
            if (result.portfolio) setState(result);
            if (result.vetoes?.length)
                setError(
                    `Order blocked: ${result.messages?.length ? result.messages.join(" ") : result.vetoes.join(", ")}`,
                );
            else if (path === "/orders")
                setNotice(
                    "Paper order accepted. It waits for the next eligible observed price and available simulated liquidity.",
                );
            else if (path.startsWith("/prepare/"))
                setNotice(
                    "Stock data loaded. Fresh streaming prices are still required for orders.",
                );
        } catch (e) {
            setError(e instanceof Error ? e.message : "Operation failed");
        } finally {
            setBusy(false);
        }
    }
    const stock = state?.stocks.find((s) => s.symbol === symbol);
    const quote = stock?.quote;
    const openOrders =
        state?.orders.filter((o) => ["OPEN", "PARTIAL"].includes(o.status)) ??
        [];
    const current = state?.positions.find(
        (p) => p.symbol === symbol && p.product === product,
    );
    const isExit =
        !!current &&
        (reduceOnly ||
            (current.quantity > 0 ? side === "SELL" : side === "BUY"));
    const riskBudget =
        (Number(state?.portfolio.equity ?? 0) *
            Number(state?.risk_per_trade_pct ?? 0)) /
        100;
    const estimatedRisk =
        quote && Number(stop) > 0 && Number(quantity) > 0
            ? Math.abs(Number(quote.price) - Number(stop)) * Number(quantity)
            : null;
    const ready =
        connected &&
        state?.feed === "connected" &&
        state.session.phase === "open" &&
        stock?.fresh &&
        (isExit || stock.prepared) &&
        (isExit || state.membership_fresh);
    function closePosition(position: Position) {
        setSymbol(position.symbol);
        setProduct(position.product);
        setSide(position.quantity > 0 ? "SELL" : "BUY");
        setQuantity(String(Math.abs(position.quantity)));
        setKind("MARKET");
        setReduceOnly(true);
        setTab(1);
        setError("");
        setNotice("Review the closing paper order, then submit.");
    }
    const tabs = [
        "Positions",
        "Trading terminal",
        "Orders",
        "Closed trades",
        "Executions",
    ];
    return (
        <div className="paper-app">
            <a className="skip-link" href="#workspace">
                Skip to workspace
            </a>
            <header className="topbar">
                <a className="brand" href="/">
                    <ChartNoAxesCombined aria-hidden="true" size={28} />
                    <span>
                        Paper Trader
                        <span className="brand-sub">Automated · NSE</span>
                    </span>
                </a>
                <div className="header-actions">
                    <span className="paper-label">Paper account</span>
                    <button
                        disabled={busy || state?.feed === "connecting"}
                        onClick={() =>
                            act(
                                state?.feed === "connected"
                                    ? "/disconnect"
                                    : "/connect",
                            )
                        }
                    >
                        <Radio size={16} aria-hidden="true" />
                        {state?.feed === "connected"
                            ? "Disconnect feed"
                            : "Connect free feed"}
                    </button>
                </div>
            </header>
            <div className="market-line">
                <span
                    className={connected ? "connection online" : "connection"}
                >
                    {connected ? "Service connected" : "Service disconnected"}
                </span>
                <span>Market {state?.session.phase ?? "loading"}</span>
                <span>Feed {state?.feed ?? "offline"}</span>
                <time>
                    {state?.now
                        ? when(state.now) + " IST"
                        : "Waiting for market data"}
                </time>
            </div>
            <main>
                <section
                    className="overview"
                    aria-labelledby="portfolio-heading"
                >
                    <div className="account">
                        <div className="section-heading">
                            <h1 id="portfolio-heading">Your portfolio</h1>
                            <span>Nifty 50</span>
                        </div>
                        <p className="muted">Portfolio equity</p>
                        <div className="equity">
                            {money(state?.portfolio.equity)}
                        </div>
                        <dl className="metrics">
                            {[
                                ["Available funds", "available_cash"],
                                ["Open P&L", "unrealized_pnl"],
                                ["Realized P&L", "realized_pnl"],
                            ].map(([label, key]) => (
                                <div key={key}>
                                    <dt>{label}</dt>
                                    <dd>{money(state?.portfolio[key])}</dd>
                                </div>
                            ))}
                        </dl>
                    </div>
                    <section
                        className="automation"
                        aria-labelledby="automation-heading"
                    >
                        <div className="section-heading">
                            <h2 id="automation-heading">Laya automation</h2>
                            <span>
                                {state?.automation.enabled
                                    ? "Enabled"
                                    : "Stopped"}
                            </span>
                        </div>
                        <p className="automation-status">
                            {state?.automation.status ??
                                "Loading automation status·"}
                        </p>
                        <button
                            className="primary"
                            disabled={
                                busy ||
                                !connected ||
                                (!state?.automation.enabled &&
                                    state?.feed !== "connected")
                            }
                            onClick={() =>
                                act(
                                    `/automation/${state?.automation.enabled ? "stop" : "start"}`,
                                )
                            }
                        >
                            {state?.automation.enabled ? (
                                <Square size={16} aria-hidden="true" />
                            ) : (
                                <Play size={16} aria-hidden="true" />
                            )}
                            {state?.automation.enabled
                                ? "Stop AI entries"
                                : "Start AI paper trading"}
                        </button>
                        <p className="muted small">
                            Intraday · {state?.automation.mover_count ?? "—"}{" "}
                            stocks · {state?.automation.max_hold_minutes ?? "—"}{" "}
                            min holding cap
                        </p>
                        <details>
                            <summary>Model and execution details</summary>
                            <p className="small">
                                {state?.automation.model ?? "Laya"} ·{" "}
                                {state?.automation.model_healthy
                                    ? "Available"
                                    : "Unavailable / not verified"}
                                {state?.automation.latency_ms != null
                                    ? ` · ${state.automation.latency_ms} ms`
                                    : ""}
                                . Active positions take priority. Qualifying
                                opposite signals may close positions. Stops and
                                targets remain active while the app and feed
                                run. Automation starts disabled after a restart.
                            </p>
                            <p className="small">
                                Watching:{" "}
                                {state?.automation.symbols.join(", ") ||
                                    "Waiting for stock selection"}
                            </p>
                        </details>
                    </section>
                </section>
                <p className="data-note">
                    Yahoo Finance · best-effort prices. Exchange timestamps and
                    freshness are shown per stock. This is not a direct NSE
                    feed. All trades and money are simulated.
                </p>
                {state && state.session.phase !== "open" && (
                    <p className="notice">
                        {state.session.phase === "closed"
                            ? "Market is closed. Paper orders require an open session and fresh regular-session prices."
                            : state.session.reason}
                    </p>
                )}
                {!!state?.positions.length && state.feed !== "connected" && (
                    <p className="notice">
                        Feed disconnected. Simulated stops and exits require
                        fresh prices.
                    </p>
                )}
                {error && (
                    <p role="alert" className="notice">
                        {error}
                    </p>
                )}
                {notice && (
                    <p role="status" className="notice">
                        {notice}
                    </p>
                )}
                <div className="workspace-grid">
                    <section
                        id="workspace"
                        className="workspace"
                        aria-label="Trading workspace"
                    >
                        <nav className="tabs" aria-label="Portfolio views">
                            {tabs.map((label, i) => (
                                <button
                                    key={label}
                                    aria-current={
                                        tab === i ? "page" : undefined
                                    }
                                    onClick={() => setTab(i)}
                                >
                                    {label}
                                    {i === 0 && (
                                        <span>
                                            {state?.positions.length ?? 0}
                                        </span>
                                    )}
                                    {i === 2 && (
                                        <span>{openOrders.length}</span>
                                    )}
                                </button>
                            ))}
                        </nav>
                        {tab === 0 && (
                            <section className="view">
                                <div className="section-heading">
                                    <h2>Active positions</h2>
                                    <button onClick={() => setTab(1)}>
                                        New paper order{" "}
                                        <ArrowUpRight
                                            size={16}
                                            aria-hidden="true"
                                        />
                                    </button>
                                </div>
                                {!state?.positions.length ? (
                                    <div className="empty">
                                        <ChartNoAxesCombined
                                            size={32}
                                            aria-hidden="true"
                                        />
                                        <h3>
                                            {state
                                                ? "No active positions"
                                                : "Loading portfolio"}
                                        </h3>
                                        <p>
                                            {state
                                                ? "Your open paper trades will appear here. Place an order in the terminal or let Laya scan during its entry window."
                                                : "Connecting to your local paper account·"}
                                        </p>
                                        <button onClick={() => setTab(1)}>
                                            Open trading terminal{" "}
                                            <ArrowUpRight
                                                size={16}
                                                aria-hidden="true"
                                            />
                                        </button>
                                    </div>
                                ) : (
                                    state.positions.map((p) => (
                                        <article
                                            className="position"
                                            key={`${p.symbol}-${p.product}`}
                                        >
                                            <div className="section-heading">
                                                <h3>
                                                    {p.symbol}{" "}
                                                    <span>
                                                        {p.quantity > 0
                                                            ? "Long"
                                                            : "Short"}{" "}
                                                        · {p.product}
                                                    </span>
                                                </h3>
                                                <strong>
                                                    {money(p.unrealized_pnl)}
                                                </strong>
                                            </div>
                                            <dl className="position-metrics">
                                                {[
                                                    [
                                                        "Quantity",
                                                        Math.abs(p.quantity),
                                                    ],
                                                    [
                                                        "Average",
                                                        money(p.average_price),
                                                    ],
                                                    ["Mark", money(p.mark)],
                                                    [
                                                        "Stop",
                                                        money(p.stop_price),
                                                    ],
                                                    [
                                                        "Target",
                                                        money(p.target_price),
                                                    ],
                                                ].map(([label, value]) => (
                                                    <div key={label}>
                                                        <dt>{label}</dt>
                                                        <dd>{value}</dd>
                                                    </div>
                                                ))}
                                            </dl>
                                            <div className="position-actions">
                                                <span className="small muted">
                                                    {p.quote_fresh
                                                        ? "Fresh quote"
                                                        : "Stale quote"}
                                                </span>
                                                <a
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    href={`https://www.tradingview.com/chart/?symbol=NSE%3A${encodeURIComponent(p.symbol)}`}
                                                >
                                                    Chart{" "}
                                                    <ArrowUpRight
                                                        size={16}
                                                        aria-hidden="true"
                                                    />
                                                </a>
                                                <button
                                                    onClick={() =>
                                                        closePosition(p)
                                                    }
                                                >
                                                    Close position
                                                </button>
                                            </div>
                                        </article>
                                    ))
                                )}
                                <p className="small muted">
                                    Estimated charges{" "}
                                    {money(state?.portfolio.charges)} · Exposure{" "}
                                    {money(state?.portfolio.exposure)}
                                </p>
                            </section>
                        )}
                        {tab === 1 && (
                            <section className="view">
                                <h2>Trading terminal</h2>
                                <div className="terminal-grid">
                                    <section>
                                        <label className="search-label">
                                            <Search
                                                size={16}
                                                aria-hidden="true"
                                            />
                                            Find a Nifty stock
                                            <input
                                                value={search}
                                                onChange={(e) =>
                                                    setSearch(e.target.value)
                                                }
                                                type="search"
                                                placeholder="Symbol or company"
                                            />
                                        </label>
                                        <div className="watchlist">
                                            {state?.stocks
                                                .filter((s) =>
                                                    `${s.symbol} ${s.company_name}`
                                                        .toLowerCase()
                                                        .includes(
                                                            search.toLowerCase(),
                                                        ),
                                                )
                                                .map((s) => (
                                                    <button
                                                        className="stock-row"
                                                        key={s.symbol}
                                                        aria-pressed={
                                                            symbol === s.symbol
                                                        }
                                                        onClick={() => {
                                                            setSymbol(s.symbol);
                                                            setReduceOnly(
                                                                false,
                                                            );
                                                        }}
                                                    >
                                                        <span>
                                                            <strong>
                                                                {s.symbol}
                                                            </strong>
                                                            <small>
                                                                {s.company_name}
                                                            </small>
                                                        </span>
                                                        <span>
                                                            {money(
                                                                s.quote?.price,
                                                            )}
                                                            <small>
                                                                {s.quote
                                                                    ?.change_percent ==
                                                                null
                                                                    ? "—"
                                                                    : `${s.quote.change_percent > 0 ? "+" : ""}${s.quote.change_percent.toFixed(2)}%`}{" "}
                                                                ·{" "}
                                                                {s.fresh
                                                                    ? "Fresh"
                                                                    : "Stale"}
                                                            </small>
                                                            <small>
                                                                {s.quote
                                                                    ? `${when(s.quote.at)} IST`
                                                                    : "No quote available"}
                                                            </small>
                                                        </span>
                                                    </button>
                                                ))}
                                        </div>
                                        {!state?.stocks.length && (
                                            <p className="muted">
                                                Connect the feed to load the
                                                Nifty 50 list.
                                            </p>
                                        )}
                                    </section>
                                    <section>
                                        <div className="section-heading">
                                            <h3>{symbol}</h3>
                                            <strong>
                                                {money(quote?.price)}
                                            </strong>
                                        </div>
                                        <p className="small muted">
                                            {quote
                                                ? `${when(quote.at)} IST · ${stock?.fresh ? "Fresh" : "Stale"}`
                                                : "No quote available"}
                                        </p>
                                        <a
                                            href={`https://www.tradingview.com/chart/?symbol=NSE%3A${encodeURIComponent(symbol)}`}
                                            target="_blank"
                                            rel="noreferrer"
                                        >
                                            Open chart{" "}
                                            <ArrowUpRight
                                                size={16}
                                                aria-hidden="true"
                                            />
                                        </a>
                                        <p className="small muted">
                                            {dataStatus}
                                        </p>
                                        <form
                                            className="order-form"
                                            onSubmit={(e) => {
                                                e.preventDefault();
                                                void act("/orders", {
                                                    symbol,
                                                    side,
                                                    product,
                                                    order_type: kind,
                                                    quantity: Number(quantity),
                                                    limit_price: [
                                                        "LIMIT",
                                                        "SL",
                                                    ].includes(kind)
                                                        ? limit || null
                                                        : null,
                                                    trigger_price: [
                                                        "SL",
                                                        "SL-M",
                                                    ].includes(kind)
                                                        ? trigger || null
                                                        : null,
                                                    stop_price: isExit
                                                        ? null
                                                        : stop || null,
                                                    target_price: isExit
                                                        ? null
                                                        : target || null,
                                                    trailing_distance: isExit
                                                        ? null
                                                        : trailing || null,
                                                    reduce_only: isExit,
                                                });
                                            }}
                                        >
                                            <label>
                                                Side
                                                <select
                                                    value={side}
                                                    onChange={(e) => {
                                                        setSide(e.target.value);
                                                        setReduceOnly(false);
                                                    }}
                                                >
                                                    <option>BUY</option>
                                                    <option>SELL</option>
                                                </select>
                                            </label>
                                            <label>
                                                Product
                                                <select
                                                    value={product}
                                                    onChange={(e) => {
                                                        setProduct(
                                                            e.target.value,
                                                        );
                                                        setReduceOnly(false);
                                                    }}
                                                >
                                                    <option value="CNC">
                                                        Delivery (CNC)
                                                    </option>
                                                    <option value="MIS">
                                                        Intraday (MIS)
                                                    </option>
                                                </select>
                                            </label>
                                            <label>
                                                Order type
                                                <select
                                                    value={kind}
                                                    onChange={(e) =>
                                                        setKind(e.target.value)
                                                    }
                                                >
                                                    {[
                                                        "MARKET",
                                                        "LIMIT",
                                                        "SL-M",
                                                        "SL",
                                                        "BRACKET",
                                                    ].map((k) => (
                                                        <option key={k}>
                                                            {k}
                                                        </option>
                                                    ))}
                                                </select>
                                            </label>
                                            <label>
                                                Quantity
                                                <input
                                                    required
                                                    type="number"
                                                    min="1"
                                                    max="1000000000"
                                                    step="1"
                                                    value={quantity}
                                                    onChange={(e) =>
                                                        setQuantity(
                                                            e.target.value,
                                                        )
                                                    }
                                                />
                                            </label>
                                            {["LIMIT", "SL"].includes(kind) && (
                                                <label>
                                                    Limit price
                                                    <input
                                                        required
                                                        type="number"
                                                        min="0.01"
                                                        step="any"
                                                        value={limit}
                                                        onChange={(e) =>
                                                            setLimit(
                                                                e.target.value,
                                                            )
                                                        }
                                                    />
                                                </label>
                                            )}
                                            {["SL", "SL-M"].includes(kind) && (
                                                <label>
                                                    Trigger price
                                                    <input
                                                        required
                                                        type="number"
                                                        min="0.01"
                                                        step="any"
                                                        value={trigger}
                                                        onChange={(e) =>
                                                            setTrigger(
                                                                e.target.value,
                                                            )
                                                        }
                                                    />
                                                </label>
                                            )}
                                            {!isExit && (
                                                <>
                                                    <label>
                                                        Stop price
                                                        <input
                                                            required
                                                            type="number"
                                                            min="0.01"
                                                            step="any"
                                                            value={stop}
                                                            onChange={(e) =>
                                                                setStop(
                                                                    e.target
                                                                        .value,
                                                                )
                                                            }
                                                        />
                                                    </label>
                                                    <label>
                                                        Target price
                                                        <input
                                                            required={
                                                                kind ===
                                                                "BRACKET"
                                                            }
                                                            type="number"
                                                            min="0.01"
                                                            step="any"
                                                            value={target}
                                                            onChange={(e) =>
                                                                setTarget(
                                                                    e.target
                                                                        .value,
                                                                )
                                                            }
                                                        />
                                                    </label>
                                                    <label>
                                                        Trailing distance
                                                        <input
                                                            type="number"
                                                            min="0.01"
                                                            step="any"
                                                            value={trailing}
                                                            onChange={(e) =>
                                                                setTrailing(
                                                                    e.target
                                                                        .value,
                                                                )
                                                            }
                                                        />
                                                    </label>
                                                </>
                                            )}
                                            <p className="full small muted">
                                                {isExit
                                                    ? "Closing an existing position. Review the quantity before submitting."
                                                    : `Estimated stop risk ${money(estimatedRisk)} · Budget ${money(riskBudget)}`}
                                            </p>
                                            <button
                                                className="primary full"
                                                disabled={!ready || busy}
                                                type="submit"
                                            >
                                                {busy
                                                    ? "Submitting·"
                                                    : `${side === "BUY" ? "Buy" : "Sell"} ${symbol} · paper order`}
                                            </button>
                                            {!ready && (
                                                <p className="full small muted">
                                                    Orders require an open
                                                    session, connected feed,
                                                    fresh quote and prepared
                                                    stock data.
                                                </p>
                                            )}
                                        </form>
                                    </section>
                                </div>
                            </section>
                        )}
                        {tab === 2 && (
                            <section className="view">
                                <h2>Orders</h2>
                                <div
                                    className="table-scroll"
                                    role="region"
                                    aria-label="Orders"
                                    tabIndex={0}
                                >
                                    <table>
                                        <caption>
                                            Paper orders and remaining
                                            quantities
                                        </caption>
                                        <thead>
                                            <tr>
                                                {[
                                                    "Stock / product",
                                                    "Side / type",
                                                    "Quantity",
                                                    "Status",
                                                    "Action",
                                                ].map((h) => (
                                                    <th scope="col" key={h}>
                                                        {h}
                                                    </th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {state?.orders.map((o) => (
                                                <tr key={o.order.id}>
                                                    <th scope="row">
                                                        {o.order.symbol}
                                                        <small>
                                                            {o.order.product}
                                                        </small>
                                                    </th>
                                                    <td>
                                                        {o.order.side}
                                                        <small>
                                                            {o.order.order_type}
                                                        </small>
                                                    </td>
                                                    <td>
                                                        {o.order.quantity}
                                                        <small>
                                                            {o.remaining}{" "}
                                                            remaining
                                                        </small>
                                                    </td>
                                                    <td>
                                                        {readable(o.status)}
                                                        <small>
                                                            {o.reasons?.join(
                                                                ", ",
                                                            )}
                                                        </small>
                                                    </td>
                                                    <td>
                                                        {[
                                                            "OPEN",
                                                            "PARTIAL",
                                                        ].includes(o.status) ? (
                                                            <button
                                                                disabled={busy}
                                                                onClick={() =>
                                                                    act(
                                                                        `/orders/${encodeURIComponent(o.order.id)}`,
                                                                        undefined,
                                                                        "DELETE",
                                                                    )
                                                                }
                                                            >
                                                                Cancel
                                                            </button>
                                                        ) : (
                                                            "—"
                                                        )}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                                {!state?.orders.length && (
                                    <p className="empty">
                                        No paper orders yet.
                                    </p>
                                )}
                            </section>
                        )}
                        {tab === 3 && (
                            <section className="view">
                                <h2>Closed trades</h2>
                                <div
                                    className="table-scroll"
                                    role="region"
                                    aria-label="Closed trades"
                                    tabIndex={0}
                                >
                                    <table>
                                        <caption>
                                            Completed paper positions · times in
                                            IST
                                        </caption>
                                        <thead>
                                            <tr>
                                                {[
                                                    "Stock",
                                                    "Quantity",
                                                    "P&L",
                                                    "Charges",
                                                    "Closed / reason",
                                                ].map((h) => (
                                                    <th scope="col" key={h}>
                                                        {h}
                                                    </th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {state?.closed_trades.map(
                                                (t, i) => (
                                                    <tr
                                                        key={`${t.closed_at}-${i}`}
                                                    >
                                                        <th scope="row">
                                                            {t.symbol}
                                                        </th>
                                                        <td>{t.quantity}</td>
                                                        <td>{money(t.pnl)}</td>
                                                        <td>
                                                            {money(t.charges)}
                                                        </td>
                                                        <td>
                                                            {when(t.closed_at)}
                                                            <small>
                                                                {readable(
                                                                    t.reason,
                                                                )}
                                                            </small>
                                                        </td>
                                                    </tr>
                                                ),
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                                {!state?.closed_trades.length && (
                                    <p className="empty">
                                        No closed trades yet.
                                    </p>
                                )}
                            </section>
                        )}
                        {tab === 4 && (
                            <section className="view">
                                <h2>Executions</h2>
                                <div
                                    className="table-scroll"
                                    role="region"
                                    aria-label="Executions"
                                    tabIndex={0}
                                >
                                    <table>
                                        <caption>
                                            Simulated fills · times in IST
                                        </caption>
                                        <thead>
                                            <tr>
                                                {[
                                                    "Stock",
                                                    "Side",
                                                    "Quantity",
                                                    "Fill price",
                                                    "Time / reason",
                                                ].map((h) => (
                                                    <th scope="col" key={h}>
                                                        {h}
                                                    </th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {state?.fills.map((f, i) => (
                                                <tr key={`${f.at}-${i}`}>
                                                    <th scope="row">
                                                        {f.symbol}
                                                    </th>
                                                    <td>{f.side}</td>
                                                    <td>{f.quantity}</td>
                                                    <td>{money(f.price)}</td>
                                                    <td>
                                                        {when(f.at)}
                                                        <small>
                                                            {readable(f.reason)}
                                                        </small>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                                {!state?.fills.length && (
                                    <p className="empty">No executions yet.</p>
                                )}
                            </section>
                        )}
                    </section>
                    <aside
                        className="journal"
                        aria-labelledby="journal-heading"
                    >
                        <div className="section-heading">
                            <h2 id="journal-heading">Decision journal</h2>
                            <span>IST</span>
                        </div>
                        <p className="small muted">
                            Latest Laya decisions and execution checks.
                        </p>
                        {state?.automation.events.length ? (
                            [...state.automation.events]
                                .reverse()
                                .slice(0, showAllDecisions ? undefined : 10)
                                .map((e, i) => (
                                    <article
                                        className="journal-entry"
                                        key={`${e.at}-${i}`}
                                    >
                                        <div className="section-heading">
                                            <strong>{e.symbol}</strong>
                                            <span>{e.direction}</span>
                                        </div>
                                        <p>
                                            {[e.action, e.reason, ...e.vetoes]
                                                .filter(Boolean)
                                                .map((v) => readable(v!))
                                                .join(" · ")}
                                        </p>
                                        <time>{when(e.at)}</time>
                                    </article>
                                ))
                        ) : (
                            <p className="muted">
                                Decisions will appear when Laya scans the
                                market.
                            </p>
                        )}
                        {!!state && state.automation.events.length > 10 && (
                            <button
                                className="journal-toggle"
                                aria-expanded={showAllDecisions}
                                onClick={() =>
                                    setShowAllDecisions(!showAllDecisions)
                                }
                            >
                                {showAllDecisions
                                    ? "Show latest decisions"
                                    : "Show earlier decisions"}
                            </button>
                        )}
                    </aside>
                </div>
                <footer>
                    <span>
                        Paper trading only · Keep the app and feed running for
                        simulated exits.
                    </span>
                    <a href="/?workspace=research">
                        Research workspace{" "}
                        <ArrowUpRight size={16} aria-hidden="true" />
                    </a>
                </footer>
            </main>
        </div>
    );
}
