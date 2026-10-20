from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from paper_trader.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_paths_are_relative_to_config_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_settings(ROOT / "config.yaml")
    assert config.storage.database_path == ROOT / "data/paper-trader.sqlite3"
    assert config.session.calendar_path == ROOT / "calendars/nse.yaml"


def test_environment_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_TRADER__ACCOUNT__STARTING_CAPITAL_INR", "250000")
    monkeypatch.setenv("PAPER_TRADER__ARENA__BOTS", "[]")
    config = load_settings(ROOT / "config.yaml")
    assert config.account.starting_capital_inr == 250000
    assert config.account.currency == "INR"


def test_dotenv_overrides_yaml(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "PAPER_TRADER__ACCOUNT__STARTING_CAPITAL_INR=500000\nPAPER_TRADER__ARENA__BOTS=[]\n"
    )
    assert load_settings(ROOT / "config.yaml", env).account.starting_capital_inr == 500000


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("account", "starting_capital_inr", -1),
        ("account", "currency", "USD"),
        ("session", "last_entry", "16:00"),
        ("session", "weekdays", [7]),
        ("risk", "max_exposure_pct", 101),
        ("risk", "max_position_pct", 90),
        ("risk", "max_position_pctx", 10),
        ("system_one", "endpoint", "https://cloud.example/v1/systemone"),
        ("system_one", "endpoint", "http://127.0.0.1:8000/chat"),
    ],
)
def test_invalid_config_rejected(section: str, key: str, value: object) -> None:
    content = yaml.safe_load((ROOT / "config.yaml").read_text())
    content[section][key] = value
    with pytest.raises(ValidationError):
        Settings(**content)


def test_live_mode_rejected() -> None:
    content = yaml.safe_load((ROOT / "config.yaml").read_text())
    content["mode"] = "live"
    with pytest.raises(ValidationError):
        Settings(**content)
