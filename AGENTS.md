# Project rules

Build the supplied NSE paper-only terminal brief in milestone order. The user authorized automatic progression through core milestones 2–9 on 2026-10-20. Run application security/adversarial tests, smoke tests, dependency audits, and repository/history PII/credential checks at every phase. Fix findings before committing and advancing. Record scope, evidence, fixes, and limitations in docs/security.md. Stop on a real blocker requiring user input; never claim unexecuted tests or external integrations work.

No comments in code files. All trading thresholds, charges, calendars, and limits belong in validated configuration. No live order placement code. AI cannot bypass deterministic risk vetoes. Closed candles only; test lookahead failures. Preserve immutable data versions and observation-time membership history. Keep credentials, personal data, logs, and databases outside Git. Check current official sources before relying on external APIs, market rules, or rates. Commit each completed milestone and push to origin. Do not rewrite published history without explicit authorization.

Use the existing Python environment and CLI. Keep the UI and inference independent of the execution engine. Persist a concrete milestone status in README.md. Optional Milestone 10 modules require separate scope confirmation.
