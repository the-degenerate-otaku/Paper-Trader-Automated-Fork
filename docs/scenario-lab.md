# Accounting audit and Laya scenario laboratory

The laboratory is separate from the active paper account. It never connects a broker, submits an application order, changes the active profile or edits historical fills. Local inference requests run serially against the existing pinned Laya checkpoint. Private observations, feedback examples and reports stay under the ignored work directory. Do not publish them as Pages artifacts.

## Accounting corrections

Stop, target and MIS-square-off fills share a protective order identity per position, exit reason and session date. Partial fills carry accumulated turnover and brokerage, including through SavedPaper serialization. Legacy partial positions reconstruct this information from their recorded fills before a subsequent protective execution. A fresh day receives a separate protective identity. Already recorded fees are never refunded or rewritten.

Consecutive losses count completed positions using the sum of all partial-close P&L. A winning final slice cannot erase an overall losing position, and losing slices do not independently trigger the completed-trade streak. Restoring an account rebuilds this derived streak from completed position groups without changing cash, charges or historical P&L.

The read-only audit checks cash when flat, realized P&L, fill charges, entry-charge allocation and entry/exit quantities. Its historical counterfactual holds the observed fills fixed and changes only protective brokerage and related GST. It is not a replay of how different fees might have changed later sizing or risk vetoes. Other tax rounding retains the simulator's per-fill conventions; this does not certify equivalence to a broker contract note.

```powershell
.venv/Scripts/python.exe scripts/run_scenario_lab.py audit --day 2026-10-22 --output work/research-20261022/accounting.json
.venv/Scripts/python.exe scripts/run_scenario_lab.py simulate --output work/research-20261022/lab
```

On Linux use .venv/bin/python. The audit also exports trade-reviews.jsonl next to its report. Reviews link each completed position to its recorded request, response, provenance and realized outcome. A losing observed action does not identify a profitable opposite direction; reviews deliberately omit a direction gold label and are not approved for weight training.

## Experiment design

profiles/scenario-lab.yaml defines twelve scenarios: rising and falling trends, sideways chop, volatile rallies and selloffs, upward and downward price gaps, failed breakouts, liquidity drought, elevated slippage, missing candles and inference outage. Price gaps are synthetic jumps, not an exchange auction model or a news feed.

Each scenario has two probes and three chronological synthetic folds, for 72 probes. Training, validation and final-test folds have independent fixed seeds. Twelve data-gap/outage probes refuse entry before inference; the remaining 60 use actual Laya responses. One response is reused across the four profiles for each identical input. Cache identities include state, timestamp, questions and checkpoint configuration. Cached responses still pass policy validation. No response from another checkpoint is substituted.

Only closed history enters the feature engine. Mutating future prices cannot change a probe input. Simulations use the deterministic PaperExchange, including latency, adverse slippage, next-eligible fills, stop-first ambiguous bars, fees, partial liquidity and time exits. Unresolved positions are reported and excluded from outcome labeling, never treated as zero-loss trades.

Each probe starts an independent flat portfolio. Summed trial P&L is not a continuous-session backtest and does not evaluate cross-probe daily limits, correlated positions or turnover interaction. A no-trade profile is not evidence of a profitable strategy.

## Initial exploratory results

The final synthetic test fold contained twenty actual-inference probes plus four fault probes:

| Profile | Entries | Net profitable entries | Sum of independent trial net P&L |
| --- | --- | --- | --- |
| Permissive baseline | 6 | 2 | -793.36 INR |
| Baseline plus cost gate | 0 | 0 | 0 INR |
| Research-balanced | 3 | 2 | +10.20 INR |
| Research plus stronger cost coverage | 0 | 0 | 0 INR |

The stronger cost candidate requires at least 1.0 net reward/risk and a gross target worth at least twice modeled costs. Other risk and selection settings come from research-balanced. Its exported YAML has its own comparison database and port; it is not started automatically. All profile manifests and the exact suite parameters are retained privately with the result. These parameter hypotheses are exploratory, not optimized or validated for deployment.

Laya selected LONG on some sideways probes and both failed-breakout test probes. In one volatile-selloff validation probe it also selected LONG. Model direction is not a net-profit forecast: sufficiently small targets can be invalid after adverse execution or unprofitable after charges even when directional movement helps. Research-balanced lost 318.14 INR in the validation trials, despite the small positive test result. The fixed NumPy-generated run does not establish robustness across generators or market regimes.

## Training boundaries

The laboratory exports separate synthetic-training, synthetic-validation and synthetic-test JSONL files, with twenty labeled cases each. Labels describe the best net-positive executable direction under the baseline cost/stop/target/time policy, otherwise NEUTRAL. Rejected entries are flat; unresolved outcomes are omitted. These are policy labels, not fundamental direction truth. Actual news, benchmark context, depth and VIX are unavailable to this experiment and are not fabricated.

An exploratory temperature calibrator fits only the training fold, checks validation and then reports the untouched test fold. The initial fitted temperature was 3.0. Test negative log loss improved from 1.8115 to 1.2990, but remained worse than a uniform predictor at 1.0986 and a smoothed training-label prior at 0.3954. All twenty training labels were NEUTRAL, so class imbalance and the baseline's cost structure dominate this tiny exercise. The calibrator is not promoted.

No model weights were fine-tuned. Twenty correlated synthetic examples and one observed paper session do not support a claim of improved NSE trading. Before weight training, collect more independent real sessions, establish a cost-consistent label policy, purge overlapping outcomes, retain untouched later sessions and compare against a no-trade baseline. Treat this lab as a failure-finding and data-preparation tool.
