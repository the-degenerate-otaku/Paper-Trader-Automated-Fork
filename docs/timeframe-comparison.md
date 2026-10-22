# Paired one-minute and five-minute experiment

The comparison recalculates indicators and asks the actual local Laya model separately for each candle size. It does not reuse a one-minute answer as a five-minute answer. The compact state has an explicit timeframe prefix in both variants. Original checkpoint, questions, direction thresholds, risk rules, fees and stop/target multiples remain fixed.

Each eligible opportunity runs four entry policies: no trade, EMA, Laya, and EMA filtered by Laya. Each runs at both timeframes and with both the existing maximum holding time and the user-selected 25-minute time exit. That separates slower signals from longer holding. The existing limit is five minutes in baseline and twenty minutes in research-balanced; the candidate limit is twenty-five in both. No setting is promoted to the active bot.

## Candle and clock rules

Five-minute candles align to the configured session open. Each requires exactly five distinct, contiguous full one-minute candles. Open, high, low, close and volume are aggregated; partial or missing buckets are omitted without padding. Duplicate minutes, mixed instruments, mixed price bases and out-of-session input are rejected.

Both indicator histories use the MIS trading window up to the configured square-off time. Post-square-off bars are omitted in both variants. This common research window avoids comparing histories with different late-session missing data and differs from the earlier journal replay. The latest two hundred signal bars must be complete, healthy and closed. Histories are truncated before calculation; changing future prices cannot change a model input.

Indicator periods stay in bars: EMA 9/20 therefore covers 9/20 minutes versus 45/100 minutes. ATR, volume ratio, RSI and other features also change. ATR-based sizing, stop and target distances respond to the recalculated ATR; their multipliers are held constant. This evaluates the configured trading system on different signal timeframes, not the isolated effect of changing a text label.

Execution always uses the same one-minute future prices and one-minute liquidity reference. Stops remain independent of AI, conservative stop-first ambiguous bars still apply and protective exits can occur between five-minute closes. All policies wait the same configured decision delay. The 25-minute rule requests an exit after the elapsed holding limit; next-eligible execution and liquidity may delay the actual fill. It does not wait for a five-minute candle to close before enforcing a stop.

## Run

```powershell
.venv/Scripts/python.exe scripts/compare_timeframes.py --prepare-only --output work/timeframe-comparison
.venv/Scripts/python.exe scripts/compare_timeframes.py --output work/timeframe-comparison
```

On Linux use .venv/bin/python. The protocol lives in profiles/timeframe-comparison.yaml. It fixes session, eligible five-minute signal boundaries, non-overlapping outcome windows, history depth, common decision delay and the candidate hold duration before inference. The original SQLite ledger opens read-only. No live/application orders, migrations or active settings writes occur.

The stored membership snapshot must precede the first signal. Incomplete history or future windows are excluded before inference. One response per timeframe is shared across all execution/exit variants. Cache identities include exact state, timestamp, questions and checkpoint configuration; invalid or unavailable responses fail closed. Cache reuse avoids repeat model calls for identical inputs.

After preserving an interrupted or failed pass, --resume-cases reuses the exact saved case set and retries only missing responses. It checks the frozen case hash, protocol and relevant source/profile hashes before execution; it does not refetch or select a new dataset. The prior report hash is retained as resume provenance and new inference attempts are journaled privately. Keep the first pass separately when comparing reliability with a later retry.

Private cases.json retains exact inputs, aggregate-history hashes, reference and future candles. Reports retain source/profile hashes, exclusion counts, model latency and paired results. Any unresolved outcome excludes that opportunity from every compared variant. Valid-response subsets require both timeframe responses to be valid. All financial observations and local model outputs remain under ignored work paths.

## Interpretation

The initial fixed schedule includes two late-session boundaries after enough five-minute history is available. It is a retrospective single-session sensitivity test, not an untouched walk-forward test. Outcomes use latest saved Yahoo candle revisions rather than original quote fills. Coverage exclusions, a small correlated opportunity set and independent flat portfolios limit the conclusion. Different sample times, input prefix and shared history window mean its totals cannot be directly compared with the earlier journal experiment's totals.

Report all variants, including no-trade and matched trade-count controls. More abstention, a larger ATR or a small positive trial sum alone does not establish a trading advantage. Neither model weights nor the active exit policy change as a result of running this experiment.
