import { useEffect, useState } from "react";
import {
    Alert,
    Box,
    Button,
    MenuItem,
    Paper,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import {
    CartesianGrid,
    Legend,
    ReferenceLine,
    ResponsiveContainer,
    Scatter,
    ScatterChart,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

type Run = {
    id: string;
    checkpoint_id: string;
    started_at: string;
    ended_at: string | null;
};
type Point = {
    count: number;
    mean_probability: number | null;
    observed_accuracy: number | null;
};
type Result = Record<string, unknown> | Record<string, unknown>[];

export default function CalibrationPanel({ runId }: { runId?: string }) {
    const [runs, setRuns] = useState<Run[]>([]);
    const [selected, setSelected] = useState(runId ?? "");
    const [strategy, setStrategy] = useState("ema");
    const [result, setResult] = useState<Result | null>(null);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        if (runId) setSelected(runId);
        fetch("/api/runs")
            .then((r) => {
                if (!r.ok) throw new Error("Cannot load runs");
                return r.json();
            })
            .then(setRuns)
            .catch((e) => setError(e.message));
    }, [runId]);
    async function analyze(kind: string) {
        setError("");
        setBusy(true);
        setResult(null);
        try {
            const response = await fetch(`/api/research/${kind}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Paper-Request": "1",
                },
                body: JSON.stringify({ run_id: selected, strategy }),
            });
            if (!response.ok) {
                const body = await response.json();
                throw new Error(
                    typeof body.detail === "string"
                        ? body.detail
                        : "Research request rejected",
                );
            }
            if (kind === "export") {
                const blob = await response.blob();
                const url = URL.createObjectURL(blob);
                const anchor = document.createElement("a");
                anchor.href = url;
                anchor.download = "nse-training.jsonl";
                anchor.click();
                URL.revokeObjectURL(url);
                setResult({
                    export_bytes: blob.size,
                    message: blob.size
                        ? "Training JSONL downloaded"
                        : "No realized model outcomes; export is empty",
                });
            } else {
                setResult(await response.json());
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : "Analysis failed");
        } finally {
            setBusy(false);
        }
    }
    async function ledger() {
        try {
            const response = await fetch(`/api/runs/${selected}/report`);
            if (!response.ok) throw new Error("Cannot load ledger");
            setResult(await response.json());
        } catch (e) {
            setError(String(e));
        }
    }
    const report = result && !Array.isArray(result) ? result : null;
    const before = Array.isArray(report?.reliability_before)
        ? (report.reliability_before as Point[]).filter((p) => p.count > 0)
        : [];
    const after = Array.isArray(report?.reliability_after)
        ? (report.reliability_after as Point[]).filter((p) => p.count > 0)
        : [];
    return (
        <Stack gap={2}>
            <Alert severity="info">
                Calibration uses realized target/stop horizon labels, a
                chronological training split and purged held-out validation.
                Declare the exact checkpoint revision first. Candidate
                temperatures are saved for review; they are not applied
                automatically.
            </Alert>
            {error && <Alert severity="warning">{error}</Alert>}
            <Paper sx={{ p: 3 }}>
                <Stack gap={2}>
                    <TextField
                        select
                        label="Source run"
                        value={selected}
                        onChange={(e) => setSelected(e.target.value)}
                    >
                        <MenuItem value="">Choose a recorded run</MenuItem>
                        {runs.map((run) => (
                            <MenuItem value={run.id} key={run.id}>
                                {run.id.slice(0, 8)} · {run.checkpoint_id} ·{" "}
                                {run.started_at
                                    ? new Date(run.started_at).toLocaleString(
                                          "en-IN",
                                          { timeZone: "Asia/Kolkata" },
                                      )
                                    : "No candles"}
                            </MenuItem>
                        ))}
                    </TextField>
                    <TextField
                        select
                        label="Walk-forward policy"
                        value={strategy}
                        onChange={(e) => setStrategy(e.target.value)}
                    >
                        {["hold", "ema", "systemone"].map((value) => (
                            <MenuItem value={value} key={value}>
                                {value}
                            </MenuItem>
                        ))}
                    </TextField>
                    <Stack direction="row" gap={1} flexWrap="wrap">
                        <Button
                            disabled={busy || !selected}
                            variant="contained"
                            onClick={() => analyze("calibrate")}
                        >
                            Fit temperature
                        </Button>
                        <Button
                            disabled={busy || !selected}
                            onClick={() => analyze("export")}
                        >
                            Export training JSONL
                        </Button>
                        <Button
                            disabled={busy || !selected}
                            onClick={() => analyze("walkforward")}
                        >
                            Walk-forward
                        </Button>
                        <Button
                            disabled={busy || !selected}
                            onClick={() => analyze("stress")}
                        >
                            Stress scenarios
                        </Button>
                        <Button disabled={busy || !selected} onClick={ledger}>
                            Ledger / charges
                        </Button>
                    </Stack>
                    {busy && (
                        <Typography color="text.secondary">
                            Analyzing immutable closed-bar data…
                        </Typography>
                    )}
                </Stack>
            </Paper>
            {after.length > 0 && (
                <Paper sx={{ p: 3 }}>
                    <Typography variant="h6">
                        Held-out reliability · candidate T ={" "}
                        {String(report?.temperature)}
                    </Typography>
                    <ResponsiveContainer width="100%" height={350}>
                        <ScatterChart>
                            <CartesianGrid stroke="#253243" />
                            <XAxis
                                type="number"
                                dataKey="mean_probability"
                                domain={[0, 1]}
                                name="Predicted probability"
                            />
                            <YAxis
                                type="number"
                                dataKey="observed_accuracy"
                                domain={[0, 1]}
                                name="Observed accuracy"
                            />
                            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                            <Legend />
                            <ReferenceLine
                                segment={[
                                    { x: 0, y: 0 },
                                    { x: 1, y: 1 },
                                ]}
                                stroke="#52677f"
                                strokeDasharray="4 4"
                            />
                            <Scatter
                                name="Before"
                                data={before}
                                fill="#a5b5fb"
                            />
                            <Scatter
                                name="Candidate"
                                data={after}
                                fill="#77dfb5"
                            />
                        </ScatterChart>
                    </ResponsiveContainer>
                </Paper>
            )}
            {!result && !busy && (
                <Typography color="text.secondary">
                    No fitted calibration is available. Baseline/demo runs have
                    no model probabilities and cannot produce a model
                    reliability curve.
                </Typography>
            )}
            {result && (
                <Paper sx={{ p: 3 }}>
                    <Box
                        component="pre"
                        sx={{ overflow: "auto", fontSize: 12 }}
                    >
                        {JSON.stringify(result, null, 2)}
                    </Box>
                </Paper>
            )}
            <Typography color="text.secondary">
                Walk-forward evaluates a fixed policy on chronological test
                windows with prior bars for indicator warmup. Model training
                happens after exporting labeled data to the Laya training
                workflow. Stress cases explicitly perturb missing bars,
                liquidity, slippage and inference availability. Short synthetic
                runs establish software behavior only.
            </Typography>
        </Stack>
    );
}
