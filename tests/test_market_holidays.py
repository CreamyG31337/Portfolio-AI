"""
Tests for MarketHolidays class.
"""
from datetime import date
import pytest
from utils.market_holidays import MarketHolidays

class TestMarketHolidays:
    def setup_method(self):
        self.holidays = MarketHolidays()

    def test_martin_luther_king_day_2026(self):
        """
        Verify holiday handling for Martin Luther King Jr. Day 2026.

        Requirements:
        - U.S. markets and banks are closed on Monday, January 19th, 2026.
        - Canadian banks and markets will remain open.
        - Regular U.S. market and banking operations will resume on Tuesday, January 20, 2026.
        """
        mlk_day = date(2026, 1, 19)
        next_day = date(2026, 1, 20)

        # 1. Check US market is closed
        assert self.holidays.is_us_market_closed(mlk_day) == True, "US market should be closed on MLK Day 2026"
        assert self.holidays.is_trading_day(mlk_day, market="us") == False

        # 2. Check Canadian market is open
        assert self.holidays.is_canadian_market_closed(mlk_day) == False, "Canadian market should be open on MLK Day 2026"
        assert self.holidays.is_trading_day(mlk_day, market="canadian") == True

        # 3. Check combined market logic
        # 'any' means AT LEAST ONE market is open. Since Canada is open, this should be True.
        assert self.holidays.is_trading_day(mlk_day, market="any") == True, "Should be a trading day for 'any' market"

        # 'both' means BOTH markets must be open. Since US is closed, this should be False.
        assert self.holidays.is_trading_day(mlk_day, market="both") == False, "Should NOT be a trading day for 'both' markets"

        # 4. Check holiday name
        assert self.holidays.get_holiday_name(mlk_day) == "Martin Luther King, Jr. Day"

        # 5. Check next day (Jan 20, 2026) is a regular trading day
        assert self.holidays.is_us_market_closed(next_day) == False
        assert self.holidays.is_canadian_market_closed(next_day) == False
        assert self.holidays.is_trading_day(next_day, market="us") == True
        assert self.holidays.is_trading_day(next_day, market="canadian") == True
        assert self.holidays.is_trading_day(next_day, market="any") == True
        assert self.holidays.is_trading_day(next_day, market="both") == True

    def test_martin_luther_king_day_general_rule(self):
        """Verify MLK Day is always the 3rd Monday of January."""
        # 2023 MLK Day: Jan 16
        assert self.holidays.is_us_market_closed(date(2023, 1, 16)) == True
        assert self.holidays.get_holiday_name(date(2023, 1, 16)) == "Martin Luther King, Jr. Day"

        # 2024 MLK Day: Jan 15
        assert self.holidays.is_us_market_closed(date(2024, 1, 15)) == True

        # 2025 MLK Day: Jan 20
        assert self.holidays.is_us_market_closed(date(2025, 1, 20)) == True

    def test_other_holidays_2026(self):
        """Verify other major holidays in 2026."""
        # New Year's Day (Shared) - Thursday Jan 1
        assert self.holidays.is_us_market_closed(date(2026, 1, 1)) == True
        assert self.holidays.is_canadian_market_closed(date(2026, 1, 1)) == True

        # Good Friday (Shared) - April 3
        assert self.holidays.is_us_market_closed(date(2026, 4, 3)) == True
        assert self.holidays.is_canadian_market_closed(date(2026, 4, 3)) == True

        # Christmas (Shared) - Friday Dec 25
        assert self.holidays.is_us_market_closed(date(2026, 12, 25)) == True
        assert self.holidays.is_canadian_market_closed(date(2026, 12, 25)) == True

        # Canada Day (Canada only) - Wednesday July 1
        assert self.holidays.is_us_market_closed(date(2026, 7, 1)) == False
        assert self.holidays.is_canadian_market_closed(date(2026, 7, 1)) == True

        # Independence Day (US only) - Observed on Friday July 3 (since July 4 is Saturday)
        # Note: MarketHolidays logic: if July 4 is Saturday, observed on Friday (July 3)
        assert self.holidays.is_us_market_closed(date(2026, 7, 3)) == True
        assert self.holidays.is_canadian_market_closed(date(2026, 7, 3)) == False
