
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import sys
import os
from datetime import datetime, timedelta

# Add web_dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard')))

# Mock dependencies before importing streamlit_utils
mock_st = MagicMock()
mock_st.cache_data = MagicMock(return_value=lambda func: lambda *args, **kwargs: func(*args, **kwargs))
sys.modules['streamlit'] = mock_st

# Mock other dependencies that might cause ImportError
sys.modules['supabase_client'] = MagicMock()
sys.modules['auth_utils'] = MagicMock()
sys.modules['log_handler'] = MagicMock()
sys.modules['exchange_rates_utils'] = MagicMock()
# Also log_handler needs to have log_execution_time
sys.modules['log_handler'].log_execution_time = MagicMock(return_value=lambda func: func)

from streamlit_utils import get_historical_fund_values

def test_get_historical_fund_values_uses_performance_metrics_table():
    """Test that get_historical_fund_values queries performance_metrics table first."""

    # Mock dates
    today = datetime.now()
    dates = [today - timedelta(days=i) for i in range(5)]
    dates.sort()

    # Mock Supabase client
    mock_client = MagicMock()

    # Configure mock responses
    # We expect a query to performance_metrics table
    mock_metrics_result = MagicMock()
    mock_metrics_result.data = [
        {
            "date": (today - timedelta(days=4)).strftime('%Y-%m-%d'),
            "total_value": 1000.0,
            "cost_basis": 900.0
        },
        {
            "date": (today - timedelta(days=3)).strftime('%Y-%m-%d'),
            "total_value": 1100.0,
            "cost_basis": 900.0
        },
        {
            "date": (today - timedelta(days=2)).strftime('%Y-%m-%d'),
            "total_value": 1200.0,
            "cost_basis": 900.0
        },
        {
            "date": (today - timedelta(days=1)).strftime('%Y-%m-%d'),
            "total_value": 1300.0,
            "cost_basis": 900.0
        },
        {
            "date": today.strftime('%Y-%m-%d'),
            "total_value": 1400.0,
            "cost_basis": 900.0
        }
    ]

    # Configure the query chain for performance_metrics
    mock_table = mock_client.supabase.table

    # Setup for performance_metrics query
    # It should look like: table("performance_metrics").select(...).eq(...).gte(...).lte(...).order(...).execute()
    # We need to distinguish between calls to "performance_metrics" and "portfolio_positions"

    def side_effect_table(table_name):
        mock_query = MagicMock()
        if table_name == "performance_metrics":
            mock_query.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_metrics_result
            # Also handle if lte is not called (optional optimization)
            mock_query.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = mock_metrics_result
            return mock_query
        elif table_name == "portfolio_positions":
            # If this is called, it means fallback happened or optimization failed
            # We'll return empty or some data, but we want to assert it's NOT called if metrics found
            mock_pos_result = MagicMock()
            mock_pos_result.data = [] # Return empty to fail if it relies on this
            mock_query.select.return_value.eq.return_value.gte.return_value.order.return_value.order.return_value.range.return_value.execute.return_value = mock_pos_result
            return mock_query
        else:
            return MagicMock()

    mock_table.side_effect = side_effect_table

    with patch('streamlit_utils.get_supabase_client', return_value=mock_client):

        # Call the function
        fund_name = "TestFund"
        values, costs = get_historical_fund_values(fund_name, dates)

        # Verify results match metrics data
        # We expect values to be {date_str: total_value}
        date_str = today.strftime('%Y-%m-%d')
        assert date_str in values
        assert values[date_str] == 1400.0
        assert costs[date_str] == 900.0

        # Verify performance_metrics was queried
        # We check if table was called with "performance_metrics"
        # We can't easily assert not called with portfolio_positions because side_effect handles it,
        # but we can check call_args_list

        calls = [call[0][0] for call in mock_table.call_args_list]
        assert "performance_metrics" in calls, "Should query performance_metrics table"

        # Ideally, we should assert "portfolio_positions" is NOT in calls if metrics found
        assert "portfolio_positions" not in calls, "Should NOT query portfolio_positions table if metrics found"

def test_get_historical_fund_values_fallback_to_positions():
    """Test that get_historical_fund_values falls back to portfolio_positions if metrics missing."""

    # Mock dates
    today = datetime.now()
    dates = [today]

    # Mock Supabase client
    mock_client = MagicMock()

    # Mock empty metrics result
    mock_metrics_result = MagicMock()
    mock_metrics_result.data = []

    # Mock positions result
    mock_pos_result = MagicMock()
    mock_pos_result.data = [
        {
            "id": 1,
            "date": today.strftime('%Y-%m-%d'),
            "ticker": "AAPL",
            "shares": 10,
            "price": 100.0,
            "currency": "USD",
            "cost_basis": 900.0
        }
    ]

    # Configure side effect
    mock_table = mock_client.supabase.table

    def side_effect_table(table_name):
        mock_query = MagicMock()
        if table_name == "performance_metrics":
            mock_query.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = mock_metrics_result
             # Handle variation
            mock_query.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = mock_metrics_result
            return mock_query
        elif table_name == "portfolio_positions":
             mock_query.select.return_value.eq.return_value.gte.return_value.order.return_value.order.return_value.range.return_value.execute.return_value = mock_pos_result
             return mock_query
        else:
            return MagicMock()

    mock_table.side_effect = side_effect_table

    # Mock exchange rates
    mock_client.get_latest_exchange_rate.return_value = 1.0
    mock_client.get_exchange_rates.return_value = [] # Fallback to latest/default

    with patch('streamlit_utils.get_supabase_client', return_value=mock_client):

        # Call the function
        fund_name = "TestFund"
        values, costs = get_historical_fund_values(fund_name, dates)

        # Verify results match positions data
        date_str = today.strftime('%Y-%m-%d')
        # Value = 10 * 100 * 1.0 (exchange rate) = 1000.0
        # Wait, get_historical_fund_values logic uses get_exchange_rates which we mocked to empty
        # So it uses fallback_rate. We need to check what fallback rate is used.
        # In the code: fallback_rate = 1.42 default, or latest rate if available.
        # We mocked get_latest_exchange_rate to 1.0. So fallback should be 1.0.

        assert date_str in values
        assert values[date_str] == 1000.0

        # Verify calls
        calls = [call[0][0] for call in mock_table.call_args_list]
        assert "performance_metrics" in calls, "Should try to query performance_metrics table"
        assert "portfolio_positions" in calls, "Should query portfolio_positions table as fallback"
