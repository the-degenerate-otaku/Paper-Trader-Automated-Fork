# Paper Trader Automated

Local Nifty 50 paper portfolio and buy/sell terminal for Windows and Linux. Virtual money only, with a free best-effort Yahoo streaming feed and no broker account required. Public fork of [Open Paper Trading MCP](https://github.com/Open-Agent-Tools/open-paper-trading-mcp). The upstream Apache-2.0 license and history are retained.

## Status

The default app is now a manual paper-trading portal: active positions, funds, P&L, pending/filled/cancelled/rejected orders, closed trades and executions. Its terminal has the official observed Nifty 50 stock list, streaming prices with exchange timestamps, market/limit/stop/bracket tickets, protective stops, targets and trailing distances. Orders fill only on later fresh observations with positive observed volume, through the existing paper exchange and deterministic risk checks. [Operation and data limitations](docs/live-paper.md).

Paper positions, balances, orders and completed trades persist across restart. Price connections and liquidity context must be re-established; no fills are reconstructed during downtime. The primary portal does not run AI automatically. Full-day unattended feed continuity is unverified.

The earlier milestone 1–9 research tools remain at `/?workspace=research`: historical charts, replay/backtest, bot arena and calibration. Actual Laya deployment is unverified, and in-memory research runs are not automatically resumed. Optional milestone 10 is outside current scope.

The React/MUI portfolio and positions components are connected to the NSE backend. Old backend/tests/scripts and launch/Docker files under upstream_reference are excluded from the installed package. No broker credentials are needed. [Milestone 9 CI](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/actions/runs/39457905629) passed tests, static analysis, dependency/privacy checks and the production frontend build on Windows and Linux. Inherited greeting/label/release/stale automations are disabled.

## CLI setup

The **Stocks / charts** workspace adds NSE symbol search, official constituent refresh, cached/downloaded stock history, five timeframes, indicator toggles and direct history-to-replay loading. The default stock is RELIANCE. Data timestamps and stale status are explicit; this is historical data, not a verified live feed. TradingView links open its full website because its public widget market list omits NSE. See [stock charts and data boundaries](docs/stock-charts.md).

Python 3.11+ and Node.js 22+ are supported targets. Linux CI verifies tests and the production build; local interactive browser smoke was performed on Windows.

```sh
python -m pip install uv
uv sync --locked --extra dev
```

Activate with `.venv/Scripts/Activate.ps1` on Windows or `source .venv/bin/activate` on Linux, then:

```sh
paper-trader init --offline
python -m pytest
```

The committed `uv.lock` is the tested dependency set used by CI. After pulling updates,
rerun `uv sync --locked --extra dev` to install security fixes into an existing environment.

Build and open the dashboard:

```sh
cd frontend
npm ci
npm run build
cd ..
paper-trader serve
```

Open http://127.0.0.1:2080. Click **Connect free feed**, open **Trading terminal**, choose a Nifty stock and click **Load stock data**. Review quantity, product and required protective stop, then submit a paper buy/sell. Review Positions, Orders, Closed trades and Executions. An opposite-side order reduces an existing position; the position's Close button prepares an exit for review. Market hours, fresh quotes, available liquidity, funds and risk rules are enforced. Research/demo controls are available separately at `/?workspace=research`. Development Vite serves at 127.0.0.1:3000, explicitly allowed by the local origin configuration.

The UI includes INR/IST portfolio metrics, candlestick/EMA/VWAP/Bollinger/RSI/MACD charts, paper order ticket with stops/targets/trailing distance, positions/orders, decisions, trade inspection, reports, settings and service health. Watchlist membership is observation-time aware; historical snapshots are not fabricated. Missing market/reference data stays unavailable.

Bot arena provides separate configured bankrolls, manual/copilot/autopilot/shadow modes, entry gates and scheduler controls. Entry gates start disabled. Continuous market refresh is opt-in. Read [arena operation and restart limitations](docs/arena.md) before using continuous mode; persisted ledgers are not automatically resumed after restart.

Calibration / research provides chronological temperature fitting, held-out reliability diagrams, notebook-compatible training JSONL, frozen-policy walk-forward windows, stress scenarios and historical ledger/charges reports. An explicit checkpoint revision and enough realized model outcomes are required for fitting. Baseline runs cannot generate a model calibration curve. See [research usage and label rules](docs/research.md) and [local inference setup](docs/inference.md).

Demo prices are synthetic. EMA is an explicit deterministic baseline separate from the AI policy. CSV/yfinance history is not an exchange-quality live feed. No live order placement is implemented.

Configure calendar, constituents, data, charges and risk in config.yaml. Databases, .env files, keys and logs are ignored by Git. Keep credentials outside this public repository. See [security](docs/security.md), [charges](docs/charges.md), [source audit](docs/reference-audit.md) and [migration](docs/fork-migration.md).
