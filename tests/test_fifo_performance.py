
import pytest
from unittest.mock import MagicMock, patch
import sys
import os
from collections import deque
from decimal import Decimal

# Add repo root to path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'web_dashboard'))

# Mock app and supabase_client
sys.modules['app'] = MagicMock()
sys.modules['supabase_client'] = MagicMock()
sys.modules['flask'] = MagicMock()
sys.modules['auth'] = MagicMock()
sys.modules['jwt'] = MagicMock()

# Import the function to test
from web_dashboard.routes.admin_routes import calculate_fifo_pnl

# Mock the get_supabase_client function
from app import get_supabase_client

@pytest.fixture
def mock_supabase_client():
    mock_client = MagicMock()
    # Setup chain: client.supabase.table().select().eq().eq().order().execute()
    mock_table = mock_client.supabase.table.return_value
    mock_select = mock_table.select.return_value
    mock_eq1 = mock_select.eq.return_value
    mock_eq2 = mock_eq1.eq.return_value
    mock_order = mock_eq2.order.return_value

    # Configure execute to return some trades
    mock_response = MagicMock()
    # Generate some dummy trades
    mock_response.data = [
        {'shares': 100, 'price': 10.0, 'reason': 'BUY', 'action': 'BUY', 'date': '2023-01-01'},
        {'shares': 100, 'price': 20.0, 'reason': 'BUY', 'action': 'BUY', 'date': '2023-01-02'}
    ]
    mock_order.execute.return_value = mock_response

    get_supabase_client.return_value = mock_client
    return mock_client

def test_calculate_fifo_pnl_baseline(benchmark, mock_supabase_client):
    """Benchmark the calculate_fifo_pnl function without pre-fetched data (Baseline)."""
    # This simulates the old behavior where it fetches from DB
    result = benchmark(calculate_fifo_pnl, "Test Fund", "TEST", 50.0, 30.0)
    assert result == 1000.0

def test_calculate_fifo_pnl_optimized(benchmark, mock_supabase_client):
    """Benchmark the calculate_fifo_pnl function WITH pre-fetched data (Optimized)."""

    # Pre-fetch data
    existing_trades = [
        {'shares': 100, 'price': 10.0, 'reason': 'BUY', 'action': 'BUY', 'date': '2023-01-01'},
        {'shares': 100, 'price': 20.0, 'reason': 'BUY', 'action': 'BUY', 'date': '2023-01-02'}
    ]

    # Run benchmark passing existing_trades
    result = benchmark(calculate_fifo_pnl, "Test Fund", "TEST", 50.0, 30.0, existing_trades)
    assert result == 1000.0

def test_calculate_fifo_pnl_db_calls(mock_supabase_client):
    """Verify DB calls."""
    # Without existing_trades, should call DB
    calculate_fifo_pnl("Test Fund", "TEST", 50.0, 30.0)
    assert mock_supabase_client.supabase.table.called

    mock_supabase_client.supabase.table.reset_mock()

    # With existing_trades, should NOT call DB
    existing_trades = [{'shares': 100, 'price': 10.0, 'action': 'BUY'}]
    calculate_fifo_pnl("Test Fund", "TEST", 50.0, 30.0, existing_trades)
    assert not mock_supabase_client.supabase.table.called
