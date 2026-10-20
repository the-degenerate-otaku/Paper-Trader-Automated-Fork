# Paper Trader Automated

Local, paper-only NSE cash-equity terminal for Windows and Linux. Public fork of [Open Paper Trading MCP](https://github.com/Open-Agent-Tools/open-paper-trading-mcp). The upstream Apache-2.0 license and history are retained.

## Status

Milestones 1–5: foundation, versioned data, indicators, execution/risk and replay/backtest validated. Milestone 6: local inference client/policy validated; actual model deployment remains unverified. Milestone 7: local FastAPI/WebSocket and adapted dashboard validated. Milestone 8: scheduler, independent bot bankrolls and shadow modes validated. Milestone 9 calibration/stress is in progress. Optional milestone 10 is outside current scope.

The React/MUI portfolio and positions components are connected to the NSE backend. Old backend/tests/scripts and launch/Docker files under upstream_reference are excluded from the installed package. No broker credentials are needed. CI now targets Windows and Linux; remote run results are still pending. Inherited greeting/label/release/stale automations are disabled.

## CLI setup

Python 3.11+ and Node.js 22+ are supported targets. Linux execution is not independently verified yet.

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

Demo prices are synthetic. EMA is an explicit deterministic baseline separate from the AI policy. CSV/yfinance history is not an exchange-quality live feed. No live order placement is implemented.

Configure calendar, constituents, data, charges and risk in config.yaml. Databases, .env files, keys and logs are ignored by Git. Keep credentials outside this public repository. See [security](docs/security.md), [charges](docs/charges.md), [source audit](docs/reference-audit.md) and [migration](docs/fork-migration.md).
