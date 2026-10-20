from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Literal, cast

import httpx

from paper_trader.config import Settings
from paper_trader.engine import Signal
from paper_trader.features import FeatureSnapshot
from paper_trader.trading import Portfolio

QUESTIONS: dict[str, object] = {
    "direction": {
        "type": "choice",
        "instructions": "Choose a cash-equity trade direction.",
        "criteria": {
            "LONG": "rising price setup",
            "SHORT": "falling price setup",
            "NEUTRAL": "no clear setup",
        },
    },
    "regime": {
        "type": "choice",
        "instructions": "Classify the current market regime.",
        "criteria": {
            "TRENDING": "sustained directional movement",
            "MEAN_REVERTING": "return toward average",
            "CHOPPY": "directionless noise",
        },
    },
    "entry_conviction": {
        "type": "score",
        "instructions": "Rate entry conviction.",
        "criteria": ["LOW", "MEDIUM", "HIGH"],
    },
    "setup_quality": {
        "type": "score",
        "instructions": "Rate setup quality.",
        "criteria": ["POOR", "FAIR", "IDEAL"],
    },
    "reversal_risk": {
        "type": "noul",
        "instructions": "A reversal against the proposed direction is likely.",
    },
    "volatility_expansion_likely": {
        "type": "noul",
        "instructions": "Volatility is likely to expand.",
    },
}


def distribution(answer: object, labels: set[str], temperature: float) -> dict[str, float]:
    if not isinstance(answer, dict) or not isinstance(answer.get("probabilities"), dict):
        raise ValueError("Missing probabilities")
    raw = answer["probabilities"]
    if set(raw) != labels or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("Invalid labels or temperature")
    if any(
        type(p) not in {int, float} or not math.isfinite(p) or not 0 <= p <= 1 for p in raw.values()
    ):
        raise ValueError("Invalid probability")
    if not math.isclose(sum(raw.values()), 1, abs_tol=0.001):
        raise ValueError("Probabilities do not sum to one")
    logits = {key: math.log(max(float(p), 1e-12)) / temperature for key, p in raw.items()}
    maximum = max(logits.values())
    weights = {key: math.exp(value - maximum) for key, value in logits.items()}
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def probability(value: object) -> float:
    if type(value) not in {float, int}:
        raise ValueError("Expected probability")
    result = float(cast(float, value))
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("Invalid probability")
    return result


class SystemOneStrategy:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings, self.transport = settings, transport
        self.last_latency_ms: float | None = None
        self.healthy = False

    async def health(self) -> bool:
        url = self.settings.system_one.endpoint.removesuffix("/v1/systemone") + "/health"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.system_one.timeout_ms / 1000,
                trust_env=False,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.get(url)
                self.healthy = response.status_code == 200
        except httpx.HTTPError:
            self.healthy = False
        return self.healthy

    async def decide(self, snapshot: FeatureSnapshot, portfolio: Portfolio) -> Signal:
        cfg = self.settings.system_one
        request: dict[str, object] = {
            "model": cfg.checkpoint,
            "state": {"body": snapshot.state},
            "questions": QUESTIONS,
        }
        started = time.perf_counter()
        raw: dict[str, object] = {
            "request": request,
            "checkpoint_repo": cfg.checkpoint_repo,
            "checkpoint_subfolder": cfg.checkpoint_subfolder,
        }
        try:
            async with asyncio.timeout(cfg.timeout_ms / 1000):
                async with httpx.AsyncClient(
                    timeout=cfg.timeout_ms / 1000,
                    trust_env=False,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    response = None
                    for attempt in range(cfg.retries + 1):
                        try:
                            async with client.stream(
                                "POST", cfg.endpoint, json=request
                            ) as streamed:
                                streamed.raise_for_status()
                                body = bytearray()
                                async for chunk in streamed.aiter_bytes():
                                    body.extend(chunk)
                                    if len(body) > cfg.max_response_bytes:
                                        raise ValueError("Inference response too large")
                                response = json.loads(body)
                            break
                        except (httpx.TimeoutException, httpx.NetworkError):
                            if attempt == cfg.retries:
                                raise
                    if not isinstance(response, dict) or response.get("model") != cfg.checkpoint:
                        raise ValueError("Wrong response model")
                    raw["response"] = response
                    result = self.policy(response, raw)
                    self.healthy = True
                    return result
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            self.healthy = False
            raw["error"] = "INFERENCE_UNAVAILABLE_OR_INVALID"
            return Signal("HOLD", "INFERENCE_UNAVAILABLE_OR_INVALID", cfg.checkpoint, raw)
        finally:
            self.last_latency_ms = (time.perf_counter() - started) * 1000
            raw["latency_ms"] = self.last_latency_ms

    def policy(self, response: dict[str, object], raw: dict[str, object]) -> Signal:
        cfg = self.settings.system_one
        answers = response["answers"]
        if not isinstance(answers, dict):
            raise ValueError("Invalid answers")
        for name, kind in (
            ("direction", "choice"),
            ("regime", "choice"),
            ("entry_conviction", "score"),
            ("setup_quality", "score"),
            ("reversal_risk", "noul"),
            ("volatility_expansion_likely", "noul"),
        ):
            if not isinstance(answers.get(name), dict) or answers[name].get("type") != kind:
                raise ValueError("Invalid answer type")
        temperature = float(cfg.temperature_scalar)
        direction = distribution(answers["direction"], {"LONG", "SHORT", "NEUTRAL"}, temperature)
        chosen = max(direction, key=lambda key: direction[key])
        if answers["direction"].get("choice") != max(
            answers["direction"]["probabilities"], key=answers["direction"]["probabilities"].get
        ):
            raise ValueError("Inconsistent direction")
        distribution(answers["regime"], {"TRENDING", "MEAN_REVERTING", "CHOPPY"}, temperature)
        conviction = distribution(answers["entry_conviction"], {"0", "1", "2"}, temperature)
        distribution(answers["setup_quality"], {"0", "1", "2"}, temperature)
        reversal = probability(answers["reversal_risk"].get("noul"))
        probability(answers["volatility_expansion_likely"].get("noul"))
        expected = sum(int(key) * value for key, value in conviction.items())
        raw["policy"] = {
            "direction_probability": direction[chosen],
            "conviction_score": expected,
            "reversal_risk": reversal,
        }
        reason = "ACCEPTED"
        if chosen == "NEUTRAL":
            reason = "MODEL_NEUTRAL"
        elif direction[chosen] < cfg.min_direction_prob:
            reason = "LOW_DIRECTION_PROBABILITY"
        elif expected < ("LOW", "MEDIUM", "HIGH").index(cfg.min_conviction):
            reason = "LOW_CONVICTION"
        elif reversal > cfg.max_reversal_risk:
            reason = "REVERSAL_RISK"
        elif chosen == "SHORT" and self.settings.simulation.product == "CNC":
            reason = "CNC_LONG_ONLY"
        direction_out = cast(
            Literal["LONG", "SHORT", "HOLD"], chosen if reason == "ACCEPTED" else "HOLD"
        )
        return Signal(direction_out, reason, cfg.checkpoint, raw)
