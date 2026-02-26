import sys
import os
import pandas as pd
from unittest.mock import MagicMock, patch
from flask import Flask

# Add web_dashboard to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../web_dashboard')))

# Mock modules
sys.modules['streamlit'] = MagicMock()
sys.modules['streamlit.runtime.scriptrunner'] = MagicMock()

# Mock auth
mock_auth = MagicMock()
mock_auth.require_auth.return_value = lambda f: f
sys.modules['auth'] = mock_auth

from web_dashboard.routes.dashboard_routes import get_holdings_data

def test_holdings_route_logo_resolution():
    print("Testing get_holdings_data logo resolution...")

    # Create minimal Flask app context
    app = Flask(__name__)

    # Mock data
    mock_df = pd.DataFrame([
        {
            "ticker": "TEST",
            "market_value": 1000,
            "currency": "USD",
            "shares": 10,
            "cost_basis": 900,
            "current_price": 100,
            "unrealized_pnl": 100,
            "return_pct": 10,
            "daily_pnl": 10,
            "daily_pnl_pct": 1,
            "five_day_pnl": 50,
            "five_day_pnl_pct": 5,
            "sector": "Tech",
            "industry": "Software",
            "website": "test.com"
        }
    ])

    with app.test_request_context():
        # IMPORTANT: Patch the functions where they are imported IN THE MODULE
        with patch('web_dashboard.routes.dashboard_routes.get_current_positions') as mock_get_current_positions, \
             patch('web_dashboard.routes.dashboard_routes.get_positions_as_of_date_flask') as mock_get_positions_as_of, \
             patch('web_dashboard.routes.dashboard_routes.get_first_trade_dates') as mock_get_dates, \
             patch('web_dashboard.routes.dashboard_routes.fetch_latest_rates_bulk') as mock_rates, \
             patch('web_dashboard.utils.logo_utils.get_ticker_logo_url') as mock_get_logo:

            # Setup mocks
            mock_get_current_positions.return_value = mock_df
            mock_get_positions_as_of.return_value = mock_df
            mock_get_dates.return_value = {}
            mock_rates.return_value = {"USD": 1.0}

            # Mock get_ticker_logo_url to verify arguments
            mock_get_logo.return_value = "https://logo.url"

            # Execute route handler
            try:
                # get_holdings_data reads from request.args, which is empty in test_request_context by default
                # This matches our desired default path (fund=None, range='ALL')
                response = get_holdings_data()
            except Exception as e:
                print(f"Function raised exception: {e}")
                import traceback
                traceback.print_exc()
                return

            # Verify get_ticker_logo_url was called with correct arguments
            call_args = mock_get_logo.call_args
            if call_args:
                args, kwargs = call_args
                print(f"get_ticker_logo_url called with: args={args}, kwargs={kwargs}")

                if args[0] == "TEST" and kwargs.get('use_alt') is True and kwargs.get('website') == "test.com":
                    print("VERIFICATION: SUCCESS - get_ticker_logo_url called correctly with website.")
                else:
                    print("VERIFICATION: FAILURE - get_ticker_logo_url arguments incorrect.")
            else:
                print("VERIFICATION: FAILURE - get_ticker_logo_url was NOT called.")

if __name__ == "__main__":
    test_holdings_route_logo_resolution()
