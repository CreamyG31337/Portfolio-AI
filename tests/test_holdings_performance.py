
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import sys
import os

# Add web_dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard')))

from flask_data_utils import get_individual_holdings_performance_flask

def test_get_individual_holdings_performance_flask_vectorized_logic():
    """Test that vectorized logic correctly calculates performance metrics."""

    # Create sample data for 2 tickers over 3 days
    # Ticker A: Doubles in value
    # Ticker B: Halves in value
    # Ticker C: Baseline 0 (should be filtered out)

    # Portfolio positions data (no longer includes securities join)
    positions_data = [
        # Ticker A
        {'ticker': 'A', 'date': '2023-01-01', 'total_value': 100, 'currency': 'USD'},
        {'ticker': 'A', 'date': '2023-01-02', 'total_value': 150, 'currency': 'USD'},
        {'ticker': 'A', 'date': '2023-01-03', 'total_value': 200, 'currency': 'USD'},

        # Ticker B
        {'ticker': 'B', 'date': '2023-01-01', 'total_value': 100, 'currency': 'USD'},
        {'ticker': 'B', 'date': '2023-01-02', 'total_value': 75, 'currency': 'USD'},
        {'ticker': 'B', 'date': '2023-01-03', 'total_value': 50, 'currency': 'USD'},

        # Ticker C (Baseline 0)
        {'ticker': 'C', 'date': '2023-01-01', 'total_value': 0, 'currency': 'USD'},
        {'ticker': 'C', 'date': '2023-01-02', 'total_value': 10, 'currency': 'USD'},
    ]

    # Securities metadata (fetched separately)
    securities_data = [
        {'ticker': 'A', 'sector': 'Tech', 'industry': None, 'currency': 'USD'},
        {'ticker': 'B', 'sector': 'Finance', 'industry': None, 'currency': 'CAD'},
        {'ticker': 'C', 'sector': 'Junk', 'industry': None, 'currency': 'USD'},
    ]

    # Mock Supabase client
    mock_client = MagicMock()
    
    # Configure table() to return different mocks for different tables
    def table_side_effect(table_name):
        query_mock = MagicMock()
        
        if table_name == "portfolio_positions":
            # Mock chain: table().select().eq().order().range().execute()
            select_mock = MagicMock()
            eq_mock = MagicMock()
            order_mock = MagicMock()
            range_mock = MagicMock()
            
            query_mock.select.return_value = select_mock
            select_mock.eq.return_value = eq_mock
            eq_mock.order.return_value = order_mock
            order_mock.range.return_value = range_mock
            
            # For pagination: return data on first call, empty on second
            result_1 = MagicMock()
            result_1.data = positions_data
            result_2 = MagicMock()
            result_2.data = []
            range_mock.execute.side_effect = [result_1, result_2]
            
            return query_mock
            
        elif table_name == "securities":
            # Mock chain: table().select().in_().execute()
            select_mock = MagicMock()
            in_mock = MagicMock()
            execute_mock = MagicMock()
            
            query_mock.select.return_value = select_mock
            select_mock.in_.return_value = in_mock
            in_mock.execute.return_value = execute_mock
            
            execute_mock.data = securities_data
            
            return query_mock
        
        return query_mock
    
    mock_client.supabase.table.side_effect = table_side_effect

    with patch('flask_data_utils.get_supabase_client_flask', return_value=mock_client), \
         patch('cache_version.get_cache_version', return_value="v1"):

        # Call function
        result_df = get_individual_holdings_performance_flask(fund="TestFund", days=0)

        # Verify Ticker C is removed
        assert 'C' not in result_df['ticker'].values

        # Verify Ticker A calculations
        df_a = result_df[result_df['ticker'] == 'A'].sort_values('date')
        # Baseline = 100
        # Performance Index: 100 -> 100, 150 -> 150, 200 -> 200
        np.testing.assert_allclose(df_a['performance_index'].values, [100.0, 150.0, 200.0])
        # Return Pct: (200/100 - 1)*100 = 100%
        assert df_a['return_pct'].iloc[0] == 100.0
        assert df_a['return_pct'].iloc[-1] == 100.0
        # Daily PnL Pct: NaN, 50, 50
        assert pd.isna(df_a['daily_pnl_pct'].iloc[0])
        np.testing.assert_allclose(df_a['daily_pnl_pct'].iloc[1:].values, [50.0, 50.0])
        # Metadata
        assert df_a['sector'].iloc[0] == 'Tech'
        assert df_a['currency'].iloc[0] == 'USD'

        # Verify Ticker B calculations
        df_b = result_df[result_df['ticker'] == 'B'].sort_values('date')
        # Baseline = 100
        # Performance Index: 100 -> 100, 75 -> 75, 50 -> 50
        np.testing.assert_allclose(df_b['performance_index'].values, [100.0, 75.0, 50.0])
        # Return Pct: (50/100 - 1)*100 = -50%
        assert df_b['return_pct'].iloc[0] == -50.0
        # Metadata backfilling (first row was empty, second had Finance/CAD)
        # transform('first') should pick up 'Finance' and 'CAD' from 2nd row?
        # WAIT. In my manual test:
        # df = pd.DataFrame({'g': [1, 1, 1], 'v': [None, 2, 3]}); print(df.groupby('g')['v'].transform('first'))
        # It returned 2.0. So yes, it skips NaNs.
        # But 'securities': {} results in sector=NaN?
        # Yes, pd.json_normalize will produce NaNs for missing keys.

        assert df_b['sector'].iloc[0] == 'Finance'
        # Currency: securities currency (CAD) takes precedence over portfolio currency (USD)
        assert df_b['currency'].iloc[0] == 'CAD'
