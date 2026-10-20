# Stock charts

Open **Stocks / charts**, the default workspace. Enter an NSE symbol without `.NS`, or refresh the official Nifty 50 / Bank Nifty catalog and select a stock. The catalog uses the latest locally observed instruments for browsing; historical watchlist membership still uses the replay clock.

**Load chart** reuses the latest stored snapshot for that symbol/timeframe when available, downloading on a cache miss. It does not guarantee the cached snapshot covers the entire requested range. **Refresh history** downloads a new immutable version. No synthetic price fallback is used. Data status, last closed candle and fetch time are visible. Browser history requests accept five supported timeframes, bounded date ranges and one concurrent market operation. One-minute requests use five days; intraday requests are limited to 30 days; daily requests allow up to 365 days. Provider retention, calendar coverage and availability can further restrict results.

The chart displays up to 300 closed candles. Indicator calculations use up to 1,500 preceding candles within the selected range; a warning appears when this calculation window is truncated. Indicators use the application's configured periods and warmup rules. Available toggles: EMA 9/20/50/200, SMA, session VWAP, Bollinger bands, Supertrend, volume, RSI, MACD with histogram, ATR, ADX and OBV. Missing warmup values remain unavailable. Browsing is independent of the execution engine, and does not update its clock or prices.

**Replay this history** creates a new replay from the downloaded version, with the policy/execution mode selected in the trading workspace. Existing open positions or running playback prevent replacement. Replay initially exposes no future candles; Step/Play reveals them through the shared engine. Historical data may be stale, revised or split-adjusted by Yahoo; it is not an exchange-quality point-in-time or real-time feed. Downloading a chart does not start trading.

## TradingView

The app provides an external full-site chart link using `NSE:SYMBOL`, with explicit NIFTY/BANKNIFTY mappings. It does not embed TradingView scripts, scrape TradingView, export widget prices, or supply TradingView values to the paper account.

Checked 2026-10-20:

- [Official widget Asia/Pacific market list](https://www.tradingview.com/widget-docs/markets/asia-pacific/): NSE is omitted; BSE is listed as end-of-day. No working live NSE embed is claimed.
- [Widget data FAQ](https://www.tradingview.com/widget-docs/faq/data/): availability and delay depend on exchange permissions; paid account plans do not upgrade embedded widget data. No widget data/indicator API is offered.
- [Official chart product comparison](https://tradingview.github.io/lightweight-charts/docs/product-comparison): Lightweight Charts requires application-supplied market data and indicators. TradingView widgets display TradingView data, with separate capabilities and restrictions.

## Executed smoke evidence

Official catalog refresh returned 50 Nifty 50 and 14 Bank Nifty members. A real RELIANCE five-minute request returned 148 closed candles, with its stale status, two gaps and zero-volume observations preserved. Browser smoke loaded this data, toggled EMA 50, created its replay at zero visible bars and stepped to exactly one closed candle. A browser-selected 90-day daily request returned 61 closed candles; daily axes show dates. Session VWAP is an approximation from typical OHLC bar prices weighted by volume; a daily bar provides only a single-bar proxy, not tick-level session VWAP. This evidence does not verify a real-time session feed or model inference.
