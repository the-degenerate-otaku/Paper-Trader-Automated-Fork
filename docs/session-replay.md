# Shared-portfolio historical and stress replay

This research-only runner compares the existing local Laya checkpoint and an explicit EMA baseline at one-minute signals/five-minute holding and five-minute signals/twenty-five-minute holding. It does not change the active bot, train weights or implement a specialist committee. The earlier factorial timeframe experiment remains separate.

The frozen protocol in profiles/session-replay.yaml specifies three named stocks, three historical sessions, common scheduled decision windows and ten constructed stress cases before inference. Historical portfolios carry capital and positions across sessions. Every policy/timeframe has its own shared portfolio across all three stocks. Each stress case starts fresh; stress returns must never be added to historical returns.

## Inputs and timing

Supply saved DataBatch JSON files named SYMBOL-1m.json and SYMBOL-5m.json inside an ignored work directory. Older native five-minute bars provide warm-up only before the earliest supplied minute. Subsequent five-minute bars require five contiguous source minutes. Both histories exclude post-MIS-square-off bars. Each signal requires a current closed bar and a healthy latest 200-bar history; gaps are not padded. When either timeframe lacks a valid signal, both arms skip that symbol's checkpoint. Exclusions are retained, including missing-data cases.

The three-stock basket is fixed research coverage, not a reconstructed historical Nifty index. Latest downloaded, provider-adjusted price revisions are not point-in-time quotes. Warm-up extends before the evaluated sessions; source files and their provenance remain private. Unavailable benchmark, VIX, event and depth inputs are not fabricated. Correlations use aligned observed historical returns; turnover uses observed earlier sessions.

The execution clock advances through observed minute bars. Every observed stock's opening marks and eligible orders are processed before any stock's minute-end protective exits or closing marks. This prevents a same-minute profit or released position slot from funding an earlier opening fill in another stock. Scheduled signals use only bars closed at that clock. Each decision becomes eligible after a common thirty-second delay plus the engine's configured latency, then fills at a later eligible minute open with modeled slippage, charges and volume capacity. Full observed minute volume is a retrospective liquidity approximation, not known live opening depth. Actual HTTP latency is recorded separately; this is a controlled historical simulation, not a measurement of production throughput. Symbol processing order is fixed by the protocol. The model sees its own book's available cash and current position. Cache identity includes the exact compact state, timestamp, questions and checkpoint configuration.

This first batch uses sparse common checkpoints to fit local CPU inference. It does not reproduce a continuous one-minute or five-minute scheduler. ATR used for execution slippage comes from the latest scheduled closed signal for that book. Five-minute ATR changes position sizing and protective distances even though their multipliers remain fixed. These are combined system comparisons; they cannot isolate candle size from holding time or ATR sizing. No outcome-driven threshold search is performed.

Stops, targets, limits and session square-off run independently of AI through the existing exchange. Maximum hold requests a reduction; latency, halts, missing observations or liquidity can delay its fill. Opposite qualifying signals request reduction without opening a reverse position. Unfilled entries expire after the configured interval. Missing late bars may leave an unresolved position: report its realized and marked results separately, without a fabricated liquidation.

## Constructed stress cases

Cases cover opening gaps up/down, a sharp reversal, extreme volatility, a late-session reversal, volume drought, increased slippage, inference outage, feed outage and a trading halt. Seeded transformations operate on a historical base; these are hypothetical conditions, not additional real trading days. Price shocks preserve valid OHLC bounds, with separate volume and execution-cost changes. A feed outage removes observed bars; a halt supplies a frozen last mark with zero volume and the deterministic halted flag. An inference outage suppresses model requests while market and protective processing continue. No future outcome labels are supplied to Laya.

An outage case that blocks all entries verifies refusal behavior only. It cannot demonstrate management of an existing position; targeted engine tests separately verify protective processing without new AI decisions. Stops cannot be guaranteed during a feed outage or trading halt.

## Run and evidence

```powershell
.venv/Scripts/python.exe scripts/run_session_replay.py --prepare-only --data work/session-data --output work/session-run
.venv/Scripts/python.exe scripts/run_session_replay.py --data work/session-data --output work/session-run
```

On Linux use .venv/bin/python. The original instrument ledger opens read-only for sector metadata. The run freezes source, protocol, calendar, sector metadata and input hashes. Use --resume only with unchanged inputs and source. Cached successful responses can be reused, while failed attempts remain in attempts.jsonl. Interrupted replay restarts its isolated books chronologically; it does not resume an application account or restore a partially advanced portfolio.

Private outputs retain coverage, response requests/answers, inference latency, decisions, risk vetoes, fills, completed trades, timed-exit requests and minute equity/exposure curves. Progress saves after each episode; report.json is written only after all episodes finish. A bounded new-inference budget prevents an accidental unbounded run. Outputs are restricted to work storage, which is ignored by Git.

Accounting checks reconcile fill charges, realized closed-trade allocations, residual entry fees and flat-book cash. Report entries, completed positions, wins, charges, drawdown, unresolved positions and inference failures for every arm, including inactivity. A positive small sample or success on constructed paths does not establish an advantage. Promotion requires additional untouched sessions and fresh paper comparison.
