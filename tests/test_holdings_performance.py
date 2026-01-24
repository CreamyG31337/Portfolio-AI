
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

    data = [
        # Ticker A
        {'ticker': 'A', 'date': '2023-01-01', 'total_value': 100, 'securities': {'sector': 'Tech', 'currency': 'USD'}},
        {'ticker': 'A', 'date': '2023-01-02', 'total_value': 150, 'securities': {'sector': 'Tech', 'currency': 'USD'}},
        {'ticker': 'A', 'date': '2023-01-03', 'total_value': 200, 'securities': {'sector': 'Tech', 'currency': 'USD'}},

        # Ticker B (missing metadata in first row, should be backfilled)
        {'ticker': 'B', 'date': '2023-01-01', 'total_value': 100, 'securities': {}},
        {'ticker': 'B', 'date': '2023-01-02', 'total_value': 75, 'securities': {'sector': 'Finance', 'currency': 'CAD'}},
        {'ticker': 'B', 'date': '2023-01-03', 'total_value': 50, 'securities': {'sector': 'Finance', 'currency': 'CAD'}},

        # Ticker C (Baseline 0)
        {'ticker': 'C', 'date': '2023-01-01', 'total_value': 0, 'securities': {'sector': 'Junk'}},
        {'ticker': 'C', 'date': '2023-01-02', 'total_value': 10, 'securities': {'sector': 'Junk'}},
    ]

    # Mock Supabase client
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.data = data

    # Configure query chain
    mock_table = mock_client.supabase.table.return_value
    mock_select = mock_table.select.return_value
    mock_eq = mock_select.eq.return_value
    mock_range = mock_eq.range.return_value if hasattr(mock_eq, 'range') else mock_eq.order.return_value.range.return_value
    # The actual chain is: table().select().eq().order().range().execute()
    # Or: table().select().eq().range().execute() depending on code
    # Let's just make sure execute() returns data

    # Based on code: query.order("date").range().execute()
    mock_client.supabase.table("portfolio_positions").select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = mock_result

    # For pagination loop, return empty data on second call
    mock_result_empty = MagicMock()
    mock_result_empty.data = []

    # We need to simulate the pagination loop.
    # The code calls execute() in a loop.
    # checking call count or side_effect
    mock_chain = mock_client.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute
    mock_chain.side_effect = [mock_result, mock_result_empty]

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
        # Currency defaults to 'USD' during flattening if missing, so it becomes USD (first valid value)
        assert df_b['currency'].iloc[0] == 'USD'
