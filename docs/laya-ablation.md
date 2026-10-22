# Does Laya add value?

The offline ablation holds execution settings fixed and substitutes four entry policies: no trade, the existing EMA direction rule, Laya's qualified direction, and EMA filtered by a qualifying Laya agreement. Every arm uses the same reference price, ATR, position sizing, stops, target, costs, future candles and decision time. The baseline and research-balanced execution profiles are evaluated separately without tuning either profile.

The simulated trial function accepts the actual symbol and an optional decision timestamp. Candles opening before the recorded response time cannot execute a comparison entry. The recorded feature LTP remains the common reference for both policies. This is a standardized candle-execution counterfactual, not a recreation of quote-driven historical fills.

## Run

```powershell
.venv/Scripts/python.exe scripts/evaluate_laya.py --output work/laya-ablation --synthetic-cache work/research-20261022/numpy-lab
```

Use .venv/bin/python on Linux. The synthetic cache must come from the scenario laboratory. The script verifies its checkpoint revision, exact state and feature hashes before reusing recorded responses. Injected inference outages block only AI arms; missing-candle scenarios are excluded for all arms. No new model requests are made.

profiles/laya-ablation.yaml fixes journal bounds, session selection, non-overlap interval, outcome window and seeded random-control budget. The original SQLite database opens in read-only mode. No application endpoints, orders, training, profile promotion or database migrations are called. Reports and observations must remain under ignored work paths.

## Recorded-session design

The journal scan keeps completed, explicitly flat ENTRY_REVIEW contexts, including completed inference failures. Pending records and position reviews are excluded. Sampling chooses the first review per symbol after each fixed separation, before inspecting model availability or future profitability. Every arm receives the same opportunities, including the arms that need no model.

Missing reference candles, stale signals or incomplete future windows exclude the entire comparison pair. The entry selection and outcome coverage counts are retained. The latest saved future candle revision is used for execution; original feature values and the model response remain those recorded at the decision. Dataset versions and input/response/future hashes are retained privately.

The main comparison includes failures as no-entry outcomes for AI arms. A separate valid-response subset removes the service availability confound. Both controls wait for the recorded inference completion time, so EMA receives no speed advantage. Historical inference latency is reported separately; it is not a fresh runtime benchmark.

The random-thinning control draws the same number of entries as the AI arm from executable EMA entries, without replacement. Its exact expected net result and a fixed-seed distribution distinguish trading less from selecting better. It is exploratory, does not preserve all cross-stock/time correlations and does not produce a statistical significance claim. Zero-entry AI arms receive no skill estimate.

## Initial findings

The recorded-session comparison did not establish an entry-selection advantage for the configured Laya integration. Lower aggregate losses alone were misleading because the AI arm traded substantially less. The synthetic comparison was mixed and sensitive to execution profile; with research-balanced execution, EMA outperformed the Laya-filtered version across the previously inspected cases. This does not establish a profitable deterministic alternative either. Detailed recorded financial results remain in private reports.

## Limits

- One real session has sufficiently explicit entry/position context; older journal records are excluded rather than guessed.
- The opportunity set reflects the original AI scheduler and account history. This is conditional entry selection, not a counterfactual full-session trading policy.
- Independent flat trials omit portfolio interaction, correlated exposure, AI exit reviews and continuous daily limits. Net sums are not account returns.
- Latest revised Yahoo candle outcomes differ from observed quote fills and introduce revision uncertainty. Missing-data exclusions can bias coverage.
- EMA uses recorded EMA features; Laya received the application's compact text state. The experiment tests the current integration, not every possible use of the underlying model.
- The synthetic paths and real session were already inspected. Neither is a new preregistered holdout. No settings are selected using this evaluation.

Keep Laya experimental until it improves a matching rule strategy on later independent sessions after costs and availability. The result does not justify promoting either entry policy, weakening risk controls or training weights on this sample.
