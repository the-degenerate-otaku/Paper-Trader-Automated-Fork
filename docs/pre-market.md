# Local paper-trading readiness

Run from the repository root with the backend and existing local Laya server running:

```powershell
.venv/Scripts/python.exe scripts/pre_market_check.py
```

On Linux use .venv/bin/python. The command reads the loopback backend's health, paper snapshot and settings. It places no orders, changes no state, prints no account balances or credentials and returns a nonzero exit code for blocked checks. Use --port to select another loopback backend port.

WAITING_FOR_MARKET means the infrastructure prechecks pass while the market is closed, on a holiday/weekend or before the continuous session. Overnight stale quotes are not misreported as a service failure. Run it again when the session opens. LIVE_PRECHECKS_PASS requires at least one fresh, prepared stock quote during the open session. It is not order approval: candle health, liquidity, available funds, session entry limits and deterministic risk still apply. Automation enabled and entry-window status are reported separately.

The existing configuration opens the continuous session at 09:15 IST, waits five minutes before AI decisions, stops new MIS entries at 15:00 and requests MIS square-off at 15:15. Exchange close is 15:30. Local settings and the verified calendar remain authoritative; execution during a feed outage or with insufficient liquidity cannot be guaranteed.

## Automated target-cost coverage

auto_paper.require_cost_coverage is enabled in config.yaml. Baseline and comparison profiles omit the new field and retain the backward-compatible false default. The global entry_economics setting remains separate, so ordinary manual stop-only tickets retain their existing behavior.

Automated entry orders carry a persisted requirement to evaluate planned target profit after estimated round-trip charges and slippage. The execution engine checks the requirement before queuing and again at each eligible fill. Observed fill volume, slipped entry price, current closed-bar ATR and remaining brokerage-cap state are considered by the existing economics estimator. Quote refreshes cannot silently drop an order's requirement; disabling the configuration later does not remove it from already queued orders. Restart still pauses/cancels queued automated entries under the existing restart policy.

Targets consumed by estimated costs are rejected with TARGET_CONSUMED_BY_COSTS. Missing required economic inputs fail closed with ECONOMICS_UNAVAILABLE. Estimates and vetoes remain in the decision/order journal. Protective exits and reduce-only orders bypass this entry gate.

This is a cost safeguard, not evidence of positive expectancy. Simulated fees/slippage and observed volume are approximations. No model probability is interpreted as a calibrated chance of profit. Research did not justify switching the active model or timeframe. Existing direction thresholds, stop/target multiples, position sizing and loss limits remain unchanged.

Automation starts disabled after a backend restart. Start it through the normal application control when desired; the configured calendar and fresh-data/risk gates remain enforced even when automation is enabled outside market hours.
