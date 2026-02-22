import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add web_dashboard to path to allow importing parallel_utils
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from web_dashboard.parallel_utils import get_unique_values_parallel

class TestParallelUtils(unittest.TestCase):
    def test_get_unique_values_parallel(self):
        # Mock Supabase client
        mock_client = MagicMock()

        # Mock count query
        mock_count_res = MagicMock()
        mock_count_res.count = 20
        # The chain is table(..).select(.., head=True).execute()
        # Note: We need to ensure we mock the exact call structure.
        # But select() is called with different args for count vs fetch.

        # Mock the table object
        table_mock = MagicMock()
        mock_client.supabase.table.return_value = table_mock

        # Mock select() to differentiate between count and fetch
        # But simpler is to mock execute() return based on what select was called with?
        # Or just mock the first select call for count.

        # Mocking the count call:
        # client.supabase.table(table).select("*", count="exact", head=True).execute()
        count_select_mock = MagicMock()
        count_select_mock.execute.return_value = mock_count_res

        # Mocking the data fetch calls:
        # client.supabase.table(table).select(column).range(start, end).execute()
        data_select_mock = MagicMock()

        def select_side_effect(*args, **kwargs):
            if kwargs.get('count') == 'exact':
                return count_select_mock
            return data_select_mock

        table_mock.select.side_effect = select_side_effect

        # Mock range() on data_select_mock
        def range_side_effect(start, end):
            mock_execute = MagicMock()
            # Generate dummy data for this range: val_0 to val_19
            data = []
            # range is inclusive in Supabase? Yes, usually.
            # But the utility generates disjoint ranges.

            # Let's say we have 20 items.
            limit = 20

            for i in range(start, min(end + 1, limit)):
                data.append({'col': f'val_{i}'})

            # Duplicate item to test set uniqueness
            if start == 0:
                data.append({'col': 'val_0'})

            mock_execute.execute.return_value.data = data
            return mock_execute

        data_select_mock.range.side_effect = range_side_effect

        # Run function
        result = get_unique_values_parallel(
            mock_client,
            "test_table",
            "col",
            batch_size=5,
            max_workers=2,
            limit_rows=20
        )

        # Verify result
        expected = [f'val_{i}' for i in range(20)]
        self.assertEqual(result, sorted(expected))

        # Verify call count
        # Total 20 rows, batch 5 -> 4 calls (0-4, 5-9, 10-14, 15-19)
        self.assertEqual(data_select_mock.range.call_count, 4)

    def test_process_func(self):
        mock_client = MagicMock()

        # Mock count
        mock_client.supabase.table.return_value.select.return_value.execute.return_value.count = 5

        # Mock data fetch
        select_mock = MagicMock()
        mock_client.supabase.table.return_value.select.side_effect = \
            lambda *args, **kwargs: select_mock if not kwargs.get('count') else MagicMock(execute=lambda: MagicMock(count=5))

        def range_side_effect(start, end):
            mock_execute = MagicMock()
            # Return mixed case
            mock_execute.execute.return_value.data = [{'col': 'VAL_1'}, {'col': 'val_2'}, {'col': 'Val_1'}]
            return mock_execute

        select_mock.range.side_effect = range_side_effect

        def normalize(val):
            return val.lower()

        result = get_unique_values_parallel(
            mock_client, "t", "col", process_func=normalize, batch_size=5
        )

        # Should be normalized and deduped
        self.assertEqual(result, ['val_1', 'val_2'])

if __name__ == '__main__':
    unittest.main()
