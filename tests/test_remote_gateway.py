import httpx
import pytest
from fastapi.testclient import TestClient

from paper_trader.remote_gateway import create_gateway

ORIGIN = "https://example.github.io"
KEY = "test-only-access-key-with-at-least-32-characters"


def test_gateway_requires_auth_and_preserves_local_upstream_boundary():
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json={"positions": []})

    app = create_gateway(KEY, ORIGIN, transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        assert client.get("/api/paper").status_code == 401
        auth = {"Authorization": f"Bearer {KEY}", "Origin": ORIGIN}
        response = client.get("/api/paper", headers=auth)
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
        assert response.headers["Cache-Control"] == "no-store"
        assert seen[-1].url.host == "127.0.0.1"
        assert seen[-1].headers["origin"] == "http://127.0.0.1:2080"
        assert "authorization" not in seen[-1].headers
        assert (
            client.get("/api/paper", headers={**auth, "Origin": "https://evil.invalid"}).status_code
            == 403
        )
        assert client.post("/api/paper/orders", headers=auth, json={}).status_code == 403
        assert (
            client.post(
                "/api/paper/orders", headers={**auth, "X-Paper-Request": "1"}, json={}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/paper/orders", headers={**auth, "X-Paper-Request": "1"}, content=b"x" * 65537
            ).status_code
            == 413
        )
        assert client.get("/.env", headers=auth).status_code == 404


def test_preflight_and_unauthorized_rate_limit_do_not_lock_out_valid_key():
    app = create_gateway(
        KEY, ORIGIN, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    )
    with TestClient(app) as client:
        response = client.options(
            "/api/paper",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert response.status_code == 200
        assert (
            client.options(
                "/api/paper",
                headers={"Origin": "https://evil.invalid", "Access-Control-Request-Method": "GET"},
            ).status_code
            == 400
        )
        for _ in range(30):
            assert client.get("/api/paper").status_code == 401
        assert client.get("/api/paper").status_code == 429
        assert (
            client.get("/api/paper", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
        )


def test_redirects_and_upstream_failures_are_sanitized():
    for transport, expected in [
        (
            httpx.MockTransport(
                lambda _: httpx.Response(302, headers={"Location": "https://evil.invalid"})
            ),
            502,
        ),
        (
            httpx.MockTransport(
                lambda r: (_ for _ in ()).throw(httpx.ConnectError("private-detail", request=r))
            ),
            503,
        ),
    ]:
        with TestClient(create_gateway(KEY, ORIGIN, transport=transport)) as client:
            response = client.get("/api/paper", headers={"Authorization": f"Bearer {KEY}"})
            assert response.status_code == expected
            assert "private-detail" not in response.text and "evil.invalid" not in response.text


@pytest.mark.parametrize(
    "origin,port,key",
    [
        ("http://example.github.io", 2080, KEY),
        (ORIGIN + "/path", 2080, KEY),
        (ORIGIN, 80, KEY),
        (ORIGIN, 2080, "short"),
    ],
)
def test_gateway_settings_reject_unsafe_origins_and_weak_keys(origin, port, key):
    with pytest.raises(ValueError):
        create_gateway(key, origin, port)
