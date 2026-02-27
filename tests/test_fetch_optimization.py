"""
Tests for consolidated fetch optimization (PRs #149, #152, #159, #163, #171, #175, #187).

Covers:
- fetch_unique_column_values_parallel (RPC fast-path + parallel fallback)
- _fetch_tickers_from_table (RPC + parallel fallback)
- app.py unique-value wrappers (congress tickers/politicians, insider tickers/names)
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Add web_dashboard to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))


class MockSupabaseResult:
    """Helper to build mock Supabase query results."""
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class MockQueryBuilder:
    """Chainable mock for Supabase query builder."""
    def __init__(self, data=None, count=None):
        self._data = data or []
        self._count = count

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def range(self, start, end):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return MockSupabaseResult(self._data, self._count)


# =============================================================================
# Tests for fetch_unique_column_values_parallel
# =============================================================================

class TestFetchUniqueColumnValuesParallel(unittest.TestCase):
    """Tests for the parallel fetch utility in flask_data_utils."""

    def _get_func(self):
        from flask_data_utils import fetch_unique_column_values_parallel
        return fetch_unique_column_values_parallel

    def test_rpc_fast_path_success(self):
        """RPC returns distinct values — parallel path should be skipped."""
        func = self._get_func()

        mock_client = MagicMock()
        mock_client.supabase.rpc.return_value.execute.return_value = MockSupabaseResult(
            data=[{'value': 'AAPL'}, {'value': 'MSFT'}, {'value': 'GOOG'}]
        )

        result = func(mock_client, 'securities', 'ticker')

        self.assertEqual(result, ['AAPL', 'GOOG', 'MSFT'])
        mock_client.supabase.rpc.assert_called_once_with(
            'get_distinct_column_values',
            {'p_table': 'securities', 'p_column': 'ticker'}
        )
        # table() should NOT be called (parallel path skipped)
        mock_client.supabase.table.assert_not_called()

    def test_rpc_fallback_to_parallel(self):
        """RPC raises exception — should fall back to parallel pagination."""
        func = self._get_func()

        mock_client = MagicMock()
        # RPC fails
        mock_client.supabase.rpc.return_value.execute.side_effect = Exception("RPC not found")

        # Parallel path: count returns 3, single chunk returns data
        mock_table = MagicMock()
        mock_client.supabase.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.range.return_value = mock_table

        # First call is count query, subsequent calls are chunk fetches
        mock_table.execute.side_effect = [
            MockSupabaseResult(data=[{'ticker': 'X'}], count=3),  # count query
            MockSupabaseResult(data=[  # chunk fetch
                {'ticker': 'AAPL'}, {'ticker': 'MSFT'}, {'ticker': 'GOOG'}
            ]),
        ]

        result = func(mock_client, 'securities', 'ticker')

        self.assertEqual(sorted(result), ['AAPL', 'GOOG', 'MSFT'])

    def test_empty_table(self):
        """Count = 0 should return empty list."""
        func = self._get_func()

        mock_client = MagicMock()
        mock_client.supabase.rpc.return_value.execute.side_effect = Exception("no RPC")

        mock_table = MagicMock()
        mock_client.supabase.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value = MockSupabaseResult(data=[], count=0)

        result = func(mock_client, 'some_table', 'col')
        self.assertEqual(result, [])

    def test_null_client_returns_empty(self):
        """None client should return empty list."""
        func = self._get_func()
        result = func(None, 'any_table', 'any_col')
        self.assertEqual(result, [])

    def test_rpc_filters_null_values(self):
        """RPC result with null values should be filtered out."""
        func = self._get_func()

        mock_client = MagicMock()
        mock_client.supabase.rpc.return_value.execute.return_value = MockSupabaseResult(
            data=[{'value': 'AAPL'}, {'value': None}, {'value': ''}, {'value': 'MSFT'}]
        )

        result = func(mock_client, 'securities', 'ticker')
        # None and '' should be filtered out
        self.assertEqual(result, ['AAPL', 'MSFT'])

    def test_deduplication(self):
        """Parallel chunks with overlapping values should produce unique results."""
        func = self._get_func()

        mock_client = MagicMock()
        mock_client.supabase.rpc.return_value.execute.side_effect = Exception("no RPC")

        mock_table = MagicMock()
        mock_client.supabase.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.range.return_value = mock_table

        # Count = 10000, so 2 chunks of 5000
        mock_table.execute.side_effect = [
            MockSupabaseResult(data=[], count=10000),
            MockSupabaseResult(data=[{'ticker': 'AAPL'}, {'ticker': 'MSFT'}]),
            MockSupabaseResult(data=[{'ticker': 'MSFT'}, {'ticker': 'GOOG'}]),
        ]

        result = func(mock_client, 'securities', 'ticker')
        # MSFT appears in both chunks, should be deduped
        self.assertEqual(result, ['AAPL', 'GOOG', 'MSFT'])


# =============================================================================
# Tests for _fetch_tickers_from_table
# =============================================================================

class TestFetchTickersFromTable(unittest.TestCase):
    """Tests for ticker_utils._fetch_tickers_from_table."""

    def _get_func(self):
        from ticker_utils import _fetch_tickers_from_table
        return _fetch_tickers_from_table

    def test_rpc_success_no_filter(self):
        """Without extra_filter, RPC DISTINCT should be used."""
        func = self._get_func()

        mock_client = MagicMock()
        mock_client.supabase.rpc.return_value.execute.return_value = MockSupabaseResult(
            data=[{'value': 'aapl'}, {'value': 'MSFT'}]
        )

        result = func(mock_client, 'securities')

        self.assertEqual(result, {'AAPL', 'MSFT'})
        mock_client.supabase.rpc.assert_called_once()

    def test_rpc_skipped_with_extra_filter(self):
        """With extra_filter, RPC is skipped and parallel path used."""
        func = self._get_func()

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.supabase.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.range.return_value = mock_table
        mock_table.execute.side_effect = [
            MockSupabaseResult(data=[], count=2),
            MockSupabaseResult(data=[{'ticker': 'AAPL'}, {'ticker': 'GOOG'}]),
        ]

        result = func(mock_client, 'securities', extra_filter={'fund': 'test'})

        # RPC should NOT be called
        mock_client.supabase.rpc.assert_not_called()
        self.assertEqual(result, {'AAPL', 'GOOG'})

    def test_rpc_fallback_on_error(self):
        """RPC failure should fall back to parallel path."""
        func = self._get_func()

        mock_client = MagicMock()
        mock_client.supabase.rpc.return_value.execute.side_effect = Exception("RPC error")

        mock_table = MagicMock()
        mock_client.supabase.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.range.return_value = mock_table
        mock_table.execute.side_effect = [
            MockSupabaseResult(data=[], count=1),
            MockSupabaseResult(data=[{'ticker': 'TEST'}]),
        ]

        result = func(mock_client, 'securities')
        self.assertIn('TEST', result)

    def test_empty_table(self):
        """Table with 0 rows should return empty set."""
        func = self._get_func()

        mock_client = MagicMock()
        mock_client.supabase.rpc.return_value.execute.side_effect = Exception("no RPC")

        mock_table = MagicMock()
        mock_client.supabase.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value = MockSupabaseResult(data=[], count=0)

        result = func(mock_client, 'securities')
        self.assertEqual(result, set())


# =============================================================================
# Tests for app.py wrapper functions (integration mocks)
# =============================================================================

class TestAppUniqueValueWrappers(unittest.TestCase):
    """Tests that app.py Congress/Insider wrappers correctly delegate."""

    @patch('flask_data_utils.fetch_unique_column_values_parallel')
    def test_congress_tickers_delegates(self, mock_parallel):
        """get_unique_tickers_congress should delegate to parallel fetch."""
        mock_parallel.return_value = ['AAPL', 'MSFT']
        mock_client = MagicMock()

        # Import after patching to avoid caching issues
        from importlib import import_module, reload
        app_module = import_module('app')

        # Call the function (bypass cache for testing)
        result = app_module.get_unique_tickers_congress.__wrapped__(mock_client, 0, 'v1')

        mock_parallel.assert_called_once_with(
            mock_client, 'congress_trades_enriched', 'ticker'
        )
        self.assertEqual(result, ['AAPL', 'MSFT'])

    @patch('flask_data_utils.fetch_unique_column_values_parallel')
    def test_congress_politicians_delegates(self, mock_parallel):
        """get_unique_politicians_congress should delegate to parallel fetch."""
        mock_parallel.return_value = ['Jane Doe', 'John Smith']
        mock_client = MagicMock()

        from importlib import import_module
        app_module = import_module('app')

        result = app_module.get_unique_politicians_congress.__wrapped__(mock_client, 0, 'v1')

        mock_parallel.assert_called_once_with(
            mock_client, 'congress_trades_enriched', 'politician'
        )
        self.assertEqual(result, ['Jane Doe', 'John Smith'])

    @patch('flask_data_utils.fetch_unique_column_values_parallel')
    def test_insider_tickers_delegates(self, mock_parallel):
        """get_unique_tickers_insider should delegate to parallel fetch."""
        mock_parallel.return_value = ['NVDA', 'TSLA']
        mock_client = MagicMock()

        from importlib import import_module
        app_module = import_module('app')

        result = app_module.get_unique_tickers_insider.__wrapped__(mock_client, 0, 'v1')

        mock_parallel.assert_called_once_with(
            mock_client, 'insider_trades', 'ticker'
        )
        self.assertEqual(result, ['NVDA', 'TSLA'])


if __name__ == '__main__':
    unittest.main()
