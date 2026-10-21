from __future__ import annotations

import importlib
import os
from pathlib import Path
from urllib.parse import urlparse

import yaml


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    endpoint = urlparse(config["system_one"]["endpoint"])
    if endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Laya must bind to loopback")
    revision = config["system_one"]["checkpoint_revision"]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("A pinned checkpoint commit SHA is required")
    environment = {
        **os.environ,
        "LAYA_HOST": "127.0.0.1",
        "LAYA_PORT": str(endpoint.port or 8000),
        "LAYA_DEVICE": "cpu",
        "LAYA_MODELS": "typed-decisions",
        "LAYA_MAX_LOADED": "1",
        "LAYA_MAX_CONCURRENT": "1",
        "LAYA_THREADS": str(config["auto_paper"]["cpu_threads"]),
        "LAYA_REVISION": revision,
        "HF_HOME": str(root / "work" / "laya-cache"),
        "HF_HUB_DISABLE_XET": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
    }
    os.environ.update(environment)
    importlib.import_module("laya.serve").main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
