import json
from pathlib import Path

import pytest
import yaml

from paper_trader.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_offline_init_and_health(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    content = yaml.safe_load((ROOT / "config.yaml").read_text())
    content["storage"]["database_path"] = str(tmp_path / "app.sqlite3")
    content["session"]["calendar_path"] = str(ROOT / "calendars/nse.yaml")
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(content))
    assert main(["--config", str(config), "init", "--offline"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] >= 2
    assert main(["--config", str(config), "health"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "paper"
    assert result["journal_mode"] == "wal"


def test_naive_session_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(ROOT / "config.yaml"), "session", "--at", "2026-10-19"]) == 1
    assert "timezone-aware" in capsys.readouterr().err
