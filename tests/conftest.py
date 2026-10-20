from pathlib import Path

import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings, load_settings
from paper_trader.storage import Database

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    config = load_settings(ROOT / "config.yaml")
    config.storage.database_path = tmp_path / "test.sqlite3"
    return config


@pytest.fixture
def database(settings: Settings) -> Database:
    database = Database(settings.storage.database_path, settings.storage.busy_timeout_ms)
    database.migrate()
    database.seed(settings, TradingCalendar.load(settings))
    return database
