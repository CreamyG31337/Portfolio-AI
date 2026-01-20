"""Field mapping utilities for converting between domain models and database formats."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float, handling None, NaN, and infinity.
    
    Args:
        value: Value to convert (Decimal, float, int, etc.)
        default: Default value to return if conversion fails
        
    Returns:
        Valid float value or default
    """
    if value is None:
        return default
    
    try:
        # Convert to float
        result = float(value)
        
        # Check for NaN or infinity
        if result != result or result == float('inf') or result == float('-inf'):
            return default
            
        return result
    except (ValueError, TypeError, OverflowError):
        return default


class TypeTransformers:
    """Type conversion utilities."""

    @staticmethod
    def iso_to_datetime(iso_string: str) -> datetime:
        """Convert ISO format string to datetime object."""
        try:
            return datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            logger.error(f"Failed to parse datetime '{iso_string}': {e}")
            return datetime.now()


class PositionMapper:
    """Maps between Position domain model and database format."""

    @staticmethod
    def model_to_db(position: Any, fund: str, timestamp: datetime, 
                    base_currency: Optional[str] = None, 
                    exchange_rate: Optional[float] = None) -> Dict[str, Any]:
        """Convert Position model to database format.
        
        Args:
            position: Position model to convert
            fund: Fund name
            timestamp: Snapshot timestamp
            base_currency: Optional base currency for pre-conversion (e.g., 'CAD')
            exchange_rate: Optional exchange rate for pre-conversion (position_currency -> base_currency)
        
        Returns:
            Dictionary with all database fields including pre-converted values if provided
        """
        # Safely convert all numeric fields, defaulting to 0.0 for invalid values
        price = safe_float(position.current_price) if position.current_price is not None else safe_float(position.avg_price)
        
        # Calculate market value and P&L
        shares = safe_float(position.shares)
        cost_basis = safe_float(position.cost_basis)
        pnl = safe_float(position.unrealized_pnl or position.calculated_unrealized_pnl)
        # Use position.market_value if available, otherwise calculate from shares * price
        if position.market_value is not None:
            market_value = safe_float(position.market_value)
        else:
            market_value = shares * price if price > 0 else 0.0
        
        # Calculate date_only for unique constraint (fund, ticker, date_only)
        # The trigger will also set this, but including it allows PostgREST upsert to work properly
        if timestamp.tzinfo is None:
            # If no timezone, assume UTC
            date_only = timestamp.date()
        else:
            # Convert to UTC and get date
            date_only = timestamp.astimezone(timezone.utc).date()
        
        # Build base dictionary
        # NOTE: total_value is a GENERATED COLUMN in the database (calculated as shares * price)
        # Do NOT include it in inserts - the database will calculate it automatically
        db_data = {
            'ticker': position.ticker,
            # 'company': position.company,  # Deprecated - now normalized in securities table
            'shares': shares,
            'price': price,  # Current market price (or avg_price if current not available)
            'cost_basis': cost_basis,
            # 'total_value': market_value,  # REMOVED: This is a generated column - DB calculates it automatically
            'pnl': pnl,
            'currency': position.currency,
            'fund': fund,
            'date': timestamp.isoformat(),
            'date_only': date_only.isoformat(),  # Include for unique constraint upsert
            'created_at': datetime.now().isoformat()
        }
        
        # Calculate pre-converted values if base_currency is provided
        if base_currency:
            position_currency = (position.currency or 'CAD').upper()
            base_currency_upper = base_currency.upper()
            
            # Determine exchange rate (keep as float for multiplication with float values)
            if exchange_rate is not None:
                rate = float(exchange_rate)
            elif position_currency == base_currency_upper:
                rate = 1.0
            else:
                # No exchange rate provided and currencies differ - will be NULL
                # The scheduled job or backfill script will populate these later
                rate = None
            
            # Calculate pre-converted values
            if rate is not None:
                db_data['base_currency'] = base_currency_upper
                db_data['total_value_base'] = safe_float(market_value * rate)
                db_data['cost_basis_base'] = safe_float(cost_basis * rate)
                db_data['pnl_base'] = safe_float(pnl * rate)
                db_data['exchange_rate'] = safe_float(rate)
            else:
                # Set to None so they can be backfilled later
                db_data['base_currency'] = base_currency_upper
                db_data['total_value_base'] = None
                db_data['cost_basis_base'] = None
                db_data['pnl_base'] = None
                db_data['exchange_rate'] = None
        else:
            # No base_currency provided - leave pre-converted fields as None
            # They will be populated by the scheduled job or backfill script
            db_data['base_currency'] = None
            db_data['total_value_base'] = None
            db_data['cost_basis_base'] = None
            db_data['pnl_base'] = None
            db_data['exchange_rate'] = None
        
        return db_data

    @staticmethod
    def db_to_model(row: Dict[str, Any]) -> Any:
        """Convert database row to Position model."""
        from ..models.portfolio import Position

        # Handle avg_price field - use 'avg_price' if available (from views), otherwise calculate from cost_basis
        avg_price = row.get('avg_price')
        if avg_price is None:
            # Calculate avg_price from cost_basis and shares (DON'T use 'price' field - that's current price!)
            shares = Decimal(str(row.get('shares', row.get('total_shares', 0))))
            cost_basis = Decimal(str(row.get('cost_basis', row.get('total_cost_basis', 0))))
            avg_price = cost_basis / shares if shares > 0 else Decimal('0')
        else:
            avg_price = Decimal(str(avg_price))

        # Handle market_value and current_price mapping
        market_value = row.get('total_market_value') or row.get('market_value')
        current_price = row.get('current_price') or row.get('price')  # Also check 'price' field

        # If we don't have market_value but have current_price and shares, calculate it
        if market_value is None and current_price is not None:
            shares = Decimal(str(row.get('shares', row.get('total_shares', 0))))
            if shares > 0:
                market_value = Decimal(str(current_price)) * shares
        
        # If we don't have current_price but have market_value and shares, calculate it
        if current_price is None and market_value is not None:
            shares = Decimal(str(row.get('shares', row.get('total_shares', 0))))
            if shares > 0:
                current_price = Decimal(str(market_value)) / shares

        # Handle pnl mapping (use pnl field from database)
        # This can come from either 'pnl' (standard) or 'unrealized_pnl' (some views) or 'total_unrealized_pnl' (enriched views)
        pnl = row.get('pnl')
        if pnl is None:
            pnl = row.get('unrealized_pnl')
        if pnl is None:
            pnl = row.get('total_unrealized_pnl')
        
        # Convert pnl to Decimal if it's not None, handling different numeric types
        if pnl is not None:
            try:
                pnl_decimal = Decimal(str(pnl))
                # Keep the value, even if it's zero (0 is valid P&L)
                pnl = pnl_decimal
            except (ValueError, TypeError, ArithmeticError):
                pnl = None
        
        # If we don't have P&L from database but have market_value and cost_basis, calculate it
        if pnl is None and market_value is not None and cost_basis is not None:
            try:
                pnl = Decimal(str(market_value)) - Decimal(str(cost_basis))
            except (ValueError, TypeError, ArithmeticError):
                pnl = None

        # Handle company field
        company = row.get('company')

        return Position(
            ticker=row['ticker'],
            shares=Decimal(str(row.get('shares', row.get('total_shares', 0)))),
            avg_price=avg_price,
            cost_basis=Decimal(str(row.get('cost_basis', row.get('total_cost_basis', 0)))),
            currency=row.get('currency', 'CAD'),
            company=company,
            current_price=Decimal(str(current_price)) if current_price is not None else None,
            market_value=Decimal(str(market_value)) if market_value is not None else None,
            unrealized_pnl=pnl,
            stop_loss=None  # Not stored in database
        )


class TradeMapper:
    """Maps between Trade domain model and database format."""

    @staticmethod
    def model_to_db(trade: Any, fund: str) -> Dict[str, Any]:
        """Convert Trade model to database format."""
        # Base fields that should always be present
        db_data = {
            'ticker': trade.ticker,
            'shares': float(trade.shares),
            'price': float(trade.price),
            'cost_basis': float(trade.cost_basis) if trade.cost_basis else 0.0,
            'pnl': float(trade.pnl) if trade.pnl else 0.0,
            'reason': trade.reason or '',
            'currency': trade.currency,
            'fund': fund,
            'date': trade.timestamp.isoformat(),
            'created_at': datetime.now().isoformat()
        }
        
        # Action is inferred from reason field, not stored separately
        
        return db_data

    @staticmethod
    def db_to_model(row: Dict[str, Any]) -> Any:
        """Convert database row to Trade model."""
        from ..models.trade import Trade

        # Derive action from reason field
        reason = row.get('reason', '').lower()
        if 'sell' in reason or 'limit sell' in reason or 'market sell' in reason:
            action = 'SELL'
        else:
            action = 'BUY'  # Default to BUY for trades

        return Trade(
            ticker=row['ticker'],
            action=action,
            shares=Decimal(str(row['shares'])),
            price=Decimal(str(row['price'])),
            currency=row.get('currency', 'CAD'),
            timestamp=TypeTransformers.iso_to_datetime(row['date']),
            cost_basis=Decimal(str(row.get('cost_basis', 0))) if row.get('cost_basis') else None,
            pnl=Decimal(str(row.get('pnl', 0))) if row.get('pnl') else None,
            reason=row.get('reason')
        )


class CashBalanceMapper:
    """Maps between cash balance data and database format."""

    @staticmethod
    def db_to_dict(data: List[Dict[str, Any]]) -> Dict[str, Decimal]:
        """Convert database rows to cash balance dictionary."""
        balances = {}
        for row in data:
            currency = row.get('currency', 'CAD')
            amount = Decimal(str(row.get('amount', 0)))
            balances[currency] = amount
        return balances

    @staticmethod
    def dict_to_db(balances: Dict[str, Decimal], fund: str) -> List[Dict[str, Any]]:
        """Convert cash balance dictionary to database format."""
        result = []
        for currency, amount in balances.items():
            result.append({
                'currency': currency,
                'amount': float(amount),
                'fund': fund,
                'created_at': datetime.now().isoformat()
            })
        return result


class SnapshotMapper:
    """Maps between portfolio snapshots and database format."""

    @staticmethod
    def group_positions_by_date(positions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group positions by date for snapshot creation."""
        grouped = {}
        for position in positions:
            date = position.get('date', '')
            if date not in grouped:
                grouped[date] = []
            grouped[date].append(position)
        return grouped

    @staticmethod
    def create_snapshot_from_positions(timestamp: datetime, positions: List[Dict[str, Any]]) -> Any:
        """Create snapshot from database position data."""
        from ..models.portfolio import PortfolioSnapshot

        # Convert positions to domain models
        position_objects = [PositionMapper.db_to_model(pos) for pos in positions]

        # Create snapshot and calculate totals
        snapshot = PortfolioSnapshot(
            timestamp=timestamp,
            positions=position_objects
        )

        # Calculate and set totals
        snapshot.total_value = snapshot.calculate_total_value()
        snapshot.total_shares = snapshot.calculate_total_shares()

        return snapshot
