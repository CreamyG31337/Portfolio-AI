
import pytest
from unittest.mock import MagicMock
import sys
import os
import importlib
from collections import deque
from decimal import Decimal

# Add repo root to path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'web_dashboard'))

@pytest.fixture
def fifo_context(monkeypatch):
    app_mock = MagicMock()
    app_mock.get_supabase_client = MagicMock()
    monkeypatch.setitem(sys.modules, "app", app_mock)
    module = importlib.import_module("web_dashboard.routes.admin_routes")
    importlib.reload(module)
    yield {"module": module, "app_mock": app_mock}
    sys.modules.pop("web_dashboard.routes.admin_routes", None)

@pytest.fixture
def mock_supabase_client(fifo_context):
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

    fifo_context["app_mock"].get_supabase_client.return_value = mock_client
    return mock_client

def test_calculate_fifo_pnl_baseline(benchmark, mock_supabase_client, fifo_context):
    """Benchmark the calculate_fifo_pnl function without pre-fetched data (Baseline)."""
    # This simulates the old behavior where it fetches from DB
    calculate_fifo_pnl = fifo_context["module"].calculate_fifo_pnl
    result = benchmark(calculate_fifo_pnl, "Test Fund", "TEST", 50.0, 30.0)
    assert result == 1000.0

def test_calculate_fifo_pnl_optimized(benchmark, mock_supabase_client, fifo_context):
    """Benchmark the calculate_fifo_pnl function WITH pre-fetched data (Optimized)."""

    # Pre-fetch data
    existing_trades = [
        {'shares': 100, 'price': 10.0, 'reason': 'BUY', 'action': 'BUY', 'date': '2023-01-01'},
        {'shares': 100, 'price': 20.0, 'reason': 'BUY', 'action': 'BUY', 'date': '2023-01-02'}
    ]

    # Run benchmark passing existing_trades
    calculate_fifo_pnl = fifo_context["module"].calculate_fifo_pnl
    result = benchmark(calculate_fifo_pnl, "Test Fund", "TEST", 50.0, 30.0, existing_trades)
    assert result == 1000.0

def test_calculate_fifo_pnl_db_calls(mock_supabase_client, fifo_context):
    """Verify DB calls."""
    calculate_fifo_pnl = fifo_context["module"].calculate_fifo_pnl
    # Without existing_trades, should call DB
    calculate_fifo_pnl("Test Fund", "TEST", 50.0, 30.0)
    assert mock_supabase_client.supabase.table.called

    mock_supabase_client.supabase.table.reset_mock()

    # With existing_trades, should NOT call DB
    existing_trades = [{'shares': 100, 'price': 10.0, 'action': 'BUY'}]
    calculate_fifo_pnl("Test Fund", "TEST", 50.0, 30.0, existing_trades)
    assert not mock_supabase_client.supabase.table.called
