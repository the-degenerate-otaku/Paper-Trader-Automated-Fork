# Local Laya intraday paper automation

The primary portfolio now has an opt-in **Start AI paper trading** control. This uses the same virtual account, positions and risk limits as manual orders. It never sends broker orders. The strategy is local Laya, with MIS intraday entries only.

## Stock selection and decisions

The active universe is all 50 observed Nifty constituents. Active MIS position reviews take priority, pending orders come next, and new entry candidates follow. Newly opened positions are promoted before the next queued candidate; active positions are revisited during a long scan. One in-flight Laya request is allowed to finish before another begins. A stale or missing quote blocks that stock rather than the entire 50-stock scan. Membership must be current. Configuring a smaller mover_count retains the optional absolute-percentage-mover ranking with a complete quote-set requirement.

At measured CPU inference speeds, 50 serial requests alone take roughly two to three minutes, with history downloads and priority reviews adding time. There is no guarantee of one decision for every stock every minute. Only the latest eligible closed candle is evaluated when a stock reaches its turn; missed historical opportunities are not replayed. Quote-driven protective execution runs independently of this queue.

Each selected stock loads closed one-minute OHLCV history automatically. A complete warmup window without gaps and a last candle no older than the configured 120 seconds are required. Future candles are excluded. Each symbol's closed candle is claimed in the private journal before inference and evaluated at most once, including after restart. Missed historical bars are never replayed as live trade opportunities.

The existing feature engine supplies indicators and compact state to the localhost System One client. Its probability, conviction and reversal gates remain authoritative. Generic Laya output has not been calibrated or demonstrated profitable on NSE outcomes. A neutral, invalid, timed-out or unavailable model cannot open a position. Stops and targets continue through the separate quote-driven paper exchange.

For accepted LONG/SHORT signals, the bot calculates quantity using the existing equity risk and position limits, places an ATR-based protective stop and reward/risk target, then submits a MIS paper order. The current quote, session, liquidity, cooldown, exposure, funds and other risk checks are applied again. Execution still waits for eligible later observed prices and volume. Existing MIS positions receive portfolio-aware Laya reviews. A qualifying opposite-direction signal submits a reduce-only closing order rather than reversing or averaging the position. Position identity is checked again after inference; a position that closed or changed during inference cannot accidentally become a new opposite entry. Pending unfilled entry quantities are cancelled before a closing order is queued. An existing pending exit prevents duplicate exits.

## Short-duration paper experiment

New bot entries use a 1 ATR stop, a 0.75 ATR target and at most 30% of equity in position value, still constrained by the 1% planned stop-risk budget, available funds and 90% total exposure cap. This can increase share quantities compared with the prior profile. A five-minute maximum holding plan is recorded with each new bot entry and restored across restart. It requests a reduce-only exit on a fresh eligible quote even if AI entries are stopped; large exits may fill partially. Legacy entries without that plan retain their existing stops and targets. This cap is an exit-request time, not a guaranteed fill deadline.

Closer targets can be outweighed by charges and slippage. These experimental settings do not establish positive expected returns or a way to recover previous losses before a deadline. See paper-experiment.md for other active limits.

## Stop and restart

**Stop AI entries** cancels pending bot entries, including remaining quantities of partially filled orders. It preserves manual pending orders and existing positions with protective stops/targets. Stopping during inference prevents a late response from creating an order. Disconnecting the source also stops automation; protective fills need the app and feed running. A service failure pauses automation and attempts to cancel its pending entries.

Automation starts disabled after every server restart. Restored pending bot entries are cancelled before quotes reconnect; manual pending orders remain available for review. Cash and existing positions retain their normal persistence. Daily MIS square-off remains subject to eligible observed quotes and liquidity, so an outage can prevent the intended exit time.

## CPU runtime setup

Install the inference service in a separate Python 3.11 environment. The trading app continues to use its existing environment. `requirements-laya.lock` pins the inference dependencies; use the CPU wheel index through uv on both Windows and Linux.

```powershell
uv venv --python 3.11 work/laya-runtime
uv pip install --python work/laya-runtime/Scripts/python.exe --torch-backend cpu -r requirements-laya.lock
work/laya-runtime/Scripts/python.exe scripts/run_laya.py
```

On Linux, use `work/laya-runtime/bin/python` in the last two commands. The launcher binds only to 127.0.0.1, selects CPU, limits resident models and threads, disables Hub telemetry, and pins the model revision from config.yaml. The first launch downloads the checkpoint; model weights and cache stay under ignored `work/`. After caching, `HF_HUB_OFFLINE=1` can enforce offline checkpoint loading. Live Yahoo market data still requires internet access.

The inspected [Laya serving source](https://github.com/NandhaKishorM/laya/blob/main/laya/serve.py) documents its localhost endpoint and environment controls. [Checkpoint metadata](https://huggingface.co/convaiinnovations/laya/tree/7b928d828b7b0e022f929d9bd2e44165aa270148/typed-decisions) identifies the pinned artifacts. A declared client revision records operator provenance; it does not cryptographically attest a separately operated server.

Start the main app, connect the price feed, then start AI paper trading. The panel shows current movers, service status and recent decisions/vetoes. Detailed features, input candle hashes, model requests/responses and bot order ownership are retained in the private local event journal. Provider failures and model failures have no synthetic fallback. There is no auto-start on login or background scheduler outside the running app.

## Market closing limitation verified 2026-10-21

The bot entry cutoff remains 15:00 IST and MIS square-off setting 15:15 IST. These are app settings, distinct from exchange timings. [NSE CAS rules](https://www.nseindia.com/static/products-services/closing-auction-session) describe the closing auction for eligible cash stocks from 15:15 to 15:35, continuous trading until 15:30 for non-CAS securities, and equity derivatives until 15:40. This simulator does not implement CAS order matching or per-symbol CAS eligibility, and its generic calendar still uses 15:30 as the session end. Do not interpret its open phase after 15:15 as verification of continuous tradability for a CAS stock. Auction simulation requires a separate calendar/execution adaptation; the bot cutoff has not been extended into it.
