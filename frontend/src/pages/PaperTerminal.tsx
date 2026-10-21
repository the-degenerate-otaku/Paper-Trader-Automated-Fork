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
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Toolbar,
    Typography,
} from "@mui/material";

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
    feed: string;
    source: string;
    now: string;
    session: { phase: string; reason: string };
    membership_fresh: boolean;
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
    Number(value ?? 0).toLocaleString("en-IN", {
        style: "currency",
        currency: "INR",
    });
const when = (value: string) =>
    new Date(value).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        hour12: false,
    });
const tint = (value: unknown) => (Number(value) >= 0 ? "#77dfb5" : "#fa8c99");

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
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
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
                setError(`Order blocked: ${result.vetoes.join(", ")}`);
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
    return (
        <>
            <AppBar
                position="static"
                color="transparent"
                elevation={0}
                sx={{ borderBottom: "1px solid #253243" }}
            >
                <Toolbar sx={{ gap: 2, flexWrap: "wrap", py: 1 }}>
                    <Box sx={{ flex: 1 }}>
                        <Typography variant="h6" fontWeight={700}>
                            Paper Trader{" "}
                            <Box component="span" color="primary.main">
                                Automated
                            </Box>
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                            NIFTY 50 · VIRTUAL MONEY · MANUAL PAPER TRADING
                        </Typography>
                    </Box>
                    <Chip
                        label="PAPER ONLY"
                        color="primary"
                        variant="outlined"
                    />
                    <Chip
                        size="small"
                        label={state?.session.phase ?? "Loading"}
                    />
                    <Chip
                        size="small"
                        label={`Feed: ${state?.feed ?? "offline"}`}
                        color={
                            state?.feed === "connected" ? "success" : "warning"
                        }
                    />
                    <Button
                        variant="contained"
                        disabled={busy || state?.feed === "connecting"}
                        onClick={() =>
                            act(
                                state?.feed === "connected"
                                    ? "/disconnect"
                                    : "/connect",
                            )
                        }
                    >
                        {state?.feed === "connected"
                            ? "Disconnect feed"
                            : "Connect free feed"}
                    </Button>
                </Toolbar>
            </AppBar>
            <Container maxWidth="xl" sx={{ py: 3 }}>
                <Stack
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                    mb={2}
                >
                    <Box>
                        <Typography variant="h4">
                            Your paper portfolio
                        </Typography>
                        <Typography color="text.secondary">
                            Positions, orders and performance · IST
                        </Typography>
                    </Box>
                    <Chip
                        label={
                            connected
                                ? "Local service connected"
                                : "Local service disconnected"
                        }
                        size="small"
                        variant="outlined"
                    />
                </Stack>
                <Box
                    sx={{
                        display: "grid",
                        gridTemplateColumns: {
                            xs: "1fr 1fr",
                            md: "repeat(4, 1fr)",
                        },
                        gap: 2,
                        mb: 3,
                    }}
                >
                    {[
                        ["Portfolio equity", "equity"],
                        ["Available funds", "available_cash"],
                        ["Open P&L", "unrealized_pnl"],
                        ["Realized P&L", "realized_pnl"],
                    ].map(([label, key]) => (
                        <Paper key={key} sx={{ p: 2 }}>
                            <Typography color="text.secondary" variant="body2">
                                {label}
                            </Typography>
                            <Typography
                                variant="h5"
                                mt={1}
                                sx={{
                                    color: key.includes("pnl")
                                        ? tint(state?.portfolio[key])
                                        : "text.primary",
                                }}
                            >
                                {money(state?.portfolio[key])}
                            </Typography>
                        </Paper>
                    ))}
                </Box>
                <Alert severity="info" sx={{ mb: 2 }}>
                    Prices: Yahoo Finance, best effort. Exchange timestamps and
                    freshness are shown for every stock. This is not a direct
                    NSE feed. All orders and money here are simulated.
                </Alert>
                {state?.session.phase !== "open" && (
                    <Alert severity="warning" sx={{ mb: 2 }}>
                        Market is {state?.session.phase ?? "unavailable"}. Paper
                        orders require an open covered session and fresh
                        regular-session prices.
                    </Alert>
                )}
                {!!state?.positions.length && state.feed !== "connected" && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                        Price feed is disconnected. Simulated stops and exits
                        cannot execute until fresh prices resume. Your saved
                        positions remain open.
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
                {notice && (
                    <Alert
                        severity="success"
                        onClose={() => setNotice("")}
                        sx={{ mb: 2 }}
                    >
                        {notice}
                    </Alert>
                )}
                <Tabs
                    value={tab}
                    onChange={(_, v) => setTab(v)}
                    variant="scrollable"
                    sx={{ mb: 2, borderBottom: "1px solid #253243" }}
                >
                    <Tab
                        label={`Positions (${state?.positions.length ?? 0})`}
                    />
                    <Tab label="Trading terminal" />
                    <Tab label={`Orders (${openOrders.length} pending)`} />
                    <Tab label="Closed trades" />
                    <Tab label="Executions" />
                </Tabs>
                {tab === 0 && (
                    <Paper sx={{ p: 2 }}>
                        <Typography variant="h6" mb={2}>
                            Active positions
                        </Typography>
                        {!state?.positions.length ? (
                            <Box textAlign="center" py={6}>
                                <Typography variant="h6">
                                    No open positions
                                </Typography>
                                <Typography color="text.secondary" mb={2}>
                                    Connect prices and place your first paper
                                    trade in the terminal.
                                </Typography>
                                <Button
                                    variant="outlined"
                                    onClick={() => setTab(1)}
                                >
                                    Open trading terminal
                                </Button>
                            </Box>
                        ) : (
                            <TableContainer>
                                <Table size="small">
                                    <TableHead>
                                        <TableRow>
                                            {[
                                                "Stock",
                                                "Product",
                                                "Qty",
                                                "Average",
                                                "Last price",
                                                "P&L",
                                                "Stop / target",
                                                "",
                                            ].map((h) => (
                                                <TableCell key={h}>
                                                    {h}
                                                </TableCell>
                                            ))}
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {state.positions.map((p) => (
                                            <TableRow
                                                key={`${p.symbol}-${p.product}`}
                                            >
                                                <TableCell>
                                                    {p.symbol}
                                                    {!p.quote_fresh && (
                                                        <Chip
                                                            label="Stale mark"
                                                            size="small"
                                                            color="warning"
                                                            sx={{ ml: 1 }}
                                                        />
                                                    )}
                                                </TableCell>
                                                <TableCell>
                                                    {p.product}
                                                </TableCell>
                                                <TableCell>
                                                    {p.quantity}
                                                </TableCell>
                                                <TableCell>
                                                    {money(p.average_price)}
                                                </TableCell>
                                                <TableCell>
                                                    {money(p.mark)}
                                                </TableCell>
                                                <TableCell
                                                    sx={{
                                                        color: tint(
                                                            p.unrealized_pnl,
                                                        ),
                                                    }}
                                                >
                                                    {money(p.unrealized_pnl)}
                                                </TableCell>
                                                <TableCell>
                                                    {money(p.stop_price)} /{" "}
                                                    {p.target_price
                                                        ? money(p.target_price)
                                                        : "—"}
                                                </TableCell>
                                                <TableCell>
                                                    <Button
                                                        size="small"
                                                        onClick={() =>
                                                            closePosition(p)
                                                        }
                                                    >
                                                        Close position
                                                    </Button>
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </TableContainer>
                        )}
                        <Typography variant="caption" color="text.secondary">
                            Total estimated charges:{" "}
                            {money(state?.portfolio.charges)} · Exposure:{" "}
                            {money(state?.portfolio.exposure)}
                        </Typography>
                    </Paper>
                )}
                {tab === 1 && (
                    <Box
                        sx={{
                            display: "grid",
                            gridTemplateColumns: { xs: "1fr", md: "1.2fr 1fr" },
                            gap: 2,
                        }}
                    >
                        <Paper sx={{ p: 2 }}>
                            <Stack
                                direction="row"
                                alignItems="center"
                                justifyContent="space-between"
                                mb={2}
                            >
                                <Typography variant="h6">
                                    Nifty 50 market watch
                                </Typography>
                                <Chip
                                    size="small"
                                    label={`${state?.stocks.filter((s) => s.fresh).length ?? 0} fresh / ${state?.stocks.length ?? 0}`}
                                />
                            </Stack>
                            <TextField
                                fullWidth
                                size="small"
                                label="Find a Nifty stock"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                sx={{ mb: 1 }}
                            />
                            {!state?.stocks.length && (
                                <Typography color="text.secondary" py={3}>
                                    Connect the free feed to load the official
                                    Nifty 50 list.
                                </Typography>
                            )}
                            <TableContainer sx={{ maxHeight: 590 }}>
                                <Table stickyHeader size="small">
                                    <TableHead>
                                        <TableRow>
                                            <TableCell>Stock</TableCell>
                                            <TableCell align="right">
                                                Price
                                            </TableCell>
                                            <TableCell align="right">
                                                Change
                                            </TableCell>
                                            <TableCell>
                                                Quote time / status
                                            </TableCell>
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {state?.stocks
                                            .filter((s) =>
                                                `${s.symbol} ${s.company_name}`
                                                    .toLowerCase()
                                                    .includes(
                                                        search.toLowerCase(),
                                                    ),
                                            )
                                            .map((s) => (
                                                <TableRow
                                                    hover
                                                    selected={
                                                        s.symbol === symbol
                                                    }
                                                    key={s.symbol}
                                                    onClick={() => {
                                                        setSymbol(s.symbol);
                                                        setReduceOnly(false);
                                                        setNotice("");
                                                    }}
                                                    sx={{ cursor: "pointer" }}
                                                >
                                                    <TableCell>
                                                        <Typography
                                                            fontWeight={600}
                                                            variant="body2"
                                                        >
                                                            {s.symbol}
                                                        </Typography>
                                                        <Typography
                                                            variant="caption"
                                                            color="text.secondary"
                                                        >
                                                            {s.company_name}
                                                        </Typography>
                                                    </TableCell>
                                                    <TableCell align="right">
                                                        {s.quote
                                                            ? money(
                                                                  s.quote.price,
                                                              )
                                                            : "—"}
                                                    </TableCell>
                                                    <TableCell
                                                        align="right"
                                                        sx={{
                                                            color: tint(
                                                                s.quote
                                                                    ?.change_percent,
                                                            ),
                                                        }}
                                                    >
                                                        {s.quote
                                                            ?.change_percent ==
                                                        null
                                                            ? "—"
                                                            : `${s.quote.change_percent.toFixed(2)}%`}
                                                    </TableCell>
                                                    <TableCell>
                                                        <Typography variant="caption">
                                                            {s.quote
                                                                ? when(
                                                                      s.quote
                                                                          .at,
                                                                  )
                                                                : "Waiting for quote"}
                                                        </Typography>
                                                        <Typography
                                                            variant="caption"
                                                            display="block"
                                                            color={
                                                                s.fresh
                                                                    ? "success.main"
                                                                    : "warning.main"
                                                            }
                                                        >
                                                            {s.fresh
                                                                ? "Fresh"
                                                                : "Stale / unavailable"}
                                                        </Typography>
                                                    </TableCell>
                                                </TableRow>
                                            ))}
                                    </TableBody>
                                </Table>
                            </TableContainer>
                        </Paper>
                        <Paper
                            component="form"
                            sx={{ p: 3, alignSelf: "start" }}
                            onSubmit={(event) => {
                                event.preventDefault();
                                act("/orders", {
                                    symbol,
                                    side,
                                    product,
                                    order_type: kind,
                                    quantity: Number(quantity),
                                    stop_price: isExit ? null : stop || null,
                                    target_price: isExit
                                        ? null
                                        : target || null,
                                    limit_price: limit || null,
                                    trigger_price: trigger || null,
                                    trailing_distance: isExit
                                        ? null
                                        : trailing || null,
                                    reduce_only: isExit,
                                });
                            }}
                        >
                            <Stack
                                direction="row"
                                justifyContent="space-between"
                                alignItems="center"
                            >
                                <Box>
                                    <Typography variant="h5">
                                        {symbol}
                                    </Typography>
                                    <Typography color="text.secondary">
                                        {stock?.company_name ??
                                            "Choose a Nifty 50 stock"}
                                    </Typography>
                                </Box>
                                <Typography variant="h5">
                                    {quote ? money(quote.price) : "—"}
                                </Typography>
                            </Stack>
                            <Typography
                                variant="caption"
                                color="text.secondary"
                                display="block"
                                mt={1}
                            >
                                {quote
                                    ? `${when(quote.at)} IST · ${stock?.fresh ? "Fresh quote" : "Stale quote"}`
                                    : "Waiting for streaming prices"}
                            </Typography>
                            <Stack direction="row" gap={1} my={2}>
                                <Button
                                    variant={
                                        side === "BUY"
                                            ? "contained"
                                            : "outlined"
                                    }
                                    onClick={() => {
                                        setSide("BUY");
                                        setReduceOnly(false);
                                    }}
                                >
                                    Buy
                                </Button>
                                <Button
                                    color="error"
                                    variant={
                                        side === "SELL"
                                            ? "contained"
                                            : "outlined"
                                    }
                                    onClick={() => {
                                        setSide("SELL");
                                        setReduceOnly(false);
                                    }}
                                >
                                    Sell
                                </Button>
                                <Button
                                    disabled={busy || !stock}
                                    onClick={() =>
                                        act(
                                            `/prepare/${encodeURIComponent(symbol)}`,
                                        )
                                    }
                                >
                                    {stock?.prepared
                                        ? "Refresh stock data"
                                        : "Load stock data"}
                                </Button>
                            </Stack>
                            {stock?.error && (
                                <Alert severity="warning" sx={{ mb: 2 }}>
                                    {stock.error}
                                </Alert>
                            )}
                            {isExit && (
                                <Alert severity="info" sx={{ mb: 2 }}>
                                    This order reduces an existing {product}{" "}
                                    position.
                                </Alert>
                            )}
                            <Box
                                sx={{
                                    display: "grid",
                                    gridTemplateColumns: "1fr 1fr",
                                    gap: 2,
                                }}
                            >
                                <TextField
                                    select
                                    label="Product"
                                    value={product}
                                    onChange={(e) => {
                                        setProduct(e.target.value);
                                        setReduceOnly(false);
                                    }}
                                >
                                    <MenuItem value="CNC">
                                        Delivery (CNC)
                                    </MenuItem>
                                    <MenuItem value="MIS">
                                        Intraday (MIS)
                                    </MenuItem>
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
                                        "SL-M",
                                        "SL",
                                        "BRACKET",
                                    ].map((t) => (
                                        <MenuItem key={t} value={t}>
                                            {t}
                                        </MenuItem>
                                    ))}
                                </TextField>
                                <TextField
                                    required
                                    label="Quantity"
                                    type="number"
                                    slotProps={{
                                        htmlInput: {
                                            min: 1,
                                            max: 1000000000,
                                            step: 1,
                                        },
                                    }}
                                    value={quantity}
                                    onChange={(e) =>
                                        setQuantity(e.target.value)
                                    }
                                />
                                {["LIMIT", "SL"].includes(kind) && (
                                    <TextField
                                        required
                                        label="Limit price"
                                        type="number"
                                        slotProps={{
                                            htmlInput: {
                                                min: 0.01,
                                                step: "any",
                                            },
                                        }}
                                        value={limit}
                                        onChange={(e) =>
                                            setLimit(e.target.value)
                                        }
                                    />
                                )}
                                {["SL", "SL-M"].includes(kind) && (
                                    <TextField
                                        required
                                        label="Trigger price"
                                        type="number"
                                        slotProps={{
                                            htmlInput: {
                                                min: 0.01,
                                                step: "any",
                                            },
                                        }}
                                        value={trigger}
                                        onChange={(e) =>
                                            setTrigger(e.target.value)
                                        }
                                    />
                                )}
                                {!isExit && (
                                    <>
                                        <TextField
                                            required
                                            label="Protective stop"
                                            type="number"
                                            slotProps={{
                                                htmlInput: {
                                                    min: 0.01,
                                                    step: "any",
                                                },
                                            }}
                                            value={stop}
                                            onChange={(e) =>
                                                setStop(e.target.value)
                                            }
                                        />
                                        <TextField
                                            required={kind === "BRACKET"}
                                            label="Target (optional)"
                                            type="number"
                                            slotProps={{
                                                htmlInput: {
                                                    min: 0.01,
                                                    step: "any",
                                                },
                                            }}
                                            value={target}
                                            onChange={(e) =>
                                                setTarget(e.target.value)
                                            }
                                        />
                                        <TextField
                                            label="Trailing distance (optional)"
                                            type="number"
                                            slotProps={{
                                                htmlInput: {
                                                    min: 0.01,
                                                    step: "any",
                                                },
                                            }}
                                            value={trailing}
                                            onChange={(e) =>
                                                setTrailing(e.target.value)
                                            }
                                        />
                                    </>
                                )}
                            </Box>
                            <Typography
                                variant="body2"
                                color="text.secondary"
                                my={2}
                            >
                                Estimated value:{" "}
                                {quote
                                    ? money(
                                          Number(quantity) *
                                              Number(quote.price),
                                      )
                                    : "—"}
                                . Actual simulated fills include slippage and
                                estimated charges. Orders wait for a later fresh
                                quote with observed volume.
                            </Typography>
                            {!ready && (
                                <Alert severity="warning" sx={{ mb: 2 }}>
                                    To submit: connect the feed, load stock
                                    data, and wait for fresh regular-session
                                    prices while the market is open.
                                </Alert>
                            )}
                            <Button
                                type="submit"
                                fullWidth
                                variant="contained"
                                color={side === "BUY" ? "primary" : "error"}
                                disabled={busy || !ready}
                            >
                                {busy
                                    ? "Working…"
                                    : `${side === "BUY" ? "Buy" : "Sell"} · paper order`}
                            </Button>
                            <Typography
                                variant="caption"
                                color="text.secondary"
                                display="block"
                                mt={2}
                            >
                                Entries require protective stops. CNC short
                                entries are blocked; MIS supports paper
                                shorting. Funds and risk are checked again at
                                fill time.
                            </Typography>
                        </Paper>
                    </Box>
                )}
                {tab === 2 && (
                    <Paper sx={{ p: 2 }}>
                        <Typography variant="h6" mb={2}>
                            Orders · {openOrders.length} pending
                        </Typography>
                        <TableContainer>
                            <Table size="small">
                                <TableHead>
                                    <TableRow>
                                        {[
                                            "Time",
                                            "Stock",
                                            "Side",
                                            "Product",
                                            "Type",
                                            "Qty / remaining",
                                            "Status",
                                            "",
                                        ].map((h) => (
                                            <TableCell key={h}>{h}</TableCell>
                                        ))}
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {[...(state?.orders ?? [])]
                                        .reverse()
                                        .map((o) => (
                                            <TableRow key={o.order.id}>
                                                <TableCell>
                                                    {when(o.order.signal_at)}
                                                </TableCell>
                                                <TableCell>
                                                    {o.order.symbol}
                                                </TableCell>
                                                <TableCell>
                                                    {o.order.side}
                                                    {o.order.reduce_only
                                                        ? " · exit"
                                                        : ""}
                                                </TableCell>
                                                <TableCell>
                                                    {o.order.product}
                                                </TableCell>
                                                <TableCell>
                                                    {o.order.order_type}
                                                </TableCell>
                                                <TableCell>
                                                    {o.order.quantity} /{" "}
                                                    {o.remaining}
                                                </TableCell>
                                                <TableCell>
                                                    <Chip
                                                        size="small"
                                                        label={o.status}
                                                    />
                                                    {o.reasons?.length && (
                                                        <Typography
                                                            variant="caption"
                                                            display="block"
                                                            color="error.main"
                                                        >
                                                            {o.reasons.join(
                                                                ", ",
                                                            )}
                                                        </Typography>
                                                    )}
                                                </TableCell>
                                                <TableCell>
                                                    {[
                                                        "OPEN",
                                                        "PARTIAL",
                                                    ].includes(o.status) && (
                                                        <Button
                                                            disabled={busy}
                                                            onClick={() =>
                                                                act(
                                                                    `/orders/${o.order.id}`,
                                                                    undefined,
                                                                    "DELETE",
                                                                )
                                                            }
                                                        >
                                                            Cancel
                                                        </Button>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                </TableBody>
                            </Table>
                        </TableContainer>
                        {!state?.orders.length && (
                            <Typography color="text.secondary" py={4}>
                                No paper orders yet.
                            </Typography>
                        )}
                    </Paper>
                )}
                {tab === 3 && (
                    <Paper sx={{ p: 2 }}>
                        <Typography variant="h6" mb={2}>
                            Closed trades
                        </Typography>
                        <TableContainer>
                            <Table size="small">
                                <TableHead>
                                    <TableRow>
                                        {[
                                            "Stock",
                                            "Qty",
                                            "Opened",
                                            "Closed",
                                            "Net P&L",
                                            "Charges",
                                            "Reason",
                                        ].map((h) => (
                                            <TableCell key={h}>{h}</TableCell>
                                        ))}
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {[...(state?.closed_trades ?? [])]
                                        .reverse()
                                        .map((t, i) => (
                                            <TableRow key={i}>
                                                <TableCell>
                                                    {t.symbol}
                                                </TableCell>
                                                <TableCell>
                                                    {t.quantity}
                                                </TableCell>
                                                <TableCell>
                                                    {when(t.opened_at)}
                                                </TableCell>
                                                <TableCell>
                                                    {when(t.closed_at)}
                                                </TableCell>
                                                <TableCell
                                                    sx={{ color: tint(t.pnl) }}
                                                >
                                                    {money(t.pnl)}
                                                </TableCell>
                                                <TableCell>
                                                    {money(t.charges)}
                                                </TableCell>
                                                <TableCell>
                                                    {t.reason}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                </TableBody>
                            </Table>
                        </TableContainer>
                        {!state?.closed_trades.length && (
                            <Typography color="text.secondary" py={4}>
                                Closed positions and partial exits will appear
                                here.
                            </Typography>
                        )}
                    </Paper>
                )}
                {tab === 4 && (
                    <Paper sx={{ p: 2 }}>
                        <Typography variant="h6" mb={2}>
                            Paper executions
                        </Typography>
                        {[...(state?.fills ?? [])].reverse().map((f, i) => (
                            <Stack
                                key={i}
                                direction="row"
                                justifyContent="space-between"
                                py={1}
                                borderBottom="1px solid #253243"
                            >
                                <Typography>
                                    {f.symbol} · {f.side} {f.quantity} @{" "}
                                    {money(f.price)}
                                </Typography>
                                <Typography color="text.secondary">
                                    {when(f.at)} · {f.reason}
                                </Typography>
                            </Stack>
                        ))}
                        {!state?.fills.length && (
                            <Typography color="text.secondary" py={4}>
                                No fills yet. Accepted orders appear here once
                                simulated execution occurs.
                            </Typography>
                        )}
                    </Paper>
                )}
                <Typography
                    variant="caption"
                    display="block"
                    color="text.secondary"
                    mt={3}
                >
                    Personal paper simulation · Saved locally · No broker
                    credentials or real orders · Keep the app and feed running
                    for simulated stops and exits
                </Typography>
            </Container>
        </>
    );
}
