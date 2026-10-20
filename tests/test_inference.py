import asyncio
import copy
import json
from datetime import datetime
from decimal import Decimal

import httpx
import pytest

from paper_trader.config import Settings
from paper_trader.features import FeatureSnapshot
from paper_trader.inference import SystemOneStrategy, distribution
from paper_trader.trading import Portfolio


def response() -> dict:
    return {
        "model": "typed-decisions",
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
        "usage": {"input_tokens": 100, "output_tokens": 6},
    }


def decide(settings: Settings, handler) -> tuple:
    strategy = SystemOneStrategy(settings, httpx.MockTransport(handler))
    snapshot = FeatureSnapshot(
        "DEMO",
        datetime.fromisoformat("2026-09-01T10:00:00+05:30"),
        {},
        "TRENDING",
        "OHLCV compact state",
    )
    return strategy, asyncio.run(strategy.decide(snapshot, Portfolio(Decimal(1000000))))


def test_single_batched_contract_and_journal(settings: Settings) -> None:
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert request.url.path == "/v1/systemone"
        assert set(payload["questions"]) == {
            "direction",
            "regime",
            "entry_conviction",
            "setup_quality",
            "reversal_risk",
            "volatility_expansion_likely",
        }
        assert payload["questions"]["entry_conviction"]["criteria"] == ["LOW", "MEDIUM", "HIGH"]
        return httpx.Response(200, json=response())

    client, signal = decide(settings, handler)
    assert client.healthy and signal.direction == "LONG"
    assert signal.raw["request"] == calls[0]
    assert signal.raw["response"]["usage"]["input_tokens"] == 100
    assert signal.raw["latency_ms"] >= 0
    assert len(calls) == 1


@pytest.mark.parametrize("bad", [float("nan"), -1, 2, True, "0.8"])
def test_malformed_probabilities_fail_closed(settings: Settings, bad: object) -> None:
    payload = response()
    payload["answers"]["direction"]["probabilities"]["LONG"] = bad
    _, signal = decide(settings, lambda _: httpx.Response(200, content=json.dumps(payload)))
    assert signal.direction == "HOLD" and signal.reason == "INFERENCE_UNAVAILABLE_OR_INVALID"


def test_outage_redirect_and_response_budget_hold(settings: Settings) -> None:
    def outage(request):
        raise httpx.ConnectError("do not log credentials or server details", request=request)

    client, signal = decide(settings, outage)
    assert not client.healthy and signal.direction == "HOLD"
    assert "credentials" not in json.dumps(signal.raw)
    _, signal = decide(
        settings, lambda _: httpx.Response(302, headers={"Location": "http://example.com"})
    )
    assert signal.direction == "HOLD"
    settings.system_one.max_response_bytes = 20
    _, signal = decide(settings, lambda _: httpx.Response(200, json=response()))
    assert signal.direction == "HOLD"


def test_policy_vetoes_and_calibrates_selected_probability(settings: Settings) -> None:
    strategy = SystemOneStrategy(settings)
    payload = response()
    payload["answers"]["direction"]["confidence"] = 0
    assert strategy.policy(payload, {}).direction == "LONG"
    payload["answers"]["reversal_risk"]["noul"] = 0.9
    assert strategy.policy(payload, {}).reason == "REVERSAL_RISK"
    payload = response()
    payload["answers"]["direction"]["choice"] = "SHORT"
    payload["answers"]["direction"]["probabilities"] = {"LONG": 0.1, "SHORT": 0.8, "NEUTRAL": 0.1}
    settings.simulation.product = "CNC"
    assert strategy.policy(payload, {}).reason == "CNC_LONG_ONLY"
    scaled = distribution(
        copy.deepcopy(response()["answers"]["direction"]), {"LONG", "SHORT", "NEUTRAL"}, 2
    )
    assert scaled["LONG"] < 0.8
