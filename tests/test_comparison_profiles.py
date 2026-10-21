import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from paper_trader.api import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher(tmp_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "comparison_launcher", ROOT / "scripts/run_comparison.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    (tmp_path / "profiles").mkdir()
    for name in ("baseline", "research-balanced"):
        (tmp_path / "profiles" / f"{name}.yaml").write_bytes(
            (ROOT / "profiles" / f"{name}.yaml").read_bytes()
        )
    return module


@pytest.mark.parametrize("name", ["baseline", "research-balanced"])
def test_check_validates_without_creating_or_touching_a_ledger(launcher, name, capsys):
    assert launcher.main(["--profile", name, "check"]) == 0
    assert not (launcher.ROOT / "data").exists()
    assert '"automatically_activated": false' in capsys.readouterr().out


@pytest.mark.parametrize("name", ["baseline", "research-balanced"])
def test_environment_cannot_redirect_comparison_into_active_ledger(launcher, name, monkeypatch):
    monkeypatch.setenv(
        "PAPER_TRADER__STORAGE__DATABASE_PATH", str(launcher.ROOT / "data/paper-trader.sqlite3")
    )
    with pytest.raises(ValueError, match="isolated"):
        launcher.checked_profile(name)
    assert not (launcher.ROOT / "data").exists()


def test_environment_cannot_reuse_main_port(launcher, monkeypatch):
    monkeypatch.setenv("PAPER_TRADER__SERVER__PORT", "2080")
    with pytest.raises(ValueError, match="port"):
        launcher.checked_profile("research-balanced")


def test_existing_hard_link_to_active_ledger_is_rejected(launcher):
    folder = launcher.ROOT / "data"
    folder.mkdir()
    protected = folder / "paper-trader.sqlite3"
    protected.write_bytes(b"untouched private ledger")
    alias = folder / "comparison-baseline.sqlite3"
    alias.hardlink_to(protected)
    with pytest.raises(ValueError, match="isolated"):
        launcher.checked_profile("baseline")
    assert protected.read_bytes() == b"untouched private ledger"


def test_rejection_does_not_echo_sensitive_config_values(launcher, monkeypatch, capsys):
    secret = "comparison-test-sensitive-value"
    monkeypatch.setenv(
        "PAPER_TRADER__SYSTEM_ONE__ENDPOINT", f"https://{secret}.invalid/v1/systemone"
    )
    with pytest.raises(SystemExit) as exc:
        launcher.main(["--profile", "baseline", "init"])
    assert exc.value.code == 2
    assert secret not in capsys.readouterr().err
    assert not (launcher.ROOT / "data").exists()


@pytest.mark.parametrize("name", ["baseline", "research-balanced"])
def test_profile_init_and_api_smoke_use_only_an_independent_account(launcher, name):
    calendar = launcher.ROOT / "calendars"
    calendar.mkdir()
    (calendar / "nse.yaml").write_bytes((ROOT / "calendars/nse.yaml").read_bytes())
    assert launcher.main(["--profile", name, "init"]) == 0
    _, settings = launcher.checked_profile(name)
    with TestClient(
        create_app(settings), base_url=f"http://127.0.0.1:{settings.server.port}"
    ) as client:
        response = client.get("/api/paper")
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot["positions"] == []
        assert snapshot["orders"] == []
        assert snapshot["automation"]["enabled"] is False
        assert snapshot["portfolio"]["equity"] == str(settings.account.starting_capital_inr)
    assert not (launcher.ROOT / "data/paper-trader.sqlite3").exists()
