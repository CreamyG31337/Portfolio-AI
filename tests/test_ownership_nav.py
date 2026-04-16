"""Golden tests for NAV-based ownership (console path: PositionCalculator).

Uses synthetic contribution rows and historical maps only — no live funds or DB.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from portfolio.position_calculator import PositionCalculator


@pytest.fixture
def calculator() -> PositionCalculator:
    return PositionCalculator(MagicMock())


def test_single_contributor_first_units_nav_one_current_value_scales(
    calculator: PositionCalculator,
) -> None:
    """One investor, first issuance at NAV 1.0; fund doubles — ownership stays 100%."""
    fund_contributions = [
        {
            "Contributor": "Alice",
            "Amount": Decimal("1000"),
            "Type": "contribution",
            "Timestamp": datetime(2024, 6, 1, 12, 0, 0),
        }
    ]
    current_fund_value = Decimal("2000")
    historical_fund_values = { "2024-06-01": Decimal("1000") }
    historical_cost_basis = { "2024-06-01": Decimal("0") }

    out = calculator.calculate_ownership_percentages(
        fund_contributions,
        current_fund_value,
        historical_fund_values,
        historical_cost_basis,
    )
    assert "Alice" in out
    alice = out["Alice"]
    assert alice["ownership_percentage"] == Decimal("100.0")
    assert alice["current_value"] == Decimal("2000.00")
    assert alice["net_contribution"] == Decimal("1000")
    assert alice["gain_loss"] == Decimal("1000.00")


def test_two_contributors_split_ownership_decimal(
    calculator: PositionCalculator,
) -> None:
    """Alice day 1, Bob day 2 with historical pricing — units and % split deterministically."""
    fund_contributions = [
        {
            "Contributor": "Alice",
            "Amount": Decimal("1000"),
            "Type": "contribution",
            "Timestamp": datetime(2024, 6, 1, 12, 0, 0),
        },
        {
            "Contributor": "Bob",
            "Amount": "500",
            "Type": "contribution",
            "Timestamp": datetime(2024, 6, 2, 12, 0, 0),
        },
    ]
    historical_fund_values = {
        "2024-06-01": Decimal("1000"),
        "2024-06-02": Decimal("1500"),
    }
    historical_cost_basis = {
        "2024-06-01": Decimal("0"),
        "2024-06-02": Decimal("1000"),
    }
    current_fund_value = Decimal("4000")

    out = calculator.calculate_ownership_percentages(
        fund_contributions,
        current_fund_value,
        historical_fund_values,
        historical_cost_basis,
    )
    assert set(out.keys()) == {"Alice", "Bob"}
    a_pct = out["Alice"]["ownership_percentage"]
    b_pct = out["Bob"]["ownership_percentage"]
    assert a_pct + b_pct == Decimal("100.0")
    assert a_pct > b_pct
    total_cv = out["Alice"]["current_value"] + out["Bob"]["current_value"]
    assert abs(total_cv - current_fund_value) < Decimal("0.02")
