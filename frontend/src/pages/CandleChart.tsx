import { useEffect, useRef, useState } from "react";
import {
    Box,
    ToggleButtonGroup,
    ToggleButton,
    Typography,
} from "@mui/material";
import {
    CandlestickSeries,
    LineSeries,
    HistogramSeries,
    ColorType,
    createChart,
    createSeriesMarkers,
} from "lightweight-charts";
import type { Time, UTCTimestamp } from "lightweight-charts";
export type Indicator = {
    at: string;
    symbol: string;
    values: Record<string, unknown>;
};
export type Fill = {
    at: string;
    symbol: string;
    side: string;
    price: string;
    reason: string;
};
export type Bar = {
    symbol: string;
    opened_at: string;
    closed_at: string;
    open: string;
    high: string;
    low: string;
    close: string;
    volume: number;
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

export default function CandleChart({
    bars,
    indicators,
    fills,
}: {
    bars: Bar[];
    indicators: Indicator[];
    fills: Fill[];
}) {
    const [enabled, setEnabled] = useState([
        "ema_9",
        "ema_20",
        "vwap",
        "bollinger",
        "rsi",
        "macd",
        "volume",
    ]);
    const options = [
        ["ema_9", "EMA 9"],
        ["ema_20", "EMA 20"],
        ["ema_50", "EMA 50"],
        ["ema_200", "EMA 200"],
        ["sma", "SMA"],
        ["vwap", "VWAP"],
        ["bollinger", "Bollinger"],
        ["supertrend", "Supertrend"],
        ["volume", "Volume"],
        ["rsi", "RSI"],
        ["macd", "MACD"],
        ["atr", "ATR"],
        ["adx", "ADX"],
        ["obv", "OBV"],
    ];
    const node = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!node.current || !bars.length) return;
        const chart = createChart(node.current, {
            autoSize: true,
            height: 560,
            layout: {
                background: { type: ColorType.Solid, color: "#131c27" },
                textColor: "#8ea1b5",
            },
            grid: {
                vertLines: { color: "#202c3b" },
                horzLines: { color: "#202c3b" },
            },
            timeScale: {
                timeVisible: true,
                tickMarkFormatter: (value: Time) =>
                    new Date(Number(value) * 1000).toLocaleTimeString("en-IN", {
                        timeZone: "Asia/Kolkata",
                        hour: "2-digit",
                        minute: "2-digit",
                        hour12: false,
                    }),
            },
            localization: {
                timeFormatter: (value: Time) =>
                    ist(new Date(Number(value) * 1000).toISOString()),
            },
        });
        const series = chart.addSeries(CandlestickSeries, {
            upColor: "#77dfb5",
            downColor: "#fa8c99",
            borderVisible: false,
            wickUpColor: "#77dfb5",
            wickDownColor: "#fa8c99",
            priceFormat: {
                type: "custom",
                formatter: (value: number) => money(value),
            },
        });
        series.setData(
            bars.map((b) => ({
                time: (Date.parse(b.opened_at) / 1000) as UTCTimestamp,
                open: +b.open,
                high: +b.high,
                low: +b.low,
                close: +b.close,
            })),
        );
        const closeToOpen = new Map(
            bars.map((b) => [
                Date.parse(b.closed_at),
                Date.parse(b.opened_at) / 1000,
            ]),
        );
        const paneMap = new Map<string, number>();
        for (const key of ["volume", "rsi", "macd", "atr", "adx", "obv"]) {
            if (enabled.includes(key)) paneMap.set(key, paneMap.size + 1);
        }
        if (enabled.includes("volume")) {
            const volume = chart.addSeries(
                HistogramSeries,
                {
                    title: "Volume",
                    priceFormat: { type: "volume" },
                    priceLineVisible: false,
                    lastValueVisible: false,
                },
                paneMap.get("volume"),
            );
            volume.setData(
                bars.map((b) => ({
                    time: (Date.parse(b.opened_at) / 1000) as UTCTimestamp,
                    value: b.volume,
                    color: +b.close >= +b.open ? "#77dfb577" : "#fa8c9977",
                })),
            );
        }
        for (const [key, color, group] of [
            ["ema_9", "#a5b5fb", "ema_9"],
            ["ema_20", "#fabf77", "ema_20"],
            ["ema_50", "#59c5ef", "ema_50"],
            ["ema_200", "#f792d6", "ema_200"],
            ["sma", "#d8e185", "sma"],
            ["supertrend", "#88e48d", "supertrend"],
            ["vwap", "#77dfb5", "vwap"],
            ["bb_high", "#607c9a", "bollinger"],
            ["bb_mid", "#607c9a", "bollinger"],
            ["bb_low", "#607c9a", "bollinger"],
            ["rsi", "#b69af7", "rsi"],
            ["macd", "#77dfb5", "macd"],
            ["macd_signal", "#fabf77", "macd"],
            ["atr", "#59c5ef", "atr"],
            ["adx", "#fabf77", "adx"],
            ["obv", "#a5b5fb", "obv"],
        ] as const) {
            if (!enabled.includes(group)) continue;
            const pane = paneMap.get(group) ?? 0;
            const line = chart.addSeries(
                LineSeries,
                {
                    color,
                    lineWidth: 1,
                    title: key,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    priceFormat: {
                        type: "custom",
                        formatter: (value: number) =>
                            pane === 0 ? money(value) : value.toFixed(2),
                    },
                },
                pane,
            );
            line.setData(
                indicators
                    .filter(
                        (i) =>
                            typeof i.values[key] === "number" &&
                            closeToOpen.has(Date.parse(i.at)),
                    )
                    .map((i) => ({
                        time: closeToOpen.get(
                            Date.parse(i.at),
                        )! as UTCTimestamp,
                        value: Number(i.values[key]),
                    })),
            );
        }
        if (enabled.includes("macd")) {
            const histogram = chart.addSeries(
                HistogramSeries,
                {
                    title: "MACD histogram",
                    priceLineVisible: false,
                    lastValueVisible: false,
                },
                paneMap.get("macd"),
            );
            histogram.setData(
                indicators
                    .filter(
                        (i) =>
                            typeof i.values.macd_hist === "number" &&
                            closeToOpen.has(Date.parse(i.at)),
                    )
                    .map((i) => ({
                        time: closeToOpen.get(
                            Date.parse(i.at),
                        )! as UTCTimestamp,
                        value: Number(i.values.macd_hist),
                        color:
                            Number(i.values.macd_hist) >= 0
                                ? "#77dfb555"
                                : "#fa8c9955",
                    })),
            );
        }
        createSeriesMarkers(
            series,
            fills
                .filter((f) =>
                    bars.some(
                        (b) => Date.parse(b.opened_at) === Date.parse(f.at),
                    ),
                )
                .map((f) => ({
                    time: (Date.parse(f.at) / 1000) as UTCTimestamp,
                    position:
                        f.side === "BUY"
                            ? ("belowBar" as const)
                            : ("aboveBar" as const),
                    color: f.side === "BUY" ? "#77dfb5" : "#fa8c99",
                    shape:
                        f.side === "BUY"
                            ? ("arrowUp" as const)
                            : ("arrowDown" as const),
                    text: `${f.side} ${f.price} ${f.reason}`,
                })),
        );
        chart.timeScale().fitContent();
        return () => chart.remove();
    }, [bars, indicators, fills, enabled]);
    return (
        <>
            <ToggleButtonGroup
                value={enabled}
                onChange={(_, values: string[]) => setEnabled(values)}
                size="small"
                aria-label="Chart indicators"
                sx={{ flexWrap: "wrap", my: 2 }}
            >
                {options.map(([value, label]) => (
                    <ToggleButton key={value} value={value}>
                        {label}
                    </ToggleButton>
                ))}
            </ToggleButtonGroup>
            {!bars.length && (
                <Typography color="text.secondary" sx={{ py: 4 }}>
                    No closed candles to display. Load market history or step
                    the replay.
                </Typography>
            )}
            <Box ref={node} sx={{ height: bars.length ? 560 : 0 }} />
        </>
    );
}
