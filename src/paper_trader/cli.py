from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import yaml
from pydantic import ValidationError

from paper_trader.calendar import TradingCalendar
from paper_trader.config import load_settings
from paper_trader.data import CandleStore, CsvProvider, YFinanceProvider, quality
from paper_trader.demo import synthetic
from paper_trader.engine import EmaStrategy, HoldStrategy, ReplayEngine
from paper_trader.features import FeatureEngine
from paper_trader.storage import Database
from paper_trader.trading import ChargesCalculator
from paper_trader.universe import UniverseService, UniverseUnavailable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paper-trader")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--offline", action="store_true")
    commands.add_parser("health")
    session = commands.add_parser("session")
    session.add_argument("--at", type=datetime.fromisoformat)
    universe = commands.add_parser("universe")
    universe.add_argument("--refresh", action="store_true")
    universe.add_argument("--as-of", type=datetime.fromisoformat)
    fetch = commands.add_parser("fetch")
    fetch.add_argument("symbol")
    fetch.add_argument("--timeframe", choices=["1m", "5m", "15m", "1h", "1d"], default="5m")
    fetch.add_argument("--start", type=datetime.fromisoformat, required=True)
    fetch.add_argument("--end", type=datetime.fromisoformat, required=True)
    fetch.add_argument("--csv", type=Path)
    candles = commands.add_parser("candles")
    candles.add_argument("symbol")
    candles.add_argument("--version", required=True)
    candles.add_argument("--timeframe", choices=["1m", "5m", "15m", "1h", "1d"], default="5m")
    candles.add_argument("--at", type=datetime.fromisoformat, required=True)
    features = commands.add_parser("features")
    features.add_argument("symbol")
    features.add_argument("--version", required=True)
    features.add_argument("--timeframe", choices=["1m", "5m", "15m", "1h", "1d"], default="5m")
    features.add_argument("--at", type=datetime.fromisoformat, required=True)
    charges = commands.add_parser("charges")
    charges.add_argument("--turnover", type=Decimal, required=True)
    charges.add_argument("--side", choices=["BUY", "SELL"], required=True)
    charges.add_argument("--product", choices=["MIS", "CNC"], required=True)
    charges.add_argument("--date", type=date.fromisoformat, required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--start", type=datetime.fromisoformat, required=True)
    demo.add_argument("--sessions", type=int, default=3)
    demo.add_argument("--strategy", choices=["hold", "ema"], default="ema")
    backtest = commands.add_parser("backtest")
    backtest.add_argument("symbol")
    backtest.add_argument("--version", required=True)
    backtest.add_argument("--timeframe", choices=["1m", "5m", "15m", "1h", "1d"], default="5m")
    backtest.add_argument("--end", type=datetime.fromisoformat, required=True)
    backtest.add_argument("--strategy", choices=["hold", "ema"], default="hold")
    backtest.add_argument("--benchmark", action="append", default=[])
    args = parser.parse_args(argv)
    if args.command == "universe" and args.refresh and args.as_of:
        parser.error("--refresh and --as-of cannot be combined")
    try:
        settings = load_settings(args.config, args.env_file)
        calendar = TradingCalendar.load(settings)
        database = Database(settings.storage.database_path, settings.storage.busy_timeout_ms)
        now = datetime.now(UTC)
        if args.command == "charges":
            charge_result = ChargesCalculator(settings.charges).calculate(
                args.turnover, args.side, args.product, args.date
            )
            print(
                json.dumps(
                    {
                        "schedule": charge_result.schedule_id,
                        "total_inr": str(charge_result.total),
                        "items": {key: str(value) for key, value in charge_result.items.items()},
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "session":
            print(json.dumps(asdict(calendar.status(args.at or now)), indent=2))
            return 0
        if args.command != "init" and not database.path.exists():
            raise ValueError("Database missing; run paper-trader init first")
        if args.command == "init":
            version = database.migrate()
            database.seed(settings, calendar)
            print(json.dumps({"schema_version": version, "database": str(database.path)}))
            if args.offline or not settings.universe.include_constituents:
                return 0
        if args.command == "health":
            with database.connect() as connection:
                result = {
                    "mode": settings.mode,
                    "schema_version": connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0],
                    "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                    "foreign_keys": bool(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
                    "database_bytes": database.path.stat().st_size,
                    "calendar_covered": calendar.is_covered(now.astimezone(calendar.zone).date()),
                    "calendar_verified_on": str(calendar.calendar.verified_on),
                    "session": asdict(calendar.status(now)),
                    "inference": "not integrated until milestone 6",
                }
            print(json.dumps(result, indent=2))
            return 0
        if args.command in {"demo", "backtest"}:
            store = CandleStore(database, calendar)
            if args.command == "demo":
                if args.sessions < 1 or args.sessions * 75 > settings.data.max_fetch_bars:
                    raise ValueError("Demo sessions exceed configured data budget")
                batch = synthetic(settings, args.start, args.sessions)
                with database.connect() as connection:
                    connection.execute(
                        "INSERT OR IGNORE INTO instruments VALUES "
                        "('DEMO', 'Synthetic demo', 'EQUITY', 'SYNTHETIC', NULL, "
                        "'EQ', 1, ?, NULL, NULL, 'DEMO')",
                        (str(settings.execution.tick_size),),
                    )
                data_version = store.save(batch)
                bars = batch.candles
                versions = {"DEMO": data_version}
            else:
                bars = store.read(args.version, args.symbol, args.timeframe, args.end)
                versions = {args.symbol: args.version}
                for item in args.benchmark:
                    symbol, version_id = item.split(":", 1)
                    bars += store.read(version_id, symbol, args.timeframe, args.end)
                    versions[symbol] = version_id
            if not bars:
                raise ValueError("No closed candles in the selected dataset")
            strategy = EmaStrategy(settings) if args.strategy == "ema" else HoldStrategy()
            replay = ReplayEngine(settings, calendar, database, bars, versions, strategy)
            report = asyncio.run(replay.run())
            print(
                json.dumps(
                    {key: value for key, value in report.items() if key not in {"curve", "trades"}},
                    indent=2,
                    allow_nan=False,
                )
            )
            return 0
        if args.command in {"fetch", "candles", "features"}:
            store = CandleStore(database, calendar)
            with database.connect() as connection:
                if not connection.execute(
                    "SELECT 1 FROM instruments WHERE symbol=?", (args.symbol,)
                ).fetchone():
                    raise ValueError("Unknown instrument; add it to custom_symbols and rerun init")
            if args.command == "fetch":
                provider = (
                    CsvProvider(args.csv, settings, calendar)
                    if args.csv
                    else YFinanceProvider(settings, calendar)
                )
                data_version = store.update(
                    provider, args.symbol, args.timeframe, args.start, args.end
                )
                visible = store.read(data_version, args.symbol, args.timeframe, args.end)
                print(
                    json.dumps(
                        {
                            "version": data_version,
                            "bars": len(visible),
                            "health": asdict(quality(visible, calendar, now)),
                        },
                        indent=2,
                    )
                )
            else:
                visible = store.read(args.version, args.symbol, args.timeframe, args.at)
                if args.command == "features":
                    feature_snapshot = FeatureEngine(settings, calendar).calculate(visible, args.at)
                    print(
                        json.dumps(
                            {
                                "symbol": feature_snapshot.symbol,
                                "at": feature_snapshot.at.isoformat(),
                                "values": feature_snapshot.values,
                                "regime": feature_snapshot.regime,
                                "state": feature_snapshot.state,
                            },
                            indent=2,
                            allow_nan=False,
                        )
                    )
                else:
                    print(json.dumps([c.model_dump(mode="json") for c in visible], indent=2))
            return 0
        failed = False
        with httpx.Client(follow_redirects=True) as client:
            service = UniverseService(settings, database, client)
            for index in settings.universe.indices:
                try:
                    if args.command == "init" or args.refresh:
                        snapshot = service.refresh(index, force=getattr(args, "refresh", False))
                    else:
                        snapshot = service.as_of(index, args.as_of or now)
                    print(json.dumps(snapshot.to_dict(), indent=2))
                    failed = failed or snapshot.error is not None or snapshot.stale
                except UniverseUnavailable as exc:
                    failed = True
                    print(json.dumps({"index_symbol": index, "error": str(exc)}), file=sys.stderr)
        return 1 if failed else 0
    except ValidationError as exc:
        errors = [
            {"field": ".".join(map(str, item["loc"])), "type": item["type"]}
            for item in exc.errors(include_input=False, include_context=False)
        ]
        print(json.dumps({"error": "Invalid configuration", "details": errors}), file=sys.stderr)
        return 1
    except (ValueError, OSError, sqlite3.Error, yaml.YAMLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
