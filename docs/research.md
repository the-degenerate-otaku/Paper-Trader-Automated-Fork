# Research, calibration and exports

The Calibration / research page selects a recorded run. Analysis uses its immutable market-data versions through the current replay clock. CLI analysis requires an explicit timezone-aware --as-of cutoff. Labels cannot appear before the complete forward horizon closes. Warmup, missing/gapped data and invalid model probabilities are excluded.

Each label starts at the next candle open, uses the decision-time ATR, the recorded stop multiple and reward/risk target, and looks forward research.horizon_bars. A stop wins an ambiguous bar. LONG/SHORT requires that direction's target to win before its stop; otherwise the label is NEUTRAL. These are nominal price-path labels. Execution returns, fill capacity, slippage and charges are evaluated separately. Label parameters, sanitized provider kinds, immutable versions and outcome availability times accompany exports.

Calibration requires one checkpoint and an explicit system_one.checkpoint_revision. The default unverified revision refuses fitting. Record the actual model revision/manifest used by the local server before collecting a new run; the client records the operator declaration and does not cryptographically verify remote weights. Historical unverified outputs are not silently relabeled.

Temperature candidates come from validated configuration. Fitting uses a chronological training subset; rows whose outcomes were unavailable at the validation boundary are purged. Held-out NLL, reliability bins, sample counts and ECE are reported. Synthetic source data is identified in metadata. Candidate temperature is saved as a content-addressed SQLite artifact and is not applied automatically. Review held-out results and matching revision before changing config.yaml. A small or synthetic sample does not establish NSE performance.

```sh
paper-trader calibrate RUN_ID --as-of 2026-10-20T20:00:00+05:30
paper-trader export-training RUN_ID --as-of 2026-10-20T20:00:00+05:30 --output data/training.jsonl
paper-trader walkforward RUN_ID --as-of 2026-10-20T20:00:00+05:30 --strategy ema
paper-trader stress RUN_ID --as-of 2026-10-20T20:00:00+05:30
```

Walk-forward evaluates a fixed hold/EMA/System One policy on chronological test windows, using earlier bars and an embargo for indicator warmup. Warmup is excluded from execution/metrics. Reports explicitly mark parameters_fitted=false: the runner does not retrain weights or perform a hyperparameter search. Actual model training belongs to the exported-data workflow. The default windows require at least 237 distinct closed-candle timestamps. A six-session synthetic CLI demo provides enough data for three software-smoke folds.

Stress cases are baseline, missing bars, liquidity drought, increased slippage and injected inference outage. Perturbed scenarios are labeled as synthetic. They exercise software behavior, not exchange guarantees. The outage/stop regression test establishes that an already open position can stop out while the inference client fails closed.

JSONL records contain state, questions, gold and meta. The state/questions/gold shape was checked against the [pinned official Laya notebook](https://github.com/NandhaKishorM/laya/blob/ffc142012af63d015fa19f05f29f9c5ff329a2cc/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb), which passes those dictionaries into items_from_rows. Only objectively generated direction labels are exported; subjective conviction/quality labels are not invented. Replace the notebook's dataset-loading step with:

```python
import json
with open("training.jsonl", encoding="utf-8") as handle:
    rows = [json.loads(line) for line in handle if line.strip()]
items, skipped = items_from_rows(tok, rows, cfg["max_len"], cfg["head_max_len"])
```

Fine-tuning, GPU execution and publishing to a model hub were not run. Export files remain local and ignored by Git. Baseline runs have no model probabilities, so their training export is empty and calibration reports insufficient data. Account names, database paths, authentication data and raw provider filenames are excluded from the export schema. Past ledgers and fill-by-fill charge records are available through the research page.
