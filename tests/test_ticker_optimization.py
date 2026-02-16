import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock SupabaseClient and PostgresClient if import fails
try:
    from web_dashboard.ticker_utils import _fetch_unique_tickers_rpc, _fetch_tickers_optimized, get_all_unique_tickers
except ImportError:
    # This might happen if dependencies are missing in test env, but we installed them.
    pass

class TestTickerOptimization(unittest.TestCase):

    def test_fetch_unique_tickers_rpc_success(self):
        """Test that RPC is used when available"""
        mock_client = MagicMock()
        mock_client.rpc.return_value.data = [{'ticker': 'AAPL'}, {'ticker': 'MSFT'}]

        tickers = _fetch_unique_tickers_rpc(mock_client, 'congress_trades')

        self.assertIsNotNone(tickers)
        self.assertEqual(tickers, {'AAPL', 'MSFT'})
        mock_client.rpc.assert_called_with('execute_sql', {'query': "SELECT DISTINCT ticker FROM congress_trades WHERE ticker IS NOT NULL"})

    def test_fetch_unique_tickers_rpc_failure(self):
        """Test that RPC returns None on failure"""
        mock_client = MagicMock()
        mock_client.rpc.side_effect = Exception("RPC Failed")

        tickers = _fetch_unique_tickers_rpc(mock_client, 'congress_trades')

        self.assertIsNone(tickers)

    @patch('web_dashboard.ticker_utils._fetch_unique_tickers_rpc')
    @patch('web_dashboard.ticker_utils._fetch_tickers_from_table')
    def test_fetch_tickers_optimized_success(self, mock_fetch_table, mock_fetch_rpc):
        """Test optimized fetch uses RPC result if available"""
        mock_client = MagicMock()
        mock_fetch_rpc.return_value = {'AAPL', 'GOOG'}

        result = _fetch_tickers_optimized(mock_client, 'congress_trades')

        self.assertEqual(result, {'AAPL', 'GOOG'})
        mock_fetch_rpc.assert_called_once()
        mock_fetch_table.assert_not_called()

    @patch('web_dashboard.ticker_utils._fetch_unique_tickers_rpc')
    @patch('web_dashboard.ticker_utils._fetch_tickers_from_table')
    def test_fetch_tickers_optimized_fallback(self, mock_fetch_table, mock_fetch_rpc):
        """Test optimized fetch falls back to table fetch if RPC fails"""
        mock_client = MagicMock()
        mock_fetch_rpc.return_value = None
        mock_fetch_table.return_value = {'TSLA'}

        result = _fetch_tickers_optimized(mock_client, 'congress_trades')

        self.assertEqual(result, {'TSLA'})
        mock_fetch_rpc.assert_called_once()
        mock_fetch_table.assert_called_once()

if __name__ == '__main__':
    unittest.main()
