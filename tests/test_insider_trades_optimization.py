import pytest
from unittest.mock import patch, MagicMock
import threading

def test_insider_trades_offloading(client):
    """
    Test that api_insider_trades_data offloads ticker metadata fetching to a background thread.
    """
    # Mock authentication and dependencies
    with patch('auth.auth_manager.verify_session') as mock_verify, \
         patch('flask_data_utils.get_supabase_client_flask') as mock_get_client, \
         patch('web_dashboard.app.threading.Thread') as mock_thread, \
         patch('web_dashboard.app.get_insider_trades_cached') as mock_get_trades, \
         patch('web_dashboard.app.get_unique_insider_names') as mock_get_names, \
         patch('web_dashboard.app.get_company_names_map_cached') as mock_get_company_names, \
         patch('cache_version.get_cache_version') as mock_get_version:

        # Setup mocks
        mock_verify.return_value = {'user_id': 'test', 'email': 'test@example.com'}

        # Mock Supabase client
        mock_supabase = MagicMock()
        # Mock securities table lookup to return nothing (empty list), causing 'UNKNOWN1' to be treated as unknown
        # The code does: supabase_client.supabase.table("securities").select(...).in_(...).execute()
        mock_supabase.supabase.table.return_value.select.return_value.in_.return_value.execute.return_value.data = []

        # Also mock ensure_ticker_in_securities for safety (though it shouldn't be called in main thread)
        mock_supabase.ensure_ticker_in_securities.return_value = True

        mock_get_client.return_value = mock_supabase

        # Mock trades data containing a ticker that will be unknown
        # The route will collect tickers from this list
        mock_get_trades.return_value = [{'ticker': 'UNKNOWN1', 'insider_name': 'Bob', 'transaction_date': '2023-01-01'}]

        # Mock other dependencies
        mock_get_names.return_value = []
        mock_get_company_names.return_value = {}
        mock_get_version.return_value = "v1"

        # Simulate authenticated user
        client.set_cookie('auth_token', 'valid_token')

        # Call the endpoint
        response = client.get('/api/insider_trades/data')

        # Verify success
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['trades']) == 1
        assert data['trades'][0]['ticker'] == 'UNKNOWN1'

        # Verify Thread was instantiated to handle background processing
        assert mock_thread.call_count == 1

        # Verify arguments passed to Thread
        # We expect target=_process_unknown_tickers_background and args=(['UNKNOWN1'], supabase_client)
        call_kwargs = mock_thread.call_args.kwargs
        target_func = call_kwargs.get('target')
        assert target_func.__name__ == '_process_unknown_tickers_background'

        thread_args = call_kwargs.get('args')
        assert 'UNKNOWN1' in thread_args[0]  # The list of tickers
        assert thread_args[1] == mock_supabase # The client

        # Verify thread was started
        mock_thread.return_value.start.assert_called_once()
