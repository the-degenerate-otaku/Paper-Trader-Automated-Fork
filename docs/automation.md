# Local Laya intraday paper automation

The primary portfolio now has an opt-in **Start AI paper trading** control. This uses the same virtual account, positions and risk limits as manual orders. It never sends broker orders. The strategy is local Laya, with MIS intraday entries only.

## Stock selection and decisions

The bot ranks the current Nifty 50 members by absolute daily percentage change, using the streaming provider's change from previous close. Gainers and losers compete in one ranking; ties sort by ticker. The top five are recomputed each scan. Missing, non-regular or stale percentage-change quotes for any member pause ranking rather than silently selecting from an incomplete list. Membership must also be current.

Each selected stock loads closed one-minute OHLCV history automatically. A complete warmup window without gaps and a last candle no older than the configured 120 seconds are required. Future candles are excluded. Each symbol's closed candle is claimed in the private journal before inference and evaluated at most once, including after restart. Missed historical bars are never replayed as live trade opportunities.

The existing feature engine supplies indicators and compact state to the localhost System One client. Its probability, conviction and reversal gates remain authoritative. Generic Laya output has not been calibrated or demonstrated profitable on NSE outcomes. A neutral, invalid, timed-out or unavailable model cannot open a position. Stops and targets continue through the separate quote-driven paper exchange.

For accepted LONG/SHORT signals, the bot calculates quantity using the existing equity risk and position limits, places an ATR-based protective stop and reward/risk target, then submits a MIS paper order. The current quote, session, liquidity, cooldown, exposure, funds and other risk checks are applied again. Execution still waits for eligible later observed prices and volume. Existing same-stock positions or pending entries are skipped; the bot does not average or reverse them.

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
