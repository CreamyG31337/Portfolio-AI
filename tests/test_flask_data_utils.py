import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import sys
import os

# Add web_dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard')))

from flask_data_utils import get_current_positions_flask

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
