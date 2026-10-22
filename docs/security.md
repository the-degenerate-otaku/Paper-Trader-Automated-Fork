# Security and smoke verification

## Shared-portfolio historical and stress replay - 2026-10-22

Added an isolated research runner for the existing local Laya and EMA controls at one-minute/five-minute signals and five/twenty-five-minute holding limits. Four portfolios share capital across a fixed three-stock basket within each arm. Historical capital carries across sessions; constructed stress cases reset separately. The protocol, source, calendar, sector metadata and market files are hashed before inference. Native five-minute history supplies older warm-up only; subsequent aggregation requires complete original minutes. Both arms refuse checkpoints when either lacks healthy closed history. No future prices are passed to features or model requests.

Stress conditions cover opening gaps, reversals, extreme volatility, late-session movement, volume drought, additional slippage, inference outage, feed outage and halts. Missing observations cannot create fills. Halted bars have zero volume and deterministic halt rules. Protective stops and timed reductions remain outside AI; opposite decisions reduce without flipping. Realized and marked results, unresolved positions, fill costs, accounting invariants and risk vetoes remain visible. This is sparse scheduled inference with minute execution, not a continuous production scheduler or a profitability certification. See session-replay.md for usage and limitations.

The first replay pass exposed cross-symbol same-minute ordering leakage and was stopped and preserved privately as invalidated evidence. Research-only minute batching processes all opening fills before any closing reflex or marks; production exchange code is unchanged. Two additional regressions verify that a same-minute target cannot free a position slot for another stock's earlier opening fill and that incomplete, duplicate or mixed-clock batches fail. Exact compact-state responses can be reused in the corrected run under a new source manifest.

Validation after the clock correction: all 230 Python tests passed, including thirteen new replay tests covering deterministic causal stress paths, valid OHLC, distinct outage/halt behavior, invalid histories, warm-up and native-history leakage, timed exits, independent stops, unresolved halted positions, opposite reductions, expired entries, shared cross-symbol limits and minute batching. The inherited Starlette/httpx deprecation warning remains. Ruff lint/format, strict source mypy and Bandit passed. Python and frontend dependency advisory audits found no known published vulnerabilities; the editable local project is validated by source checks rather than PyPI auditing. All thirteen local HTTP security checks passed. Repository/history scanning found no blocking credentials or PII. Direct CLI smoke rejected a changed frozen protocol and output outside ignored work storage before inference.

The instrument database opens read-only. No application order, active configuration edit, database migration, model training or production restart occurs. Market files, generated financial reports and model requests/responses remain private under ignored work storage. The active account was verified flat with automation stopped, feed connected and all balances unchanged during replay. No frontend, new model, committee, Linux runtime or external trading integration was tested.

The corrected batch completed all eleven episodes: one three-session historical portfolio replay and ten separately reset constructed stress cases. Strict gaps excluded the first historical session entirely, leaving effective trading observations from two days. There were 126 model evaluations using 123 distinct successful responses: 41 new requests and 85 exact-input cache hits, including earlier-pass responses and three repeated inputs. No inference failed. All 176 accounting invariants passed across 44 isolated portfolios, with no unresolved positions or open orders. Source/input hashes verified against the frozen manifest. The four-trade historical five-minute result and weaker stress outcomes do not justify promotion. Private Tailscale probes still returned 401 anonymously and 200 with authentication.

## Paired candle sizes and 25-minute exits - 2026-10-22

Added a research-only comparison of recalculated one-minute/five-minute signals and current/25-minute maximum holding limits. The same original minute data, common MIS history window, full 200-bar signal warm-up and one-minute execution apply to both variants. Aggregation rejects duplicate or mixed-basis inputs and omits incomplete buckets without padding. Fixed signal boundaries, complete future windows and observed membership are selected before inference. Each actual model response is shared across execution/exit variants; failures remain no-entry outcomes. Joint unresolved exclusions and both-model-valid subsets keep comparisons paired.

The ledger opens read-only. Outputs, captured model responses and financial results stay under ignored work storage. No application orders, live profile edits, weight training or service restarts occur. Stops, targets, next-eligible fills, costs and deterministic risk remain independent of AI. The 25-minute rule requests a timed exit; liquidity and eligible-fill timing can delay execution. Configuration and source/data hashes retain provenance. Single-session coverage, revised Yahoo candles and independent portfolios limit interpretation; no live trading advantage is established.

Validation: 217 local Python tests passed with the inherited Starlette/httpx deprecation warning. Six new tests verify exact OHLCV aggregation, incomplete buckets, duplicate/mixed-basis rejection, closed-bar/no-future-leak invariants, full warm-up, strict gap handling, shared MIS history cutoff, longer timed exits and earlier protective stops. Ruff check/format, strict mypy and Bandit passed. npm audit and pip-audit found no known published dependency vulnerabilities; local source is covered by static/tests checks rather than PyPI auditing. Thirteen local HTTP security checks passed. Repository/history privacy scanning found no blocking findings. No frontend, Linux execution or model fine-tuning was tested. See timeframe-comparison.md for the frozen protocol and limitations.

The experiment retained 130 successful actual-model responses across 65 input pairs after retrying two missing responses against the exact frozen case set. Original timeout/unavailable results remain in a separately preserved first pass. One unresolved simulated outcome excluded its opportunity from all variants, leaving 64 common resolved pairs. Frozen-input tampering was rejected before inference in a direct CLI smoke check. Report source and case hashes verified. The live account remained flat with automation stopped, feed connected and balances unchanged.

## Paired Laya entry ablation - 2026-10-22

Added an offline four-arm entry-policy comparison with identical execution settings, a valid-response subset and seeded trade-count controls. Sampling precedes future profitability and model availability checks. Explicit entry/flat contexts, non-overlapping symbol windows, closed recorded inputs, complete outcome windows and paired unresolved exclusions prevent obvious context/lookahead errors. Historical response completion timestamps delay every arm equally. Real symbols and recorded reference prices are supported by the isolated simulator. The underlying live trading engine and active profile are unchanged.

The original journal opens read-only; no application orders, inference requests, migrations, weight training or profile activation occur. Output and synthetic-cache paths are restricted to ignored work storage. Recorded financial results remain private. Source/profile/data hashes and coverage exclusions are retained. Legacy contexts are excluded rather than guessed. Latest revised outcome candles, original scheduler selection, one real session and previously inspected synthetic paths limit the inference; no profitability or statistical-significance claim is made.

Validation: 211 Python regression tests passed with the inherited Starlette/httpx deprecation warning. Seven new tests cover deterministic rule parity, response failure, agreement filtering, response-time execution, outcome-independent sampling, paired unresolved exclusions and seeded matched-count controls. Ruff check/format, strict mypy and Bandit passed; npm audit and pip-audit found no known published dependency vulnerabilities. The local editable project is covered by source checks rather than PyPI auditing. Thirteen local HTTP security checks passed. Repository/history privacy checks found no blocking findings. No frontend, Linux runtime or newly trained model was tested in this phase. See laya-ablation.md for usage and limitations.

## Accounting corrections and isolated scenario lab - 2026-10-22

Validated a read-only account audit and fixed protective partial-fill brokerage state and completed-position loss-streak accounting. Protective state survives serialization, reconstructs from legacy partial fills and resets its identity by session date. Restoration repairs the derived streak without rewriting recorded fills, charges, cash or realized P&L. Regression coverage checks exact allocation, cash reconciliation, cap continuity, legacy state, aggregate loss semantics and audit immutability.

The lab runs only isolated synthetic PaperExchange portfolios and loopback Laya requests. It does not initialize or write any comparison/live database. Outputs are restricted to ignored work paths; each response is shared across profiles, checkpoint/model probabilities are validated and failures cannot create labels or simulated entries. Chronological synthetic folds and separate training/validation/test exports retain explicit provenance and cost-aware label definitions. The actual paper feedback export never invents counterfactual direction labels. Reports and training data remain private. Default trading parameters and model weights are unchanged. Results and limitations are documented in scenario-lab.md; lower simulated loss caused by abstaining is not a trading edge.

Validation: 204 Python tests passed, with the existing Starlette/httpx deprecation warning. The six scenario tests passed again after replacing the deterministic generator with NumPy. Ruff check/format, strict mypy, Bandit, npm audit and pip-audit passed. The repository/history privacy scan found no blocking findings. The actual pinned local Laya model completed 60 inference probes; twelve additional injected gap/outage probes refused entry. Four profiles used identical responses for each valid probe. Model weights and active strategy settings were not promoted.

After market close, the flat account with automation already stopped was reloaded to activate the accounting fixes. Cash, equity, realized P&L and charges were preserved and the read-only audit passed again. Thirteen localhost HTTP security checks passed. Private Tailscale HTTPS returned 200 with authentication and 401 without it. The previously connected feed was reconnected through the normal request boundary. No frontend, live broker integration, model weight training or Linux execution was tested in this phase.

## Remembered phone login and private Tailscale access - 2026-10-21

Remember this device is unchecked by default. After an authenticated backend probe succeeds, opting in stores the address and bearer key together in this browser's local storage. Reload reconnects with the saved credentials. Disconnect clears the in-memory connection but preserves the stored login as requested; Forget this device removes the stored credential and disconnects. The last-used nonsecret address remains separately saved. Blocked storage and malformed saved data are handled; storage errors do not echo credentials. This persistent storage is readable by scripts on the same origin and is intended only for the user's own protected devices. It is not an encrypted credential vault.

The installed Tailscale client was connected and Serve was enabled after the user completed its HTTPS authorization. Serve forwards privately to the existing authenticated loopback gateway. Live HTTPS probes returned 401 without a key and 200 with a valid key and the permitted Pages origin. No public Cloudflare tunnel or Funnel was started. No real keys or machine-specific connection addresses are committed.

Validation: 191 Python regression tests and three frontend authentication/storage tests pass. The browser flow used a dummy key through a temporary read-only loopback test gateway: opt-in, reload reconnect, Disconnect preserving login, reload after Disconnect and Forget followed by reload all behaved correctly. Mobile 390px, tablet 768px and desktop 1440px layouts had no page overflow. Lighthouse production-preview performance and accessibility both scored 100. Frontend ESLint, TypeScript and production Pages build pass; npm audit and the Python environment audit report no known vulnerabilities. Repository/history privacy scan has no blocking findings; inherited public-upstream findings remain separately identified. No paper order was placed and no trading configuration changed. Physical-phone use remains user verified.

## GitHub Pages frontend and phone gateway - 2026-10-21

The user authorized pushing the research commits into main and publishing the frontend on GitHub Pages while keeping the backend/model on this PC. The Pages artifact contains only the frontend build. GitHub refused the initial workflow upload because the existing OAuth login lacks workflow scope; the unpushed commit was amended to retain that template under docs/ and use supported built-file branch publishing with existing repository permissions. No published history was rewritten. A separate loopback-only gateway requires a random private bearer key and forwards API routes to the existing local backend without weakening its Host/origin/CSRF checks. Public-tunnel activation was rejected by automatic approval review pending explicit approval for portfolio data and paper-trading commands to transit Cloudflare. That approval is requested separately; no tunnel start is claimed here.

191 tests passed. Gateway adversarial coverage includes unauthenticated requests, unauthorized origins, required mutation headers, request bounds, blocked non-API paths, CORS preflight, authentication throttling without locking out valid keys, rejected redirects, sanitized backend failures, weak keys and invalid configuration. An actual loopback smoke check rejected an unauthenticated portfolio request with 401 and returned an authenticated snapshot. No order or trade was submitted by that smoke. The existing httpx/TestClient deprecation warning remains.

Ruff lint/format, strict mypy, Bandit, targeted frontend ESLint, TypeScript and the Pages production build passed. Python/npm audits reported no known advisories. The pre-existing research bundle-size advisory remains. Repository/history scanning found no new blocking credentials or PII. The private access key lives under ignored .secrets; the browser holds it only in memory, sends it as an Authorization header and clears it on disconnect/reload. The remote research account cache is disabled. Only the nonsecret backend origin is saved in localStorage. Neither key nor endpoint is injected into the public build. A failed connection never substitutes prices or creates fills.

The production preview was inspected at 390, 768 and 1440 pixels without page overflow; invalid connection addresses are rejected before a request is sent. Lighthouse 13.5.0 measured performance 100 and accessibility 100 with both mobile and desktop presets against the local production preview. Placeholder contrast was aligned with the existing muted text token. The new screen reuses DESIGN.md tokens, existing typography and native controls. No independent penetration-test certification, physical-phone session or publicly tunneled account session is claimed without subsequent verification.

## Research phase 1 - 2026-10-21

The interrupted partial patch was discarded from the clean comparison commit and rebuilt. The new entry economics gate runs in the shared risk engine at submission and fill time. Both long and short target/stop paths include dated charges, slippage, tick rounding, volume/ATR buffers and a bounded partial-fill model. The candidate's optional portfolio stop-risk cap includes queued entries, retains unfilled risk through partial fills, releases cancelled risk and fails closed for unknown legacy reservations. Reduce-only exits bypass the entry-only checks. Default and baseline gates remain disabled. No active database, model weights or main branch was changed.

Economic diagnostics, configuration fingerprints and model/schema/membership provenance persist with local events. The estimates and planned heat are not maximum-loss guarantees. Actual future fills and net performance are unverified. The current frontend is unchanged; API diagnostics and candidate-profile smoke cover this phase.

Final verification: 184 tests passed, including long/short cost vetoes, zero-cost finite outputs, bounded fill estimates, cumulative brokerage caps, repricing at fill time, pending-risk reservations, partial-fill accounting, cancellation, unknown legacy reservations, reduction availability, restart persistence and isolated baseline/candidate API smoke. The API smoke confirms the candidate enables cost screening and a 1.5% planned-risk cap while the baseline leaves both disabled. A preceding run passed 183 tests; the final run includes the additional continuing-brokerage test and final preservation refinements. TestClient reports an existing httpx deprecation warning.

Ruff lint/format, strict mypy, Bandit and both profile check commands passed. Python and npm advisory audits reported no known vulnerabilities; the editable application is covered by source checks, not a published dependency advisory. TypeScript, frontend ESLint and the production build passed; the existing research chunk-size advisory remains. Privacy/history scanning examined 3,236 file versions and found no blocking credentials or new PII; inherited public examples and attribution remain separately counted. These are scoped developer-run adversarial tests and smoke checks, not independent penetration-test certification. No new market feed, model training, forward performance comparison or remote CI result is claimed.

## Research review and isolated comparison profiles - 2026-10-21

The user requested independent assessment of two supplied Gemini research documents, then chose separate comparison profiles before integration into main. Work is on codex/research-comparison. The original PDFs and extracted text remain outside this repository. The review separates existing functionality from proposed features, checks relevant primary sources, flags unsupported performance/parameter claims and records the model-training limitations.

The frozen baseline and research-balanced YAML files validate against the existing Settings schema. Candidate thresholds are explicitly experimental. config.yaml, application sources, the running bot and model weights are unchanged. Neither new profile is automatically started, and no production comparison ledger has been initialized. The launcher uses separate named ledgers and ports, explicitly avoids the main dotenv path, rejects process-environment redirection into the main ledger or port, detects an existing hard-link alias to the active ledger, and avoids echoing invalid configuration values in its own rejection message. Both profiles are still paper-only and retain the existing 1m live feature pipeline. Research profile parameters do not implement unbuilt 5m processing, cost gates, new context features or AI training.

All 172 tests pass, including nine new guard and initialization/API smoke cases. An initial full run exposed a test-only hostname mismatch: the default testserver host was correctly rejected by the app's host protection. The test now uses each profile's loopback host and configured port; no host protection was relaxed. The clean full rerun passed. Ruff lint/format, strict mypy including the launcher, application/launcher Bandit and the production TypeScript/lint/build passed. The existing lazy research bundle size advisory remains unchanged. Application and normalized inference dependency audits plus npm audit found no known vulnerabilities. Repository/history privacy scanning found no new blocking credentials or PII, and all 13 live local HTTP security probes passed against the unchanged current service.

No forward trading performance comparison, model fine-tuning, trained calibration or positive-expectancy claim has been made. Isolated smoke accounts used temporary test directories, not the active account. Local checks do not constitute independent penetration-test certification. This branch is reviewable and must not be merged into main or selected as the active profile without the requested review.

## Portfolio visual redesign - 2026-10-21

The primary workspace uses semantic React controls, a single centralized token sheet, Manrope from Google Fonts and Lucide icons. Account figures and active positions precede the separate decision journal. Native order fields preserve the existing request contracts, automatic stock preparation, freshness checks and reduce-only review flow. Trade history, execution history, full recent decision history and external chart links remain available. The research workspace retains its prior theme and loads only when selected. No execution-engine settings, account data or authentication material changed.

The requested Uncodixfy instructions were read before installation and contain design guidance only. Its source was pinned to cyxzdev/uncodixfy at e0e028058b5259debdd94b78147c6d6c77bf7da2. The supplied frontend-design repository returned 404; the installed official Anthropic alternative was pinned to anthropics/skills at dbd4588f9e1033efb41dad4bef2f7947c8993d44. The user design rules were saved separately in global Codex instructions. Skill contents are not application dependencies.

Verification: all 163 regression tests passed, plus the production TypeScript build, primary and changed-file ESLint, Ruff and strict mypy. Bandit found no issues in application sources or the inference launcher. A broader scripts scan flags three low-severity subprocess checks in the existing privacy scanner; these refer to its fixed Git argument-list invocation without a shell and are outside the UI change. Application and normalized inference dependency audits and npm audit reported no known vulnerabilities. Repository/history scanning reported no new blocking credentials or PII. All 13 live local HTTP adversarial probes passed, covering private-path exposure, traversal, CSRF, cross-origin requests, host rebinding, body bounds, WebSocket origins and response headers. These are scoped developer checks, not independent penetration-test certification.

The dev server was started and the production app was inspected in the browser at 390, 768 and 1440 pixels. The page had no horizontal overflow; wide tables scroll inside their own region. Browser smoke covered stock search and selection, conditional stop-limit fields, a correctly disabled order button outside the session, 57 order rows, 14 closed trades, 37 executions, expansion to 50 recent decisions and research navigation. No test order was submitted to the user's paper account. Text encoding problems found during review were corrected. Lighthouse measured mobile performance 98 and accessibility 100, and desktop performance 100 and accessibility 100. A first mobile audit scored 69 because a manual bundle configuration eagerly loaded research libraries and font CSS blocked rendering; lazy research loading and nonblocking font loading fixed those findings. The research-only bundle still triggers Vite's size advisory and has not been separately optimized or redesigned. New-commit CI has not yet been observed.

## All-50 scan, position priority and short-duration paper exits - 2026-10-21

The user expanded automation to all 50 Nifty constituents, prioritized active positions over queued opportunities, authorized qualifying Laya opposite-signal exits, and requested smaller targets with larger share quantities. The complete universe and history cache are now 50 stocks. Per-stock freshness prevents one missing quote from blocking the full scan. Active MIS positions are promoted dynamically before queued entries, and history refresh also prioritizes positions then pending orders. In-flight local inference finishes before the next priority selection; quote-driven protective execution remains separate.

Laya receives LONG/SHORT position context for active MIS reviews. A qualifying opposite signal queues only a reduce-only exit, with identity rechecked after inference, duplicate exits suppressed and unfilled entry quantities cancelled first. New bot orders carry a persisted five-minute holding plan; eligible quote processing requests its exit independently of the AI queue and entry toggle. Legacy entries keep their prior plans. Stop distance is 1 ATR, target distance 0.75 ATR, and position-value cap 30%, while planned per-trade risk remains 1% and overall exposure 90%. No forced fills, equity resets, loss erasure or changes to session cutoffs were introduced. Restart display also omits internal inference-claim rows while retaining them for durable deduplication; completed decision actions are visible.

The full 162-case suite passed during implementation. After the final active-review regression and closed-entry-window status adjustment, all 26 live-paper cases passed, plus Ruff, formatting, strict mypy, source/launcher Bandit and the production TypeScript/lint/build. Coverage includes all-50 selection despite a missing quote, promotion of newly active positions, portfolio-aware inference, opposite-signal reduction without reversal, position-change fencing, holding-plan restoration, timeout exits while AI entries are stopped and realistic partial exit fills. Application and normalized inference advisory audits, npm audit and repository/history privacy checks passed. After restart, all 13 live HTTP adversarial probes passed again; the API confirmed a 50-stock universe/cache, five-minute plan, 1 ATR stop, 0.75 target ratio and 30% position cap. Browser smoke showed the all-50 panel, active-position priority and the closed-entry-window status. No new live entry was attempted after the configured 15:00 cutoff. Developer checks are not independent penetration-test certification; CPU load, source limits and actual quote liquidity prevent guaranteed rapid execution or loss recovery.

## Permissive paper-risk experiment - 2026-10-21

Final verification: all 157 tests passed, alongside Ruff, formatting, mypy, source/launcher Bandit, application/inference dependency advisory audits, npm audit and the repository/history privacy scan. All 13 live HTTP security probes passed. The restarted settings API confirmed the full permissive configuration, and the connected AI bot was re-enabled. An earlier full-suite attempt failed on the old configuration-dependent coherence assumption and ended with a Windows faulthandler access violation; the corrected full rerun completed successfully without that timeout hook. New-commit CI has not yet been observed.

The user explicitly chose looser restrictions for more paper trades. config.yaml now raises quantitative risk, concentration, loss, trade-count and correlation allowances and lowers liquidity, spacing and cooldown restrictions. The reversal-score ceiling is 0.70; direction remains 0.50 and conviction LOW. The full before/after settings are in paper-experiment.md. This increases allowed paper losses and exposure, rather than making the strategy low-risk. Fresh data, closed-candle integrity, valid stops, funds/margin, banned instruments, market-session restrictions and paper-only transport remain enforced. Account balances, positions, loss counters and kill-switch state are not reset.

Regression assertions for risk budgets, cooldown timestamps, loss limits and position/exposure coherence now derive their inputs from configuration instead of assuming the prior defaults. The original coherence check had treated a 90% position as invalid only because the previous total exposure cap was lower; the replacement explicitly verifies position value cannot exceed total exposure under either profile. The rules themselves were not bypassed or removed.

## Requested LOW-conviction paper experiment - 2026-10-21

Changed only system_one.min_conviction from MEDIUM to LOW with explicit user authorization. Direction remains 0.5 and reversal-risk maximum remains 0.4; all execution, stop, funds, exposure, session and loss checks remain unchanged. LOW corresponds to an expected ordinal score minimum of zero, so the conviction filter no longer excludes otherwise valid probability distributions in this experiment. This is not a calibrated trading-performance claim.

All 28 inference/live-paper tests, Ruff, mypy, source/launcher Bandit, application/inference advisory audits, npm audit, repository/history privacy scan and 13 live HTTP security probes passed. The restarted settings API confirmed LOW/0.5/0.4 and the bot was re-enabled with its connected source. Account history and protective parameters were preserved. New-commit CI has not yet been observed.

## Requested direction threshold experiment - 2026-10-21

Changed only system_one.min_direction_prob from 0.65 to 0.5 at the user request for a paper-trading experiment. Conviction, reversal-risk, stop, funds, session, exposure and other risk gates remain unchanged. This is a model-score threshold, not a calibrated trade win probability.

All 28 inference/live-paper tests passed. Ruff, mypy and source/launcher Bandit passed. Application and normalized inference dependency audits and npm audit found no known vulnerabilities. Repository/history scanning found no new blocking PII or credentials, and all 13 live HTTP security probes passed. The server was restarted, its settings API confirmed 0.5, and the live feed and AI bot were re-enabled after source connectivity was ready. Existing positions and account history were preserved. This does not force entries or establish trading performance.

## Local Laya top-mover MIS automation - 2026-10-21

The primary manual account now supports opt-in local Laya AI entries for the five largest absolute percentage movers in the observed Nifty 50 universe. Ranking requires all 50 current regular-session quotes and percentage changes. Closed one-minute candles, a complete warmup window and a configured maximum age gate inference; duplicate and future candles cannot create repeated or lookahead decisions. ATR sizing and protective prices pass through existing deterministic funds, liquidity, session, cooldown and risk checks. Model unavailability fails closed. No broker transport or cloud inference was added.

157 tests passed in the complete local suite. New cases cover absolute-mover ranking, incomplete/stale quote sets, unavailable model startup, MIS sizing, preserved manual orders, bot-only cancellation, restart ownership and cancellation, cooldown/stale-quote vetoes, disabled-entry fencing, closed-candle deduplication across restart, future-candle exclusion, gap rejection and cancellation during inference. After measuring the CPU and changing only the inference timeout to five seconds, the live-paper and inference suites passed again (28 tests). Ruff, formatting, strict mypy, source/launcher Bandit and the production TypeScript/lint/build passed. All 13 live HTTP adversarial probes passed, and the existing API boundary protects automation controls.

A separate CPU environment runs laya 0.4.12 with pinned dependencies in requirements-laya.lock. The checkpoint revision is 7b928d828b7b0e022f929d9bd2e44165aa270148. The downloaded 842609220-byte safetensors file matched SHA-256 4fa56de72383a9d3efa9cfa78955733c81b9fc8067a587ca4beb82c78107a24e. Local health reported that revision and actual CPU execution. Three real requests returned valid policy HOLD/LOW_DIRECTION_PROBABILITY responses at approximately 3.54, 2.64 and 2.54 seconds. The bot was then enabled from the browser and journaled real closed-candle HOLD decisions for all five selected movers. No AI-generated entry was observed in that scan.

Both application and inference dependency sets were audited with no known advisories. The CPU torch local-version suffix was additionally normalized to the same upstream release for a complete PyPI advisory lookup, because direct environment auditing skips that vendor-wheel identifier. npm audit also passed. Repository/history scanning found no new blocking credentials or PII; model weights, input/output journals, account state, download/probe logs and caches remain ignored. Browser smoke verified start/status/current movers and the visible decision journal.

The inference launcher is loopback-only and CPU-only, with one resident checkpoint, bounded concurrency/threads and disabled Hub telemetry. No shell-built command or model-provided order parameters are executed. Full decision inputs and responses remain private in SQLite; WebSocket summaries expose only the compact decision journal. Local model smoke was executed on Windows; Linux runtime loading has not been observed here. New-commit GitHub CI has not yet been observed.

Native Laya warned about a clamped checkpoint temperature for choice sets of 11 or more; this client asks three-option choices, and no NSE confidence calibration or profitability has been established regardless. The bot can remain at HOLD. Inference is slower than the original 300ms configuration on this CPU; five seconds accommodates the measured calls without relaxing signal or risk thresholds. Full-session stability, guaranteed protective fills through outages, and calibrated trading performance remain unverified. These are developer-run security/adversarial checks, not independent penetration-test certification.

## Cooldown and stop rejection explanations - 2026-10-21

Manual order rejection responses now explain the configured consecutive-loss cooldown with an exact IST resume timestamp. Invalid-stop messages describe the side-specific absolute-price rule and tick-size rounding. Additional veto codes are retained when a response also has explanatory messages, so one explanation cannot hide another blocker. Existing risk thresholds, account state and entry/exit behavior are unchanged.

New regression cases verify simultaneous cooldown/short-stop explanations, the opposite stop direction for buys, cooldown expiry and preservation of additional vetoes. Targeted live-paper tests passed (13 cases); Ruff, formatting, mypy, Bandit, TypeScript/lint/frontend build, Python/npm dependency audits and all 13 live HTTP security probes passed. The repository/history PII scan found zero new blocking findings. The complete local suite passed all 150 tests. The updated local server restarted successfully and reconnected with all 50 stocks fresh; new-commit GitHub CI has not been observed. These checks are developer-run and do not constitute independent penetration-test certification.

## Automatic stock refresh and understandable risk rejection - 2026-10-21

Selecting a stock in the connected manual terminal now loads liquidity context automatically, refreshes it at the configured interval, and retries failures. Streaming quotes remain independent. Server-side refresh coalescing avoids repeated provider downloads within that interval. The bounded cache preserves contexts required by positions and pending orders when replacing idle stocks. Manual orders still require fresh quotes, valid closed history and all existing risk checks.

The ticket labels protective stop as an absolute stock price and shows estimated loss to stop versus the configured equity risk budget. Rejected risk-limit responses include a plain-language explanation. Estimates exclude gaps, slippage and charges; thresholds were not relaxed.

148 tests passed locally, including regressions for risk messages, cache coalescing and refresh expiry, sanitized failure retries, and preservation of pending-order context. Ruff, formatting, mypy, Bandit and the production TypeScript/lint/build passed. Python and npm audits found no known vulnerabilities. All 13 live HTTP security probes passed; repository/history scanning found zero new blocking PII or credential findings (inherited public examples remain separately classified). Browser smoke verified automatic data loading on stock selection and the original 20-share low-stop risk warning without submitting another order; all 50 quotes were fresh. These developer checks are not independent penetration-test certification. New-commit GitHub CI has not yet been observed.

## Nifty 50 live paper portfolio — 2026-10-21

[CI run 39560185388](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/actions/runs/39560185388) passed on Windows and Linux for source commit f2d8536: 145 tests, locked dependency audits, source/privacy checks, and frontend build including the new paper UI lint gate.

The user narrowed the primary product to a Nifty 50 portfolio and manual buy/sell terminal, with a free source and no broker account. The default UI now shows positions, funds, P&L, orders, closed trades and executions. Historical research is secondary at `/?workspace=research`. The source is Yahoo streaming, explicitly best effort; no direct-NSE feed guarantee, broker API or automatic LLM orders are introduced.

145 tests passed in the final full local suite, including eight live-paper regressions. Tests cover later-quote execution, persisted cash/charges/protective positions/orders, entry/exit and restored state, no fresh-quote bypass after restart, malformed/future/duplicate/out-of-order/decreasing-volume rejection, stale-context vetoes, Nifty membership freshness, protective stops without AI/history, and in-memory rollback on checkpoint-write failure. Stream gaps cannot turn accumulated unseen volume into fill liquidity. Schema 5 uses typed JSON checkpoints plus an event journal; no pickle/eval or user-supplied provider URL is used.

Market-session smoke connected to all 50 observed Nifty stocks, with changing prices and exchange timestamps; all 50 were fresh in a recorded snapshot. Browser smoke submitted a one-share RELIANCE paper buy, observed its later-quote fill and active position, prepared and submitted its closing order, and verified the closed ledger. A repeat entry was blocked by trade-spacing risk. A separate HDFCBANK limit order remained pending and was cancelled from the browser. No open test exposure or pending test order remained. After server restart, the live local API matched prior balances, orders, positions, closed trades and fills, with the source correctly disconnected.

Ruff lint/format, strict mypy, Bandit and the production frontend build passed. The new paper UI's ESLint check is part of `npm run build`, so CI checks it too. Python and npm dependency audits found no known vulnerabilities; all 13 live local HTTP adversarial probes passed again. Repository/history privacy scans are repeated before publication, with inherited public baseline attribution/examples separated from new findings. The primary source uses no account credentials. These are developer-run checks, not independent penetration-test certification, a profitability claim or a full-day source-reliability guarantee.

Historical gaps may conservatively undercount turnover; current manual-quote health is checked separately from older gaps. AI/replay closed-candle quality gates are unchanged. Simulated fills require eligible later observations and positive observed volume; source outages, market closure or illiquidity can delay protective execution. Saved manual paper state restores, while connectivity and liquidity context require operator review/re-establishment. Research replay restart limitations remain separate.

## Stock-chart workspace — 2026-10-20

[Combined source CI run 39467868140](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/actions/runs/39467868140) passed on Windows and Linux for commit bded0ca, including the locked environment, tests, source analysis, privacy/dependency gates and frontend build.

137 tests passed after merging the remote locked-dependency and static-file security fixes, including nine new chart API regressions. Tests cover safe symbols/timeframes, bounded history ranges, redacted provider failure, immutable cache/version selection, rejected refresh of pinned versions, warmup values, and unchanged replay state while browsing/downloading charts. Market downloads run in a worker thread behind a separate operation lock. The app accepts no user-supplied provider URLs. Existing local Host/origin/CSRF/body/WebSocket boundaries apply to the new routes. No TradingView scripts, scraping or widget price extraction were added.

Real public-source smoke refreshed the official 50/14-member constituent lists and downloaded 148 RELIANCE five-minute closed candles. Stale data, gaps and zero-volume bars remained explicit. Browser smoke rendered the real chart, toggled EMA 50 and handed the pinned version to replay, which exposed zero bars before Step and one afterward. Indicator toggles include volume, EMA/SMA, VWAP, Bollinger, Supertrend, RSI/MACD, ATR/ADX and OBV. External TradingView links use a fixed HTTPS destination, encoded symbols and noreferrer.

Ruff lint/format, strict mypy and Bandit passed. Privacy scanning of the merged history/working tree found no blocking findings across 3,130 file versions. The frontend production build and ESLint checks on all active terminal pages passed; Python and npm audits found no known vulnerabilities. All 13 live local HTTP adversarial checks passed again on the combined source. Public inherited baseline findings remain reported separately. These are developer-run application checks, not independent penetration-test certification or verification of live NSE pricing. TradingView's current public widget market list omits NSE; the app uses historical data with visible provenance instead of claiming a live embed.

## Locked-dependency remediation — 2026-10-20

Regenerated the stale lockfile and aligned the Windows tested snapshot. Starlette now
resolves to 1.9.0, with an explicit minimum of 1.3.1; the other advisory-affected
packages were upgraded. CI and the documented setup now install the committed lock
and audit that environment. Existing installations must rerun
`uv sync --locked --extra dev` to receive the fixes.

The HTTP boundary rejects backslashes and NULs before filesystem resolution and
bounds aggregate Range-header bytes using validated configuration. Five regression
cases cover UNC/device paths, traversal, NULs, duplicate Range headers and valid
partial-content responses. Safe probes confirmed zero UNC resolver calls and prompt
431 responses to oversized Range inputs.

Windows verification: 128 tests passed; all 13 live loopback security smoke checks
passed; Ruff, format checks, strict mypy and Bandit passed. The patched environment's
pip-audit reported no known vulnerabilities. Privacy scanning found no blocking
matches across 3,104 file versions before this record was added. The test client
emits an upstream httpx deprecation warning. Linux execution is left to the updated
CI job; local results do not certify remote CI success.

## Milestone 9 — research and final boundaries

Research uses immutable source versions, realized outcomes available at the declared clock, chronological splits and a purged training boundary. Temperature fitting requires an explicit checkpoint revision and enough held-out outcomes. Baseline runs do not produce fabricated model labels or calibration curves. Training exports contain objective labels and sanitized provenance, without local paths or account identifiers. Candidate temperatures are not applied automatically.

All 123 tests passed locally on Windows. Regression checks cover native Laya response identity and routing, numerical stability at extreme temperatures, reference-only benchmark ordering, calibration leakage, outage-independent protective stops and prices that round to zero at the configured tick. Such orders are rejected before entry. Schema 4 preserves checkpoint provenance and content-addressed calibration artifacts.

Windows CLI smoke completed three walk-forward folds and five stress scenarios. A real unreachable local inference endpoint produced zero entries; the separate outage regression verifies protective exits still execute. The browser completed a 225-bar EMA demo with chart indicators and zero remaining exposure. The loopback HTTP adversarial smoke passed all 13 checks, covering private-file/traversal requests, origin/Host/CSRF boundaries, request budgets and WebSocket origins.

Ruff lint/format, strict mypy and Bandit passed. Python dependency audit found no known vulnerabilities, skipping only the editable application; frontend production build, active-page ESLint and npm audit passed with zero advisories. Privacy scanning examined 3,075 file versions with zero blocking findings. Inherited public attribution/examples remain separately counted; pattern scanning is not proof that every possible secret or personal datum is absent. Authentication remains outside Git.

Actual model loading/CPU throughput, real-session continuous NSE polling and automatic restoration of in-memory execution state remain unverified or unsupported. No model training or live order placement was performed. [Milestone 9 CI run 39457905629](https://github.com/the-degenerate-otaku/Paper-Trader-Automated-Fork/actions/runs/39457905629), for source commit 13bceb3, passed on Windows and Linux: tests, Ruff, mypy, Bandit, privacy scanning, Python/npm dependency audits and frontend production build. Local browser smoke supplements CI; CI does not certify live market or model behavior.

## Milestone 8 — scheduler and arena

106 tests passed in the full suite, then added arena API start/immediate-pause smoke and reran affected config/arena/API tests. Tests cover separate accounts, allocation limits, observation clocks, no duplicate ticks, shadow no-fill behavior, pending-entry cancellation, blocked mode transitions, stale-feed and failed-feed vetoes, and rejected future/duplicate/late appends. Prior environment-precedence tests were updated to clear bot allocations when lowering total capital. Allocation validation was retained.

Ruff, strict mypy and Bandit passed; frontend TypeScript/production build and ESLint on active new pages passed. pip-audit and npm audit reported no known advisories. Privacy scan checked 3,048 versions without blocking findings; inherited public baseline remains separately reported. Browser smoke created two independent INR 5,00,000 bots with entries disabled, ran both to the same 39-bar cursor and paused the scheduler with unchanged capital and zero exposure.

Continuous polling is opt-in and refuses synthetic demo sources. Feed errors/staleness prevent new entries; risk/reflex execution is shared with the tested engine. Real-session continuous polling, actual Laya deployment/CPU performance and automatic restoration of in-memory execution state after restart are unverified or unsupported. Ledger records persist for audit. The app is a local paper experiment, not a production broker service.

GitHub CI was replaced with read-only checks for Windows/Linux and inherited social/release/stale workflows were disabled. The browser commit uses GitHub's private noreply email. Remote checks are not counted as passed until observed.

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


## 2026-10-21 code-size and runtime cleanup

Audited the 415 tracked-file snapshot at e1777df1ef82e38c7d438c1cfbc3382a950627ca.
Removed 63 unreachable frontend source/assets/documentation files and one CSS import wrapper;
TypeScript parser traversal independently confirmed the source reachability findings.
Removed the date-picker, date-fns and router direct dependencies used only by those modules.
Kept public API compatibility exports, migration history and the explicitly archived upstream reference.
No trading thresholds, financial arithmetic, persistence schema, origin checks or risk vetoes changed.

Optimized Supertrend array access, chronological validation, corporate-action sorting,
chart marker timestamp lookup, account refresh lookup and redundant loading-state updates.
Calendar configuration is loaded once per metrics report and once per calibration outcome pass.
The primary workspace CSS is unchanged. Fonts now load from the document head.

Validation: 191 backend tests; 95 exact feature/Supertrend comparisons and four exact metrics
comparisons against the original implementation; three frontend connection tests; production
build with full frontend lint; Ruff check/format, mypy and Bandit; 13 localhost HTTP boundary
checks. npm audit and pip-audit reported no known vulnerabilities. Repository/history privacy
scan found no blocking findings. The inherited Starlette/httpx test-client deprecation warning remains.

Browser checks used an isolated database and disconnected feed at 390, 768 and 1440 CSS pixels.
The primary terminal, tab navigation, research overview, synthetic replay and chart toggle worked.
The research replay has existing narrow-screen horizontal overflow: the untouched baseline and
refactor both measured 1316px scroll width at 390px viewport width. Preserved under the explicit
no-visual-change constraint. No Lighthouse score, exhaustive pixel equivalence, real market feed,
local model integration, Linux execution or remote GitHub CI verification is claimed for this pass.
The existing research bundle remains approximately 1.43 MB uncompressed because its chart/grid
libraries are active features. Archived code was statically scanned, not executed or refactored.
