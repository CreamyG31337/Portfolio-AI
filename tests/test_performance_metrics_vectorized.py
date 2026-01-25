
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import sys
import os

# Add web_dashboard to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard')))

from flask_data_utils import calculate_performance_metrics_flask

def test_calculate_performance_metrics_logic():
    """Test the logic of calculate_performance_metrics_flask with vectorized operations."""
    # Create sample data
    # Row 1: market_value provided
    # Row 2: market_value 0, calculated from shares * current_price
    # Row 3: everything 0
    data = {
        'shares': [10.0, 20.0, 0.0],
        'current_price': [100.0, 50.0, 0.0],
        'price': [90.0, 45.0, 0.0], # Fallback price
        'market_value': [1000.0, 0.0, 0.0],
        'cost_basis': [900.0, 800.0, 0.0]
    }
    positions_df = pd.DataFrame(data)

    # Expected calculations:
    # Row 1: Value = 1000.0 (market_value), Cost = 900.0
    # Row 2: Value = 20 * 50 = 1000.0 (calculated), Cost = 800.0
    # Row 3: Value = 0, Cost = 0
    # Total Value = 2000.0
    # Total Cost = 1700.0
    # Return Pct = (2000 - 1700) / 1700 * 100 = 17.647...

    expected_value = 2000.0
    expected_cost = 1700.0
    expected_return = (expected_value - expected_cost) / expected_cost * 100

    # Mock dependencies
    with patch('flask_data_utils.get_current_positions_flask', return_value=positions_df), \
         patch('flask_data_utils.calculate_portfolio_value_over_time_flask', return_value=pd.DataFrame()):

        result = calculate_performance_metrics_flask("TestFund")

        assert result['current_value'] == expected_value
        assert result['total_invested'] == expected_cost
        assert abs(result['total_return_pct'] - expected_return) < 0.0001

def test_calculate_performance_metrics_empty():
    """Test behavior with empty dataframe."""
    with patch('flask_data_utils.get_current_positions_flask', return_value=pd.DataFrame()), \
         patch('flask_data_utils.calculate_portfolio_value_over_time_flask', return_value=pd.DataFrame()):

        result = calculate_performance_metrics_flask("TestFund")

        assert result['current_value'] == 0.0
        assert result['total_invested'] == 0.0
        assert result['total_return_pct'] == 0.0
