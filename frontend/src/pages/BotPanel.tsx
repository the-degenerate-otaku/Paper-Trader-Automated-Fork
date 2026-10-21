import { apiFetch } from "../connection";
import { useEffect, useState } from "react";
import {
    Alert,
    Box,
    Button,
    Chip,
    MenuItem,
    Paper,
    Stack,
    TextField,
    Typography,
} from "@mui/material";

type Bot = {
    id: string;
    name: string;
    mode: string;
    enabled: boolean;
    bankroll_inr: string;
    equity: string;
    exposure: string;
    charges: string;
    positions: number;
    cursor: number;
    total: number;
    last_decision: null | { direction: string; reason: string };
};
type Arena = { running: boolean; bots: Bot[]; feed_error: string | null };
const money = (value: string) =>
    Number(value).toLocaleString("en-IN", {
        style: "currency",
        currency: "INR",
    });

export default function BotPanel() {
    const [arena, setArena] = useState<Arena>({
        running: false,
        bots: [],
        feed_error: null,
    });
    const [error, setError] = useState("");
    async function request(path = "", payload?: unknown) {
        const response = await apiFetch(`/api/arena${path}`, {
            method: payload === undefined ? "GET" : "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Paper-Request": "1",
            },
            body: payload === undefined ? undefined : JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok)
            throw new Error(
                typeof result.detail === "string"
                    ? result.detail
                    : "Arena operation failed",
            );
        if (result.bots) setArena(result);
    }
    useEffect(() => {
        const update = () => request().catch((e) => setError(e.message));
        update();
        const timer = setInterval(update, 1000);
        return () => clearInterval(timer);
    }, []);
    async function act(path: string, payload: unknown = {}) {
        try {
            setError("");
            await request(path, payload);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Operation failed");
        }
    }
    return (
        <Stack gap={2}>
            <Alert severity="info">
                Bots have separate configured bankrolls and ledgers. All entry
                gates start disabled. Stop entries cancels pending entries while
                the running scheduler continues protective stops. Pausing the
                scheduler pauses candle processing.
            </Alert>
            {error && <Alert severity="error">{error}</Alert>}
            {arena.feed_error && (
                <Alert severity="warning">
                    {arena.feed_error} · New entries are held until the feed
                    recovers.
                </Alert>
            )}
            <Stack direction="row" gap={1}>
                <Button
                    variant="contained"
                    disabled={arena.running}
                    onClick={() => act("/create")}
                >
                    Create arena from replay
                </Button>
                <Button
                    variant="outlined"
                    disabled={arena.running || !arena.bots.length}
                    onClick={() => act("/play")}
                >
                    Start scheduler
                </Button>
                <Button disabled={!arena.running} onClick={() => act("/pause")}>
                    Pause scheduler
                </Button>
                <Chip label={arena.running ? "Running" : "Paused"} />
            </Stack>
            <Box
                sx={{
                    display: "grid",
                    gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
                    gap: 2,
                }}
            >
                {arena.bots.map((bot) => (
                    <Paper key={bot.id} sx={{ p: 3 }}>
                        <Typography variant="h6">{bot.name}</Typography>
                        <Typography color="text.secondary" my={1}>
                            Bankroll {money(bot.bankroll_inr)} · {bot.cursor}/
                            {bot.total} closed bars
                        </Typography>
                        <Typography variant="h5">
                            {money(bot.equity)}
                        </Typography>
                        <Typography variant="body2" my={2}>
                            Exposure {money(bot.exposure)} · Charges{" "}
                            {money(bot.charges)} · {bot.positions} positions
                        </Typography>
                        <Stack direction="row" gap={2}>
                            <TextField
                                select
                                size="small"
                                label="Mode"
                                value={bot.mode}
                                onChange={(e) =>
                                    act(`/bots/${bot.id}`, {
                                        mode: e.target.value,
                                        enabled: bot.enabled,
                                    })
                                }
                            >
                                {[
                                    "manual",
                                    "copilot",
                                    "autopilot",
                                    "shadow",
                                ].map((mode) => (
                                    <MenuItem value={mode} key={mode}>
                                        {mode}
                                    </MenuItem>
                                ))}
                            </TextField>
                            <Button
                                variant="outlined"
                                onClick={() =>
                                    act(`/bots/${bot.id}`, {
                                        mode: bot.mode,
                                        enabled: !bot.enabled,
                                    })
                                }
                            >
                                {bot.enabled
                                    ? "Stop entries"
                                    : "Enable entries"}
                            </Button>
                        </Stack>
                        <Typography color="text.secondary" mt={2}>
                            {bot.last_decision
                                ? `${bot.last_decision.direction} · ${bot.last_decision.reason}`
                                : "Waiting for a decision"}
                        </Typography>
                    </Paper>
                ))}
            </Box>
            <Typography color="text.secondary">
                Manual mode holds automated entries. Copilot and shadow modes
                record model judgments without automatic fills. Autopilot still
                passes every order through deterministic risk vetoes. Live
                refresh is disabled by default; configure eligible symbols and
                immutable market data before enabling it.
            </Typography>
        </Stack>
    );
}
