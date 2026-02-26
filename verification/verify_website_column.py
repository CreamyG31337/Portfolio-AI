import sys
import os
import pandas as pd
from unittest.mock import MagicMock, patch

# Add web_dashboard to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../web_dashboard')))

# Mock modules that might cause issues if imported directly
sys.modules['streamlit'] = MagicMock()
sys.modules['streamlit.runtime.scriptrunner'] = MagicMock()

# Need to ensure flask_cache_utils doesn't break things
# We can mock the decorator if needed, but let's see if it works as is.
# If flask_caching is not initialized, it might warn or fail.
# Let's mock the cache_data decorator to just call the function.
def mock_cache_data(**kwargs):
    def decorator(f):
        return f
    return decorator

sys.modules['flask_cache_utils'] = MagicMock()
sys.modules['flask_cache_utils'].cache_data = mock_cache_data

from flask_data_utils import get_individual_holdings_performance_flask

def test_get_individual_holdings_performance_flask():
    print("Testing get_individual_holdings_performance_flask...")

    # Mock data for portfolio positions
    mock_positions_data = [
        {
            "ticker": "TEST",
            "date": "2023-01-01T00:00:00",
            "shares": 10,
            "price": 100,
            "total_value": 1000,
            "currency": "USD"
        }
    ]

    # Mock data for securities (including website)
    mock_securities_data = [
        {
            "ticker": "TEST",
            "sector": "Technology",
            "industry": "Software",
            "currency": "USD",
            "website": "example.com"
        }
    ]

    with patch('flask_data_utils.get_supabase_client_flask') as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_pos_query = MagicMock()
        mock_sec_query = MagicMock()

        def table_side_effect(name):
            if name == "portfolio_positions":
                return mock_pos_query
            if name == "securities":
                return mock_sec_query
            return MagicMock()

        mock_client.supabase.table.side_effect = table_side_effect

        # Mock positions query chain
        mock_pos_query.select.return_value = mock_pos_query
        mock_pos_query.eq.return_value = mock_pos_query
        mock_pos_query.gte.return_value = mock_pos_query
        mock_pos_query.order.return_value = mock_pos_query
        mock_pos_query.range.return_value = mock_pos_query

        # Mock execute for positions
        # First call returns data, second call returns empty list (to break loop)
        pos_result_1 = MagicMock()
        pos_result_1.data = mock_positions_data
        pos_result_2 = MagicMock()
        pos_result_2.data = []

        mock_pos_query.execute.side_effect = [pos_result_1, pos_result_2]

        # Mock securities query chain
        mock_sec_query.select.return_value = mock_sec_query
        mock_sec_query.in_.return_value = mock_sec_query

        # Mock execute for securities
        sec_result = MagicMock()
        sec_result.data = mock_securities_data
        mock_sec_query.execute.return_value = sec_result

        # Run function
        try:
            df = get_individual_holdings_performance_flask("Test Fund", days=7)
        except Exception as e:
            print(f"Function raised exception: {e}")
            import traceback
            traceback.print_exc()
            return

        # Verify what was selected from securities table
        call_args = mock_sec_query.select.call_args
        if call_args:
            args, _ = call_args
            select_str = args[0]
            print(f"Select string used for securities: '{select_str}'")
            if "website" in select_str:
                print("VERIFICATION: SUCCESS - 'website' was requested from DB.")
            else:
                print("VERIFICATION: FAILURE - 'website' was NOT requested from DB.")
        else:
            print("WARNING: select() was not called on securities table (maybe no positions found?)")

        # Check if website column is present in result DataFrame
        if 'website' in df.columns:
            print("DATAFRAME CHECK: SUCCESS - 'website' column is present.")
            # Check content
            if not df.empty and df.iloc[0]['website'] == "example.com":
                 print("DATA CHECK: SUCCESS - 'website' data is correct.")
            else:
                 print(f"DATA CHECK: FAILURE - 'website' data is incorrect: {df.iloc[0].get('website')}")
        else:
            print("DATAFRAME CHECK: FAILURE - 'website' column is MISSING.")

if __name__ == "__main__":
    test_get_individual_holdings_performance_flask()
