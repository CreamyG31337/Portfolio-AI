from web_dashboard.scheduler.jobs_rebalance import _analyze_fund_rebalance


def test_analyze_fund_rebalance_detects_overweight_position() -> None:
    positions = [
        {"ticker": "AAA", "market_value": "600"},
        {"ticker": "BBB", "market_value": "250"},
        {"ticker": "CCC", "market_value": "150"},
    ]
    cash_rows = [{"amount": "0"}]
    policy = {
        "max_position_pct": 40.0,
        "max_top3_pct": 95.0,
        "min_positions": 3,
        "min_cash_pct": 0.0,
        "max_cash_pct": 100.0,
    }

    analysis = _analyze_fund_rebalance(positions, cash_rows, policy)
    assert analysis["actionable"] is True
    assert any("Trim AAA" in line for line in analysis["recommendations"])


def test_analyze_fund_rebalance_reports_healthy_portfolio() -> None:
    positions = [
        {"ticker": "AAA", "market_value": "350"},
        {"ticker": "BBB", "market_value": "330"},
        {"ticker": "CCC", "market_value": "320"},
    ]
    cash_rows = [{"amount": "100"}]
    policy = {
        "max_position_pct": 40.0,
        "max_top3_pct": 100.0,
        "min_positions": 3,
        "min_cash_pct": 5.0,
        "max_cash_pct": 20.0,
    }

    analysis = _analyze_fund_rebalance(positions, cash_rows, policy)
    assert analysis["actionable"] is False
    assert analysis["recommendations"] == ["Portfolio concentration is within profile limits."]
