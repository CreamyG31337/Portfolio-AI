"""Unit tests for PriceService.

These tests verify the price service functionality without touching
any storage layer (no CSV, no Supabase). All tests use mocks for
external dependencies.
"""

import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch
import pandas as pd

from utils.price_service import PriceService
from data.models.portfolio import Position


class TestPriceService(unittest.TestCase):
    """Test suite for PriceService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_fetcher = Mock()
        self.mock_cache = Mock()
        self.mock_market_hours = Mock()
        
        self.service = PriceService(
            market_data_fetcher=self.mock_fetcher,
            price_cache=self.mock_cache,
            market_hours=self.mock_market_hours
        )
        
        # Sample dates
        self.today = datetime.now()
        self.week_ago = self.today - timedelta(days=7)
    
    def test_get_historical_prices_cache_hit(self):
        """Test historical price fetch with cache hit."""
        # Setup mock cache to return data
        mock_df = pd.DataFrame({
            'Close': [100.0, 101.0, 102.0],
            'Volume': [1000, 1100, 1200]
        })
        self.mock_cache.get_cached_price.return_value = mock_df
        
        # Fetch prices
        market_data, hits, calls = self.service.get_historical_prices(
            ['AAPL'],
            self.week_ago,
            self.today,
            verbose=False
        )
        
        # Verify results
        self.assertEqual(len(market_data), 1)
        self.assertTrue('AAPL' in market_data)
        self.assertEqual(hits, 1)
        self.assertEqual(calls, 0)
        
        # Verify cache was checked
        self.mock_cache.get_cached_price.assert_called_once()
    
    def test_get_historical_prices_cache_miss(self):
        """Test historical price fetch with cache miss (API call)."""
        # Setup cache to return None (miss)
        self.mock_cache.get_cached_price.return_value = None
        
        # Setup fetcher to return data
        mock_df = pd.DataFrame({
            'Close': [100.0, 101.0, 102.0],
            'Volume': [1000, 1100, 1200]
        })
        mock_result = Mock()
        mock_result.df = mock_df
        mock_result.source = 'yfinance'
        self.mock_fetcher.fetch_price_data.return_value = mock_result
        
        # Fetch prices
        market_data, hits, calls = self.service.get_historical_prices(
            ['MSFT'],
            self.week_ago,
            self.today,
            verbose=False
        )
        
        # Verify results
        self.assertEqual(len(market_data), 1)
        self.assertTrue('MSFT' in market_data)
        self.assertEqual(hits, 0)
        self.assertEqual(calls, 1)
        
        # Verify API was called
        self.mock_fetcher.fetch_price_data.assert_called_once()
        
        # Verify result was cached
        self.mock_cache.cache_price_data.assert_called_once()
    
    def test_get_historical_prices_multiple_tickers(self):
        """Test fetching historical prices for multiple tickers."""
        # Setup mixed cache hits and misses
        def cache_side_effect(ticker, start, end):
            if ticker == 'AAPL':
                return pd.DataFrame({'Close': [100.0]})
            return None
        
        self.mock_cache.get_cached_price.side_effect = cache_side_effect
        
        # Setup fetcher for cache misses
        mock_df = pd.DataFrame({'Close': [200.0]})
        mock_result = Mock()
        mock_result.df = mock_df
        mock_result.source = 'yfinance'
        self.mock_fetcher.fetch_price_data.return_value = mock_result
        
        # Fetch prices
        market_data, hits, calls = self.service.get_historical_prices(
            ['AAPL', 'MSFT', 'GOOGL'],
            self.week_ago,
            self.today,
            verbose=False
        )
        
        # Verify results
        self.assertEqual(len(market_data), 3)
        self.assertEqual(hits, 1)  # AAPL from cache
        self.assertEqual(calls, 2)  # MSFT and GOOGL from API
    
    def test_get_current_prices_success(self):
        """Test current price fetching."""
        # Setup fetcher to return prices
        def price_side_effect(ticker):
            prices = {
                'AAPL': Decimal('150.25'),
                'MSFT': Decimal('300.50')
            }
            return prices.get(ticker)
        
        self.mock_fetcher.get_current_price.side_effect = price_side_effect
        
        # Fetch prices
        prices = self.service.get_current_prices(['AAPL', 'MSFT'], verbose=False)
        
        # Verify results
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices['AAPL'], Decimal('150.25'))
        self.assertEqual(prices['MSFT'], Decimal('300.50'))
    
    def test_get_current_prices_failure(self):
        """Test current price fetching with API failure."""
        # Setup fetcher to return None
        self.mock_fetcher.get_current_price.return_value = None
        
        # Fetch prices
        prices = self.service.get_current_prices(['INVALID'], verbose=False)
        
        # Verify results
        self.assertEqual(len(prices), 1)
        self.assertIsNone(prices['INVALID'])
    
    def test_update_positions_with_historical_prices(self):
        """Test updating positions with historical price data."""
        # Create sample positions
        positions = [
            Position(
                ticker='AAPL',
                shares=Decimal('100'),
                avg_price=Decimal('140.00'),
                cost_basis=Decimal('14000.00'),
                currency='USD',
                company='Apple Inc.',
                current_price=Decimal('140.00')
            )
        ]
        
        # Setup mock data
        mock_df = pd.DataFrame({'Close': [150.0]})
        self.mock_cache.get_cached_price.return_value = mock_df
        
        # Update positions
        updated, hits, calls = self.service.update_positions_with_prices(
            positions,
            use_historical=True,
            start_date=self.week_ago,
            end_date=self.today,
            verbose=False
        )
        
        # Verify results
        self.assertEqual(len(updated), 1)
        pos = updated[0]
        
        # Verify price was updated
        self.assertEqual(pos.current_price, Decimal('150.0'))
        
        # Verify calculated fields
        expected_market_value = Decimal('100') * Decimal('150.0')
        self.assertEqual(pos.market_value, expected_market_value)
        
        expected_pnl = (Decimal('150.0') - Decimal('140.00')) * Decimal('100')
        self.assertEqual(pos.unrealized_pnl, expected_pnl)
        
        # Verify original fields preserved
        self.assertEqual(pos.ticker, 'AAPL')
        self.assertEqual(pos.shares, Decimal('100'))
        self.assertEqual(pos.avg_price, Decimal('140.00'))
        self.assertEqual(pos.company, 'Apple Inc.')
    
    def test_update_positions_with_current_prices(self):
        """Test updating positions with current prices."""
        # Create sample positions
        positions = [
            Position(
                ticker='MSFT',
                shares=Decimal('50'),
                avg_price=Decimal('280.00'),
                cost_basis=Decimal('14000.00'),
                currency='USD',
                company='Microsoft Corp.'
            )
        ]
        
        # Setup mock current price
        self.mock_fetcher.get_current_price.return_value = Decimal('300.50')
        
        # Update positions
        updated, hits, calls = self.service.update_positions_with_prices(
            positions,
            use_historical=False,
            verbose=False
        )
        
        # Verify results
        self.assertEqual(len(updated), 1)
        pos = updated[0]
        
        # Verify price was updated
        self.assertEqual(pos.current_price, Decimal('300.50'))
        
        # Verify calculated fields
        expected_market_value = Decimal('50') * Decimal('300.50')
        self.assertEqual(pos.market_value, expected_market_value)
    
    def test_update_positions_fallback_to_existing_price(self):
        """Test behavior when fetch fails - positions without prices are excluded."""
        # Create position with existing price
        positions = [
            Position(
                ticker='AAPL',
                shares=Decimal('100'),
                avg_price=Decimal('140.00'),
                cost_basis=Decimal('14000.00'),
                currency='USD',
                company='Apple Inc.',
                current_price=Decimal('145.00'),  # Existing price from CSV
                market_value=Decimal('14500.00')
            )
        ]
        
        # Setup fetcher to return None (failure)
        self.mock_fetcher.get_current_price.return_value = None
        
        # Update positions
        updated, hits, calls = self.service.update_positions_with_prices(
            positions,
            use_historical=False,
            verbose=False
        )
        
        # Verify behavior: positions without prices are excluded (not kept with fallback)
        # This ensures data integrity - no stale prices will be saved
        self.assertEqual(len(updated), 0, "Positions without prices should be excluded")
    
    def test_update_positions_no_price_available(self):
        """Test handling position with no price available - position is excluded."""
        # Create position with no price
        positions = [
            Position(
                ticker='INVALID',
                shares=Decimal('100'),
                avg_price=Decimal('10.00'),
                cost_basis=Decimal('1000.00'),
                currency='CAD',
                company='Invalid Company'
            )
        ]
        
        # Setup fetcher to return None
        self.mock_fetcher.get_current_price.return_value = None
        
        # Update positions
        updated, hits, calls = self.service.update_positions_with_prices(
            positions,
            use_historical=False,
            verbose=False
        )
        
        # Verify position is excluded (not kept with None price)
        # This ensures data integrity - no stale prices will be saved
        self.assertEqual(len(updated), 0, "Positions without prices should be excluded")
    
    def test_update_positions_empty_list(self):
        """Test updating empty position list."""
        updated, hits, calls = self.service.update_positions_with_prices(
            [],
            use_historical=False,
            verbose=False
        )
        
        self.assertEqual(len(updated), 0)
        self.assertEqual(hits, 0)
        self.assertEqual(calls, 0)
    
    def test_update_positions_requires_dates_for_historical(self):
        """Test that historical mode requires date parameters."""
        positions = [Position(
            ticker='AAPL',
            shares=Decimal('100'),
            avg_price=Decimal('100'),
            cost_basis=Decimal('10000')
        )]
        
        with self.assertRaises(ValueError) as ctx:
            self.service.update_positions_with_prices(
                positions,
                use_historical=True,
                start_date=None,
                end_date=None
            )
        
        self.assertIn('start_date and end_date required', str(ctx.exception))
    
    @patch('utils.portfolio_update_logic.should_update_portfolio')
    def test_should_update_portfolio_delegates(self, mock_should_update):
        """Test that should_update_portfolio delegates to utility function."""
        # Setup mock
        mock_should_update.return_value = (True, "Market is open")
        mock_pm = Mock()
        
        # Call method
        should_update, reason = self.service.should_update_portfolio(mock_pm)
        
        # Verify delegation
        mock_should_update.assert_called_once_with(
            self.mock_market_hours,
            mock_pm,
            None
        )
        self.assertTrue(should_update)
        self.assertEqual(reason, "Market is open")
    
    @patch('utils.currency_converter.load_exchange_rates')
    @patch('utils.currency_converter.convert_usd_to_cad')
    def test_apply_currency_conversion(self, mock_convert, mock_load_rates):
        """Test currency conversion for mixed USD/CAD positions."""
        from pathlib import Path
        
        # Setup mocks
        mock_load_rates.return_value = {'USDCAD': Decimal('1.35')}
        mock_convert.return_value = Decimal('13500.00')  # 10000 USD * 1.35
        
        # Create mixed positions
        positions = [
            Position(
                ticker='AAPL',
                shares=Decimal('100'),
                avg_price=Decimal('100.00'),
                cost_basis=Decimal('10000.00'),
                currency='USD',
                current_price=Decimal('100.00'),
                market_value=Decimal('10000.00')
            ),
            Position(
                ticker='XMA.TO',
                shares=Decimal('1000'),
                avg_price=Decimal('5.00'),
                cost_basis=Decimal('5000.00'),
                currency='CAD',
                current_price=Decimal('5.00'),
                market_value=Decimal('5000.00')
            )
        ]
        
        # Apply conversion
        result = self.service.apply_currency_conversion(
            positions,
            Path('/fake/path')
        )
        
        # Verify results
        self.assertEqual(result['total_usd'], Decimal('10000.00'))
        self.assertEqual(result['total_cad'], Decimal('18500.00'))  # 13500 + 5000
        self.assertEqual(result['exchange_rate'], Decimal('1.35'))
    
    def test_format_cache_stats(self):
        """Test cache statistics formatting."""
        # With cache hits
        stats = self.service.format_cache_stats(8, 2)
        self.assertEqual(stats, "8 from cache, 2 fresh fetches")
        
        # Without cache hits
        stats = self.service.format_cache_stats(0, 5)
        self.assertEqual(stats, "5 API calls")


if __name__ == '__main__':
    unittest.main()

