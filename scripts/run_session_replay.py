from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from paper_trader.ablation import directions
from paper_trader.calendar import TradingCalendar
from paper_trader.config import InstrumentRule, load_settings
from paper_trader.inference import QUESTIONS, SystemOneStrategy
from paper_trader.market import DataBatch
from paper_trader.session_lab import (
    ReplayBook,
    Scenario,
    SessionProtocol,
    active_shocks,
    market_features,
    stressed,
)

ROOT = Path(__file__).resolve().parents[1]


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


async def run(data: Path, output: Path, prepare_only: bool, resume: bool) -> None:
    config_path = ROOT / "profiles/session-replay.yaml"
    protocol = SessionProtocol.model_validate(yaml.safe_load(config_path.read_text()))
    settings = load_settings(ROOT / "profiles/baseline.yaml", ROOT / "profiles/.unused-env")
    calendar = TradingCalendar.load(settings)
    if (
        len(set(protocol.symbols)) != len(protocol.symbols)
        or sorted(set(protocol.historical_days)) != protocol.historical_days
    ):
        raise ValueError("Require unique symbols and chronological unique sessions")
    if len({s.name for s in protocol.scenarios}) != len(protocol.scenarios):
        raise ValueError("Scenario names must be unique")
    inputs = [
        data / f"{symbol}-{frame}.json" for symbol in protocol.symbols for frame in ("1m", "5m")
    ]
    source_paths = [
        Path(__file__),
        config_path,
        ROOT / "profiles/baseline.yaml",
        ROOT / "src/paper_trader/session_lab.py",
        ROOT / "src/paper_trader/timeframe_lab.py",
        ROOT / "src/paper_trader/trading.py",
        ROOT / "src/paper_trader/features.py",
        ROOT / "src/paper_trader/inference.py",
        ROOT / "src/paper_trader/ablation.py",
        ROOT / "src/paper_trader/calendar.py",
        ROOT / "src/paper_trader/config.py",
        ROOT / "src/paper_trader/data.py",
        ROOT / "src/paper_trader/entry_economics.py",
        ROOT / "src/paper_trader/market.py",
        settings.session.calendar_path,
    ]
    manifest = {
        "protocol": protocol.model_dump(mode="json"),
        "files": {
            str(p.resolve().relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (*inputs, *source_paths)
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    minutes = {
        s: DataBatch.model_validate_json((data / f"{s}-1m.json").read_text()).candles
        for s in protocol.symbols
    }
    fives = {
        s: DataBatch.model_validate_json((data / f"{s}-5m.json").read_text()).candles
        for s in protocol.symbols
    }
    for symbol in protocol.symbols:
        if any(bar.symbol != symbol for bar in (*minutes[symbol], *fives[symbol])):
            raise ValueError("Market file symbol mismatch")
    active = load_settings(ROOT / "config.yaml", ROOT / ".env")
    with sqlite3.connect(
        active.storage.database_path.resolve().as_uri() + "?mode=ro", uri=True
    ) as connection:
        sectors = {
            row[0]: row[1] or "UNKNOWN"
            for row in connection.execute(
                "SELECT symbol,sector FROM instruments WHERE instrument_type='EQUITY'"
            )
        }
    manifest["sectors"] = sectors
    if resume and json.loads((output / "manifest.json").read_text()) != manifest:
        raise ValueError("Frozen data, protocol, sectors or source changed")
    episodes: list[tuple[str, list[date], Scenario | None]] = [
        ("historical", protocol.historical_days, None)
    ]
    episodes.extend(
        (scenario.name, [protocol.stress_day], scenario) for scenario in protocol.scenarios
    )
    coverage = {}
    for name, days, scenario in episodes:
        source = {
            symbol: stressed(bars, scenario, protocol.stress_day, calendar, protocol.random_seed)
            if scenario
            else bars
            for symbol, bars in minutes.items()
        }
        exclusions: Counter[str] = Counter()
        eligible = 0
        for day in days:
            for clock in scenario.decisions if scenario else protocol.decision_times:
                at = datetime.combine(day, clock, calendar.zone)
                if not calendar.status(at).can_enter_mis:
                    exclusions["OUTSIDE_ENTRY_WINDOW"] += len(protocol.symbols)
                    continue
                for symbol in protocol.symbols:
                    try:
                        for frame in ("1m", "5m"):
                            market_features(source[symbol], fives[symbol], settings, at, frame)
                    except ValueError as exc:
                        exclusions[str(exc)] += 1
                    else:
                        eligible += 1
        coverage[name] = {"paired_entry_slots": eligible, "exclusions": dict(exclusions)}
    save(output / "coverage.json", coverage)
    print(json.dumps({"coverage": coverage}), flush=True)
    if prepare_only:
        return
    if not resume:
        if (output / "manifest.json").exists():
            raise ValueError("Use --resume for an existing frozen run")
        save(output / "manifest.json", manifest)
    inference = settings.model_copy(deep=True)
    inference.system_one.timeout_ms = protocol.inference_timeout_ms
    strategy = SystemOneStrategy(inference)
    if not await strategy.health():
        raise ValueError("Local model unavailable")
    cache_dir = output / "cache"
    cache_dir.mkdir(exist_ok=True)
    calls = 0
    hits = 0
    reports: dict[str, Any] = {}
    for name, days, scenario in episodes:
        books: dict[str, ReplayBook] = {}
        for policy in ("ema", "laya"):
            for frame, hold in (
                ("1m", settings.auto_paper.max_hold_minutes),
                ("5m", protocol.new_hold_minutes),
            ):
                cfg = settings.model_copy(deep=True)
                cfg.auto_paper.max_hold_minutes = hold
                books[f"{policy}/{frame}/{hold}"] = ReplayBook(cfg, frame)
        source = {
            symbol: stressed(bars, scenario, protocol.stress_day, calendar, protocol.random_seed)
            if scenario
            else bars
            for symbol, bars in minutes.items()
        }
        by_time = {symbol: {bar.closed_at: bar for bar in bars} for symbol, bars in source.items()}
        episode_dir = output / name
        episode_dir.mkdir(exist_ok=True)
        decisions = set(scenario.decisions if scenario else protocol.decision_times)
        guards: Counter[str] = Counter()
        inference_rows = []
        for day in days:
            now = datetime.combine(day, time(9, 10), calendar.zone)
            end = datetime.combine(day, time(15, 31), calendar.zone)
            while now <= end:
                observed = tuple(
                    by_time[symbol][now] for symbol in protocol.symbols if now in by_time[symbol]
                )
                if observed:
                    for book in books.values():
                        book.exchange.begin_batch(observed)
                for symbol in protocol.symbols:
                    bar = by_time[symbol].get(now)
                    if bar is None:
                        continue
                    history = {
                        s: tuple(b for b in source[s] if b.closed_at <= bar.opened_at)
                        for s in protocol.symbols
                    }
                    shocks = active_shocks(scenario, bar.opened_at, calendar)
                    for book in books.values():
                        book.settings.execution.slippage_bps = settings.execution.slippage_bps
                        for shock in shocks:
                            book.settings.execution.slippage_bps *= shock.slippage_multiplier
                        original = settings.instrument_rules.get(symbol, InstrumentRule())
                        book.settings.instrument_rules[symbol] = original.model_copy(
                            update={
                                "halted": original.halted or any(shock.halted for shock in shocks)
                            }
                        )
                        previous = book.latest.get(symbol)
                        atr = Decimal(str(previous.values["atr"])) if previous else Decimal(0)
                        context = book.context(
                            symbol,
                            history[symbol],
                            sectors.get(symbol, "UNKNOWN"),
                            atr,
                            history,
                            bar.opened_at,
                        )
                        book.advance(bar, context, protocol.entry_expiry_minutes)
                if observed:
                    for book in books.values():
                        book.end_batch()
                if now.time() in decisions:
                    session = calendar.status(now)
                    if not session.can_decide:
                        guards["OUTSIDE_DECISION_WINDOW"] += len(protocol.symbols)
                    else:
                        visible = {
                            s: tuple(b for b in source[s] if b.closed_at <= now)
                            for s in protocol.symbols
                        }
                        for symbol in protocol.symbols:
                            try:
                                snapshots = {
                                    frame: market_features(
                                        source[symbol], fives[symbol], settings, now, frame
                                    )
                                    for frame in ("1m", "5m")
                                }
                            except ValueError as exc:
                                guards[str(exc)] += 1
                                continue
                            for key, book in books.items():
                                snapshot = snapshots[book.frame]
                                book.latest[symbol] = snapshot
                                context = book.context(
                                    symbol,
                                    visible[symbol],
                                    sectors.get(symbol, "UNKNOWN"),
                                    Decimal(str(snapshot.values["atr"])),
                                    visible,
                                    now,
                                )
                                if (
                                    not session.can_enter_mis
                                    and (symbol, "MIS") not in book.exchange.portfolio.positions
                                ):
                                    guards["ENTRY_WINDOW"] += 1
                                    continue
                                snapshot = book.portfolio_features(snapshot)
                                if key.startswith("ema/"):
                                    chosen, _ = directions(settings, snapshot, None)
                                    direction, reason = chosen["ema"], "EXPLICIT_EMA_BASELINE"
                                elif any(
                                    shock.inference_outage
                                    for shock in active_shocks(scenario, now, calendar)
                                ):
                                    direction, reason = "HOLD", "INJECTED_INFERENCE_OUTAGE"
                                else:
                                    identity = digest(
                                        {
                                            "state": snapshot.state,
                                            "at": now.isoformat(),
                                            "questions": QUESTIONS,
                                            "checkpoint": inference.system_one.model_dump(
                                                mode="json"
                                            ),
                                        }
                                    )
                                    path = cache_dir / f"{identity}.json"
                                    if path.exists():
                                        raw = json.loads(path.read_text())
                                        response = raw.get("response")
                                        hits += 1
                                    else:
                                        if calls >= protocol.max_new_inferences:
                                            raise ValueError(
                                                "Inference budget exhausted; resume frozen run"
                                            )
                                        signal = await strategy.decide(
                                            snapshot, book.exchange.portfolio
                                        )
                                        raw = signal.raw
                                        response = raw.get("response") if strategy.healthy else None
                                        calls += 1
                                        with (output / "attempts.jsonl").open(
                                            "a", encoding="utf-8"
                                        ) as handle:
                                            handle.write(
                                                json.dumps(
                                                    {"episode": name, "key": identity, "raw": raw},
                                                    allow_nan=False,
                                                )
                                                + "\n"
                                            )
                                        if strategy.healthy:
                                            save(path, raw)
                                    chosen, reason = directions(inference, snapshot, response)
                                    direction = chosen["laya"]
                                    inference_rows.append(
                                        {
                                            "symbol": symbol,
                                            "at": now.isoformat(),
                                            "arm": key,
                                            "cache_key": identity,
                                            "reason": reason,
                                            "latency_ms": raw.get("latency_ms"),
                                        }
                                    )
                                book.act(
                                    snapshot,
                                    direction,
                                    context,
                                    now + timedelta(seconds=protocol.decision_delay_seconds),
                                    reason,
                                )
                            print(
                                f"{name} {now.strftime('%m-%d %H:%M')} {symbol}; "
                                f"calls={calls} cache={hits}",
                                flush=True,
                            )
                for book in books.values():
                    book.record(now)
                now += timedelta(minutes=1)
            save(
                episode_dir / f"{day}-decisions.json",
                {key: book.decisions for key, book in books.items()},
            )
            print(f"Finished {name} {day}", flush=True)
        details = {
            key: {
                "curve": book.curve,
                "decisions": book.decisions,
                "exit_requests": book.closes,
                "closed_trades": book.exchange.portfolio.closed_trades,
                "fills": [
                    {
                        "order_id": fill.order_id,
                        "symbol": fill.symbol,
                        "at": fill.at.isoformat(),
                        "side": fill.side,
                        "quantity": fill.quantity,
                        "price": str(fill.price),
                        "charges": str(fill.charges.total),
                        "reason": fill.reason,
                    }
                    for fill in book.exchange.portfolio.fills
                ],
                "vetoes": book.exchange.veto_log,
            }
            for key, book in books.items()
        }
        save(episode_dir / "observations.json", details)
        save(episode_dir / "inference.json", inference_rows)
        reports[name] = {
            "kind": "historical" if scenario is None else "constructed_stress",
            "guards": dict(guards),
            "arms": {key: book.report() for key, book in books.items()},
            "inference_failures": sum(
                row["reason"] == "INFERENCE_UNAVAILABLE_OR_INVALID" for row in inference_rows
            ),
        }
        save(output / "progress.json", reports)
        print(json.dumps({name: reports[name]}), flush=True)
    save(
        output / "report.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "manifest_hash": digest(manifest),
            "coverage": coverage,
            "new_model_requests": calls,
            "cache_hits": hits,
            "episodes": reports,
            "limitations": [
                "Fixed three-stock basket, not historical Nifty constituent performance.",
                "Sparse common decision windows, not full production cadence.",
                "Latest revised historical data; missing bars never generate synthetic fills.",
                "Shared capital per arm; stress resets are not real-session returns.",
                "Portfolio-aware inputs differ; actual inference latency logged separately.",
                "No retraining, parameter tuning, committee or live profile change.",
            ],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical and stressed shared-portfolio replay")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    for path in (args.data, args.output):
        if not path.resolve().is_relative_to((ROOT / "work").resolve()):
            parser.error("Research inputs and outputs must stay under private work")
    asyncio.run(run(args.data.resolve(), args.output.resolve(), args.prepare_only, args.resume))


if __name__ == "__main__":
    main()
