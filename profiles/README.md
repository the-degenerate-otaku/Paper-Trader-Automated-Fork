# Isolated research comparison profiles

These are parameter hypotheses, not trained models or validated profitable strategies. Neither is automatically loaded by config.yaml or the current server. Source baseline: cfb091ab8ad0e13281d4345b17cf6585b998d43d. Read ../docs/research-review.md before interpreting results.

| Parameter | Baseline | Research-balanced |
| --- | --- | --- |
| Account starting capital | INR 1,000,000 | INR 1,000,000 |
| Risk per trade | 1% | 0.5% |
| Maximum position / total exposure | 30% / 90% | 15% / 45% |
| Open positions / positions per sector | 10 / 5 | 3 / 1 |
| Daily / weekly loss limit | 10% / 20% | 2% / 5% |
| Drawdown kill / consecutive losses | 30% / 10 | 8% / 3 |
| Loss cooldown / minimum entry gap | 1 min / 0 min | 10 min / 5 min |
| Maximum entries per day / per stock | 100 / 20 | 10 / 3 |
| ATR stop multiple / target reward-risk | 1.0 / 0.75 | 1.5 / 1.5 |
| Maximum holding plan | 5 min | 20 min |
| Direction score / conviction / reversal score | 0.50 / LOW / 0.70 | 0.60 / MEDIUM / 0.40 |
| Opening entry blackout / last entry | 5 min / 15:00 | 15 min / 14:45 |
| Symbol scope | All 50, active positions first | Same |
| Live candle timeframe | 1m | 1m; 5m integration is future work |
| Model weights / temperature | Existing checkpoint / 1 | Unchanged; not calibrated |
| Cost-aware entry and fill check | Disabled | Enabled; gross target must exceed estimated costs |
| Aggregate planned stop risk, open plus pending | No additional cap | 1.5% of current paper equity |
| Port | 2081 | 2082 |
| Ledger basename | comparison-baseline.sqlite3 | comparison-research-balanced.sqlite3 |

At a fixed gross 0.75R reward and 1R loss, break-even requires 57.1% wins before costs. An illustrative constant 0.20R round-trip cost raises it to 68.6%. With 1.5R reward and the same illustrative cost, it is 48.0%. Wider targets can lower the actual win rate; this arithmetic does not predict either profile's performance. Actual costs differ by position size, side and fill path.

## Validate without launching or writing a ledger

From the repository root, using the existing environment:

```powershell
.venv/Scripts/python.exe scripts/run_comparison.py --profile baseline check
.venv/Scripts/python.exe scripts/run_comparison.py --profile research-balanced check
```

On Linux use .venv/bin/python. The guard validates the full settings schema, expected ledger and port. Process environment overrides still apply; unsafe destination overrides are rejected. The launcher explicitly selects profiles/.unused-env instead of the main .env; no such dotenv file is shipped.

## Optional manual activation after review

```powershell
.venv/Scripts/python.exe scripts/run_comparison.py --profile research-balanced init
.venv/Scripts/python.exe scripts/run_comparison.py --profile research-balanced serve
```

Open http://127.0.0.1:2082. For baseline use baseline in both commands and port 2081. Initialization is offline. Connect prices and explicitly enable AI entries if running a forward paper experiment. The local Laya server must still be available at its configured loopback endpoint. The ordinary app remains on 2080. No cash, holdings or completed trades are copied between accounts. Keep the comparison databases private and backed up.

Compare profiles on identical recorded data before attributing an improvement to these settings. Running them on different sessions or concurrently against one CPU inference process is not a controlled comparison. [Research phase 1](../docs/research-phase-1.md) implements cost screening and aggregate planned stop-risk budgeting. Paid data, 5m resampling, setup meta-gating, RVOL, recording/replay extensions and model training are future phases.
