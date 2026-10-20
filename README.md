# Paper Trader Automated

Local, paper-only NSE cash-equity terminal for Windows and Linux. Public fork of [Open Paper Trading MCP](https://github.com/Open-Agent-Tools/open-paper-trading-mcp). The upstream Apache-2.0 license and history are retained.

## Status

Core implementation through milestone 9 is complete: versioned NSE data, indicators, paper execution/risk, replay/backtest, local inference client/policy, FastAPI/WebSocket dashboard, isolated bot scheduler, calibration/export and walk-forward/stress tooling. Automated tests and local Windows smoke checks cover the implementation. Actual model deployment, NSE-session continuous-feed behavior and automatic execution-state restoration after restart remain unverified or unsupported. Optional milestone 10 is outside current scope.

The React/MUI portfolio and positions components are connected to the NSE backend. Old backend/tests/scripts and launch/Docker files under upstream_reference are excluded from the installed package. No broker credentials are needed. [Milestone 9 CI](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/actions/runs/39457905629) passed tests, static analysis, dependency/privacy checks and the production frontend build on Windows and Linux. Inherited greeting/label/release/stale automations are disabled.

## CLI setup

Python 3.11+ and Node.js 22+ are supported targets. Linux CI verifies tests and the production build; local interactive browser smoke was performed on Windows.

```sh
python -m venv .venv
```

Activate with `.venv/Scripts/Activate.ps1` on Windows or `source .venv/bin/activate` on Linux, then:

```sh
python -m pip install -e ".[dev]"
paper-trader init --offline
paper-trader demo --start 2026-09-01T09:15:00+05:30 --sessions 3 --strategy ema
python -m pytest
```

Build and open the dashboard:

```sh
cd frontend
npm ci
npm run build
cd ..
paper-trader serve
```

Open http://127.0.0.1:2080. Click New demo, then Step or Play. Hold and EMA are explicit baselines; Local Laya requires a running local inference server. Alt+O opens the order ticket. The Reports tab can create a replay from a CLI-imported immutable data version. Development Vite serves at 127.0.0.1:3000, explicitly allowed by the local origin configuration.

The UI includes INR/IST portfolio metrics, candlestick/EMA/VWAP/Bollinger/RSI/MACD charts, paper order ticket with stops/targets/trailing distance, positions/orders, decisions, trade inspection, reports, settings and service health. Watchlist membership is observation-time aware; historical snapshots are not fabricated. Missing market/reference data stays unavailable.

Bot arena provides separate configured bankrolls, manual/copilot/autopilot/shadow modes, entry gates and scheduler controls. Entry gates start disabled. Continuous market refresh is opt-in. Read [arena operation and restart limitations](docs/arena.md) before using continuous mode; persisted ledgers are not automatically resumed after restart.

Calibration / research provides chronological temperature fitting, held-out reliability diagrams, notebook-compatible training JSONL, frozen-policy walk-forward windows, stress scenarios and historical ledger/charges reports. An explicit checkpoint revision and enough realized model outcomes are required for fitting. Baseline runs cannot generate a model calibration curve. See [research usage and label rules](docs/research.md) and [local inference setup](docs/inference.md).

Demo prices are synthetic. EMA is an explicit deterministic baseline separate from the AI policy. CSV/yfinance history is not an exchange-quality live feed. No live order placement is implemented.

Configure calendar, constituents, data, charges and risk in config.yaml. Databases, .env files, keys and logs are ignored by Git. Keep credentials outside this public repository. See [security](docs/security.md), [charges](docs/charges.md), [source audit](docs/reference-audit.md) and [migration](docs/fork-migration.md).
