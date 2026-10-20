import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

from paper_trader.cli import main
from paper_trader.config import Settings, load_settings
from paper_trader.storage import Database
from paper_trader.universe import UniverseService, UniverseUnavailable

ROOT = Path(__file__).resolve().parents[1]


def test_validation_does_not_echo_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = yaml.safe_load((ROOT / "config.yaml").read_text())
    sentinel = "private-value-do-not-echo"
    content["system_one"]["endpoint"] = f"http://user:{sentinel}@127.0.0.1:8000/v1/systemone"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(content))
    assert main(["--config", str(path), "health"]) == 1
    output = capsys.readouterr()
    assert sentinel not in output.err + output.out
    assert json.loads(output.err)["error"] == "Invalid configuration"


def test_yaml_object_tags_cannot_execute(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("!!python/object/apply:builtins.print ['payload']")
    with pytest.raises(yaml.YAMLError):
        load_settings(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "https://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "https://www.niftyindices.com.evil.example/list.csv",
        "https://user:secret@127.0.0.1/list.csv",
        "https://www.niftyindices.com/list.csv?token=secret",
    ],
)
def test_constituent_ssrf_urls_rejected(url: str) -> None:
    content = yaml.safe_load((ROOT / "config.yaml").read_text())
    content["universe"]["indices"]["NIFTY50"]["constituents_url"] = url
    with pytest.raises(ValidationError):
        Settings(**content)


def test_redirect_to_private_network_is_never_followed(
    settings: Settings, database: Database
) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        with pytest.raises(UniverseUnavailable):
            UniverseService(settings, database, client).refresh("NIFTY50")
    assert len(requests) == 1
    assert requests[0].startswith("https://www.niftyindices.com/")


def test_oversized_response_rejected_atomically(settings: Settings, database: Database) -> None:
    settings.universe.max_csv_bytes = 64
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="a" * 65))
    ) as c:
        with pytest.raises(UniverseUnavailable):
            UniverseService(settings, database, c).refresh("NIFTY50")
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM universe_snapshots").fetchone()[0] == 0


def test_symbol_sql_injection_remains_data(settings: Settings, database: Database) -> None:
    with httpx.Client() as client:
        service = UniverseService(settings, database, client)
        with pytest.raises(UniverseUnavailable):
            service.as_of("'; DROP TABLE accounts; --", datetime.now(UTC))
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
