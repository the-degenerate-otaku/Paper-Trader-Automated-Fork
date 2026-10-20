import { useEffect, useState } from "react";
import {
    Alert,
    Autocomplete,
    Box,
    Button,
    Chip,
    MenuItem,
    Paper,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import CandleChart from "./CandleChart";
import type { Bar, Indicator } from "./CandleChart";

type Stock = {
    symbol: string;
    name: string;
    sector: string | null;
    instrument_type: string;
};
type Dataset = {
    symbol: string;
    timeframe: string;
    version: string;
    fetched_at: string;
    candles: Bar[];
    indicators: Indicator[];
    warnings: string[];
    health: {
        status: string;
        latest_close: string | null;
        age_seconds: number | null;
        gaps: string[];
    };
    feature: { regime: string; values: Record<string, unknown> } | null;
};
const fills: [] = [];
const atIst = (value: string) =>
    new Date(value).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        hour12: false,
    });

async function request(path: string, body?: unknown) {
    const response = await fetch(`/api/market/${path}`, {
        method: body === undefined ? "GET" : "POST",
        headers: { "Content-Type": "application/json", "X-Paper-Request": "1" },
        body: body === undefined ? undefined : JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok)
        throw new Error(
            typeof result.detail === "string"
                ? result.detail
                : "Invalid market request",
        );
    return result;
}

export default function MarketPanel({
    initialSymbol,
    onReplay,
}: {
    initialSymbol: string;
    onReplay: (
        symbol: string,
        timeframe: string,
        version: string,
    ) => Promise<void>;
}) {
    const [stocks, setStocks] = useState<Stock[]>([]);
    const [symbol, setSymbol] = useState(initialSymbol);
    const [timeframe, setTimeframe] = useState("5m");
    const [days, setDays] = useState(5);
    const [data, setData] = useState<Dataset | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");
    useEffect(() => {
        let active = true;
        request("symbols")
            .then((rows) => {
                if (active) setStocks(rows);
            })
            .catch(() => {
                if (active)
                    setError(
                        "Stock catalog unavailable. You can enter an NSE symbol directly.",
                    );
            });
        return () => {
            active = false;
        };
    }, []);
    async function load(refresh: boolean) {
        setBusy(true);
        setError("");
        setData(null);
        try {
            setData(
                await request("chart", {
                    symbol: symbol.trim().toUpperCase(),
                    timeframe,
                    days,
                    refresh,
                }),
            );
        } catch (e) {
            setError(
                e instanceof Error ? e.message : "Market history unavailable",
            );
        } finally {
            setBusy(false);
        }
    }
    async function universe() {
        setBusy(true);
        setError("");
        try {
            const result = await request("universe", {});
            setStocks(await request("symbols"));
            setNotice(
                Object.entries(result)
                    .map(([index, value]) => {
                        const item = value as {
                            count?: number;
                            error?: string;
                            stale?: boolean;
                        };
                        return `${index}: ${item.error ?? `${item.count} observed members${item.stale ? " (stale)" : ""}`}`;
                    })
                    .join(" · "),
            );
        } catch (e) {
            setError(
                e instanceof Error ? e.message : "Membership refresh failed",
            );
        } finally {
            setBusy(false);
        }
    }
    const cleanSymbol = symbol.trim().toUpperCase();
    const valid =
        /^[A-Z0-9][A-Z0-9&_.-]{0,39}$/.test(cleanSymbol) &&
        !cleanSymbol.endsWith(".NS") &&
        cleanSymbol !== "DEMO";
    const tvSymbol =
        cleanSymbol === "NIFTY50"
            ? "NIFTY"
            : cleanSymbol === "NIFTYBANK"
              ? "BANKNIFTY"
              : cleanSymbol;
    return (
        <Paper sx={{ p: { xs: 2, md: 3 } }}>
            <Stack direction="row" gap={1} alignItems="center" mb={2}>
                <Typography variant="h5" sx={{ flex: 1 }}>
                    Stocks & indicators
                </Typography>
                <Chip
                    label="Historical data · paper only"
                    color="info"
                    variant="outlined"
                />
            </Stack>
            <Stack direction="row" gap={2} flexWrap="wrap" alignItems="center">
                <Autocomplete
                    freeSolo
                    disabled={busy}
                    options={stocks.map((s) => s.symbol)}
                    inputValue={symbol}
                    onInputChange={(_, value) => setSymbol(value.toUpperCase())}
                    renderOption={(props, option) => {
                        const stock = stocks.find((s) => s.symbol === option);
                        return (
                            <li {...props} key={option}>
                                <Box>
                                    <Typography>{option}</Typography>
                                    <Typography
                                        variant="caption"
                                        color="text.secondary"
                                    >
                                        {stock?.name} ·{" "}
                                        {stock?.sector ??
                                            stock?.instrument_type}
                                    </Typography>
                                </Box>
                            </li>
                        );
                    }}
                    sx={{ minWidth: 235, flex: 1 }}
                    renderInput={(params) => (
                        <TextField
                            {...params}
                            label="NSE stock / index"
                            helperText="Search catalog or enter an NSE symbol"
                        />
                    )}
                />
                <TextField
                    select
                    disabled={busy}
                    label="Timeframe"
                    value={timeframe}
                    sx={{ minWidth: 125 }}
                    onChange={(e) => {
                        setTimeframe(e.target.value);
                        setDays(5);
                    }}
                >
                    {[
                        ["1m", "1 minute"],
                        ["5m", "5 minutes"],
                        ["15m", "15 minutes"],
                        ["1h", "1 hour"],
                        ["1d", "1 day"],
                    ].map(([v, label]) => (
                        <MenuItem key={v} value={v}>
                            {label}
                        </MenuItem>
                    ))}
                </TextField>
                <TextField
                    select
                    disabled={busy}
                    label="History"
                    value={days}
                    sx={{ minWidth: 125 }}
                    onChange={(e) => setDays(Number(e.target.value))}
                >
                    {(timeframe === "1m"
                        ? [5]
                        : timeframe === "1d"
                          ? [5, 30, 90, 365]
                          : [5, 30]
                    ).map((d) => (
                        <MenuItem key={d} value={d}>
                            {d} days
                        </MenuItem>
                    ))}
                </TextField>
                <Button
                    variant="contained"
                    disabled={busy || !valid}
                    onClick={() => load(false)}
                >
                    {busy ? "Loading…" : "Load chart"}
                </Button>
                <Button disabled={busy || !valid} onClick={() => load(true)}>
                    Refresh history
                </Button>
            </Stack>
            <Stack direction="row" gap={2} flexWrap="wrap" my={2}>
                <Button disabled={busy} onClick={universe}>
                    Refresh Nifty / Bank Nifty stocks
                </Button>
                <Button
                    component="a"
                    href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(`NSE:${tvSymbol}`)}`}
                    target="_blank"
                    rel="noreferrer"
                    disabled={!valid}
                >
                    Open TradingView chart ↗
                </Button>
            </Stack>
            <Typography color="text.secondary" variant="body2" mb={2}>
                Charts use closed candles from Yahoo Finance or a saved history
                snapshot. Quotes may be delayed or stale. Load chart reuses
                saved history when available. Refresh downloads a new snapshot;
                this view does not feed prices into an active replay.
            </Typography>
            {error && (
                <Alert severity="error" sx={{ mb: 2 }}>
                    {error}
                </Alert>
            )}
            {notice && (
                <Alert severity="info" sx={{ mb: 2 }}>
                    {notice}
                </Alert>
            )}
            {busy && (
                <Alert severity="info">
                    Loading market data. Your paper execution engine is
                    unchanged.
                </Alert>
            )}
            {!data && !busy && (
                <Box sx={{ py: 7, textAlign: "center" }}>
                    <Typography variant="h6">
                        Pick a stock. Explore its candles and indicators.
                    </Typography>
                    <Typography color="text.secondary">
                        Load a chart to start. Refresh the catalog for observed
                        Nifty 50 and Bank Nifty members.
                    </Typography>
                </Box>
            )}
            {data && (
                <>
                    <Stack
                        direction="row"
                        alignItems="center"
                        flexWrap="wrap"
                        gap={1}
                    >
                        <Typography variant="h6" sx={{ flex: 1 }}>
                            {data.symbol} · {data.timeframe} ·{" "}
                            {data.candles.length} closed candles
                        </Typography>
                        <Chip
                            label={data.feature?.regime ?? "WARMUP"}
                            size="small"
                        />
                        <Chip
                            label={`Data: ${data.health.status}`}
                            size="small"
                            color={
                                data.health.status === "healthy"
                                    ? "success"
                                    : "warning"
                            }
                        />
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                        Last candle:{" "}
                        {data.health.latest_close
                            ? atIst(data.health.latest_close)
                            : "Unavailable"}{" "}
                        IST · Downloaded {atIst(data.fetched_at)} IST
                    </Typography>
                    <CandleChart
                        bars={data.candles}
                        indicators={data.indicators}
                        fills={fills}
                    />
                    <Stack direction="row" gap={1} flexWrap="wrap" my={2}>
                        {Object.entries(data.feature?.values ?? {})
                            .filter(
                                ([key, value]) =>
                                    [
                                        "ltp",
                                        "rsi",
                                        "atr",
                                        "adx",
                                        "volume_ratio",
                                        "vwap",
                                        "macd",
                                    ].includes(key) &&
                                    typeof value === "number",
                            )
                            .map(([key, value]) => (
                                <Chip
                                    key={key}
                                    variant="outlined"
                                    label={`${key.toUpperCase()}: ${Number(value).toFixed(2)}`}
                                />
                            ))}
                    </Stack>
                    <Alert severity="info">
                        History may be revised or split-adjusted by the
                        provider. Indicators need warmup; missing values are not
                        filled with invented numbers. Display is limited to the
                        last 300 candles.{" "}
                        {data.warnings.includes(
                            "CHART_CALCULATION_WINDOW_LIMITED_TO_1500_BARS",
                        )
                            ? "Indicator calculations use a bounded 1,500-bar window."
                            : ""}
                    </Alert>
                    <Stack
                        direction="row"
                        gap={2}
                        alignItems="center"
                        flexWrap="wrap"
                        mt={2}
                    >
                        <Button
                            variant="outlined"
                            disabled={busy}
                            onClick={async () => {
                                setBusy(true);
                                try {
                                    await onReplay(
                                        data.symbol,
                                        data.timeframe,
                                        data.version,
                                    );
                                } catch (e) {
                                    setError(
                                        e instanceof Error
                                            ? e.message
                                            : "Replay could not start",
                                    );
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Replay this history
                        </Button>
                        <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{ overflowWrap: "anywhere" }}
                        >
                            Dataset {data.version.slice(0, 12)} · No automatic
                            trades
                        </Typography>
                    </Stack>
                </>
            )}
            <Typography
                variant="caption"
                display="block"
                color="text.secondary"
                mt={2}
            >
                TradingView opens separately. Chart availability and quote
                delays are controlled by TradingView. Its displayed prices and
                indicators are not used by this paper account.
            </Typography>
        </Paper>
    );
}
