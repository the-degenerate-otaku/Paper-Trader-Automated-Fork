# Nifty 50 paper portfolio and terminal

This is the default app at http://127.0.0.1:2080. It uses virtual money and never calls a broker order API. No broker account, market-data key or payment is required for the current Yahoo source.

## Use

1. Click **Connect free feed** to refresh/read the official Nifty 50 membership and subscribe to those stocks' `.NS` quotes.
2. Open **Trading terminal** and select a stock in the market watch. Search matches the company name or symbol.
3. The selected stock automatically loads closed one-minute history for liquidity/turnover risk checks, with automatic refresh and retry every configured 60 seconds by default. Quotes continue streaming independently. This does not replay historical trades. Up to ten contexts are cached by default; selecting more stocks replaces old idle contexts while preserving contexts required by active positions or pending orders. Concurrent refreshes share cached results within the refresh interval.
4. Choose Buy or Sell, delivery/CNC or intraday/MIS, quantity and order type. Entries require a protective stop expressed as an absolute stock price, not a rupee loss or percentage. The ticket estimates quantity times the distance from the current quote to the stop and displays the configured per-trade allowance (0.5% of equity by default). This estimate excludes gaps, slippage and charges; risk is checked again at fill time. Limit and stop-trigger fields appear for their order types. Bracket orders require a target. Optional targets and trailing distances are supported.
5. Review and submit. A market order is queued until a later eligible fresh quote with an observed increase in volume. It is not filled retroactively at the displayed price. Slippage, participation caps and estimated Indian charges apply.
6. Inspect **Positions**, **Orders**, **Closed trades** and **Executions**. Close position prepares an opposite-side order for review. Pending/partial orders can be cancelled; filled orders cannot be cancelled.

Orders are Nifty-50-only for new entries. Official membership is observation-time based and must be within the configured refresh window. CNC short entries are blocked; MIS supports simulated shorts and session square-off. Deterministic funds, stop, sizing, exposure, sector, correlation, event and loss limits remain in force, including at fill time. Existing same-stock/product positions cannot be averaged into a new entry order. Opposite-side orders reduce a position, including partial exits. Remaining pending capital is not reserved up front; cash/margin and risk are checked again before each fill.

## Prices and simulated execution

Yahoo's official exchange table lists `.NS` as real-time, and yfinance provides a streaming client. This integration is best effort, not an NSE-authorized direct-feed guarantee or a latency SLA. Every displayed stock includes the exchange timestamp and freshness status. Missing, stale, malformed, future, duplicate, out-of-order, non-INR and decreasing-volume messages cannot create fills. The first connection snapshot establishes a volume baseline. After reconnects or long gaps, accumulated unseen volume is not treated as available fill liquidity.

Only a fresh regular-session quote during an open covered NSE session can enable an order. Source connectivity alone is insufficient. The execution adapter passes one observed trade price and its positive volume delta into the existing paper exchange; these point-price events are not represented as real minute OHLC charts. AI/replay feature calculations continue to use closed provider candles. The opt-in local Laya automation panel can submit MIS paper entries through these same risk and execution checks; see automation.md.

Older history can have missing minutes. Manual entry context uses fresh streaming quotes plus recent closed liquidity history; its conservative historical turnover estimate can undercount missing bars. Old historical gaps alone do not declare current quotes stale. Existing research/AI history-quality gates are unchanged. No synthetic price or volume fallback is used.

Stops and targets are simulated only when eligible prices and volume are observed. During feed outages, app shutdown, market closure, or illiquidity, fills cannot be guaranteed. Missed intragap prices cannot be reconstructed. Leave the app and source connected for monitoring.

## Persistence and restart

Schema 5 stores a typed JSON paper-account checkpoint and an append-only event journal in the private local SQLite database. Cash, risk counters, positions with protective parameters, orders, fees, fill records, closed trades and DP-charge deduplication state are restored. Failed checkpoint writes roll back in-memory execution changes. Invalid saved state fails instead of silently resetting capital.

After restart, the feed is disconnected and quotes are not considered fresh. Review pending orders and reconnect. Selecting a stock automatically loads its liquidity context. Pending entries can be rejected at the fill-time risk check if required context is unavailable. Protective exits do not depend on AI or liquidity-history warmup, but still require fresh observed prices and volume. Saved open positions outside a subsequently changed membership can be reduced through the backend; v1's visible market watch remains the current Nifty 50 list.

Runtime databases, stream observations, account snapshots and smoke logs stay outside Git. The old research/replay workspace remains optional at `/?workspace=research`, with its separate restart limitations.

## Verified sources — 2026-10-21

- [Yahoo exchange data table](https://help.yahoo.com/kb/finance/article-exchanges-data-delays-sln2310.html): NSE `.NS` is listed as real-time; this is not proof that every delivered update is timely.
- [yfinance WebSocket documentation](https://github.com/ranaroussi/yfinance/blob/main/doc/source/reference/yfinance.websocket.rst): synchronous and asynchronous live-price clients.
- [Installed-client contract source](https://github.com/ranaroussi/yfinance/blob/main/yfinance/live.py): subscription, decoding and heartbeat behavior were also checked against installed yfinance 1.7.0.

The Windows market-session smoke observed changing prices for all 50 Nifty stocks and executed a one-share RELIANCE paper buy and close. It also verified a rejected repeat entry under trade-spacing rules, an HDFCBANK limit order remaining open, and cancellation. This test leaves a simulated audit ledger and charges, with no open position or pending test order. It is not a profitability claim or full-session reliability certification.
