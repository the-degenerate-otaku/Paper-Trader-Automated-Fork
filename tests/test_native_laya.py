import asyncio
from datetime import datetime
from decimal import Decimal

import httpx

from paper_trader.config import Settings
from paper_trader.features import FeatureSnapshot
from paper_trader.inference import SystemOneStrategy
from paper_trader.trading import Portfolio


def test_native_laya_model_name_and_routed_checkpoint(settings: Settings) -> None:
    payload = {
        "model": "laya-rl-agent",
        "routing": {"model": "typed-decisions"},
        "answers": {
            "direction": {
                "type": "choice",
                "choice": "LONG",
                "probabilities": {"LONG": 0.8, "SHORT": 0.1, "NEUTRAL": 0.1},
            },
            "regime": {
                "type": "choice",
                "choice": "TRENDING",
                "probabilities": {"TRENDING": 0.8, "MEAN_REVERTING": 0.1, "CHOPPY": 0.1},
            },
            "entry_conviction": {
                "type": "score",
                "score": 1.7,
                "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8},
            },
            "setup_quality": {
                "type": "score",
                "score": 1.7,
                "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8},
            },
            "reversal_risk": {"type": "noul", "noul": 0.1},
            "volatility_expansion_likely": {"type": "noul", "noul": 0.2},
        },
    }
    strategy = SystemOneStrategy(
        settings, httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    snapshot = FeatureSnapshot(
        "DEMO", datetime.fromisoformat("2026-09-01T10:00:00+05:30"), {}, "TRENDING", "compact state"
    )
    portfolio = Portfolio(Decimal(1000000))
    assert asyncio.run(strategy.decide(snapshot, portfolio)).direction == "LONG"
    payload["routing"]["model"] = "english"
    assert asyncio.run(strategy.decide(snapshot, portfolio)).direction == "HOLD"
    payload.pop("routing")
    assert asyncio.run(strategy.decide(snapshot, portfolio)).direction == "LONG"
    payload["model"] = "unrecognized"
    assert asyncio.run(strategy.decide(snapshot, portfolio)).direction == "HOLD"
