import { useEffect, useState } from "react";
import {
    Alert,
    AppBar,
    Box,
    Button,
    Chip,
    Container,
    MenuItem,
    Paper,
    Stack,
    Tab,
    Tabs,
    TextField,
    Toolbar,
    Typography,
} from "@mui/material";
import {
    Area,
    ComposedChart,
    Line,
    Legend,
    CartesianGrid,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";
import CandleChart from "./CandleChart";
import type { Bar, Indicator, Fill } from "./CandleChart";
import MarketPanel from "./MarketPanel";
import PortfolioValue from "../components/PortfolioValue";
import PositionsTable from "../components/PositionsTable";
import BotPanel from "./BotPanel";
import CalibrationPanel from "./CalibrationPanel";
import { useAccountContext } from "../contexts/AccountContext";

type State = {
    inference?: {
        active: boolean;
        last_error: string | null;
        latency_ms: number | null;
    };
    indicators?: Indicator[];
    fills?: Fill[];
    mode: string;
    source: string;
    run: null | {
        id: string;
        clock: string | null;
        cursor: number;
        total: number;
        playing: boolean;
        shadow: boolean;
    };
    candles: Bar[];
    curve: {
        at: string;
        equity: string;
        benchmarks?: Record<string, string>;
    }[];
    orders: {
        status: string;
        order: {
            id: string;
            symbol: string;
            side: string;
            quantity: number;
            product: string;
        };
    }[];
    decisions: {
        at: string;
        symbol: string;
        payload: { direction: string; reason: string; vetoes: string[] };
    }[];
    trades: Record<string, unknown>[];
    features: Record<
        string,
        { state: string; regime: string; values: Record<string, unknown> }
    >;
    metrics: Record<string, unknown>;
    exposure?: string;
    charges?: string;
};
const money = (value: unknown) =>
    Number(value ?? 0).toLocaleString("en-IN", {
        style: "currency",
        currency: "INR",
    });
const ist = (value: string | null) =>
    value
        ? new Date(value).toLocaleString("en-IN", {
              timeZone: "Asia/Kolkata",
              hour12: false,
          })
        : "Waiting for a closed candle";

async function api(path: string, body?: unknown, method?: string) {
    const response = await fetch(`/api/${path}`, {
        method: method ?? (body === undefined ? "GET" : "POST"),
        headers: { "Content-Type": "application/json", "X-Paper-Request": "1" },
        body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok)
        throw new Error(
            typeof payload.detail === "string"
                ? payload.detail
                : "Request rejected",
        );
    return payload;
}

export default function Terminal() {
    const [state, setState] = useState<State | null>(null);
    const [tab, setTab] = useState(11);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const [strategy, setStrategy] = useState("hold");
    const [shadow, setShadow] = useState("false");
    const [marketSymbol, setMarketSymbol] = useState("RELIANCE");
    const [symbol, setSymbol] = useState("DEMO");
    const [side, setSide] = useState("BUY");
    const [product, setProduct] = useState("MIS");
    const [kind, setKind] = useState("MARKET");
    const [quantity, setQuantity] = useState("1");
    const [stop, setStop] = useState("");
    const [target, setTarget] = useState("");
    const [trailing, setTrailing] = useState("");
    const [reduceOnly, setReduceOnly] = useState("false");
    const [tradeDetails, setTradeDetails] = useState<Record<string, unknown>>(
        {},
    );
    const [limit, setLimit] = useState("");
    const [trigger, setTrigger] = useState("");
    const [dataVersion, setDataVersion] = useState("");
    const [niftyVersion, setNiftyVersion] = useState("");
    const [bankVersion, setBankVersion] = useState("");
    const [settingsView, setSettingsView] = useState<Record<string, unknown>>(
        {},
    );
    const [watchIndex, setWatchIndex] = useState("NIFTY50");
    const [watchlist, setWatchlist] = useState<{
        members?: { symbol: string; company_name: string; sector: string }[];
        message?: string;
    }>({});
    const [health, setHealth] = useState<Record<string, unknown>>({});
    const [connected, setConnected] = useState(false);
    const {
        refreshAccounts,
        availableAccounts,
        selectedAccount,
        selectAccount,
    } = useAccountContext();
    useEffect(() => {
        if (
            availableAccounts.length &&
            !availableAccounts.some((a) => a.id === selectedAccount?.id)
        )
            selectAccount(availableAccounts[0]);
    }, [availableAccounts, selectedAccount, selectAccount]);
    useEffect(() => {
        api("terminal")
            .then(setState)
            .catch((e) => setError(e.message));
        const socket = new WebSocket(
            `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`,
        );
        socket.onopen = () => setConnected(true);
        socket.onmessage = (event) => setState(JSON.parse(event.data));
        socket.onclose = () => setConnected(false);
        return () => socket.close();
    }, []);
    async function act(path: string, body: unknown = {}) {
        setBusy(true);
        setError("");
        try {
            const result = await api(path, body);
            if (result.mode) setState(result);
            if (path === "run") await refreshAccounts();
            if (result.vetoes?.length)
                setError(`Risk veto: ${result.vetoes.join(", ")}`);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Operation failed");
        } finally {
            setBusy(false);
        }
    }
    useEffect(() => {
        const key = (event: KeyboardEvent) => {
            if (event.altKey && event.key.toLowerCase() === "o") {
                event.preventDefault();
                setTab(2);
            }
        };
        window.addEventListener("keydown", key);
        return () => window.removeEventListener("keydown", key);
    }, []);
    const tabs = [
        "Overview",
        "Replay chart",
        "Order ticket",
        "Decisions",
        "Trade inspector",
        "Reports",
        "Settings",
        "System health",
        "Watchlist",
        "Bot arena",
        "Calibration / research",
        "Stocks / charts",
    ];
    const run = state?.run;
    const bars = state?.candles.filter((b) => b.symbol === symbol) ?? [];
    const feature = state?.features[symbol];
    return (
        <>
            <AppBar
                position="static"
                color="transparent"
                elevation={0}
                sx={{ borderBottom: "1px solid #253243" }}
            >
                <Toolbar sx={{ gap: 2 }}>
                    <Box sx={{ flex: 1 }}>
                        <Typography variant="h6" fontWeight={700}>
                            Paper Trader{" "}
                            <Box
                                component="span"
                                sx={{ color: "primary.main" }}
                            >
                                Automated
                            </Box>
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                            NSE CASH EQUITIES · LOCAL TERMINAL
                        </Typography>
                    </Box>
                    <Chip
                        label="PAPER ONLY"
                        color="primary"
                        variant="outlined"
                    />
                    <Chip
                        label={
                            connected
                                ? "Local service connected"
                                : "Local service disconnected"
                        }
                        color={connected ? "success" : "warning"}
                        size="small"
                    />
                </Toolbar>
            </AppBar>
            <Container maxWidth="xl" sx={{ py: 4 }}>
                <Stack
                    direction={{ xs: "column", md: "row" }}
                    justifyContent="space-between"
                    gap={2}
                    mb={3}
                >
                    <Box>
                        <Typography variant="h4">
                            {tab === 11
                                ? "Market workspace"
                                : "Trading workspace"}
                        </Typography>
                        <Typography color="text.secondary" mt={1}>
                            {tab === 11
                                ? "NSE stocks, historical candles and technical indicators"
                                : `${ist(run?.clock ?? null)} · IST`}
                        </Typography>
                    </Box>
                    <Stack
                        direction="row"
                        gap={1}
                        alignItems="center"
                        sx={{ display: tab === 11 ? "none" : "flex" }}
                    >
                        <TextField
                            select
                            size="small"
                            label="Policy"
                            value={strategy}
                            onChange={(e) => setStrategy(e.target.value)}
                            sx={{ minWidth: 155 }}
                        >
                            <MenuItem value="hold">Hold baseline</MenuItem>
                            <MenuItem value="ema">EMA baseline</MenuItem>
                            <MenuItem value="systemone">Local Laya</MenuItem>
                        </TextField>
                        <TextField
                            select
                            size="small"
                            label="Execution"
                            value={shadow}
                            onChange={(e) => setShadow(e.target.value)}
                        >
                            <MenuItem value="false">Paper fills</MenuItem>
                            <MenuItem value="true">Shadow</MenuItem>
                        </TextField>
                        <Button
                            variant="contained"
                            disabled={busy || run?.playing}
                            onClick={() =>
                                act("run", {
                                    strategy,
                                    shadow: shadow === "true",
                                    source: "synthetic",
                                })
                            }
                        >
                            New demo
                        </Button>
                    </Stack>
                </Stack>
                <Alert severity="info" sx={{ mb: 2 }}>
                    {tab === 11 ? (
                        "Browse market history here. Replay controls, paper positions and execution stay in the trading tabs."
                    ) : (
                        <>
                            {state?.source === "synthetic"
                                ? "Synthetic demo prices. "
                                : ""}
                            Closed candles only. Laya must be running locally
                            for AI decisions; inference failures hold new
                            entries.
                        </>
                    )}
                </Alert>
                {state?.inference?.last_error && (
                    <Alert severity="warning" sx={{ mb: 2 }}>
                        Local inference failed or timed out. New entries are
                        held; protective stops continue through the engine.
                    </Alert>
                )}
                {error && (
                    <Alert
                        severity="error"
                        onClose={() => setError("")}
                        sx={{ mb: 2 }}
                    >
                        {error}
                    </Alert>
                )}
                <Stack
                    direction="row"
                    gap={1}
                    alignItems="center"
                    flexWrap="wrap"
                    mb={3}
                    sx={{ display: tab === 11 ? "none" : "flex" }}
                >
                    <Button
                        variant="outlined"
                        disabled={busy || !run || run.playing}
                        onClick={() => act("step")}
                    >
                        Step
                    </Button>
                    <Button
                        variant="outlined"
                        disabled={busy || !run || run.playing}
                        onClick={() => act("play")}
                    >
                        Play
                    </Button>
                    <Button
                        variant="outlined"
                        disabled={busy || !run?.playing}
                        onClick={() => act("pause")}
                    >
                        Pause
                    </Button>
                    <Typography variant="body2" color="text.secondary">
                        {run
                            ? `${run.cursor} / ${run.total} bars · ${run.shadow ? "Shadow decisions" : "Paper execution"}`
                            : "Create a demo to start"}
                    </Typography>
                    <Box sx={{ flex: 1 }} />
                    <Typography variant="body2">
                        Exposure {money(state?.exposure)} · Charges{" "}
                        {money(state?.charges)}
                    </Typography>
                </Stack>
                <Tabs
                    value={tab}
                    onChange={(_, value) => setTab(value)}
                    variant="scrollable"
                    scrollButtons="auto"
                    sx={{ mb: 3, borderBottom: "1px solid #253243" }}
                >
                    {tabs.map((t) => (
                        <Tab label={t} key={t} />
                    ))}
                </Tabs>
                {tab === 0 && (
                    <Box
                        sx={{
                            display: "grid",
                            gridTemplateColumns: { xs: "1fr", lg: "1fr 2fr" },
                            gap: 3,
                        }}
                    >
                        <PortfolioValue key={`p-${run?.cursor}`} />
                        <Paper sx={{ p: 3 }}>
                            <Typography variant="h6" mb={2}>
                                Equity · INR
                            </Typography>
                            <ResponsiveContainer width="100%" height={280}>
                                <ComposedChart
                                    data={
                                        state?.curve.map((p) => ({
                                            at: ist(p.at),
                                            equity: +p.equity,
                                            NIFTY50:
                                                p.benchmarks?.NIFTY50 ===
                                                undefined
                                                    ? undefined
                                                    : Number(
                                                          p.benchmarks.NIFTY50,
                                                      ),
                                            NIFTYBANK:
                                                p.benchmarks?.NIFTYBANK ===
                                                undefined
                                                    ? undefined
                                                    : Number(
                                                          p.benchmarks
                                                              .NIFTYBANK,
                                                      ),
                                        })) ?? []
                                    }
                                >
                                    <CartesianGrid stroke="#253243" />
                                    <Legend />
                                    {state?.curve.some(
                                        (p) =>
                                            p.benchmarks?.NIFTY50 !== undefined,
                                    ) && (
                                        <Line
                                            dataKey="NIFTY50"
                                            stroke="#a5b5fb"
                                            dot={false}
                                            connectNulls={false}
                                        />
                                    )}
                                    {state?.curve.some(
                                        (p) =>
                                            p.benchmarks?.NIFTYBANK !==
                                            undefined,
                                    ) && (
                                        <Line
                                            dataKey="NIFTYBANK"
                                            stroke="#fabf77"
                                            dot={false}
                                            connectNulls={false}
                                        />
                                    )}
                                    <XAxis dataKey="at" hide />
                                    <YAxis
                                        domain={["auto", "auto"]}
                                        tickFormatter={(v) =>
                                            Number(v).toLocaleString("en-IN")
                                        }
                                        width={90}
                                    />
                                    <Tooltip
                                        formatter={(value) => money(value)}
                                    />
                                    <Area
                                        dataKey="equity"
                                        stroke="#77dfb5"
                                        fill="#77dfb5"
                                        fillOpacity={0.12}
                                    />
                                </ComposedChart>
                            </ResponsiveContainer>
                        </Paper>
                        <Box sx={{ gridColumn: "1 / -1" }}>
                            <PositionsTable key={`positions-${run?.cursor}`} />
                        </Box>
                    </Box>
                )}
                {tab === 1 && (
                    <Paper sx={{ p: 3 }}>
                        <Stack direction="row" justifyContent="space-between">
                            <Typography variant="h6">
                                {symbol} · Replay candles
                            </Typography>
                            <Chip
                                label={feature?.regime ?? "WARMUP"}
                                size="small"
                            />
                        </Stack>
                        <CandleChart
                            bars={bars}
                            indicators={
                                state?.indicators?.filter(
                                    (i) => i.symbol === symbol,
                                ) ?? []
                            }
                            fills={
                                state?.fills?.filter(
                                    (f) => f.symbol === symbol,
                                ) ?? []
                            }
                        />
                        <Typography variant="caption">
                            Charts powered by{" "}
                            <a
                                href="https://www.tradingview.com/"
                                target="_blank"
                                rel="noreferrer"
                            >
                                TradingView Lightweight Charts
                            </a>
                        </Typography>
                        <Typography sx={{ mt: 2, fontFamily: "monospace" }}>
                            {feature?.state ??
                                "Step the replay to build market state."}
                        </Typography>
                    </Paper>
                )}
                {tab === 2 && (
                    <Paper
                        component="form"
                        sx={{ p: 3, maxWidth: 800 }}
                        onSubmit={(e) => {
                            e.preventDefault();
                            act("orders", {
                                symbol,
                                side,
                                product,
                                order_type: kind,
                                quantity: +quantity,
                                signal_at: run?.clock,
                                stop_price: stop || undefined,
                                trailing_distance: trailing || undefined,
                                reduce_only: reduceOnly === "true",
                                validity: product === "CNC" ? "GTC" : "DAY",
                                target_price: target || undefined,
                                limit_price: limit || undefined,
                                trigger_price: trigger || undefined,
                            });
                        }}
                    >
                        <Typography variant="h6" mb={2}>
                            Paper order · Alt+O
                        </Typography>
                        <Box
                            sx={{
                                display: "grid",
                                gridTemplateColumns: {
                                    xs: "1fr",
                                    sm: "1fr 1fr",
                                },
                                gap: 2,
                            }}
                        >
                            <TextField
                                label="Symbol"
                                value={symbol}
                                onChange={(e) =>
                                    setSymbol(e.target.value.toUpperCase())
                                }
                            />
                            <TextField
                                select
                                label="Side"
                                value={side}
                                onChange={(e) => setSide(e.target.value)}
                            >
                                {["BUY", "SELL"].map((v) => (
                                    <MenuItem value={v} key={v}>
                                        {v}
                                    </MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                select
                                label="Product"
                                value={product}
                                onChange={(e) => setProduct(e.target.value)}
                            >
                                {["MIS", "CNC"].map((v) => (
                                    <MenuItem value={v} key={v}>
                                        {v}
                                    </MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                select
                                label="Order type"
                                value={kind}
                                onChange={(e) => setKind(e.target.value)}
                            >
                                {[
                                    "MARKET",
                                    "LIMIT",
                                    "SL",
                                    "SL-M",
                                    "BRACKET",
                                ].map((v) => (
                                    <MenuItem value={v} key={v}>
                                        {v}
                                    </MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                required
                                label="Quantity"
                                type="number"
                                value={quantity}
                                onChange={(e) => setQuantity(e.target.value)}
                            />
                            <TextField
                                required={reduceOnly === "false"}
                                label="Protective stop (INR)"
                                value={stop}
                                onChange={(e) => setStop(e.target.value)}
                            />
                            <TextField
                                label="Target (INR)"
                                value={target}
                                onChange={(e) => setTarget(e.target.value)}
                            />
                            <TextField
                                label="Limit (INR)"
                                value={limit}
                                onChange={(e) => setLimit(e.target.value)}
                            />
                            <TextField
                                label="Trigger (INR)"
                                value={trigger}
                                onChange={(e) => setTrigger(e.target.value)}
                            />
                            <TextField
                                label="Trailing distance (INR)"
                                value={trailing}
                                onChange={(e) => setTrailing(e.target.value)}
                            />
                            <TextField
                                select
                                label="Intent"
                                value={reduceOnly}
                                onChange={(e) => setReduceOnly(e.target.value)}
                            >
                                <MenuItem value="false">Entry</MenuItem>
                                <MenuItem value="true">
                                    Reduce existing position
                                </MenuItem>
                            </TextField>
                        </Box>
                        <Button
                            type="submit"
                            variant="contained"
                            disabled={busy || !run || run.shadow || run.playing}
                            sx={{ mt: 3 }}
                        >
                            Submit paper order
                        </Button>
                        <Typography color="text.secondary" mt={2}>
                            Stops, cash, session, liquidity and risk limits are
                            checked by the engine. The order fills on a later
                            eligible bar.
                        </Typography>
                        <Stack gap={1} mt={3}>
                            {state?.orders.map((o) => (
                                <Stack
                                    key={o.order.id}
                                    direction="row"
                                    justifyContent="space-between"
                                >
                                    <Typography>
                                        {o.order.symbol} · {o.order.side}{" "}
                                        {o.order.quantity} · {o.status}
                                    </Typography>
                                    {["OPEN", "PARTIAL"].includes(o.status) && (
                                        <Button
                                            onClick={async () => {
                                                try {
                                                    await api(
                                                        `orders/${o.order.id}`,
                                                        undefined,
                                                        "DELETE",
                                                    );
                                                    setState(
                                                        await api("terminal"),
                                                    );
                                                } catch (e) {
                                                    setError(String(e));
                                                }
                                            }}
                                        >
                                            Cancel
                                        </Button>
                                    )}
                                </Stack>
                            ))}
                        </Stack>
                    </Paper>
                )}
                {tab === 3 && (
                    <Stack gap={1}>
                        {state?.decisions
                            .slice()
                            .reverse()
                            .map((d, i) => (
                                <Paper key={i} sx={{ p: 2 }}>
                                    <Stack direction="row" gap={2}>
                                        <Chip
                                            size="small"
                                            label={d.payload.direction}
                                        />
                                        <Typography>
                                            {d.symbol} · {ist(d.at)}
                                        </Typography>
                                    </Stack>
                                    <Typography color="text.secondary" mt={1}>
                                        {d.payload.reason}
                                        {d.payload.vetoes.length
                                            ? ` · ${d.payload.vetoes.join(", ")}`
                                            : ""}
                                    </Typography>
                                </Paper>
                            ))}
                        {!state?.decisions.length && (
                            <Typography color="text.secondary">
                                No decisions yet.
                            </Typography>
                        )}
                    </Stack>
                )}
                {tab === 4 && (
                    <Stack gap={2}>
                        {state?.trades.map((t, i) => (
                            <Paper key={i} sx={{ p: 3 }}>
                                <Typography variant="h6">
                                    {String(t.symbol)} · {money(t.pnl)}
                                </Typography>
                                <Typography color="text.secondary">
                                    {String(t.reason)} · Charges{" "}
                                    {money(t.charges)}
                                </Typography>
                                <Box
                                    component="pre"
                                    sx={{ overflow: "auto", fontSize: 12 }}
                                >
                                    {JSON.stringify(t, null, 2)}
                                </Box>
                                <Button
                                    onClick={async () => {
                                        try {
                                            setTradeDetails(
                                                await api(
                                                    `trades/${String(t.entry_order_id)}`,
                                                ),
                                            );
                                        } catch (e) {
                                            setError(String(e));
                                        }
                                    }}
                                >
                                    Inspect entry decision
                                </Button>
                                <Box
                                    component="pre"
                                    sx={{ overflow: "auto", fontSize: 12 }}
                                >
                                    {JSON.stringify(tradeDetails, null, 2)}
                                </Box>
                            </Paper>
                        ))}
                        {!state?.trades.length && (
                            <Typography color="text.secondary">
                                Closed trade details appear here after an exit.
                            </Typography>
                        )}
                    </Stack>
                )}
                {tab === 5 && (
                    <Paper sx={{ p: 3 }}>
                        <Typography variant="h6">
                            Run report / stored replay
                        </Typography>
                        <Stack
                            direction={{ xs: "column", sm: "row" }}
                            gap={2}
                            my={2}
                        >
                            <TextField
                                size="small"
                                label="Symbol"
                                value={symbol}
                                onChange={(e) =>
                                    setSymbol(e.target.value.toUpperCase())
                                }
                            />
                            <TextField
                                size="small"
                                label="Immutable data version"
                                value={dataVersion}
                                onChange={(e) => setDataVersion(e.target.value)}
                                sx={{ flex: 1 }}
                            />
                            <Button
                                disabled={busy || run?.playing || !dataVersion}
                                onClick={() =>
                                    act("run", {
                                        source: "stored",
                                        symbol,
                                        version: dataVersion,
                                        benchmarks: {
                                            ...(niftyVersion
                                                ? { NIFTY50: niftyVersion }
                                                : {}),
                                            ...(bankVersion
                                                ? { NIFTYBANK: bankVersion }
                                                : {}),
                                        },
                                        strategy,
                                        shadow: shadow === "true",
                                    })
                                }
                            >
                                Replay stored
                            </Button>
                        </Stack>
                        <Stack
                            direction={{ xs: "column", sm: "row" }}
                            gap={2}
                            mb={2}
                        >
                            <TextField
                                size="small"
                                label="Nifty 50 version (optional)"
                                value={niftyVersion}
                                onChange={(e) =>
                                    setNiftyVersion(e.target.value)
                                }
                                fullWidth
                            />
                            <TextField
                                size="small"
                                label="Bank Nifty version (optional)"
                                value={bankVersion}
                                onChange={(e) => setBankVersion(e.target.value)}
                                fullWidth
                            />
                        </Stack>
                        <Typography color="text.secondary">
                            Undefined metrics display as null. Short synthetic
                            runs do not establish performance.
                        </Typography>
                        <Box component="pre" sx={{ overflow: "auto" }}>
                            {JSON.stringify(state?.metrics, null, 2)}
                        </Box>
                    </Paper>
                )}
                {tab === 6 && (
                    <Paper sx={{ p: 3 }}>
                        <Typography variant="h6">
                            Validated configuration
                        </Typography>
                        <Typography color="text.secondary" mt={1}>
                            Edit config.yaml locally to change risk, charges,
                            sessions, universe and inference thresholds. Restart
                            to apply; each run stores its configuration and
                            immutable data versions. Runtime credential files
                            remain outside Git.
                        </Typography>
                        <Typography mt={2}>
                            Use the CLI fetch/backtest commands for real stored
                            history. This demo does not fetch live prices.
                        </Typography>
                        <Button
                            onClick={async () => {
                                try {
                                    setSettingsView(await api("settings"));
                                } catch (e) {
                                    setError(String(e));
                                }
                            }}
                        >
                            View current parameters
                        </Button>
                        <Box component="pre" sx={{ overflow: "auto" }}>
                            {JSON.stringify(settingsView, null, 2)}
                        </Box>
                    </Paper>
                )}
                {tab === 7 && (
                    <Paper sx={{ p: 3 }}>
                        <Typography variant="h6">System health</Typography>
                        <Button
                            onClick={async () => {
                                try {
                                    setHealth(await api("health"));
                                } catch (e) {
                                    setError(String(e));
                                }
                            }}
                        >
                            Check services
                        </Button>
                        <Box component="pre" sx={{ overflow: "auto" }}>
                            {JSON.stringify(health, null, 2)}
                        </Box>
                    </Paper>
                )}
                {tab === 8 && (
                    <Paper sx={{ p: 3 }}>
                        <Stack direction="row" gap={2}>
                            <TextField
                                select
                                size="small"
                                label="Index"
                                value={watchIndex}
                                onChange={(e) => setWatchIndex(e.target.value)}
                            >
                                <MenuItem value="NIFTY50">Nifty 50</MenuItem>
                                <MenuItem value="NIFTYBANK">
                                    Bank Nifty
                                </MenuItem>
                            </TextField>
                            <Button
                                onClick={async () => {
                                    try {
                                        setWatchlist(
                                            await api(
                                                `watchlist/${watchIndex}`,
                                            ),
                                        );
                                    } catch (e) {
                                        setError(String(e));
                                    }
                                }}
                            >
                                Load observed members
                            </Button>
                        </Stack>
                        <Typography color="text.secondary" my={2}>
                            {watchlist.message ??
                                "Membership uses the replay clock. Refresh official snapshots with the CLI; current members are never backfilled into past runs."}
                        </Typography>
                        <Box
                            sx={{
                                display: "grid",
                                gridTemplateColumns:
                                    "repeat(auto-fill, minmax(160px, 1fr))",
                                gap: 1,
                            }}
                        >
                            {watchlist.members?.map((member) => (
                                <Paper key={member.symbol} sx={{ p: 2 }}>
                                    <Button
                                        onClick={() => {
                                            setMarketSymbol(member.symbol);
                                            setTab(11);
                                        }}
                                    >
                                        {member.symbol}
                                    </Button>
                                    <Typography
                                        variant="caption"
                                        color="text.secondary"
                                    >
                                        {member.company_name} · {member.sector}
                                    </Typography>
                                </Paper>
                            ))}
                        </Box>
                    </Paper>
                )}
                {tab === 9 && <BotPanel />}
                {tab === 10 && <CalibrationPanel runId={run?.id} />}
                {tab === 11 && (
                    <MarketPanel
                        initialSymbol={marketSymbol}
                        onReplay={async (selected, timeframe, version) => {
                            const result = await api("run", {
                                source: "stored",
                                symbol: selected,
                                timeframe,
                                version,
                                strategy,
                                shadow: shadow === "true",
                            });
                            setState(result);
                            await refreshAccounts();
                            setSymbol(selected);
                            setTab(1);
                        }}
                    />
                )}
                <Typography
                    variant="caption"
                    color="text.secondary"
                    display="block"
                    mt={4}
                >
                    Adapted from Open Paper Trading MCP · Apache-2.0 · Local
                    paper simulation
                </Typography>
            </Container>
        </>
    );
}
