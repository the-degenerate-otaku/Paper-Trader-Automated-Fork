# Permissive paper-trading experiment

This is a higher-risk, more permissive configuration requested for observing automated paper entries. It is not a low-risk strategy or a validated recommendation for real trading. Paper funds and account history are retained.

| Setting | Previous | Experiment |
| --- | ---: | ---: |
| Planned stop risk per trade | 0.5% equity | 1% equity |
| Maximum position value | 10% equity | 20% equity |
| Total exposure cap | 60% equity | 90% equity |
| Open positions / per sector | 6 / 3 | 10 / 5 |
| Daily / weekly loss limits | 2% / 5% | 10% / 20% |
| Drawdown kill threshold | 10% | 30% |
| Consecutive losses before cooldown | 3 | 10 |
| Cooldown | 30 minutes | 1 minute |
| Entries per day / per symbol | 20 / 3 | 100 / 20 |
| Minimum gap between entries | 5 minutes | 0 minutes |
| Average daily turnover filter | INR 100 million | INR 1 million |
| Minimum closed-bar volume | 100 | 10 |
| Correlated positions / correlation threshold | 2 / 0.80 | 10 / 0.95 |
| Extra blackout days around configured events | 1 | 0 |
| Model reversal-score ceiling | 0.40 | 0.70 |

Direction score remains at 0.50 and minimum conviction remains LOW. ATR stop distance remains 1.5 ATR, reward/risk ratio remains 2 and sizing buffer remains 25 bps. Existing banned-symbol and explicit same-day event guards remain available. All values live in config.yaml.

These limits are maximum allowances, not target allocations or guaranteed losses. Available funds, fees and leverage still constrain fills. Entries still require valid protective prices, fresh regular-session quotes, complete recent closed candles, current Nifty membership and the intraday entry window. Missing or invalid model responses fail closed. Simulated fills require later observed prices and positive observed volume; no historical fills or synthetic liquidity are introduced. Short entries remain MIS-only, with the existing square-off rules. Re-enabling the bot does not reset loss counters, cash, kill-switch state or account history.
