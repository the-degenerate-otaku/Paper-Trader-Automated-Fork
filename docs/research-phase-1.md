# Research phase 1: entry economics and planned stop risk

This is the first implementation phase from the PDF review. The user authorized merging it into main on 2026-10-21. It does not train Laya, introduce multi-day trading or activate a comparison account. The baseline and default configuration retain their previous entry behavior. The research-balanced profile enables the new checks for all its manual and automated entries.

## Cost-aware entries

The shared deterministic risk engine evaluates a tick-rounded stop and target at submission and rechecks the actual fill price and available volume before every fill. A target must produce positive estimated net profit and meet the configured gross-target-to-cost multiple and net reward/risk floor. Closing orders bypass these entry gates.

Estimates include the existing dated charge schedule, both sides of the trade, adverse tick rounding, configured slippage, volume impact, ATR-based slippage and modeled partial fills. Entry brokerage already paid on the same order is retained during fill rechecks. A finite fill-count budget prevents very large quantities and tiny liquidity from creating unbounded computation. Missing target, stop, ATR or fill capacity fails closed when the gate is enabled. No new exchange rates are asserted or substituted for the configured charge schedule.

Each estimate reports gross target profit, target and stop costs, entry/exit charges, modeled slippage, net target profit, net stop loss, net reward/risk, assumed fills and charge-schedule identifier. The break-even win rate is payoff arithmetic for a hypothetical two-outcome trade with those fixed costs. It is not Laya's confidence, an estimated win probability or a prediction of returns.

The candidate initially requires a gross-target-to-cost multiple of 1 and a net reward/risk floor of 0, with a maximum of 32 assumed fills per side. Positive net target profit is still mandatory. These are explicit experimental screening settings, not optimized trading parameters.

## Portfolio budget

The candidate caps aggregate planned stop risk at 1.5% of current paper equity. The engine sums adverse entry-to-stop risk on open quantities and reserves reference-price-to-stop risk for queued entry quantities. A partial fill moves risk from the queue to the position; the remaining order stays reserved. Cancellation releases the reservation. Legacy queued orders without a reference price make the budget unknown and block new entries under this opt-in cap. Valid reductions and protective exits remain available.

The paper API includes open and pending planned stop risk, the configured budget and remaining allowance, sector breakdown and remaining daily filled-entry allowance. This is a planned price-loss budget. Fees, gaps, outages and poor liquidity can make realized losses larger.

## Audit trail and limits

Submitted and rejected orders persist the economics and a SHA-256 fingerprint of effective settings. AI decision events also record the checkpoint revision, feature schema and observed membership timestamp; no raw settings paths or authentication material are added to those events. Diagnostics are included in API results and decision events. No frontend layout changes are included in this phase.

Future exit volume, price paths, holding duration, fee rounding and partial-fill sequences are unknown. Historical one-minute volume is a submission-time proxy; fill checks use the actual execution observation. The exit estimate applies impact and ATR buffers on both paths, which can be more conservative than the present protective-exit simulator. These estimates cannot certify a profitable trade or guarantee a maximum loss.

## Remaining research work

The next phases cover receive/exchange/inference/scan timing and incident records; immutable observed-data replay; dated instrument metadata; time-of-day RVOL and aligned index/sector context; complete session-aligned 5m context with 1m execution; labeled ORB/VWAP setups and optional Laya filtering; cost-matched outcome labels and chronological calibration; and grouped net attribution across partial exits. Dated event-feed population remains a later extension. The research review still defines the scope and promotion criteria. Nothing is automatically merged into main or promoted into the active account.
