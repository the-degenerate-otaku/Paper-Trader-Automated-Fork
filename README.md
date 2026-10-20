# Paper Trader Automated

Local, paper-only NSE cash-equity terminal for Windows and Linux. Public fork of [Open Paper Trading MCP](https://github.com/Open-Agent-Tools/open-paper-trading-mcp). The upstream Apache-2.0 license and history are retained.

## Status

Milestones 1–5: foundation, versioned data, indicators, execution/risk and shared replay/backtest engine validated. Milestones 6–9: inference, adapted dashboard/API, scheduler/bots and calibration/stress in progress. Optional milestone 10 is outside current scope.

The inherited React/MUI frontend is being connected to the NSE backend. Upstream backend/tests/scripts under upstream_reference are excluded from the installed package. Do not run the old Docker/start scripts or use upstream credential instructions during migration. No broker credentials are needed.

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

Demo prices are synthetic. EMA is an explicit deterministic baseline separate from the AI policy. CSV/yfinance history is not an exchange-quality live feed. No live order placement is implemented.

Configure calendar, constituents, data, charges and risk in config.yaml. Databases, .env files, keys and logs are ignored by Git. Keep credentials outside this public repository. See [security](docs/security.md), [charges](docs/charges.md), [source audit](docs/reference-audit.md) and [migration](docs/fork-migration.md).
