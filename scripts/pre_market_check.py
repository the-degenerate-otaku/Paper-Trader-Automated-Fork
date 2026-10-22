from __future__ import annotations

import argparse
import json

import httpx

from paper_trader.readiness import assess_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only local paper-trader pre-market checks")
    parser.add_argument("--port", type=int, default=2080)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{args.port}",
            timeout=15,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            responses = [
                client.get(path) for path in ("/api/health", "/api/paper", "/api/settings")
            ]
            for response in responses:
                response.raise_for_status()
            payloads = [response.json() for response in responses]
            if not all(isinstance(payload, dict) for payload in payloads):
                raise ValueError("Invalid service response")
            report = assess_readiness(*payloads)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
        print(json.dumps({"status": "BLOCKED", "reason": "Local service check unavailable"}))
        return 1
    print(json.dumps(report, indent=2))
    return int(report["status"] == "BLOCKED")


if __name__ == "__main__":
    raise SystemExit(main())
