from __future__ import annotations

from typing import Any


def assess_readiness(
    health: dict[str, Any], paper: dict[str, Any], settings: dict[str, Any]
) -> dict[str, Any]:
    phase = health.get("calendar", {}).get("phase")
    automation = paper.get("automation", {})
    stocks = paper.get("stocks", [])
    expected = settings.get("auto_paper", {}).get("mover_count", 0)
    fresh = sum(
        bool(
            stock.get("fresh")
            and stock.get("prepared")
            and not stock.get("error")
            and (stock.get("quote") or {}).get("regular") is True
        )
        for stock in stocks
    )
    checks = {
        "paper_mode": health.get("mode") == "paper",
        "verified_calendar": phase in {"holiday", "weekend", "pre_open", "open", "closed"},
        "local_model_reachable": health.get("inference_reachable") is True,
        "feed_connected": paper.get("feed") == "connected",
        "universe_current": paper.get("membership_fresh") is True
        and expected > 0
        and len(stocks) == expected,
        "automated_cost_guard": automation.get("cost_gate_enabled") is True,
    }
    if phase == "open":
        checks["fresh_prepared_quotes"] = fresh > 0
    infrastructure = all(checks.values())
    return {
        "status": "BLOCKED"
        if not infrastructure
        else "LIVE_PRECHECKS_PASS"
        if phase == "open"
        else "WAITING_FOR_MARKET",
        "checks": checks,
        "market_phase": phase,
        "entry_window_open": paper.get("session", {}).get("can_enter_mis") is True,
        "automation_enabled": automation.get("enabled") is True,
        "fresh_prepared_symbols": fresh,
        "note": "Read-only prechecks; candle quality, liquidity, funds and risk still gate orders.",
    }
