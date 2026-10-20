from __future__ import annotations

import argparse
import json

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port", type=int, default=2080, choices=range(1024, 65536), metavar="PORT"
    )
    args = parser.parse_args()
    results = []
    with httpx.Client(
        base_url=f"http://127.0.0.1:{args.port}", trust_env=False, follow_redirects=False, timeout=5
    ) as client:
        for path in (
            "/.env",
            "/config.yaml",
            "/.git/config",
            "/src/paper_trader/config.py",
            "/upstream_reference/app/core/config.py",
            "/%2e%2e/config.yaml",
        ):
            response = client.get(path)
            results.append(
                {
                    "case": path,
                    "status": response.status_code,
                    "passed": response.status_code == 404,
                }
            )
        cases = [
            ("csrf", {}, b"{}", 403),
            (
                "cross_origin",
                {"X-Paper-Request": "1", "Origin": "https://evil.example"},
                b"{}",
                403,
            ),
            ("host_rebinding", {"Host": "evil.example", "X-Paper-Request": "1"}, b"{}", 403),
            ("body_limit", {"X-Paper-Request": "1"}, b"x" * 65537, 413),
        ]
        for name, headers, content, expected in cases:
            response = client.post("/api/run", headers=headers, content=content)
            results.append(
                {
                    "case": name,
                    "status": response.status_code,
                    "passed": response.status_code == expected,
                }
            )
        for origin in (None, "https://evil.example"):
            headers = {
                "Connection": "Upgrade",
                "Upgrade": "websocket",
                "Sec-WebSocket-Version": "13",
                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            }
            if origin:
                headers["Origin"] = origin
            response = client.get("/api/ws", headers=headers)
            results.append(
                {
                    "case": "websocket_origin",
                    "status": response.status_code,
                    "passed": response.status_code == 403,
                }
            )
        response = client.get("/api/terminal")
        results.append(
            {
                "case": "safe_read_and_headers",
                "status": response.status_code,
                "passed": response.status_code == 200
                and response.headers.get("x-content-type-options") == "nosniff",
            }
        )
    print(json.dumps({"target": "local application only", "checks": results}, indent=2))
    return int(not all(row["passed"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
