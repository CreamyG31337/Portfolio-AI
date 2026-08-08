"""Position calculation module.

This module provides the PositionCalculator class for handling position sizing,
metrics, and ownership calculations. It includes analytics functions designed
for both current use and future web dashboard integration.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
import pandas as pd

from data.repositories.base_repository import BaseRepository, RepositoryError
from data.models.portfolio import Position, PortfolioSnapshot
from data.models.trade import Trade
from financial.calculations import money_to_decimal, calculate_cost_basis, calculate_position_value
from utils.currency_converter import load_exchange_rates, convert_usd_to_cad

logger = logging.getLogger(__name__)


class PositionCalculatorError(Exception):
    """Base exception for position calculator operations."""
    pass


class PositionCalculator:
    """Calculates position sizing, metrics, and analytics using the repository pattern.
    
    This class provides comprehensive position analysis capabilities while abstracting
    the underlying data storage mechanism through the repository interface.
    It supports both CSV and future database backends seamlessly.
    """
    
    def __init__(self, repository: BaseRepository):
        """Initialize position calculator.
        
        Args:
            repository: Repository implementation for data access
        """
        self.repository = repository
        logger.info(f"Position calculator initialized with {type(repository).__name__}")
    
    def calculate_position_size(self, available_capital: Decimal, risk_percentage: Decimal,
                               entry_price: Decimal, stop_loss_price: Optional[Decimal] = None) -> Dict[str, Any]:
        """Calculate optimal position size based on risk management rules.
        
        Args:
            available_capital: Total available capital
            risk_percentage: Percentage of capital to risk (e.g., 0.02 for 2%)
            entry_price: Planned entry price
            stop_loss_price: Optional stop loss price for risk calculation
            
        Returns:
            Dictionary containing position sizing information
            
        Raises:
            PositionCalculatorError: If calculation fails
        """
        try:
            logger.info(f"Calculating position size: capital={available_capital}, risk={risk_percentage}")
            
            # Validate inputs
            if available_capital <= 0:
                raise PositionCalculatorError("Available capital must be positive")
            if risk_percentage <= 0 or risk_percentage > 1:
                raise PositionCalculatorError("Risk percentage must be between 0 and 1")
            if entry_price <= 0:
                raise PositionCalculatorError("Entry price must be positive")
            
            # Calculate risk amount
            risk_amount = available_capital * risk_percentage
            
            # Calculate position size based on risk
            if stop_loss_price and stop_loss_price > 0:
                # Risk-based position sizing
                risk_per_share = abs(entry_price - stop_loss_price)
                if risk_per_share > 0:
                    shares = risk_amount / risk_per_share
                    position_value = shares * entry_price
                else:
                    # If no risk per share, use percentage of capital
                    position_value = available_capital * risk_percentage * 10  # 10x leverage for no stop loss
                    shares = position_value / entry_price
            else:
                # Simple percentage-based sizing (no stop loss)
                position_value = available_capital * risk_percentage * 5  # 5x leverage for no stop loss
                shares = position_value / entry_price
            
            # Ensure we don't exceed available capital
            max_position_value = available_capital * Decimal('0.25')  # Max 25% of capital per position
            if position_value > max_position_value:
                position_value = max_position_value
                shares = position_value / entry_price
            
            result = {
                'recommended_shares': shares.quantize(Decimal('0.0001')),  # 4 decimal places for shares
                'position_value': position_value.quantize(Decimal('0.01')),  # 2 decimal places for currency
                'risk_amount': risk_amount.quantize(Decimal('0.01')),
                'risk_per_share': abs(entry_price - stop_loss_price).quantize(Decimal('0.01')) if stop_loss_price else Decimal('0'),
                'capital_allocation_percentage': (position_value / available_capital * Decimal('100')).quantize(Decimal('0.1')),
                'entry_price': entry_price,
                'stop_loss_price': stop_loss_price
            }
            
            logger.info(f"Position size calculated: {result['recommended_shares']} shares, "
                       f"${result['position_value']} value")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to calculate position size: {e}")
            raise PositionCalculatorError(f"Failed to calculate position size: {e}") from e
    
    def update_position_with_price(self, position: Position, current_price: Decimal) -> Position:
        """Update a position with new current price and recalculate derived values.
        
        Args:
            position: Position to update
            current_price: New current price
            
        Returns:
            Updated Position object with new price and calculated values
        """
        try:
            # Create a new position with updated price
            updated_position = Position(
                ticker=position.ticker,
                shares=position.shares,
                avg_price=position.avg_price,
                cost_basis=position.cost_basis,
                currency=position.currency,
                company=position.company,
                current_price=current_price,
                market_value=position.shares * current_price,
                unrealized_pnl=(current_price - position.avg_price) * position.shares,
                stop_loss=position.stop_loss,
                position_id=position.position_id
            )
            
            return updated_position
            
        except Exception as e:
            logger.error(f"Failed to update position {position.ticker} with price {current_price}: {e}")
            # Return original position if update fails
            return position

    def calculate_position_metrics(self, position: Position, current_price: Optional[Decimal] = None) -> Dict[str, Any]:
        """Calculate comprehensive metrics for a single position.
        
        Args:
            position: Position to analyze
            current_price: Optional current market price
            
        Returns:
            Dictionary containing position metrics
            
        Raises:
            PositionCalculatorError: If calculation fails
        """
        try:
            # logger.debug(f"Calculating position metrics for {position.ticker}")
            
            # Use provided current price or position's current price
            price = current_price or position.current_price
            
            # Basic metrics
            cost_basis = position.cost_basis
            shares = position.shares
            avg_price = position.avg_price
            
            # Market value and P&L
            if price:
                market_value = calculate_position_value(price, shares)
                unrealized_pnl = market_value - cost_basis
                unrealized_pnl_percentage = (unrealized_pnl / cost_basis * Decimal('100')) if cost_basis > 0 else Decimal('0')
                
                # Price change metrics
                price_change = price - avg_price
                price_change_percentage = (price_change / avg_price * Decimal('100')) if avg_price > 0 else Decimal('0')
            else:
                market_value = None
                unrealized_pnl = None
                unrealized_pnl_percentage = None
                price_change = None
                price_change_percentage = None
            
            # Risk metrics
            stop_loss_distance = None
            stop_loss_risk_amount = None
            if position.stop_loss and price:
                stop_loss_distance = abs(price - position.stop_loss)
                stop_loss_risk_amount = stop_loss_distance * shares
            
            metrics = {
                'ticker': position.ticker,
                'shares': shares,
                'avg_price': avg_price,
                'current_price': price,
                'cost_basis': cost_basis,
                'market_value': market_value,
                'unrealized_pnl': unrealized_pnl,
                'unrealized_pnl_percentage': unrealized_pnl_percentage,
                'price_change': price_change,
                'price_change_percentage': price_change_percentage,
                'stop_loss_price': position.stop_loss,
                'stop_loss_distance': stop_loss_distance,
                'stop_loss_risk_amount': stop_loss_risk_amount,
                'currency': position.currency,
                'company': position.company
            }
            
            # logger.debug(f"Position metrics calculated for {position.ticker}: "
            #            f"P&L: {unrealized_pnl}, {unrealized_pnl_percentage}%")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to calculate position metrics for {position.ticker}: {e}")
            raise PositionCalculatorError(f"Failed to calculate position metrics: {e}") from e
    
    def calculate_portfolio_metrics(self, snapshot: Optional[PortfolioSnapshot] = None,
                                   current_prices: Optional[Dict[str, Decimal]] = None) -> Dict[str, Any]:
        """Calculate comprehensive portfolio-level metrics with currency conversion.
        
        Args:
            snapshot: Portfolio snapshot to analyze (uses latest if None)
            current_prices: Optional dictionary of current prices by ticker
            
        Returns:
            Dictionary containing portfolio metrics
            
        Raises:
            PositionCalculatorError: If calculation fails
        """
        try:
            if snapshot is None:
                snapshot = self.repository.get_latest_portfolio_snapshot()
                if snapshot is None:
                    return self._empty_portfolio_metrics()
            
            logger.debug(f"Calculating portfolio metrics for {len(snapshot.positions)} positions")
            
            # Load exchange rates for currency conversion
            exchange_rates = {}
            if hasattr(self.repository, 'data_dir'):
                exchange_rates = load_exchange_rates(Path(self.repository.data_dir))
            
            # Initialize metrics (all in CAD equivalent)
            total_cost_basis_cad = Decimal('0')
            total_market_value_cad = Decimal('0')
            total_unrealized_pnl_cad = Decimal('0')
            positions_with_gains = 0
            positions_with_losses = 0
            largest_position_value_cad = Decimal('0')
            largest_position_ticker = None
            position_metrics = []
            
            # Track separate USD and CAD totals for debugging
            total_cost_basis_usd = Decimal('0')
            total_cost_basis_cad_only = Decimal('0')
            total_market_value_usd = Decimal('0')
            total_market_value_cad_only = Decimal('0')
            
            # Calculate metrics for each position
            for position in snapshot.positions:
                # Get current price
                current_price = None
                if current_prices and position.ticker in current_prices:
                    current_price = current_prices[position.ticker]
                elif position.current_price:
                    current_price = position.current_price
                
                # Calculate position metrics
                pos_metrics = self.calculate_position_metrics(position, current_price)
                position_metrics.append(pos_metrics)
                
                # Convert cost basis to CAD equivalent using position.currency field
                if position.currency == 'USD':
                    cost_basis_cad = convert_usd_to_cad(position.cost_basis, exchange_rates)
                    total_cost_basis_usd += position.cost_basis
                else:
                    # Assume CAD for all non-USD currencies (or missing currency field)
                    cost_basis_cad = position.cost_basis
                    total_cost_basis_cad_only += position.cost_basis
                
                total_cost_basis_cad += cost_basis_cad
                
                # Convert market value to CAD using position.currency field
                if pos_metrics['market_value']:
                    market_value = pos_metrics['market_value']
                    
                    if position.currency == 'USD':
                        market_value_cad = convert_usd_to_cad(market_value, exchange_rates)
                        total_market_value_usd += market_value
                    else:
                        # Assume CAD for all non-USD currencies (or missing currency field)
                        market_value_cad = market_value
                        total_market_value_cad_only += market_value
                    
                    total_market_value_cad += market_value_cad
                    
                    # Track largest position
                    if market_value_cad > largest_position_value_cad:
                        largest_position_value_cad = market_value_cad
                        largest_position_ticker = position.ticker
                
                # Convert P&L to CAD using position.currency field
                if pos_metrics['unrealized_pnl']:
                    pnl = pos_metrics['unrealized_pnl']
                    
                    if position.currency == 'USD':
                        pnl_cad = convert_usd_to_cad(pnl, exchange_rates)
                    else:
                        # Assume CAD for all non-USD currencies (or missing currency field)
                        pnl_cad = pnl
                    
                    total_unrealized_pnl_cad += pnl_cad
                    
                    # Count gains/losses
                    if pnl_cad > 0:
                        positions_with_gains += 1
                    elif pnl_cad < 0:
                        positions_with_losses += 1
            
            # Calculate portfolio-level percentages
            total_unrealized_pnl_percentage = Decimal('0')
            if total_cost_basis_cad > 0:
                total_unrealized_pnl_percentage = (total_unrealized_pnl_cad / total_cost_basis_cad * Decimal('100'))
            
            # Calculate position weights (convert each position to CAD before dividing)
            for i, pos_metrics in enumerate(position_metrics):
                position = snapshot.positions[i] if i < len(snapshot.positions) else None
                if pos_metrics['market_value'] and total_market_value_cad > 0 and position is not None:
                    if position.currency == 'USD':
                        mv_cad = convert_usd_to_cad(pos_metrics['market_value'], exchange_rates)
                    else:
                        mv_cad = pos_metrics['market_value']
                    weight = (mv_cad / total_market_value_cad * Decimal('100'))
                    # Convert Decimal to float for JSON serialization
                    # WARNING: Float conversion may introduce precision loss but required for JSON compatibility
                    pos_metrics['portfolio_weight_percentage'] = float(weight.quantize(Decimal('0.1')))
                else:
                    # Convert Decimal to float for JSON serialization
                    pos_metrics['portfolio_weight_percentage'] = 0.0
            
            # Win rate calculation
            total_positions_with_pnl = positions_with_gains + positions_with_losses
            win_rate = (Decimal(positions_with_gains) / Decimal(total_positions_with_pnl) * Decimal('100')) if total_positions_with_pnl > 0 else Decimal('0')
            
            metrics = {
                'total_positions': len(snapshot.positions),
                'total_cost_basis': total_cost_basis_cad,  # Now in CAD equivalent
                'total_market_value': total_market_value_cad,  # Now in CAD equivalent
                'total_unrealized_pnl': total_unrealized_pnl_cad,  # Now in CAD equivalent
                'total_unrealized_pnl_percentage': total_unrealized_pnl_percentage,
                'positions_with_gains': positions_with_gains,
                'positions_with_losses': positions_with_losses,
                # Convert Decimal to float for JSON serialization compatibility
                # WARNING: Float conversion may introduce precision loss but is required for JSON storage
                'win_rate_percentage': float(Decimal(str(win_rate)).quantize(Decimal('0.1'))),
                'largest_position_value': largest_position_value_cad,  # Now in CAD equivalent
                'largest_position_ticker': largest_position_ticker,
                'snapshot_timestamp': snapshot.timestamp,
                'position_metrics': position_metrics,
                # Debug information for currency breakdown
                'debug_currency_breakdown': {
                    'total_cost_basis_usd': total_cost_basis_usd,
                    'total_cost_basis_cad_only': total_cost_basis_cad_only,
                    'total_cost_basis_cad_equivalent': total_cost_basis_cad,
                    'total_market_value_usd': total_market_value_usd,
                    'total_market_value_cad_only': total_market_value_cad_only,
                    'total_market_value_cad_equivalent': total_market_value_cad
                }
            }
            
            logger.debug(f"Portfolio metrics calculated: {len(snapshot.positions)} positions, "
                       f"${total_market_value_cad} CAD total value, {total_unrealized_pnl_percentage}% P&L")
            logger.debug(f"Currency breakdown - USD: ${total_cost_basis_usd} -> ${total_cost_basis_cad - total_cost_basis_cad_only:.2f} CAD, "
                       f"CAD: ${total_cost_basis_cad_only}")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to calculate portfolio metrics: {e}")
            raise PositionCalculatorError(f"Failed to calculate portfolio metrics: {e}") from e
    
    def calculate_ownership_percentages(self, fund_contributions_data: List[Dict[str, Any]],
                                       current_fund_value: Decimal,
                                       historical_fund_values: Optional[Dict[str, Decimal]] = None,
                                       historical_cost_basis: Optional[Dict[str, Decimal]] = None) -> Dict[str, Dict[str, Any]]:
        """Calculate ownership percentages based on fund contributions using NAV-based tracking.
        
        This method properly accounts for WHEN each contributor joined by using a 
        unit-based system (similar to mutual fund NAV). Investors who join when the fund
        is worth more get fewer units per dollar, resulting in accurate per-investor returns.
        
        For perfect accuracy, pass historical_fund_values with actual fund values at each
        contribution date. Otherwise, the method estimates NAV using time-weighted growth.
        
        The NAV calculation now includes uninvested cash:
        Fund Value = Stock Value + max(0, contributions_at_start_of_day - cost_basis)
        
        Example:
            - Day 1: Fund starts with $1,000 from Investor A. NAV = $1.00, A owns 1,000 units.
            - Day 30: Fund grows 20% to $1,200. Investor B joins with $2,000.
              NAV = $1.20, B buys 1,666.67 units. Total units = 2,666.67.
            - Day 60: Fund grows to $3,520. NAV = $1.32.
              A's value = 1,000 * $1.32 = $1,320 (+32% return)
              B's value = 1,666.67 * $1.32 = $2,200 (+10% return)
        
        Args:
            fund_contributions_data: List of contribution records with Timestamp fields
            current_fund_value: Current total fund value
            historical_fund_values: Optional dict mapping date strings (YYYY-MM-DD) to 
                                   fund values at those dates for perfect accuracy
            historical_cost_basis: Optional dict mapping date strings to cost basis for
                                  calculating uninvested cash (contributions - cost_basis)
            
        Returns:
            Dictionary mapping contributor names to ownership details
            
        Raises:
            PositionCalculatorError: If calculation fails
        """
        try:
            logger.debug(f"Calculating NAV-based ownership for {len(fund_contributions_data)} contributions")
            
            if not fund_contributions_data or current_fund_value <= 0:
                return {}
            
            # Parse and sort contributions chronologically
            from datetime import datetime
            
            parsed_contributions = []
            for contribution in fund_contributions_data:
                contributor = contribution.get('Contributor', contribution.get('contributor', 'Unknown'))
                amount = Decimal(str(contribution.get('Amount', contribution.get('amount', 0))))
                contribution_type = contribution.get('Type', contribution.get('type', 'contribution'))
                timestamp_raw = contribution.get('Timestamp', contribution.get('timestamp', ''))
                
                # Parse timestamp - use proper ISO format parser for database timestamps
                timestamp = None
                if timestamp_raw:
                    try:
                        if isinstance(timestamp_raw, datetime):
                            timestamp = timestamp_raw
                        elif isinstance(timestamp_raw, str):
                            # Use the same ISO parser that the repository uses for database timestamps
                            from data.repositories.field_mapper import TypeTransformers
                            timestamp = TypeTransformers.iso_to_datetime(timestamp_raw)
                        else:
                            logger.debug(f"Unexpected timestamp type '{type(timestamp_raw)}' for contributor {contributor}")
                    except Exception as e:
                        logger.warning(f"Could not parse timestamp '{timestamp_raw}' for contributor {contributor}: {e}")
                
                parsed_contributions.append({
                    'contributor': contributor,
                    'amount': amount,
                    'type': contribution_type.lower(),
                    'timestamp': timestamp
                })
            
            # Sort by timestamp (None/unknown dates go first as they're likely the earliest)
            parsed_contributions.sort(key=lambda x: x['timestamp'] or datetime.min)
            
            # Check if we have historical data for perfect accuracy
            use_historical = historical_fund_values and len(historical_fund_values) > 0
            
            # Fallback: calculate growth rate for time-weighted estimation
            if not use_historical:
                total_net_contributions = Decimal('0')
                for contrib in parsed_contributions:
                    if contrib['type'] == 'withdrawal':
                        total_net_contributions -= contrib['amount']
                    else:
                        total_net_contributions += contrib['amount']
                
                if total_net_contributions <= 0:
                    return {}
                
                growth_rate = current_fund_value / total_net_contributions
                
                timestamps = [c['timestamp'] for c in parsed_contributions if c['timestamp']]
                if timestamps:
                    first_timestamp = min(timestamps)
                    now = datetime.now()
                    total_days = max((now - first_timestamp).days, 1)
                else:
                    first_timestamp = None
                    total_days = 1
                    
                logger.warning(f"⚠️  NAV FALLBACK: No historical fund values provided - using time-weighted estimation (growth_rate={growth_rate:.4f})")
            else:
                logger.info(f"✓ Using {len(historical_fund_values)} historical fund values for accurate NAV calculation")
            
            # Calculate units per contributor
            contributor_units = {}
            contributor_data = {}
            total_units = Decimal('0')
            running_contributions = Decimal('0')
            
            # Track state at start of each day for same-day contribution NAV calculation
            # CRITICAL FIX: Multiple contributions on the same day should all use the SAME NAV
            # (the NAV before any contributions that day), otherwise later contributions get
            # exponentially more units, causing massive ownership inflation
            units_at_start_of_day = Decimal('0')
            contributions_at_start_of_day = Decimal('0')  # For uninvested cash calculation
            last_contribution_date = None
            
            for contrib in parsed_contributions:
                contributor = contrib['contributor']
                amount = contrib['amount']
                contrib_type = contrib['type']
                timestamp = contrib['timestamp']
                
                # Same-day NAV fix - capture state at START of each new day
                date_str = timestamp.strftime('%Y-%m-%d') if timestamp else None
                if date_str != last_contribution_date:
                    units_at_start_of_day = total_units
                    contributions_at_start_of_day = running_contributions
                    last_contribution_date = date_str
                
                # Initialize contributor tracking if needed
                if contributor not in contributor_units:
                    contributor_units[contributor] = Decimal('0')
                if contributor not in contributor_data:
                    contributor_data[contributor] = {
                        'contributions': Decimal('0'),
                        'withdrawals': Decimal('0'),
                        'net_contribution': Decimal('0')
                    }
                
                if contrib_type == 'withdrawal':
                    contributor_data[contributor]['withdrawals'] += amount
                    contributor_data[contributor]['net_contribution'] -= amount
                    
                    # Redeem units at NAV on withdrawal date
                    # IMPORTANT: Only redeem if contributor actually has units to prevent total_units corruption
                    if total_units > 0 and contributor_units[contributor] > 0:
                        # date_str already calculated above
                        
                        if use_historical and date_str and date_str in historical_fund_values:
                            fund_value_at_date = Decimal(str(historical_fund_values[date_str]))
                            nav_at_withdrawal = fund_value_at_date / total_units
                        elif not use_historical and first_timestamp and timestamp:
                            elapsed_days = (timestamp - first_timestamp).days
                            time_fraction = Decimal(str(elapsed_days / total_days))
                            nav_at_withdrawal = Decimal('1') + (growth_rate - Decimal('1')) * time_fraction
                        else:
                            nav_at_withdrawal = running_contributions / total_units if total_units > 0 else Decimal('1')
                        
                        units_to_redeem = amount / nav_at_withdrawal if nav_at_withdrawal > 0 else amount
                        # Cap redemption at contributor's actual units to prevent going negative
                        actual_units_redeemed = min(units_to_redeem, contributor_units[contributor])
                        contributor_units[contributor] -= actual_units_redeemed
                        total_units -= actual_units_redeemed
                    elif contributor_units[contributor] <= 0 and amount > 0:
                        logger.warning(f"⚠️  Withdrawal of ${amount} from {contributor} skipped - no units to redeem")
                    
                    running_contributions -= amount
                else:
                    contributor_data[contributor]['contributions'] += amount
                    contributor_data[contributor]['net_contribution'] += amount
                    
                    # Calculate NAV at time of contribution
                    # date_str already calculated above
                    
                    if total_units == 0:
                        # First contribution - NAV = 1.0
                        nav_at_contribution = Decimal('1.0')
                    elif use_historical and date_str and date_str in historical_fund_values:
                        # PROPER NAV FIX: Fund Value = Stock Value + Uninvested Cash
                        stock_value_at_date = Decimal(str(historical_fund_values[date_str]))
                        
                        # Get cost basis for this date (if available)
                        cost_basis_at_date = Decimal('0')
                        if historical_cost_basis and date_str in historical_cost_basis:
                            cost_basis_at_date = Decimal(str(historical_cost_basis[date_str]))
                        
                        # Uninvested Cash = contributions before today that aren't yet in stocks
                        uninvested_cash = max(Decimal('0'), contributions_at_start_of_day - cost_basis_at_date)
                        fund_value_at_date = stock_value_at_date + uninvested_cash
                        
                        # Use units_at_start_of_day for same-day contributions
                        units_for_nav = units_at_start_of_day if units_at_start_of_day > 0 else total_units
                        nav_at_contribution = fund_value_at_date / units_for_nav if units_for_nav > 0 else Decimal('1')
                    elif use_historical and date_str:
                        # Historical data provided but missing for this date - 7-day lookback
                        nav_at_contribution = Decimal('1')
                        units_for_nav = units_at_start_of_day if units_at_start_of_day > 0 else total_units
                        
                        found_fallback = False
                        if units_for_nav > 0:
                            try:
                                from datetime import datetime as dt, timedelta
                                contribution_date = dt.strptime(date_str, '%Y-%m-%d')
                                for days_back in range(1, 8):
                                    prior_date = contribution_date - timedelta(days=days_back)
                                    prior_date_str = prior_date.strftime('%Y-%m-%d')
                                    if prior_date_str in historical_fund_values:
                                        fund_value_at_prior = Decimal(str(historical_fund_values[prior_date_str]))
                                        nav_at_contribution = fund_value_at_prior / units_for_nav
                                        found_fallback = True
                                        logger.info(f"ℹ️  NAV FALLBACK: {date_str} -> using {prior_date_str} (NAV=${nav_at_contribution:.4f})")
                                        break
                            except Exception:
                                pass
                        
                        if not found_fallback:
                            logger.warning(f"⚠️  NAV FALLBACK: Missing historical data for {date_str} (contributor: {contributor}). Using estimation.")
                            nav_at_contribution = running_contributions / units_for_nav if units_for_nav > 0 else Decimal('1')
                    elif not use_historical and first_timestamp and timestamp:
                        # Fallback: time-weighted growth estimation (already warned at start)
                        elapsed_days = (timestamp - first_timestamp).days
                        time_fraction = Decimal(str(elapsed_days / total_days))
                        nav_at_contribution = Decimal('1') + (growth_rate - Decimal('1')) * time_fraction
                    else:
                        logger.warning(f"⚠️  NAV FALLBACK: No timestamp for contribution from {contributor}. Using simple estimation.")
                        nav_at_contribution = running_contributions / total_units if total_units > 0 else Decimal('1')
                    
                    # Ensure NAV is positive
                    if nav_at_contribution <= 0:
                        nav_at_contribution = Decimal('1')
                    
                    # Units purchased = contribution / NAV
                    units_purchased = amount / nav_at_contribution
                    contributor_units[contributor] += units_purchased
                    total_units += units_purchased
                    running_contributions += amount
                    
                    logger.debug(f"  {contributor}: +${amount} at NAV ${nav_at_contribution:.4f} = {units_purchased:.4f} units")
            
            # Calculate final values based on current NAV
            if total_units <= 0:
                return {}
            
            current_nav = current_fund_value / total_units
            logger.debug(f"Current NAV: ${current_nav:.4f} (fund value ${current_fund_value:.2f} / {total_units:.4f} units)")
            
            # Build ownership details with accurate per-contributor returns
            ownership_details = {}
            for contributor, units in contributor_units.items():
                if units > 0:
                    data = contributor_data[contributor]
                    net_contribution = data['net_contribution']
                    
                    if net_contribution <= 0:
                        continue
                    
                    # Current value based on units owned
                    current_value = units * current_nav
                    
                    # Ownership percentage based on units
                    ownership_pct = (units / total_units * Decimal('100'))
                    
                    # Individual gain/loss - this is now ACCURATE per contributor
                    gain_loss = current_value - net_contribution
                    gain_loss_pct = (gain_loss / net_contribution * Decimal('100')) if net_contribution > 0 else Decimal('0')
                    
                    ownership_details[contributor] = {
                        'contributions': data['contributions'],
                        'withdrawals': data['withdrawals'],
                        'net_contribution': net_contribution,
                        'ownership_percentage': ownership_pct.quantize(Decimal('0.1')),
                        'current_value': current_value.quantize(Decimal('0.01')),
                        'gain_loss': gain_loss.quantize(Decimal('0.01')),
                        'gain_loss_percentage': gain_loss_pct.quantize(Decimal('0.1')),
                        # New fields for transparency
                        'units': units.quantize(Decimal('0.0001')),
                        'unit_price': current_nav.quantize(Decimal('0.0001'))
                    }
                    
                    logger.debug(f"  {contributor}: {units:.4f} units = ${current_value:.2f} ({gain_loss_pct:.1f}% return)")
            
            logger.debug(f"NAV-based ownership calculated for {len(ownership_details)} contributors")
            return ownership_details
            
        except Exception as e:
            logger.error(f"Failed to calculate ownership percentages: {e}")
            raise PositionCalculatorError(f"Failed to calculate ownership percentages: {e}") from e
    
    def calculate_liquidation_requirements(self, contributor: str, withdrawal_amount: Decimal,
                                         ownership_details: Dict[str, Dict[str, Any]],
                                         current_portfolio_value: Decimal) -> Dict[str, Any]:
        """Calculate liquidation requirements for a withdrawal.
        
        Args:
            contributor: Name of contributor making withdrawal
            withdrawal_amount: Amount to withdraw
            ownership_details: Current ownership details
            current_portfolio_value: Current portfolio value
            
        Returns:
            Dictionary containing liquidation requirements
            
        Raises:
            PositionCalculatorError: If calculation fails
        """
        try:
            logger.info(f"Calculating liquidation requirements: {contributor} withdrawing ${withdrawal_amount}")
            
            if contributor not in ownership_details:
                raise PositionCalculatorError(f"Contributor {contributor} not found in ownership details")
            
            contributor_data = ownership_details[contributor]
            ownership_percentage = contributor_data['ownership_percentage'] / 100
            current_value = contributor_data['current_value']
            
            # Check if withdrawal amount is valid
            if withdrawal_amount > current_value:
                return {
                    'error': f"Withdrawal amount ${withdrawal_amount} exceeds contributor's current value ${current_value}",
                    'max_withdrawal': current_value
                }
            
            # Calculate liquidation requirements
            liquidation_percentage = withdrawal_amount / current_portfolio_value
            positions_to_liquidate = liquidation_percentage * Decimal('100')
            
            # Calculate remaining ownership after withdrawal
            remaining_value = current_value - withdrawal_amount
            new_total_value = current_portfolio_value - withdrawal_amount
            new_ownership_percentage = (remaining_value / new_total_value * Decimal('100')) if new_total_value > 0 else Decimal('0')
            
            result = {
                'contributor': contributor,
                'withdrawal_amount': withdrawal_amount,
                'current_ownership_percentage': contributor_data['ownership_percentage'],
                'current_value': current_value,
                'liquidation_percentage': (liquidation_percentage * Decimal('100')).quantize(Decimal('0.1')),
                'positions_to_liquidate_percentage': positions_to_liquidate.quantize(Decimal('0.1')),
                'remaining_value': remaining_value.quantize(Decimal('0.01')),
                'new_ownership_percentage': Decimal(str(new_ownership_percentage)).quantize(Decimal('0.1')),
                'feasible': withdrawal_amount <= current_value
            }
            
            logger.info(f"Liquidation requirements calculated: {positions_to_liquidate:.1f}% of portfolio")
            return result
            
        except Exception as e:
            logger.error(f"Failed to calculate liquidation requirements: {e}")
            raise PositionCalculatorError(f"Failed to calculate liquidation requirements: {e}") from e
    
    def analyze_position_performance(self, ticker: str, days_back: int = 30) -> Dict[str, Any]:
        """Analyze historical performance of a specific position.
        
        Args:
            ticker: Ticker symbol to analyze
            days_back: Number of days to look back for analysis
            
        Returns:
            Dictionary containing performance analysis
            
        Raises:
            PositionCalculatorError: If analysis fails
        """
        try:
            logger.info(f"Analyzing position performance for {ticker} over {days_back} days")
            
            # Get historical positions
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            historical_positions = self.repository.get_positions_by_ticker(ticker)
            if not historical_positions:
                return {
                    'ticker': ticker,
                    'error': 'No historical position data found',
                    'analysis_period_days': days_back
                }
            
            # Get trade history for the ticker
            trades = self.repository.get_trade_history(ticker, (start_date, end_date))
            
            # Calculate performance metrics
            buy_trades = [t for t in trades if t.is_buy()]
            sell_trades = [t for t in trades if t.is_sell()]
            
            total_bought = sum(t.shares for t in buy_trades)
            total_sold = sum(t.shares for t in sell_trades)
            total_invested = sum(t.cost_basis for t in buy_trades if t.cost_basis)
            total_proceeds = sum(t.price * t.shares for t in sell_trades)
            realized_pnl = sum(t.pnl for t in sell_trades if t.pnl)
            
            # Current position
            current_position = None
            latest_snapshot = self.repository.get_latest_portfolio_snapshot()
            if latest_snapshot:
                current_position = latest_snapshot.get_position_by_ticker(ticker)
            
            analysis = {
                'ticker': ticker,
                'analysis_period_days': days_back,
                'total_trades': len(trades),
                'buy_trades': len(buy_trades),
                'sell_trades': len(sell_trades),
                'total_shares_bought': total_bought,
                'total_shares_sold': total_sold,
                'current_shares': current_position.shares if current_position else Decimal('0'),
                'total_invested': total_invested,
                'total_proceeds': total_proceeds,
                'realized_pnl': realized_pnl,
                'has_current_position': current_position is not None,
                'current_position_metrics': (
                    self.calculate_position_metrics(current_position) 
                    if current_position else None
                )
            }
            
            logger.info(f"Position performance analyzed for {ticker}: "
                       f"{len(trades)} trades, realized P&L: {realized_pnl}")
            
            return analysis
            
        except Exception as e:
            logger.error(f"Failed to analyze position performance for {ticker}: {e}")
            raise PositionCalculatorError(f"Failed to analyze position performance: {e}") from e
    
    def get_portfolio_analytics_summary(self) -> Dict[str, Any]:
        """Get comprehensive portfolio analytics summary for web dashboard.
        
        Returns:
            Dictionary containing analytics summary
            
        Raises:
            PositionCalculatorError: If summary generation fails
        """
        try:
            logger.info("Generating portfolio analytics summary")
            
            # Get latest portfolio metrics
            portfolio_metrics = self.calculate_portfolio_metrics()
            
            # Get recent trade activity (last 30 days)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            recent_trades = self.repository.get_trade_history(None, (start_date, end_date))
            
            # Calculate trade metrics
            recent_buy_trades = [t for t in recent_trades if t.is_buy()]
            recent_sell_trades = [t for t in recent_trades if t.is_sell()]
            recent_realized_pnl = sum(t.pnl for t in recent_sell_trades if t.pnl)
            
            # Top performers (by unrealized P&L percentage)
            position_metrics = portfolio_metrics.get('position_metrics', [])
            top_performers = sorted(
                [p for p in position_metrics if p.get('unrealized_pnl_percentage')],
                key=lambda x: x['unrealized_pnl_percentage'],
                reverse=True
            )[:5]
            
            # Worst performers
            worst_performers = sorted(
                [p for p in position_metrics if p.get('unrealized_pnl_percentage')],
                key=lambda x: x['unrealized_pnl_percentage']
            )[:5]
            
            summary = {
                'generated_at': datetime.now(),
                'portfolio_metrics': portfolio_metrics,
                'recent_activity': {
                    'period_days': 30,
                    'total_trades': len(recent_trades),
                    'buy_trades': len(recent_buy_trades),
                    'sell_trades': len(recent_sell_trades),
                    'realized_pnl': recent_realized_pnl
                },
                'top_performers': top_performers,
                'worst_performers': worst_performers,
                'risk_metrics': {
                    'largest_position_percentage': (
                        portfolio_metrics['largest_position_value'] / 
                        portfolio_metrics['total_market_value'] * Decimal('100')
                    ).quantize(Decimal('0.1')) if portfolio_metrics['total_market_value'] > 0 else Decimal('0'),
                    'positions_at_risk': len([
                        p for p in position_metrics 
                        if p.get('unrealized_pnl_percentage', 0) < -10
                    ])
                }
            }
            
            logger.info("Portfolio analytics summary generated successfully")
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate portfolio analytics summary: {e}")
            raise PositionCalculatorError(f"Failed to generate analytics summary: {e}") from e
    
    def _empty_portfolio_metrics(self) -> Dict[str, Any]:
        """Return empty portfolio metrics structure.
        
        Returns:
            Dictionary with zero/empty values for all metrics
        """
        return {
            'total_positions': 0,
            'total_cost_basis': Decimal('0'),
            'total_market_value': Decimal('0'),
            'total_unrealized_pnl': Decimal('0'),
            'total_unrealized_pnl_percentage': Decimal('0'),
            'positions_with_gains': 0,
            'positions_with_losses': 0,
            'win_rate_percentage': Decimal('0'),
            'largest_position_value': Decimal('0'),
            'largest_position_ticker': None,
            'snapshot_timestamp': None,
            'position_metrics': []
        }