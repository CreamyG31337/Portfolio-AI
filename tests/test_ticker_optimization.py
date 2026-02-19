import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add web_dashboard to path to allow imports
sys.path.append(os.path.join(os.getcwd(), 'web_dashboard'))

# Mock logging to avoid clutter
logging_mock = MagicMock()
sys.modules['logging'] = logging_mock

try:
    from ticker_utils import _fetch_tickers_from_table
except ImportError:
    # Handle case where dependencies might be missing in test environment
    # We mock the dependencies if needed, but for now assuming requirements are installed
    sys.path.append(os.path.join(os.getcwd()))
    from web_dashboard.ticker_utils import _fetch_tickers_from_table

class TestTickerOptimization(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        # Mock rpc method
        self.mock_client.rpc = MagicMock()

        # Mock table().select().range().execute() chain for fallback
        self.mock_table = MagicMock()
        self.mock_select = MagicMock()
        self.mock_range = MagicMock()
        self.mock_execute = MagicMock()
        self.mock_result = MagicMock()

        self.mock_client.supabase.table.return_value = self.mock_table
        self.mock_table.select.return_value = self.mock_select
        self.mock_select.eq.return_value = self.mock_select # For extra_filter
        self.mock_select.range.return_value = self.mock_range
        self.mock_range.execute.return_value = self.mock_result
        self.mock_result.data = [] # Default empty

    def test_fetch_tickers_rpc_success(self):
        """Test that RPC is used for whitelisted tables and returns correct data."""
        # Setup RPC success
        rpc_result = MagicMock()
        rpc_result.data = [{'ticker': 'AAPL'}, {'ticker': 'GOOG'}]
        self.mock_client.rpc.return_value = rpc_result

        tickers = _fetch_tickers_from_table(self.mock_client, 'securities')

        # Verify RPC called with correct query
        self.mock_client.rpc.assert_called_with('execute_sql', {'query': 'SELECT DISTINCT "ticker" FROM "securities"'})

        # Verify result
        self.assertEqual(tickers, {'AAPL', 'GOOG'})

        # Verify pagination NOT called
        self.mock_client.supabase.table.assert_not_called()

    def test_fetch_tickers_rpc_failure_fallback(self):
        """Test that failure in RPC triggers fallback to pagination."""
        # Setup RPC failure
        self.mock_client.rpc.side_effect = Exception("RPC Failed")

        # Setup Pagination success
        self.mock_result.data = [{'ticker': 'MSFT'}]
        # Need to simulate end of pagination: first call returns data, second returns empty
        self.mock_range.execute.side_effect = [self.mock_result, MagicMock(data=[])]

        tickers = _fetch_tickers_from_table(self.mock_client, 'securities')

        # Verify RPC called
        self.mock_client.rpc.assert_called()

        # Verify Pagination called
        self.mock_client.supabase.table.assert_called_with('securities')

        # Verify result
        self.assertEqual(tickers, {'MSFT'})

    def test_fetch_tickers_not_whitelisted(self):
        """Test that non-whitelisted tables skip RPC and use pagination."""
        # Table not in whitelist
        table = 'some_other_table'

        # Setup Pagination success
        self.mock_result.data = [{'ticker': 'TSLA'}]
        self.mock_range.execute.side_effect = [self.mock_result, MagicMock(data=[])]

        tickers = _fetch_tickers_from_table(self.mock_client, table)

        # Verify RPC NOT called
        self.mock_client.rpc.assert_not_called()

        # Verify Pagination called
        self.mock_client.supabase.table.assert_called_with(table)

        # Verify result
        self.assertEqual(tickers, {'TSLA'})

    def test_fetch_tickers_rpc_with_filter(self):
        """Test RPC query construction with filters."""
        # Setup RPC success
        rpc_result = MagicMock()
        rpc_result.data = [{'ticker': 'AMZN'}]
        self.mock_client.rpc.return_value = rpc_result

        extra_filter = {'is_active': True, 'type': 'stock'}
        tickers = _fetch_tickers_from_table(self.mock_client, 'watched_tickers', extra_filter=extra_filter)

        # Verify RPC called with WHERE clause
        # Note: Order of dictionary items is not guaranteed in older python, but usually stable in 3.7+
        # We check if query contains expected parts
        call_args = self.mock_client.rpc.call_args
        query = call_args[0][1]['query']

        self.assertIn('SELECT DISTINCT "ticker" FROM "watched_tickers"', query)
        self.assertIn('WHERE', query)
        self.assertIn('"is_active" IS TRUE', query)
        self.assertIn('"type" = \'stock\'', query)

        self.assertEqual(tickers, {'AMZN'})

    def test_fetch_tickers_rpc_unsafe_column(self):
        """Test that unsafe column names skip RPC."""
        # Unsafe column name
        ticker_column = 'ticker; DROP TABLE securities;'

        # Setup Pagination success - simulating that the DB returns the requested column
        # Note: In reality Supabase might error on this select too, but we verify RPC skip logic here
        self.mock_result.data = [{ticker_column: 'TEST'}]
        self.mock_range.execute.side_effect = [self.mock_result, MagicMock(data=[])]

        tickers = _fetch_tickers_from_table(self.mock_client, 'securities', ticker_column=ticker_column)

        # Verify RPC NOT called
        self.mock_client.rpc.assert_not_called()

        # Verify Pagination called
        self.mock_client.supabase.table.assert_called_with('securities')
        self.mock_table.select.assert_called_with(ticker_column)

        # Verify result
        self.assertEqual(tickers, {'TEST'})

if __name__ == '__main__':
    unittest.main()
