
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import pandas as pd

# Add web_dashboard to path
sys.path.append(os.path.join(os.getcwd(), 'web_dashboard'))

# Mock cache decorator
from functools import wraps
def mock_cache_data(*args, **kwargs):
    def decorator(f):
        @wraps(f)
        def wrapper(*f_args, **f_kwargs):
            return f(*f_args, **f_kwargs)
        return wrapper
    return decorator

# Patch flask_cache_utils BEFORE importing flask_data_utils
sys.modules['flask_cache_utils'] = MagicMock()
sys.modules['flask_cache_utils'].cache_data = mock_cache_data

from flask_data_utils import get_individual_holdings_performance_flask

class TestHoldingsOptimization(unittest.TestCase):

    @patch('flask_data_utils.get_supabase_client_flask')
    def test_optimization(self, mock_get_client):
        # Setup mock client
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock portfolio_positions query response
        # Using 3 rows, 2 unique tickers
        positions_data = [
            {'ticker': 'AAPL', 'date': '2023-01-01', 'shares': 10, 'price': 150, 'total_value': 1500, 'currency': 'USD'},
            {'ticker': 'AAPL', 'date': '2023-01-02', 'shares': 10, 'price': 155, 'total_value': 1550, 'currency': 'USD'},
            {'ticker': 'MSFT', 'date': '2023-01-01', 'shares': 5, 'price': 250, 'total_value': 1250, 'currency': 'USD'}
        ]

        # Mock securities query response
        securities_data = [
            {'ticker': 'AAPL', 'sector': 'Technology', 'industry': 'Consumer Electronics', 'currency': 'USD'},
            {'ticker': 'MSFT', 'sector': 'Technology', 'industry': 'Software - Infrastructure', 'currency': 'USD'}
        ]

        # Configure mock chains
        # We need to handle two different table queries: "portfolio_positions" and "securities"

        def table_side_effect(table_name):
            query_mock = MagicMock()
            if table_name == "portfolio_positions":
                # Mock chain for portfolio_positions
                # table().select().eq().gte().order().range().execute()
                # Simplified chain logic
                select_mock = MagicMock()
                eq_mock = MagicMock()
                gte_mock = MagicMock()
                order_mock = MagicMock()
                range_mock = MagicMock()
                execute_mock = MagicMock()

                query_mock.select.return_value = select_mock
                select_mock.eq.return_value = eq_mock

                # Handle optional gte (cutoff)
                eq_mock.gte.return_value = gte_mock
                eq_mock.order.return_value = order_mock # If gte skipped
                gte_mock.order.return_value = order_mock

                order_mock.range.return_value = range_mock
                range_mock.execute.return_value = execute_mock

                # Mock execute response
                # Return data on first call, empty on second (to break loop)
                execute_mock.data = positions_data

                # If called multiple times (pagination), we need side_effect on range().execute()
                # But here we just mock the chain end
                # We need to make sure subsequent calls return empty to stop pagination loop
                # range_mock is called in loop.
                # Let's use side_effect on range() to return different execute mocks

                exec_1 = MagicMock()
                exec_1.data = positions_data
                exec_2 = MagicMock()
                exec_2.data = [] # End of data

                range_mock.execute.side_effect = [exec_1, exec_2]

                return query_mock

            elif table_name == "securities":
                # Mock chain for securities
                # table().select().in_().execute()
                select_mock = MagicMock()
                in_mock = MagicMock()
                execute_mock = MagicMock()

                query_mock.select.return_value = select_mock
                select_mock.in_.return_value = in_mock
                in_mock.execute.return_value = execute_mock

                execute_mock.data = securities_data
                return query_mock

            return MagicMock() # Fallback

        mock_client.supabase.table.side_effect = table_side_effect

        # Run function
        print("Calling get_individual_holdings_performance_flask...")
        df = get_individual_holdings_performance_flask("Test Fund", days=7)

        # Assertions
        print("Verifying results...")
        self.assertFalse(df.empty, "DataFrame should not be empty")
        self.assertEqual(len(df), 3, "Should have 3 rows")

        # Check if merged columns exist and are correct
        self.assertIn('sector', df.columns)
        self.assertIn('industry', df.columns)

        aapl_row = df[df['ticker'] == 'AAPL'].iloc[0]
        self.assertEqual(aapl_row['sector'], 'Technology')
        self.assertEqual(aapl_row['industry'], 'Consumer Electronics')

        msft_row = df[df['ticker'] == 'MSFT'].iloc[0]
        self.assertEqual(msft_row['industry'], 'Software - Infrastructure')

        # Verify securities table was queried
        mock_client.supabase.table.assert_any_call("securities")

        print("Optimization verified successfully!")

if __name__ == '__main__':
    unittest.main()
