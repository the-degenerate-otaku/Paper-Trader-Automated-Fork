from paper_trader.readiness import assess_readiness


def responses(phase="closed", fresh=False):
    return (
        {"mode": "paper", "inference_reachable": True, "calendar": {"phase": phase}},
        {
            "feed": "connected",
            "membership_fresh": True,
            "automation": {"enabled": False, "cost_gate_enabled": True},
            "session": {"can_enter_mis": phase == "open"},
            "stocks": [{"fresh": fresh, "prepared": True, "quote": {"regular": True}}],
        },
        {"auto_paper": {"mover_count": 1}},
    )


def test_closed_market_is_waiting_not_a_quote_failure_or_trading_permission():
    result = assess_readiness(*responses())
    assert result["status"] == "WAITING_FOR_MARKET"
    assert not result["entry_window_open"]
    assert not result["automation_enabled"]
    assert "fresh_prepared_quotes" not in result["checks"]


def test_open_market_requires_fresh_prepared_quotes():
    assert assess_readiness(*responses("open"))["status"] == "BLOCKED"
    assert assess_readiness(*responses("open", True))["status"] == "LIVE_PRECHECKS_PASS"
    health, paper, config = responses("open", True)
    paper["stocks"][0]["quote"]["regular"] = False
    assert assess_readiness(health, paper, config)["status"] == "BLOCKED"


def test_model_calendar_feed_and_cost_failures_block_even_before_open():
    health, paper, config = responses()
    health["inference_reachable"] = False
    assert assess_readiness(health, paper, config)["status"] == "BLOCKED"
    health["inference_reachable"] = True
    paper["automation"]["cost_gate_enabled"] = False
    assert assess_readiness(health, paper, config)["status"] == "BLOCKED"
    paper["automation"]["cost_gate_enabled"] = True
    paper["feed"] = "disconnected"
    assert assess_readiness(health, paper, config)["status"] == "BLOCKED"
    paper["feed"] = "connected"
    health["calendar"]["phase"] = "unknown_calendar"
    assert assess_readiness(health, paper, config)["status"] == "BLOCKED"
