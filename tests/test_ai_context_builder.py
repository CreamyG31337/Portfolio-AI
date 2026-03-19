import pytest
import pandas as pd
from web_dashboard.ai_context_builder import _format_portfolio_snapshot_table, format_price_volume_table

def test_itertuples_replaces_iterrows_snapshot_table():
    df = pd.DataFrame({
        'symbol': ['AAPL', 'MSFT'],
        'shares': [10, 20],
        'market_value': [1500, 6000],
        'unrealized_pnl': [100, 500],
        'company': ['Apple Inc.', 'Microsoft Corp.']
    })

    output = _format_portfolio_snapshot_table(df, "Test Fund")

    assert "AAPL" in output
    assert "Apple Inc." in output
    assert "10.0" in output
    assert "1,500" in output
    assert "MSFT" in output

def test_itertuples_replaces_iterrows_price_volume():
    df = pd.DataFrame({
        'symbol': ['GOOGL', 'AMZN'],
        'current_price': [100.5, 120.0],
        'yesterday_price': [95.0, 115.0]
    })

    output = format_price_volume_table(df)

    assert "GOOGL" in output
    assert "100.50" in output
    assert "AMZN" in output
    assert "120.00" in output

if __name__ == '__main__':
    pytest.main(['-v', __file__])
