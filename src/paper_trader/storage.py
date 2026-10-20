from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings


class Database:
    def __init__(self, path: Path, busy_timeout_ms: int) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def migrate(self) -> int:
        migration_dir = files("paper_trader").joinpath("migrations")
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            current = version or 0
            for resource in sorted(migration_dir.iterdir(), key=lambda item: item.name):
                if not resource.name.endswith(".sql"):
                    continue
                number = int(resource.name.split("_")[0])
                if number <= current:
                    continue
                sql = resource.read_text(encoding="utf-8")
                applied = datetime.now(UTC).isoformat()
                try:
                    connection.executescript("BEGIN IMMEDIATE;\n" + sql)
                    connection.execute(
                        "INSERT INTO schema_migrations VALUES (?, ?, ?)",
                        (number, resource.name, applied),
                    )
                    connection.commit()
                except sqlite3.Error:
                    connection.rollback()
                    raise
                current = number
            return current

    def seed(self, settings: Settings, calendar: TradingCalendar) -> None:
        now = datetime.now(UTC).isoformat()
        capital_paise = settings.account.starting_capital_inr * 100
        if capital_paise != capital_paise.to_integral_value():
            raise ValueError("Starting capital must be expressed in whole paise")
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO accounts "
                "(id, name, currency, starting_capital_paise, cash_paise, created_at) "
                "VALUES ('personal', ?, ?, ?, ?, ?)",
                (settings.account.name, "INR", int(capital_paise), int(capital_paise), now),
            )
            for symbol, index in settings.universe.indices.items():
                connection.execute(
                    "INSERT INTO instruments (symbol, name, instrument_type, lot_size, "
                    "tick_size, provider_symbol) VALUES (?, ?, 'INDEX', 1, ?, ?) "
                    "ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, "
                    "provider_symbol=excluded.provider_symbol",
                    (symbol, index.name, str(settings.execution.tick_size), index.provider_symbol),
                )
            for symbol in settings.universe.custom_symbols:
                connection.execute(
                    "INSERT OR IGNORE INTO instruments "
                    "(symbol, name, instrument_type, lot_size, tick_size, provider_symbol) "
                    "VALUES (?, ?, 'EQUITY', 1, ?, ?)",
                    (symbol, symbol, str(settings.execution.tick_size), symbol + ".NS"),
                )
            for year in calendar.calendar.covered_years:
                connection.execute("DELETE FROM holidays WHERE substr(day, 1, 4)=?", (str(year),))
            connection.executemany(
                "INSERT INTO holidays (day, name, source) VALUES (?, ?, ?)", calendar.holiday_rows()
            )
            connection.execute(
                "INSERT INTO audit_log (created_at, event, payload_json) VALUES (?, ?, ?)",
                (
                    now,
                    "seed",
                    json.dumps({"calendar_verified_on": str(calendar.calendar.verified_on)}),
                ),
            )
