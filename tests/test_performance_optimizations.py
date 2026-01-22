import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import sys
import os

# Add web_dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard')))

from flask_data_utils import get_portfolio_start_date_flask, get_first_trade_dates_flask

def test_get_portfolio_start_date_flask_uses_optimized_query():
    """Test that get_portfolio_start_date_flask uses optimized query (limit 1)."""
    # Mock Supabase client
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.data = [{"date": "2023-01-01"}]

    # Configure the query chain
    mock_table = mock_client.supabase.table.return_value
    mock_select = mock_table.select.return_value
    # Depending on implementation, eq might be called or not
    mock_eq = mock_select.eq.return_value
    mock_order = mock_eq.order.return_value
    mock_limit = mock_order.limit.return_value
    mock_limit.execute.return_value = mock_result

    with patch('flask_data_utils.get_supabase_client_flask', return_value=mock_client), \
         patch('cache_version.get_cache_version', return_value="v1"):

        # Call the function
        result = get_portfolio_start_date_flask(fund="TestFund")

        # Verify result
        assert result == "2023-01-01"

        # Verify the query chain
        # It should be table("trade_log").select("date").eq("fund", fund).order("date", desc=False).limit(1)
        mock_client.supabase.table.assert_called_with("trade_log")
        mock_table.select.assert_called_with("date")
        mock_select.eq.assert_called_with("fund", "TestFund")
        mock_eq.order.assert_called_with("date", desc=False)
        mock_order.limit.assert_called_with(1)

def test_get_first_trade_dates_flask_uses_optimized_selection():
    """Test that get_first_trade_dates_flask selects only ticker and date."""
    # Mock data
    mock_data = [
        {"ticker": "AAPL", "date": "2023-01-01"},
        {"ticker": "AAPL", "date": "2023-01-05"},
        {"ticker": "GOOGL", "date": "2023-02-01"}
    ]

    # Mock Supabase client
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.data = mock_data

    # Configure the query chain
    mock_table = mock_client.supabase.table.return_value
    mock_select = mock_table.select.return_value
    mock_eq = mock_select.eq.return_value
    mock_order = mock_eq.order.return_value
    mock_limit = mock_order.limit.return_value
    mock_limit.execute.return_value = mock_result

    with patch('flask_data_utils.get_supabase_client_flask', return_value=mock_client), \
         patch('cache_version.get_cache_version', return_value="v1"):

        # Call the function
        result = get_first_trade_dates_flask(fund="TestFund")

        # Verify result keys (dates as timestamps)
        assert "AAPL" in result
        assert "GOOGL" in result
        assert result["AAPL"] == pd.Timestamp("2023-01-01")
        assert result["GOOGL"] == pd.Timestamp("2023-02-01")

        # Verify the query chain
        # It should be table("trade_log").select("ticker, date")
        mock_client.supabase.table.assert_called_with("trade_log")
        mock_table.select.assert_called_with("ticker, date")
        # And limit should be 5000 (or whatever we set)
        mock_order.limit.assert_called_with(5000)
