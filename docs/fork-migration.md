# Fork migration

Public fork of Open-Agent-Tools/open-paper-trading-mcp at 3c48168bc78e7c34b0c8247543349b02ee5aefd2. Its Apache-2.0 license/history are preserved. Upstream backend, tests and scripts are archived under upstream_reference and excluded from the installed package. The React/MUI frontend supplies reusable application components.

Active src/paper_trader replaces Robinhood, PostgreSQL, Redis and cloud MCP execution paths with local SQLite and an NSE paper engine. Never start the archived backend. Old start/Docker/Actions files describe upstream architecture pending replacement. Local checks are authoritative during migration.

The independent Paper-Trader-Automated prototype remains preserved with milestones 1–4 committed. Its tested components and milestone 5 replay work were migrated here. No private database, credentials, authentication files or runtime logs were copied. Public upstream attribution and sample identifiers are inherited baseline data. Checks distinguish that baseline while flagging credentials in every version and personal information introduced by this fork.

Inherited US/options screens do not imply supported NSE features. Actual completion is recorded in README and docs/security.md.
