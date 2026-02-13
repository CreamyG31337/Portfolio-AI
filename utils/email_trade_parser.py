"""Email trade parser utility.

This module provides functionality to parse trade information from email notifications
and convert them into Trade objects that can be added to the trading system.

Supports various email formats from different brokers and trading platforms.
"""

import re
import sys
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
import logging

# Ensure project root is in path for imports
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from data.models.trade import Trade
from utils.timezone_utils import parse_csv_timestamp, get_current_trading_time
from utils.ticker_utils import normalize_ticker_symbol

logger = logging.getLogger(__name__)


class EmailTradeParser:
    """Parser for extracting trade information from email notifications."""
    
    def __init__(self):
        """Initialize the email trade parser."""
        # Common patterns for different email formats
        self.patterns = {
            'symbol': [
                r'Symbol:\s*([A-Za-z0-9.]+)',
                r'Ticker:\s*([A-Za-z0-9.]+)',
                r'Stock:\s*([A-Za-z0-9.]+)',
                r'^([A-Za-z0-9.]+)\s*$',  # Standalone symbol
            ],
            'shares': [
                r'Shares:\s*([0-9,]+\.?[0-9]*)',
                r'Quantity:\s*([0-9,]+\.?[0-9]*)',
                r'Qty:\s*([0-9,]+\.?[0-9]*)',
                r'(\d+\.?\d*)\s*shares?',
            ],
            'price': [
                r'Average price:\s*.*?\$([0-9,]+\.?[0-9]*)',
                r'Average price:\s*[A-Z]*\$([0-9,]+\.?[0-9]*)',
                r'Average price:\s*US\$([0-9,]+\.?[0-9]*)',
                r'Average price:\s*CAD\$([0-9,]+\.?[0-9]*)',
                r'Price:\s*[A-Z]*\$?([0-9,]+\.?[0-9]*)',
                r'Fill price:\s*[A-Z]*\$?([0-9,]+\.?[0-9]*)',
                r'Executed at:\s*[A-Z]*\$?([0-9,]+\.?[0-9]*)',
                r'[A-Z]*\$([0-9,]+\.?[0-9]*)',
                r'price:\s*[A-Z]*\$?([0-9,]+\.?[0-9]*)',  # Case insensitive
            ],
            'total_cost': [
                r'Total cost:\s*US\$([0-9,]+\.?[0-9]*)',
                r'Total cost:\s*CA\$([0-9,]+\.?[0-9]*)',
                r'Total cost:\s*\$([0-9,]+\.?[0-9]*)',
                r'Total value:\s*US\$([0-9,]+\.?[0-9]*)',
                r'Total value:\s*CA\$([0-9,]+\.?[0-9]*)',
                r'Total value:\s*\$([0-9,]+\.?[0-9]*)',
                r'Total:\s*US\$([0-9,]+\.?[0-9]*)',
                r'Total:\s*CA\$([0-9,]+\.?[0-9]*)',
                r'Total:\s*\$([0-9,]+\.?[0-9]*)',
                r'Amount:\s*US\$([0-9,]+\.?[0-9]*)',
                r'Amount:\s*CA\$([0-9,]+\.?[0-9]*)',
                r'Amount:\s*\$([0-9,]+\.?[0-9]*)',
                r'Value:\s*US\$([0-9,]+\.?[0-9]*)',
                r'Value:\s*CA\$([0-9,]+\.?[0-9]*)',
                r'Value:\s*\$([0-9,]+\.?[0-9]*)',
            ],
            'action': [
                r'Type:\s*(Market\s+)?(Buy|Sell|Bought|Sold)',
                r'Type:\s*(Limit\s+)?(Buy|Sell|Bought|Sold)',
                r'Type:\s*(Fractional\s+)?(Buy|Sell|Bought|Sold)',
                r'Action:\s*(Buy|Sell|Bought|Sold)',
                r'(Buy|Sell|Bought|Sold)\s+order',
                r'Order type:\s*(Buy|Sell)',
            ],
            'time': [
                r'Time:\s*([^\\n]+)',
                r'Date:\s*([^\\n]+)',
                r'Executed:\s*([^\\n]+)',
                r'Fill time:\s*([^\\n]+)',
            ]
        }
    
    def parse_email_trade(self, email_text: str) -> Optional[Trade]:
        """Parse trade information from email text.
        
        Args:
            email_text: Raw email text containing trade information
            
        Returns:
            Trade object if parsing successful, None otherwise
        """
        try:
            # Clean up the email text
            cleaned_text = self._clean_email_text(email_text)
            
            # Extract trade components
            symbol = self._extract_symbol(cleaned_text)
            shares = self._extract_shares(cleaned_text)
            price = self._extract_price(cleaned_text)
            action = self._extract_action(cleaned_text)
            timestamp = self._extract_timestamp(cleaned_text)
            total_cost = self._extract_total_cost(cleaned_text)
            currency = self._extract_currency(cleaned_text)
            
            # Validate required fields
            if not all([symbol, shares, price, action]):
                missing = []
                if not symbol: missing.append('symbol')
                if not shares: missing.append('shares')
                if not price: missing.append('price')
                if not action: missing.append('action')
                logger.warning(f"Missing required fields: {missing}")
                return None
            
            # Normalize action
            action = self._normalize_action(action)
            
            # Normalize ticker symbol based on currency and price context
            symbol = normalize_ticker_symbol(symbol, currency, price)
            
            # Use provided timestamp or current time
            if not timestamp:
                timestamp = get_current_trading_time()
            else:
                # Convert to PDT for consistent formatting
                timestamp = self._convert_to_pdt(timestamp)
            
            # Calculate cost basis if not provided
            calculated_cost = shares * price
            if not total_cost:
                # Use calculated cost if not provided in email
                total_cost = calculated_cost
            else:
                # Verify email total matches calculated total
                if abs(total_cost - calculated_cost) > Decimal('0.01'):
                    print(f"⚠️  Warning: Email total cost (${total_cost}) doesn't match calculated cost (${calculated_cost}) for {symbol}")
                    logger.warning(f"Email total cost ({total_cost}) doesn't match calculated cost ({calculated_cost}) for {symbol}")
            
            # Create Trade object
            trade = Trade(
                ticker=symbol,
                action=action,
                shares=shares,
                price=price,
                timestamp=timestamp,
                cost_basis=total_cost,
                reason=f"EMAIL TRADE - {action}",
                currency=currency
            )
            
            # Validate currency matches ticker pattern and warn if mismatch
            self._validate_currency_ticker_match(symbol, currency)
            
            logger.info(f"Successfully parsed trade: {symbol} {action} {shares} @ {price}")
            return trade
            
        except Exception as e:
            logger.error(f"Failed to parse email trade: {e}")
            return None
    
    def _clean_email_text(self, text: str) -> str:
        """Clean and normalize email text for parsing."""
        # Remove extra whitespace and normalize line breaks
        text = re.sub(r'\s+', ' ', text.strip())
        # Remove common email headers/footers
        text = re.sub(r'^(From:|To:|Subject:|Date:).*$', '', text, flags=re.MULTILINE)
        return text
    
    def _extract_symbol(self, text: str) -> Optional[str]:
        """Extract ticker symbol from text."""
        for pattern in self.patterns['symbol']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                symbol = match.group(1).strip()
                # Clean up the symbol (remove extra spaces, normalize)
                symbol = re.sub(r'\s+', '', symbol)
                return symbol.upper()
        return None
    
    def _extract_shares(self, text: str) -> Optional[Decimal]:
        """Extract number of shares from text."""
        for pattern in self.patterns['shares']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                shares_str = match.group(1).replace(',', '')
                try:
                    return Decimal(shares_str)
                except ValueError:
                    continue
        return None
    
    def _extract_price(self, text: str) -> Optional[Decimal]:
        """Extract price per share from text."""
        for pattern in self.patterns['price']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                price_str = match.group(1).replace(',', '')
                try:
                    return Decimal(price_str)
                except ValueError:
                    continue
        return None
    
    def _extract_currency(self, text: str) -> str:
        """Extract currency from text (CAD, USD, etc.)."""
        # Look for currency indicators in the text
        if re.search(r'US\$|USD|US\s+Dollar|Average price:\s*US\$|Total cost:\s*US\$', text, re.IGNORECASE):
            return 'USD'
        elif re.search(r'CA\$|CAD|Canadian|C\$', text, re.IGNORECASE):
            return 'CAD'
        else:
            # Default to CAD for Canadian market
            return 'CAD'
    
    
    def _extract_total_cost(self, text: str) -> Optional[Decimal]:
        """Extract total cost from text."""
        for pattern in self.patterns['total_cost']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                cost_str = match.group(1).replace(',', '')
                try:
                    return Decimal(cost_str)
                except ValueError:
                    continue
        return None
    
    def _extract_action(self, text: str) -> Optional[str]:
        """Extract buy/sell action from text."""
        for pattern in self.patterns['action']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Get the last group (the actual action word)
                action = match.groups()[-1].strip()
                return action.upper()
        return None
    
    def _extract_timestamp(self, text: str) -> Optional[datetime]:
        """Extract timestamp from text."""
        for pattern in self.patterns['time']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = match.group(1).strip()
                return self._parse_timestamp(time_str)
        return None
    
    def _parse_timestamp(self, time_str: str) -> Optional[datetime]:
        """Parse various timestamp formats."""
        # Common timestamp formats
        formats = [
            '%B %d, %Y %H:%M %Z',  # September 12, 2025 09:30 EDT
            '%B %d, %Y %H:%M %Z%z',  # September 12, 2025 09:30 EDT-0400
            '%Y-%m-%d %H:%M:%S %Z',  # 2025-09-12 09:30:00 EDT
            '%Y-%m-%d %H:%M %Z',     # 2025-09-12 09:30 EDT
            '%m/%d/%Y %H:%M %Z',     # 09/12/2025 09:30 EDT
            '%m/%d/%Y %H:%M:%S %Z',  # 09/12/2025 09:30:00 EDT
        ]
        
        # Try each format
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str, fmt)
                # Convert to timezone-aware datetime
                return self._make_timezone_aware(dt, time_str)
            except ValueError:
                continue
        
        # Try using the existing CSV timestamp parser
        try:
            parsed = parse_csv_timestamp(time_str)
            if parsed is not None:
                return parsed.to_pydatetime()
        except Exception:
            pass
        
        logger.warning(f"Could not parse timestamp: {time_str}")
        return None
    
    def _make_timezone_aware(self, dt: datetime, time_str: str) -> datetime:
        """Make a naive datetime timezone-aware based on timezone info in the string."""
        # Extract timezone info
        tz_patterns = [
            r'([A-Z]{3,4})$',  # EDT, EST, PST, etc.
            r'([A-Z]{3,4})\s*$',  # EDT , EST , etc.
        ]
        
        for pattern in tz_patterns:
            match = re.search(pattern, time_str)
            if match:
                tz_abbr = match.group(1)
                # Convert timezone abbreviation to offset
                tz_offset = self._get_timezone_offset(tz_abbr)
                if tz_offset is not None:
                    from datetime import timezone, timedelta
                    tz = timezone(timedelta(hours=tz_offset))
                    return dt.replace(tzinfo=tz)
        
        # Default to current trading timezone if no timezone info
        from utils.timezone_utils import get_trading_timezone
        tz = get_trading_timezone()
        return dt.replace(tzinfo=tz)
    
    def _convert_to_pdt(self, dt: datetime) -> datetime:
        """Convert any timezone to PDT for consistent CSV formatting."""
        from utils.timezone_utils import get_trading_timezone
        tz = get_trading_timezone()
        return dt.astimezone(tz)
    
    def _get_timezone_offset(self, tz_abbr: str) -> Optional[int]:
        """Get UTC offset for timezone abbreviation."""
        tz_offsets = {
            'EST': -5, 'EDT': -4,
            'CST': -6, 'CDT': -5,
            'MST': -7, 'MDT': -6,
            'PST': -8, 'PDT': -7,
            'UTC': 0, 'GMT': 0,
        }
        return tz_offsets.get(tz_abbr.upper())
    
    def _normalize_action(self, action: str) -> str:
        """Normalize action to standard format."""
        action = action.upper().strip()
        if action in ['BUY', 'BOUGHT', 'MARKET BUY']:
            return 'BUY'
        elif action in ['SELL', 'SOLD', 'MARKET SELL']:
            return 'SELL'
        else:
            return action
    
    def _validate_currency_ticker_match(self, ticker: str, currency: str) -> None:
        """Validate that currency matches ticker suffix pattern and warn if mismatch.
        
        - Canadian tickers (.TO, .V, .CN, .NE) should always be CAD
        - US tickers (no suffix) on a US brokerage are typically USD
        
        When CAD currency is detected but no suffix, automatically looks up Canadian ticker candidates
        and includes suggestions in the log message.
        
        This doesn't change the currency, just logs a warning for review.
        """
        canadian_suffixes = ['.TO', '.V', '.CN', '.NE']
        is_canadian_ticker = any(ticker.upper().endswith(suffix) for suffix in canadian_suffixes)
        
        if is_canadian_ticker and currency.upper() != 'CAD':
            warning_msg = f"⚠️ Currency mismatch: {ticker} appears to be a Canadian stock (has suffix) but currency is '{currency}'. Expected CAD."
            print(warning_msg)
            logger.warning(warning_msg)
        elif not is_canadian_ticker and currency.upper() == 'CAD':
            # This could be intentional (trading CAD on TSX without suffix from Wealthsimple)
            # Try to look up Canadian ticker candidates to provide better info
            try:
                from utils.ticker_utils import lookup_ticker_suffix_candidates
                ticker_suggestions = lookup_ticker_suffix_candidates(ticker, currency)
                
                if ticker_suggestions:
                    if len(ticker_suggestions) == 1:
                        # Single match found
                        suggested = ticker_suggestions[0]
                        info_msg = (
                            f"ℹ️ Currency note: {ticker} has no Canadian suffix but currency is CAD. "
                            f"Found Canadian ticker: {suggested['ticker']} - {suggested['name']} ({suggested['exchange']}). "
                            f"Consider using {suggested['ticker']} instead."
                        )
                    else:
                        # Multiple matches found
                        suggestions_list = ", ".join([f"{m['ticker']} ({m['exchange']})" for m in ticker_suggestions])
                        info_msg = (
                            f"ℹ️ Currency note: {ticker} has no Canadian suffix but currency is CAD. "
                            f"Found {len(ticker_suggestions)} Canadian ticker candidates: {suggestions_list}. "
                            f"Verify this is correct or consider using one of these tickers."
                        )
                else:
                    # No matches found - use original message
                    info_msg = f"ℹ️ Currency note: {ticker} has no Canadian suffix but currency is CAD. Verify this is correct."
            except Exception as e:
                # Fallback to original message if lookup fails
                logger.debug(f"Ticker suffix lookup failed for {ticker}: {e}")
                info_msg = f"ℹ️ Currency note: {ticker} has no Canadian suffix but currency is CAD. Verify this is correct."
            
            print(info_msg)
            logger.info(info_msg)


def parse_trade_from_email(email_text: str) -> Optional[Trade]:
    """Convenience function to parse a trade from email text.
    
    Args:
        email_text: Raw email text containing trade information
        
    Returns:
        Trade object if parsing successful, None otherwise
    """
    parser = EmailTradeParser()
    return parser.parse_email_trade(email_text)


def is_duplicate_trade(trade: Trade, repository) -> bool:
    """Check if a trade already exists in the trade log (idempotent guard).
    
    A trade is considered duplicate if another trade exists with:
    - Same ticker (case-insensitive)
    - Same action (BUY/SELL)
    - Shares equal within 1e-6
    - Price equal within 1e-6
    - Timestamp within ±5 minutes
    """
    try:
        from decimal import Decimal
        from datetime import timedelta
        # Load existing trades via repository for consistent parsing
        existing = repository.get_trade_history()
        if not existing:
            return False
        t_ticker = trade.ticker.upper().strip()
        t_action = trade.action.upper().strip()
        t_shares = Decimal(str(trade.shares))
        t_price = Decimal(str(trade.price))
        t_time = trade.timestamp
        eps = Decimal('0.000001')
        for ex in existing:
            if ex.ticker.upper().strip() != t_ticker:
                continue
            if ex.action.upper().strip() != t_action:
                continue
            try:
                e_shares = Decimal(str(ex.shares))
                e_price = Decimal(str(ex.price))
            except Exception:
                continue
            if abs(e_shares - t_shares) > eps:
                continue
            if abs(e_price - t_price) > eps:
                continue
            try:
                dt = ex.timestamp
                if dt.tzinfo is None and t_time.tzinfo is not None:
                    # Assume same TZ if missing
                    dt = dt.replace(tzinfo=t_time.tzinfo)
                delta = abs((dt - t_time).total_seconds())
            except Exception:
                # Fallback: consider duplicate on matching all other fields
                delta = 0
            if delta <= 300:  # within 5 minutes
                return True
        return False
    except Exception as e:
        logger.debug(f"Duplicate check failed: {e}")
        return False


def add_trade_from_email(email_text: str, data_dir: str, fund_name: str = None) -> bool:
    """Parse email text and add the trade to the trading system.

    Args:
        email_text: Raw email text containing trade information
        data_dir: Directory containing trading data files
        fund_name: Fund name for Supabase operations (optional)

    Returns:
        True if trade was successfully added, False otherwise
    """
    try:
        # Parse the trade (may have incomplete cost_basis for sells)
        trade = parse_trade_from_email(email_text)
        if not trade:
            print("Failed to parse trade from email text")
            return False

        # Import here to avoid circular imports
        from data.repositories.csv_repository import CSVRepository
        from data.repositories.repository_factory import RepositoryFactory
        from portfolio.trade_processor import TradeProcessor

        # Initialize repository - use dual write if fund_name provided, otherwise CSV only
        if fund_name:
            try:
                repository = RepositoryFactory.create_dual_write_repository(fund_name=fund_name, data_directory=data_dir)
                print(f"Using dual-write repository (CSV + Supabase) for fund: {fund_name}")
            except Exception as e:
                print(f"Warning: Failed to create dual-write repository: {e}")
                print("Falling back to CSV-only repository")
                repository = CSVRepository(data_dir)
        else:
            repository = CSVRepository(data_dir)

        # Idempotency guard: skip exact duplicates
        if is_duplicate_trade(trade, repository):
            print("ℹ️  Duplicate trade detected; skipping insert.")
            return True

        processor = TradeProcessor(repository)

        # For sell trades, fix the cost_basis and PnL calculation
        if trade.action == 'SELL':
            # Get current position to calculate correct cost basis
            current_position = processor._get_current_position(trade.ticker)
            if current_position and current_position.shares >= trade.shares:
                # Calculate actual cost basis from existing position
                cost_basis = current_position.avg_price * trade.shares
                proceeds = trade.price * trade.shares
                pnl = proceeds - cost_basis

                # Update trade with correct values
                trade = Trade(
                    ticker=trade.ticker,
                    action=trade.action,
                    shares=trade.shares,
                    price=trade.price,
                    timestamp=trade.timestamp,
                    cost_basis=cost_basis,
                    pnl=pnl,
                    reason=trade.reason,
                    currency=trade.currency
                )
                logger.info(f"Corrected sell trade cost basis: {cost_basis}, PnL: {pnl}")
            else:
                logger.warning(f"No sufficient position found for sell trade: {trade.ticker}")

        # Use unified trade entry function to save trade, update positions, clear caches, and handle backdated trades
        success = processor.process_trade_entry(trade, clear_caches=True, trade_already_saved=False)
        
        if not success:
            print(f"❌ Failed to process trade entry for {trade.ticker}")
            print("   Manual portfolio rebuild may be needed")
            return False

        # Check if this is a sell trade that might close the position
        if trade.action == 'SELL':
            try:
                # Get current position after the sell to check remaining shares
                current_position = processor._get_current_position(trade.ticker)
                remaining_shares = current_position.shares if current_position else Decimal('0')
                
                # If remaining position value is small (likely a fractional remainder), ask user
                if remaining_shares > Decimal('0'):
                    # Calculate remaining position value
                    remaining_value = remaining_shares * trade.price
                    if remaining_value < Decimal('1.00'):  # Less than $1 remaining
                        print(f"\n📊 Remaining position: {remaining_shares} shares of {trade.ticker} (${remaining_value:.2f})")
                        response = input(f"Did you sell your entire position in {trade.ticker}? (y/N): ").strip().lower()
                        
                        if response in ('y', 'yes'):
                            print(f"✅ Marking {trade.ticker} position as completely closed")
                        
                            # Create a corrective trade to zero out the position
                            corrective_trade = Trade(
                                ticker=trade.ticker,
                                action='SELL',
                                shares=remaining_shares,
                                price=Decimal('0.01'),  # Minimal price for cleanup
                                timestamp=trade.timestamp,
                                cost_basis=Decimal('0'),
                                pnl=Decimal('0'),
                                reason=f"POSITION CLEANUP - Close remaining {remaining_shares} shares",
                                currency=trade.currency
                            )
                            
                            # Save the corrective trade
                            repository.save_trade(corrective_trade)
                            
                            # Update position to zero
                            processor._update_position_after_sell(corrective_trade)
                            
                            print(f"   Added cleanup trade: {remaining_shares} shares @ $0.01")
                            print(f"   Position in {trade.ticker} is now zero")
                        
            except Exception as e:
                print(f"⚠️  Could not check position closure: {e}")
                logger.warning(f"Could not check position closure for {trade.ticker}: {e}")

        print(f"Successfully added trade: {trade.ticker} {trade.action} {trade.shares} @ {trade.price}")
        return True

    except Exception as e:
        print(f"Error adding trade from email: {e}")
        logger.error(f"Error adding trade from email: {e}")
        return False


if __name__ == "__main__":
    # Example usage
    sample_email = """
    Your order has been filled
    Account: TFSA
    Type: Market Buy
    Symbol: VEE
    Shares: 4
    Average price: $44.59
    Total cost: $178.36
    Time: September 12, 2025 09:30 EDT
    """
    
    print("Parsing sample email trade...")
    trade = parse_trade_from_email(sample_email)
    if trade:
        print(f"Parsed trade: {trade}")
    else:
        print("Failed to parse trade")
