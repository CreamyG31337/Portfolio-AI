
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add web_dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard')))

from flask_data_utils import fetch_latest_rates_bulk_flask

def test_fetch_latest_rates_optimization():
    """Test that fetch_latest_rates_bulk_flask is optimized."""

    # Mock Supabase client
    mock_client = MagicMock()
    mock_table = mock_client.supabase.table.return_value
    mock_select = mock_table.select.return_value
    mock_gte = mock_select.gte.return_value

    # Setup mock return data
    mock_result = MagicMock()
    mock_result.data = [
        {"from_currency": "USD", "to_currency": "CAD", "timestamp": "2024-01-01T00:00:00", "rate": 1.35},
        {"from_currency": "CAD", "to_currency": "USD", "timestamp": "2024-01-01T00:00:00", "rate": 0.74}
    ]

    # Handle the chain: table -> select -> gte -> in_ -> in_ -> execute
    # Chain: select() -> gte() -> in_() -> in_() -> execute()

    # Since .in_() returns the builder, we can make it return mock_gte to simulate chaining
    mock_gte.in_.return_value = mock_gte
    mock_gte.execute.return_value = mock_result

    with patch('flask_data_utils.get_supabase_client_flask', return_value=mock_client):
        # Call the function
        currencies = ["USD", "CAD", "EUR"]
        target = "CAD"
        fetch_latest_rates_bulk_flask(currencies, target)

        # Check what select was called with
        # It should be specific columns now
        mock_table.select.assert_called_with('from_currency,to_currency,timestamp,rate')

        # Check if filtering was applied
        # We expect two in_ calls: one for from_currency, one for to_currency
        assert mock_gte.in_.call_count == 2

        # Verify arguments
        call_args_list = mock_gte.in_.call_args_list
        columns_filtered = [args[0] for args, kwargs in call_args_list]
        values_filtered = [args[1] for args, kwargs in call_args_list]

        assert 'from_currency' in columns_filtered
        assert 'to_currency' in columns_filtered

        # Check values
        expected_currencies = {'USD', 'CAD', 'EUR'}
        for val_list in values_filtered:
            assert set(val_list) == expected_currencies
