# Security and smoke verification

## Milestone 7 — local API and adapted UI

101 tests passed, including five API/security tests. Verified Host/origin boundaries, custom-header CSRF protection, request size limits, redacted validation errors, traversal rejection, extreme numeric values, immutable replay visibility, WebSocket snapshots, shadow-order vetoes, replay timestamps and manual order persistence/cancellation. Orders go through the same deterministic risk/exchange path. SQLite statements bind values. Open positions prevent accidentally replacing the active run.

Ruff, strict mypy, Bandit, explicit-path pip-audit and privacy checks passed. No known Python advisories; npm dependency installation/audit reported zero advisories. Privacy scan examined 3,019 file versions with zero blocking findings. Public inherited sample/attribution findings remain separated. Windows browser smoke created a demo, stepped and played 225 bars, rendered portfolio INR values, IST clock, candles, EMA/VWAP/Bollinger and RSI/MACD panels. The inherited account-selection issue found during smoke was fixed.

Service binds only 127.0.0.1. Same-origin production UI is served from the built frontend. Explicit loopback development origins can be configured; no wildcard CORS is used. WebSocket is read-only. No authentication secrets are returned by settings/health endpoints. The design trusts other native processes running as the same local user; it is not a hosted multi-user deployment. Linux execution/CI, actual model CPU latency and external live-feed end-to-end behavior remain unverified. Static upstream workflows are not evidence of current checks.

## Milestone 6 — local inference client/policy

Eight additional inference tests passed alongside all 88 core tests. The combined working tree, including the API under development, passed 99 tests. Ruff, strict mypy, Bandit, explicit-path pip-audit and the privacy scan passed again; no blocking findings across 3,010 file versions. The editable application itself is checked by tests/static analysis, not a published advisory record.

The HTTP transport contract is pinned to inspected Laya source, with score levels starting at zero and selected-direction probability gating. Tests verify batched questions, calibrated probabilities, high reversal/CNC-short vetoes, unavailable inference, redirects, response budgets and malformed/non-finite probabilities. Requests/responses, checkpoint, latency and sanitized failures are persisted by the shared event loop. Timeout/retry budget is bounded. No inference failure enables entries; reflex execution remains independent.

Smoke evidence uses mock HTTP transport, not a downloaded model. Actual checkpoint loading, CPU throughput, ONNX export and real NSE calibration remain unverified. No hosted model service or credentials are required by the client.

## Fork migration and milestone 5 — 2026-10-20

Public fork of Open-Agent-Tools/open-paper-trading-mcp at 3c48168bc78e7c34b0c8247543349b02ee5aefd2, preserving its Apache-2.0 license/history. Archived upstream backend/tests/scripts are excluded from the installed package. The active runtime has no Robinhood/cloud MCP order path. No credentials, private database or runtime logs were copied.

Executed: 88 NSE tests passed; ruff lint/format, strict mypy and Bandit passed. Tests cover replay lookahead, reproducibility, persistence, controls and adverse execution. Three-session synthetic CLI smoke completed 225 bars with no remaining positions. This baseline is not a profitability claim. HTTP testing follows with the API phase.

Frontend production build passed before and after dependency remediation. npm audit initially found 30 vulnerable packages (25 high, 4 moderate, 1 low). npm audit fix updated the lockfile and reported zero vulnerabilities. Python pip/setuptools were upgraded. pip-audit with an explicit site-packages path found no known vulnerabilities, skipping only the editable application. Default audit collection hung in this sandbox and was interrupted; the explicit-path audit completed.

Privacy scan examined 2,963 file versions with zero credential-pattern or newly introduced personal-information findings. Public upstream baseline attribution/sample data is reported separately: 363 email matches and 60 example home paths across historical/working copies. Values are not printed. Pattern scanning cannot prove absence of every possible secret or personal datum. Checks are scoped developer-run adversarial tests, not independent penetration-test certification.

## Scope and phase gates

Each milestone is gated by unit/integration tests, a CLI or API smoke test, adversarial tests for its attack surface, static source analysis, dependency advisories, and a Git working-tree/history credential and PII scan. These are developer-run application security checks, not an independent penetration-testing certification. No tests attack NSE, Yahoo, GitHub, or other third-party infrastructure. Network calls to those services are normal documented read-only application requests.

`python scripts/privacy_scan.py` checks committed file versions and nonignored working files for common credential signatures, private keys, personal filesystem paths, and email addresses. GitHub's public noreply commit identity is expected metadata. This is pattern-based detection and cannot prove absence of every form of personal data. Authentication storage remains outside the repository. Diagnostics and reports must never contain actual credentials.

Run `python -m bandit -r src -q`, `python -m pip_audit --local --skip-editable`, the test suite, Ruff, mypy, and the privacy scan before each milestone commit. The audit tools are development-only dependencies. Dependency results are time-specific advisory snapshots.

## Milestone 1 audit

Surface: local CLI, YAML/environment input, official constituent HTTP downloader, and SQLite. There was no application HTTP listener to remotely probe.

Fixed findings:

- Configuration validation printed rejected raw values, which could include a credential supplied by the operator. CLI validation errors now contain only field paths and error types.
- Constituent source URLs accepted arbitrary destinations and followed redirects. Source configuration now restricts HTTPS hosts, ports, credentials, queries and fragments, and redirects are never followed.
- Downloads were not bounded. Streaming reads now reject responses beyond the configured byte limit without committing a partial snapshot.
- HTTP exceptions could echo request URLs. Errors now expose only sanitized failure categories.
- Migration ledger insertion used interpolated packaged metadata. It now uses bound SQL parameters, with atomic rollback retained.
- Special-session offset-bearing times and unknown timezones now fail validation consistently.

Evidence: 53 tests pass, including adversarial YAML tags, URL/redirect abuse, oversized data, SQL injection, and sensitive-value error redaction. Ruff lint/format and strict mypy pass. Bandit reports no source findings. CLI health and session smoke tests pass against the existing initialized local database. The repository scan found no PII/credential findings. Dependency audit initially identified 12 pip and 2 setuptools advisories; upgrading the isolated environment to pip 26.2.1 and setuptools 84.2.0 produced a clean final advisory result.

## Milestone 2 audit

Added tests exercise future/current-bar access, historical revision immutability, naive/NaN/invalid OHLCV rejection, duplicate bars, transaction failure, holiday/session filtering, CSV size bounds, stale/gap/zero-volume diagnostics, split/bonus/dividend effects, announcement/ex-date gating, and the explicit yfinance request contract. Corporate-action source records and candle versions are preserved. Provider errors cannot enable trading. CSV imports are data-only; no eval or object deserialization is used.

Smoke: migrated the existing database to schema 2 and downloaded 12 NIFTY 50 daily bars using the real provider. Historical data correctly reports stale for the current clock. A recorded provider limitation is that Yahoo history is split-adjusted and revised; this is flagged in each downloaded batch rather than misrepresented as exchange point-in-time data.

## Milestone 3 audit

Indicator calculations accept only chronological, unique, closed candles of one symbol/timeframe. Every supplied context series is checked against the decision clock. Tests mutate a future price and verify it cannot influence a prefix. Warmup and unavailable context values are explicit nulls; missing VIX, sector, expiry and benchmark inputs are never fabricated. Opening range is withheld until its full contiguous interval closes. Session VWAP resets each day. Compact state is deterministic and bounded by 380 UTF-8 bytes, a conservative budget below 400 byte-level tokens. Feature JSON rejects NaN/Infinity.

Verification covers indicator reference values, flat/zero-loss RSI, incomplete periods, session reset, prior-day context, matched-timestamp relative strength, opening-range gating, deterministic compact state, and future-context rejection. The offline feature CLI is the smoke surface; no HTTP listener exists yet.

## Milestone 4 audit

All entries, including queued orders at fill time, pass deterministic risk validation. Tested adversarial cases include CNC shorting, reference-index trading, missing stops, zero/negative quantities, NaN reference prices, oversized positions, excessive per-trade loss, missing liquidity, daily/weekly/drawdown limits, cooldown, duplicate order IDs, circuit and halt conditions, and results blackouts. No live venue adapter exists. Protective exits are independent of AI and remain subject to simulated liquidity. Short-sale proceeds do not become spendable cash.

Smoke and numerical checks cover entry-to-exit account reconciliation for MIS longs and shorts, delivery cash accounting, multi-bar partial fills, per-order brokerage caps, DP deduplication, next-bar entry, triggered/limit orders, gap-through stops, conservative ambiguous bars, trailing protection, and MIS square-off. Four fee examples are checked against hand calculations. See [charges.md](charges.md) for dated sources and approximation boundaries. Full suite: 83 tests; source, lint and strict type checks pass.
