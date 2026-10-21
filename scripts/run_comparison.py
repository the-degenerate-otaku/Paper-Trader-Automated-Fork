from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from paper_trader.cli import main as trader_main
from paper_trader.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]
Profile = Literal["baseline", "research-balanced"]
PORTS = {"baseline": 2081, "research-balanced": 2082}


def checked_profile(name: Profile) -> tuple[Path, Settings]:
    path = ROOT / "profiles" / f"{name}.yaml"
    settings = load_settings(path, ROOT / "profiles" / ".unused-env")
    expected = ROOT / "data" / f"comparison-{name}.sqlite3"
    protected = ROOT / "data" / "paper-trader.sqlite3"
    actual = settings.storage.database_path
    if (
        actual.resolve() != expected.resolve()
        or actual.resolve() == protected.resolve()
        or actual.is_symlink()
        or (actual.exists() and protected.exists() and actual.samefile(protected))
    ):
        raise ValueError("Comparison database must be isolated from the active paper ledger")
    if settings.server.port != PORTS[name]:
        raise ValueError("Comparison port must remain separate from the active app")
    return path, settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an isolated paper comparison profile")
    parser.add_argument("--profile", choices=list(PORTS), required=True)
    parser.add_argument("command", choices=["check", "init", "serve", "health"])
    args = parser.parse_args(argv)
    try:
        path, settings = checked_profile(args.profile)
        if args.command == "check":
            print(
                json.dumps(
                    {
                        "profile": args.profile,
                        "mode": settings.mode,
                        "port": settings.server.port,
                        "database": settings.storage.database_path.name,
                        "risk_per_trade_pct": str(settings.risk.risk_per_trade_pct),
                        "reward_risk_ratio": str(settings.risk.reward_risk_ratio),
                        "max_trades_per_day": settings.risk.max_trades_per_day,
                        "max_hold_minutes": settings.auto_paper.max_hold_minutes,
                        "direction_score_min": settings.system_one.min_direction_prob,
                        "model_retrained": False,
                        "automatically_activated": False,
                    },
                    indent=2,
                )
            )
            return 0
        command = [
            "--config",
            str(path),
            "--env-file",
            str(ROOT / "profiles" / ".unused-env"),
            args.command,
        ]
        if args.command == "init":
            command.append("--offline")
        return trader_main(command)
    except ValueError:
        parser.exit(
            2, "Comparison profile rejected; check configuration and environment overrides.\n"
        )


if __name__ == "__main__":
    raise SystemExit(main())
