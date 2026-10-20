from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Literal

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings
from paper_trader.engine import EmaStrategy, HoldStrategy, ReplayEngine, Signal, Strategy
from paper_trader.features import FeatureSnapshot
from paper_trader.inference import SystemOneStrategy
from paper_trader.market import Candle, stamp
from paper_trader.storage import Database
from paper_trader.trading import Portfolio


def load_dataset(
    database: Database, run_id: str, as_of: datetime, settings: Settings
) -> tuple[Settings, tuple[Candle, ...], dict[str, str]]:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT config_json, data_version FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown run")
        recorded = Settings.model_validate_json(row["config_json"])
        recorded.research = settings.research.model_copy(deep=True)
        if not recorded.session.calendar_path.exists():
            recorded.session.calendar_path = settings.session.calendar_path
        versions: dict[str, str] = json.loads(row["data_version"])
        collected: dict[tuple[str, str, datetime], Candle] = {}
        for version in versions.values():
            rows = connection.execute(
                "SELECT payload_json FROM candle_versions WHERE data_version=? "
                "AND closed_at<=? ORDER BY closed_at, symbol LIMIT ?",
                (version, stamp(as_of), settings.data.max_fetch_bars + 1),
            ).fetchall()
            for item in rows:
                bar = Candle.model_validate_json(item[0])
                collected.setdefault(bar.identity, bar)
                if len(collected) > settings.data.max_fetch_bars:
                    raise ValueError("Dataset exceeds configured research budget")
    return (
        recorded,
        tuple(sorted(collected.values(), key=lambda c: (c.closed_at, c.symbol))),
        versions,
    )


class OutageScenario:
    def __init__(self, settings: Settings, after: datetime) -> None:
        self.baseline = EmaStrategy(settings)
        self.after = after

    async def decide(self, snapshot: FeatureSnapshot, portfolio: Portfolio) -> Signal:
        if snapshot.at >= self.after:
            return Signal("HOLD", "INJECTED_INFERENCE_OUTAGE")
        return await self.baseline.decide(snapshot, portfolio)


def slices(
    candles: tuple[Candle, ...], settings: Settings
) -> list[tuple[tuple[Candle, ...], tuple[Candle, ...]]]:
    grouped: dict[datetime, list[Candle]] = defaultdict(list)
    for candle in candles:
        grouped[candle.closed_at].append(candle)
    times = sorted(grouped)
    config = settings.research
    result = []
    for start in range(0, len(times), config.walk_step_bars):
        train_end = start + config.train_bars
        test_start = train_end + config.embargo_bars
        test_end = test_start + config.test_bars
        if test_end > len(times):
            break
        warmup = tuple(c for t in times[start:test_start] for c in grouped[t])
        test = tuple(c for t in times[test_start:test_end] for c in grouped[t])
        if warmup[-1].closed_at > test[0].opened_at:
            raise ValueError("Walk-forward warmup overlaps test candle")
        result.append((warmup, test))
    return result


async def walk_forward(
    settings: Settings,
    calendar: TradingCalendar,
    database: Database,
    candles: tuple[Candle, ...],
    versions: dict[str, str],
    strategy: Literal["hold", "ema", "systemone"],
) -> list[dict[str, object]]:
    result = []
    folds = slices(candles, settings)
    if not folds:
        raise ValueError("Insufficient data for configured train/embargo/test windows")
    for warmup, test in folds:
        settings = settings.model_copy(deep=True)
        settings.simulation.strategy = strategy
        policy: Strategy = (
            SystemOneStrategy(settings)
            if strategy == "systemone"
            else EmaStrategy(settings)
            if strategy == "ema"
            else HoldStrategy()
        )
        engine = ReplayEngine(settings, calendar, database, test, versions, policy)
        for bar in warmup:
            engine.history[bar.symbol].append(bar)
        for symbol, history in engine.history.items():
            engine.latest_features[symbol] = engine.features.calculate(
                tuple(history), history[-1].closed_at
            )
        report = await engine.run()
        result.append(
            {
                "train_start": warmup[0].opened_at.isoformat(),
                "warmup_end": warmup[-1].closed_at.isoformat(),
                "test_start": test[0].opened_at.isoformat(),
                "test_end": test[-1].closed_at.isoformat(),
                "strategy": strategy,
                "parameters_fitted": False,
                "run_id": report["run_id"],
                "metrics": report["metrics"],
            }
        )
    return result


async def stress(
    settings: Settings,
    calendar: TradingCalendar,
    database: Database,
    candles: tuple[Candle, ...],
    versions: dict[str, str],
) -> list[dict[str, object]]:
    result = []
    for scenario in (
        "baseline",
        "missing_bars",
        "liquidity_drought",
        "high_slippage",
        "inference_outage",
    ):
        config = settings.model_copy(deep=True)
        config.simulation.strategy = "ema"
        data = candles
        policy: Strategy = EmaStrategy(config)
        if scenario == "missing_bars":
            data = tuple(
                c for i, c in enumerate(data) if (i + 1) % config.research.stress_drop_every
            )
        elif scenario == "liquidity_drought":
            data = tuple(
                c.model_copy(
                    update={"volume": int(c.volume * config.research.stress_volume_factor)}
                )
                for c in data
            )
        elif scenario == "high_slippage":
            config.execution.slippage_bps *= config.research.stress_slippage_factor
        elif scenario == "inference_outage":
            if not data:
                raise ValueError("Stress run requires closed candles")
            policy = OutageScenario(
                config, data[min(config.research.stress_outage_after_bars, len(data) - 1)].closed_at
            )
        engine = ReplayEngine(config, calendar, database, data, versions, policy)
        report = await engine.run()
        result.append(
            {
                "scenario": scenario,
                "synthetic_perturbation": scenario != "baseline",
                "run_id": report["run_id"],
                "metrics": report["metrics"],
                "open_positions": report["open_positions"],
                "veto_count": len(engine.exchange.veto_log),
            }
        )
    return result
