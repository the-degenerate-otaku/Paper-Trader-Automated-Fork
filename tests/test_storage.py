import sqlite3

import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.storage import Database


def test_migration_seed_idempotent_preserves_cash(database: Database, settings: Settings) -> None:
    with database.connect() as connection:
        connection.execute("UPDATE accounts SET cash_paise=123 WHERE id='personal'")
    version = database.migrate()
    assert version >= 2
    database.seed(settings, TradingCalendar.load(settings))
    with database.connect() as connection:
        assert connection.execute("SELECT cash_paise FROM accounts").fetchone()[0] == 123
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == version
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_constraints_and_rollback(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with database.connect() as connection:
            connection.execute("INSERT INTO holidays VALUES ('2099-01-01', 'test', 'test')")
            connection.execute(
                "INSERT INTO constituents_history VALUES (999, 'MISSING', 'a', 'b', 'c')"
            )
    with database.connect() as connection:
        assert not connection.execute("SELECT * FROM holidays WHERE day='2099-01-01'").fetchall()


def test_cnc_cannot_be_short(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO positions VALUES ('personal', 'NIFTY50', 'CNC', -1, '100', '99', NULL)"
            )
