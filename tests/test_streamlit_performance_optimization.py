
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

    mock_initial_result = MagicMock()
    mock_initial_result.data = []

    # Configure the query chain for performance_metrics
    mock_table = mock_client.supabase.table

    def side_effect_table(table_name):
        mock_query = MagicMock()
        if table_name == "performance_metrics":
            # Determine if this is the range query or the initial query
            # We can check the mock call history later, or return a mock that handles both via side effects
            # Simpler: just return the same mock query that can handle both chain patterns

            # Initial query: .eq().lt().order().limit().execute()
            mock_query.select.return_value.eq.return_value.lt.return_value.order.return_value.limit.return_value.execute.return_value = mock_initial_result

            # Range query: .eq().gte().order().execute()
            mock_query.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = mock_metrics_result

            return mock_query
        elif table_name == "portfolio_positions":
            mock_pos_result = MagicMock()
            mock_pos_result.data = []
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
        date_str = today.strftime('%Y-%m-%d')
        assert date_str in values
        assert values[date_str] == 1400.0
        assert costs[date_str] == 900.0

        # Verify performance_metrics was queried
        calls = [call[0][0] for call in mock_table.call_args_list]
        assert "performance_metrics" in calls

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

    mock_initial_result = MagicMock()
    mock_initial_result.data = []

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

    mock_table = mock_client.supabase.table

    def side_effect_table(table_name):
        mock_query = MagicMock()
        if table_name == "performance_metrics":
            # Initial query
            mock_query.select.return_value.eq.return_value.lt.return_value.order.return_value.limit.return_value.execute.return_value = mock_initial_result
            # Range query
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

        fund_name = "TestFund"
        values, costs = get_historical_fund_values(fund_name, dates)

        date_str = today.strftime('%Y-%m-%d')
        assert date_str in values
        assert values[date_str] == 1000.0

        calls = [call[0][0] for call in mock_table.call_args_list]
        assert "performance_metrics" in calls
        assert "portfolio_positions" in calls

def test_get_historical_fund_values_with_initial_gap():
    """Test that get_historical_fund_values uses initial record when gap exists at start."""

    today = datetime.now()
    # Requesting data for today and yesterday
    dates = [today - timedelta(days=1), today]

    mock_client = MagicMock()
    mock_table = mock_client.supabase.table

    # Range query returns ONLY today (gap for yesterday)
    mock_metrics_result = MagicMock()
    mock_metrics_result.data = [
        {
            "date": today.strftime('%Y-%m-%d'),
            "total_value": 2000.0,
            "cost_basis": 1500.0
        }
    ]

    # Initial query returns a record from 5 days ago (to fill the gap)
    mock_initial_result = MagicMock()
    mock_initial_result.data = [
        {
            "date": (today - timedelta(days=5)).strftime('%Y-%m-%d'),
            "total_value": 1000.0,
            "cost_basis": 1000.0
        }
    ]

    def side_effect_table(table_name):
        mock_query = MagicMock()
        if table_name == "performance_metrics":
            # Initial query
            mock_query.select.return_value.eq.return_value.lt.return_value.order.return_value.limit.return_value.execute.return_value = mock_initial_result
            # Range query
            mock_query.select.return_value.eq.return_value.gte.return_value.order.return_value.execute.return_value = mock_metrics_result
            return mock_query
        return MagicMock()

    mock_table.side_effect = side_effect_table

    with patch('streamlit_utils.get_supabase_client', return_value=mock_client):
        fund_name = "TestFund"
        values, costs = get_historical_fund_values(fund_name, dates)

        today_str = today.strftime('%Y-%m-%d')
        yesterday_str = (today - timedelta(days=1)).strftime('%Y-%m-%d')

        # Today should use the exact record
        assert values[today_str] == 2000.0

        # Yesterday (gap) should use the initial record (forward fill)
        assert values[yesterday_str] == 1000.0
