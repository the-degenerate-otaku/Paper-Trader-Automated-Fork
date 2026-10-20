import os
from pathlib import Path

import pytest
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from paper_trader.api import create_app
from paper_trader.config import Settings


@pytest.fixture
def static_client(settings: Settings, tmp_path: Path) -> TestClient:
    (tmp_path / "asset.txt").write_text("0123456789", encoding="utf-8")
    app = create_app(settings)
    app.router.routes = [
        route for route in app.router.routes if getattr(route, "name", None) != "frontend"
    ]
    app.mount("/", StaticFiles(directory=tmp_path))
    return TestClient(app, base_url="http://127.0.0.1:2080")


@pytest.mark.parametrize(
    "path",
    [
        "/%5C%5Csecurity-test.invalid%5Cshare%5Cprobe",
        "/%5C%5C%3F%5CUNC%5Csecurity-test.invalid%5Cshare",
        "/folder%5C..%5Casset.txt",
        "/asset.txt%00",
    ],
)
def test_unsafe_static_paths_rejected_before_resolution(
    static_client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    def forbidden_resolution(*args: object, **kwargs: object) -> str:
        pytest.fail("Unsafe path reached filesystem resolution")

    with static_client as client:
        assert client.get("/asset.txt").status_code == 200
        with monkeypatch.context() as guard:
            guard.setattr(os.path, "realpath", forbidden_resolution)
            assert client.get(path).status_code == 404


def test_range_budget_and_valid_partial_content(
    static_client: TestClient, settings: Settings
) -> None:
    with static_client as client:
        response = client.get("/asset.txt", headers={"Range": "bytes=2-4"})
        assert response.status_code == 206
        assert response.text == "234"
        assert response.headers["content-range"] == "bytes 2-4/10"
        response = client.get(
            "/asset.txt",
            headers={"Range": "bytes=" + "0" * settings.server.max_range_header_bytes + "a-"},
        )
        assert response.status_code == 431
        assert response.headers["x-content-type-options"] == "nosniff"
        response = client.get(
            "/asset.txt",
            headers=[
                ("Range", "0" * (settings.server.max_range_header_bytes // 2 + 1)),
                ("Range", "0" * (settings.server.max_range_header_bytes // 2 + 1)),
            ],
        )
        assert response.status_code == 431
