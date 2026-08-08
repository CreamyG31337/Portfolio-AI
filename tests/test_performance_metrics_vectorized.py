import sys
import os
from unittest.mock import patch

import pandas as pd

# Add web_dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web_dashboard")))

from flask_data_utils import calculate_performance_metrics_flask


def test_calculate_performance_metrics_logic():
    """Test the logic of calculate_performance_metrics_flask with vectorized operations."""
    # Row 1: market_value provided
    # Row 2: market_value 0, calculated from shares * current_price
    # Row 3: everything 0
    data = {
        "shares": [10.0, 20.0, 0.0],
        "current_price": [100.0, 50.0, 0.0],
        "price": [90.0, 45.0, 0.0],
        "market_value": [1000.0, 0.0, 0.0],
        "cost_basis": [900.0, 800.0, 0.0],
        "currency": ["CAD", "CAD", "CAD"],
    }
    positions_df = pd.DataFrame(data)

    expected_value = 2000.0
    expected_cost = 1700.0
    expected_return = (expected_value - expected_cost) / expected_cost * 100

    with patch("flask_data_utils.get_current_positions_flask", return_value=positions_df), patch(
        "flask_data_utils.get_cash_balances_flask", return_value={}
    ), patch("flask_data_utils.fetch_latest_rates_bulk_flask", return_value={}), patch(
        "flask_data_utils.get_flask_cache_scope_id", return_value="test-user"
    ), patch(
        "flask_data_utils.calculate_portfolio_value_over_time_flask", return_value=pd.DataFrame()
    ):
        result = calculate_performance_metrics_flask(
            "TestFund", display_currency="CAD", _cache_version="metrics-logic-v1"
        )

        assert result["current_value"] == expected_value
        assert result["total_invested"] == expected_cost
        assert abs(result["total_return_pct"] - expected_return) < 0.0001
        assert result["display_currency"] == "CAD"


def test_calculate_performance_metrics_empty():
    """Test behavior with empty dataframe."""
    with patch("flask_data_utils.get_current_positions_flask", return_value=pd.DataFrame()), patch(
        "flask_data_utils.get_cash_balances_flask", return_value={}
    ), patch("flask_data_utils.fetch_latest_rates_bulk_flask", return_value={}), patch(
        "flask_data_utils.get_flask_cache_scope_id", return_value="test-user"
    ), patch(
        "flask_data_utils.calculate_portfolio_value_over_time_flask", return_value=pd.DataFrame()
    ):
        result = calculate_performance_metrics_flask(
            "TestFund", display_currency="CAD", _cache_version="metrics-empty-v1"
        )

        assert result["current_value"] == 0.0
        assert result["total_invested"] == 0.0
        assert result["total_return_pct"] == 0.0


def test_calculate_performance_metrics_applies_fx_and_cash():
    """AI metrics must match dashboard: FX to display currency + include cash."""
    positions_df = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "shares": [10.0, 5.0],
            "current_price": [100.0, 40.0],
            "market_value": [1000.0, 200.0],  # CAD + USD native
            "cost_basis": [800.0, 100.0],
            "unrealized_pnl": [200.0, 100.0],
            "currency": ["CAD", "USD"],
        }
    )
    cash = {"CAD": 50.0, "USD": 10.0}
    rates = {"USD": 1.25}

    # Positions FX'd: 1000 + 200*1.25 = 1250
    # Cash FX'd: 50 + 10*1.25 = 62.5
    # Total value: 1312.5
    # Unrealized FX'd: 200 + 100*1.25 = 325
    # Cost basis FX'd: 1250 - 325 = 925
    expected_value = 1312.5
    expected_invested = 925.0
    expected_return = (325.0 / 925.0) * 100
    expected_pnl = 325.0

    with patch("flask_data_utils.get_current_positions_flask", return_value=positions_df), patch(
        "flask_data_utils.get_cash_balances_flask", return_value=cash
    ), patch("flask_data_utils.fetch_latest_rates_bulk_flask", return_value=rates), patch(
        "flask_data_utils.get_flask_cache_scope_id", return_value="test-user"
    ), patch(
        "flask_data_utils.calculate_portfolio_value_over_time_flask", return_value=pd.DataFrame()
    ):
        result = calculate_performance_metrics_flask(
            "Webull", display_currency="CAD", _cache_version="metrics-fx-cash-v1"
        )

    assert abs(result["current_value"] - expected_value) < 1e-6
    assert abs(result["total_invested"] - expected_invested) < 1e-6
    assert abs(result["total_return_pct"] - expected_return) < 1e-6
    assert abs(result["unrealized_pnl"] - expected_pnl) < 1e-6
    assert abs(result["cash_balance"] - 62.5) < 1e-6
