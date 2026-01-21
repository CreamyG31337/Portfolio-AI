import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import sys
import os

# Add web_dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard')))

from flask_data_utils import get_current_positions_flask, fetch_dividend_log_flask

def test_get_current_positions_flattens_all_fundamentals():
    """Test that get_current_positions_flask correctly flattens all fundamentals from securities join."""
    # Mock data returned by Supabase with nested securities
    mock_data = [
        {
            "symbol": "AAPL",
            "quantity": 10,
            "securities": {
                "company_name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "market_cap": 3000000000000,
                "country": "USA"
            }
        }
    ]
    
    # Mock Supabase client and query chain
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.data = mock_data
    
    # Configure the chain to handle .eq() if called, or skip it
    mock_table = mock_client.supabase.table.return_value
    mock_select = mock_table.select.return_value
    mock_eq = mock_select.eq.return_value
    
    # Ensure both select().range() and select().eq().range() work
    mock_select.range.return_value.execute.return_value = mock_result
    mock_eq.range.return_value.execute.return_value = mock_result
    
    with patch('flask_data_utils.get_supabase_client_flask', return_value=mock_client), \
         patch('cache_version.get_cache_version', return_value="v1"):
        
        df = get_current_positions_flask(fund="TestFund")
        
        # Verify the basics
        assert not df.empty
        assert df.iloc[0]['symbol'] == "AAPL"
        
        # Verify flattened columns
        assert 'sector' in df.columns
        assert 'industry' in df.columns
        assert df.iloc[0]['sector'] == "Technology"
        assert df.iloc[0]['industry'] == "Consumer Electronics"
        
        # THESE ARE EXPECTED TO FAIL UNTIL FIXED
        assert 'market_cap' in df.columns, "market_cap column missing"
        assert 'country' in df.columns, "country column missing"
        assert df.iloc[0]['market_cap'] == 3000000000000
        assert df.iloc[0]['country'] == "USA"


def test_fetch_dividend_log_flask_includes_securities_join():
    """Test that fetch_dividend_log_flask includes securities(company_name) in the select query."""
    # Mock data returned by Supabase with nested securities
    mock_data = [
        {
            "ticker": "AAPL",
            "pay_date": "2024-01-15",
            "net_amount": 100.0,
            "securities": {
                "company_name": "Apple Inc."
            }
        }
    ]
    
    # Mock Supabase client and query chain
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.data = mock_data
    
    # Configure the query chain
    mock_table = mock_client.supabase.table.return_value
    mock_select = mock_table.select.return_value
    mock_gte = mock_select.gte.return_value
    mock_eq = mock_gte.eq.return_value
    mock_order = mock_eq.order.return_value if hasattr(mock_eq, 'order') else mock_gte.order.return_value
    
    # Set up execute to return mock_result
    mock_order.execute.return_value = mock_result
    mock_gte.order.return_value.execute.return_value = mock_result
    
    with patch('flask_data_utils.get_supabase_client_flask', return_value=mock_client), \
         patch('flask_data_utils.get_user_id_flask', return_value='test-user-123'), \
         patch('cache_version.get_cache_version', return_value="v1"):
        
        # Call without user_id to test automatic retrieval
        result = fetch_dividend_log_flask(days_lookback=365, fund="TestFund")
        
        # Verify the function was called
        assert mock_table.select.called
        
        # Verify that select was called with securities join
        # The select call should include '*, securities(company_name)'
        select_call_args = mock_table.select.call_args
        assert select_call_args is not None
        # Check that the select includes securities join
        select_arg = select_call_args[0][0] if select_call_args[0] else select_call_args[1].get('select', '')
        assert 'securities' in str(select_call_args), f"Expected securities join in select, got: {select_call_args}"
        
        # Verify result contains the data
        assert len(result) == 1
        assert result[0]['ticker'] == "AAPL"
        assert result[0]['securities']['company_name'] == "Apple Inc."
