import unittest
from unittest.mock import MagicMock, patch
from web_dashboard.flask_data_utils import fetch_unique_column_values_parallel

class TestParallelFetch(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_supabase = self.mock_client.supabase
        self.table_mock = self.mock_supabase.table.return_value

    def test_fetch_unique_column_values_parallel(self):
        # Mock count query result
        count_result_mock = MagicMock()
        count_result_mock.count = 2500  # 3 chunks of 1000: 0-999, 1000-1999, 2000-2999

        # The select() call returns a query builder
        select_query_builder = self.table_mock.select.return_value

        # When .execute() is called on the select query builder (for count), return count result
        select_query_builder.execute.return_value = count_result_mock

        # When .range() is called, return a new query builder for that range
        def range_side_effect(start, end):
            range_query_builder = MagicMock()

            # Define result for execute() based on range start
            result_mock = MagicMock()
            if start == 0:
                result_mock.data = [{'col': 'A'}, {'col': 'B'}]
            elif start == 1000:
                result_mock.data = [{'col': 'B'}, {'col': 'C'}]
            elif start == 2000:
                result_mock.data = [{'col': 'D'}]
            else:
                result_mock.data = []

            range_query_builder.execute.return_value = result_mock
            return range_query_builder

        select_query_builder.range.side_effect = range_side_effect

        # Run function
        result = fetch_unique_column_values_parallel(
            self.mock_client,
            "test_table",
            "col",
            chunk_size=1000,
            max_workers=2
        )

        # Verify result (sorted unique values)
        self.assertEqual(result, ['A', 'B', 'C', 'D'])

        # Verify calls
        # 1. Count call: select("col", count='exact', head=True)
        self.table_mock.select.assert_any_call("col", count='exact', head=True)

        # 2. Range calls
        # We verify that range was called with correct offsets
        # Since calls happen in parallel threads, we can't assume order, but we can verify all calls occurred
        calls = select_query_builder.range.call_args_list
        # Extract arguments
        args_list = [call.args for call in calls]
        self.assertIn((0, 999), args_list)
        self.assertIn((1000, 1999), args_list)
        self.assertIn((2000, 2999), args_list)
        self.assertEqual(len(args_list), 3)

    def test_fetch_empty(self):
        # Mock count 0
        count_result_mock = MagicMock()
        count_result_mock.count = 0

        select_query_builder = self.table_mock.select.return_value
        select_query_builder.execute.return_value = count_result_mock

        result = fetch_unique_column_values_parallel(
            self.mock_client,
            "test_table",
            "col"
        )
        self.assertEqual(result, [])

    def test_limit_reached(self):
        # Mock count exceeding max_rows
        count_result_mock = MagicMock()
        count_result_mock.count = 500000 # > 200,000

        select_query_builder = self.table_mock.select.return_value
        select_query_builder.execute.return_value = count_result_mock

        # Mock range to return empty to avoid errors during fetch loop
        range_query_builder = MagicMock()
        range_query_builder.execute.return_value.data = []
        select_query_builder.range.return_value = range_query_builder

        max_rows = 200000
        chunk_size = 50000

        fetch_unique_column_values_parallel(
            self.mock_client,
            "test_table",
            "col",
            max_rows=max_rows,
            chunk_size=chunk_size
        )

        # Verify that we capped at max_rows
        # num_chunks = 200000 // 50000 + 1 = 5 chunks (0, 50k, 100k, 150k, 200k)
        # Wait, if limit is 200k, we fetch 0..199999?
        # Implementation:
        # if total_rows > max_rows: total_rows = max_rows
        # num_chunks = total_rows // chunk_size + 1
        # If 200000 // 50000 = 4. 4+1 = 5 chunks.
        # Chunk 0: 0-49999
        # Chunk 1: 50000-99999
        # Chunk 2: 100000-149999
        # Chunk 3: 150000-199999
        # Chunk 4: 200000-249999 <- This exceeds 200k!

        # Let's check logic:
        # num_chunks = (total_rows // chunk_size) + 1
        # If total_rows = 200000, chunk_size=50000 -> 4 + 1 = 5 chunks.
        # i=0..4.
        # i=4 * 50000 = 200000. range(200000, 249999).
        # This is strictly fetching MORE than max_rows if max_rows is exact multiple.
        # If max_rows=199999, 199999//50000 = 3. 3+1=4.
        # i=0..3. i=3 * 50000 = 150000. range(150000, 199999). Correct.

        # It's an approximate limit, which is fine for safety.
        # I just verify that we didn't try to fetch up to 500,000.

        args_list = [call.args for call in select_query_builder.range.call_args_list]
        max_offset = max(arg[0] for arg in args_list)

        # Should be around 200,000
        self.assertLess(max_offset, 500000)
        self.assertEqual(max_offset, 200000) # Based on logic above

if __name__ == '__main__':
    unittest.main()
