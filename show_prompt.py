#!/usr/bin/env python3
"""
Show Complete LLM Prompt

This script shows you the complete prompt that you should copy and paste into your LLM.
"""

from market_config import get_daily_instructions, get_market_info, ACTIVE_MARKET
from dual_currency import load_cash_balances, format_cash_display
import argparse
from market_data.market_hours import MarketHours
from market_data.data_fetcher import MarketDataFetcher
from market_data.price_cache import PriceCache
from display.console_output import _safe_emoji
import pandas as pd
import numpy as np
from pathlib import Path
import sys

# Colorama imports for terminal coloring
try:
    from colorama import Fore, Style, init
    init()  # Initialize colorama
except ImportError:
    class DummyColor:
        def __getattr__(self, name):
            return ""
    Fore = Style = DummyColor()

def calculate_position_metrics(portfolio_df, cash_balance):
    """Calculate enhanced position metrics for portfolio display"""
    if portfolio_df.empty:
        return pd.DataFrame(), 0

    enhanced_df = portfolio_df.copy()

    current_prices = []
    pnl_amounts = []
    pnl_percentages = []
    position_values = []
    position_weights = []
    daily_pnl_amounts = []
    daily_pnl_percentages = []
    days_held = []

    total_portfolio_value = 0

    # ⚡ Bolt: Replaced slow O(N) df.iterrows() with bulk conversion to_dict('records')
    for row in portfolio_df.to_dict('records') if portfolio_df is not None and not portfolio_df.empty else []:
        ticker = str(row.get('ticker', ''))

        # Get current price from the row data
        current_price = float(row.get('current_price', row.get('buy_price', 0)))
        shares = float(row.get('shares', 0))
        buy_price = float(row.get('buy_price', 0))
        cost_basis = float(row.get('cost_basis', 0))

        # Use daily P&L from the data if available, otherwise calculate
        daily_pnl_str = row.get('daily_pnl', '$0.00')
        if daily_pnl_str and daily_pnl_str != 'N/A':
            # Parse the daily P&L string (e.g., "$123.45" -> 123.45)
            try:
                daily_pnl_amount = float(daily_pnl_str.replace('$', '').replace(',', '').replace('*', ''))
            except (ValueError, AttributeError):
                daily_pnl_amount = 0.0
        else:
            daily_pnl_amount = 0.0

        # Calculate total P&L since purchase
        position_value = current_price * shares
        actual_cost_basis = buy_price * shares
        total_pnl_amount = position_value - actual_cost_basis
        total_pnl_percent = (total_pnl_amount / actual_cost_basis * 100) if actual_cost_basis > 0 else 0

        # Calculate daily P&L percentage from the amount
        daily_pnl_percent = (daily_pnl_amount / position_value * 100) if position_value > 0 else 0

        # Calculate days held (simplified - in real system you'd track purchase dates)
        days_held_approx = 1  # Default to 1 day for now

        current_prices.append(current_price)
        pnl_amounts.append(total_pnl_amount)
        pnl_percentages.append(total_pnl_percent)
        position_values.append(position_value)
        daily_pnl_amounts.append(daily_pnl_amount)
        daily_pnl_percentages.append(daily_pnl_percent)
        days_held.append(days_held_approx)

        total_portfolio_value += position_value
    
    # Calculate position weights
    for i, value in enumerate(position_values):
        weight = (value / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
        position_weights.append(weight)
    
    # Add calculated columns
    enhanced_df['Current_Price'] = current_prices
    enhanced_df['Position_Value'] = position_values
    enhanced_df['Total_PnL_Amount'] = pnl_amounts
    enhanced_df['Total_PnL_Percent'] = pnl_percentages
    enhanced_df['Daily_PnL_Amount'] = daily_pnl_amounts
    enhanced_df['Daily_PnL_Percent'] = daily_pnl_percentages
    enhanced_df['Days_Held'] = days_held
    enhanced_df['Weight_Percent'] = position_weights
    
    return enhanced_df, total_portfolio_value

def format_enhanced_portfolio_display(enhanced_df):
    """Format the enhanced portfolio display with better metrics"""
    if enhanced_df.empty:
        return "No current holdings"

    lines = []
    lines.append("Ticker        Shares    Avg Price  Current   Total P&L        Daily P&L        5-Day P&L     Weight %")
    lines.append("                                              $      %            $      %          $      %")
    lines.append("-" * 104)
    
    # ⚡ Bolt: Replaced slow O(N) df.iterrows() with bulk conversion to_dict('records')
    for row in enhanced_df.to_dict('records') if enhanced_df is not None and not enhanced_df.empty else []:
        # Color ticker based on currency (same as Rich table formatter)
        ticker_raw = str(row.get('ticker', ''))
        currency = row.get('currency', 'CAD')  # Default to CAD if not specified
        
        if currency == 'USD':
            ticker = f"{Fore.BLUE}{ticker_raw[:12].ljust(12)}{Style.RESET_ALL}"  # Blue for USD
        elif currency == 'CAD':
            ticker = f"{Fore.CYAN}{ticker_raw[:12].ljust(12)}{Style.RESET_ALL}"  # Cyan for CAD
        else:
            ticker = ticker_raw[:12].ljust(12)  # Default color for unknown currencies
        
        shares = f"{float(row.get('shares', 0)):.4f}".rjust(8)  # Show fractional shares with 4 decimal places
        buy_price = f"${float(row.get('buy_price', 0)):.2f}".rjust(9)
        current = f"${float(row.get('Current_Price', 0)):.2f}".rjust(8)
        
        # Total P&L (since purchase) with color coding
        total_pnl_amt = float(row.get('Total_PnL_Amount', 0))
        total_pnl_pct = float(row.get('Total_PnL_Percent', 0))
        
        if total_pnl_pct > 0:
            total_pnl_amount = f"{Fore.GREEN}${total_pnl_amt:+.2f}{Style.RESET_ALL}".rjust(9 + len(Fore.GREEN) + len(Style.RESET_ALL))
            total_pnl_percent = f"{Fore.GREEN}{total_pnl_pct:+.1f}%{Style.RESET_ALL}".rjust(8 + len(Fore.GREEN) + len(Style.RESET_ALL))
        elif total_pnl_pct < 0:
            total_pnl_amount = f"{Fore.RED}${total_pnl_amt:+.2f}{Style.RESET_ALL}".rjust(9 + len(Fore.RED) + len(Style.RESET_ALL))
            total_pnl_percent = f"{Fore.RED}{total_pnl_pct:+.1f}%{Style.RESET_ALL}".rjust(8 + len(Fore.RED) + len(Style.RESET_ALL))
        else:
            total_pnl_amount = f"{Fore.CYAN}${total_pnl_amt:+.2f}{Style.RESET_ALL}".rjust(9 + len(Fore.CYAN) + len(Style.RESET_ALL))
            total_pnl_percent = f"{Fore.CYAN}{total_pnl_pct:+.1f}%{Style.RESET_ALL}".rjust(8 + len(Fore.CYAN) + len(Style.RESET_ALL))
        
        # Daily P&L (today's change) with color coding
        daily_pnl_amt = float(row.get('Daily_PnL_Amount', 0))
        daily_pnl_pct = float(row.get('Daily_PnL_Percent', 0))
        
        if daily_pnl_pct > 0:
            daily_pnl_amount = f"{Fore.GREEN}${daily_pnl_amt:+.2f}{Style.RESET_ALL}".rjust(9 + len(Fore.GREEN) + len(Style.RESET_ALL))
            daily_pnl_percent = f"{Fore.GREEN}{daily_pnl_pct:+.1f}%{Style.RESET_ALL}".rjust(8 + len(Fore.GREEN) + len(Style.RESET_ALL))
        elif daily_pnl_pct < 0:
            daily_pnl_amount = f"{Fore.RED}${daily_pnl_amt:+.2f}{Style.RESET_ALL}".rjust(9 + len(Fore.RED) + len(Style.RESET_ALL))
            daily_pnl_percent = f"{Fore.RED}{daily_pnl_pct:+.1f}%{Style.RESET_ALL}".rjust(8 + len(Fore.RED) + len(Style.RESET_ALL))
        else:
            daily_pnl_amount = f"{Fore.CYAN}${daily_pnl_amt:+.2f}{Style.RESET_ALL}".rjust(9 + len(Fore.CYAN) + len(Style.RESET_ALL))
            daily_pnl_percent = f"{Fore.CYAN}{daily_pnl_pct:+.1f}%{Style.RESET_ALL}".rjust(8 + len(Fore.CYAN) + len(Style.RESET_ALL))
        
        # 5-Day P&L (use actual data if available)
        five_day_pnl_raw = str(row.get('five_day_pnl', 'N/A'))
        if five_day_pnl_raw != 'N/A' and '$' in five_day_pnl_raw:
            # Parse existing formatted string like "$+12.34 +5.6%"
            five_day_pnl_display = five_day_pnl_raw.rjust(15)
        else:
            five_day_pnl_display = "N/A".rjust(15)
        
        weight = f"{float(row.get('Weight_Percent', 0)):.1f}%".rjust(8)
        
        lines.append(f"{ticker} {shares} {buy_price} {current} {total_pnl_amount} {total_pnl_percent} {daily_pnl_amount} {daily_pnl_percent} {five_day_pnl_display} {weight}")
    
    return "\n".join(lines)

def calculate_portfolio_risk_metrics(enhanced_df, total_portfolio_value, cash_balance):
    """Calculate basic risk metrics for the portfolio"""
    if enhanced_df.empty:
        return {
            'concentration_risk': 0,
            'cash_allocation': 100,
            'total_positions': 0,
            'largest_position': 0,
            'portfolio_volatility': 0
        }
    
    # Concentration risk (largest position as % of portfolio)
    if not enhanced_df.empty:
        max_weight = enhanced_df['Weight_Percent'].max()
        largest_position = enhanced_df.loc[enhanced_df['Weight_Percent'].idxmax(), 'ticker']
    else:
        max_weight = 0
        largest_position = "N/A"
    
    # Cash allocation
    total_equity = total_portfolio_value + cash_balance
    cash_allocation = (cash_balance / total_equity * 100) if total_equity > 0 else 100
    
    # Portfolio volatility (simplified - average of individual position volatilities)
    # This is a basic approximation - in practice you'd calculate portfolio volatility properly
    portfolio_volatility = enhanced_df['Total_PnL_Percent'].std() if len(enhanced_df) > 1 else 0
    
    return {
        'concentration_risk': max_weight,
        'largest_position': largest_position,
        'cash_allocation': cash_allocation,
        'total_positions': len(enhanced_df),
        'portfolio_volatility': portfolio_volatility
    }

def show_complete_prompt(data_dir: str = None):
    """Display the complete LLM prompt for the current configuration
    
    Args:
        data_dir: Required data directory path
    """
    
    print("=" * 80)
    print("COMPLETE LLM PROMPT FOR COPY/PASTE")
    print("=" * 80)
    print()
    
    # Status indicators
    print(f"{Fore.CYAN}{_safe_emoji('🔄')} Initializing prompt generation...{Style.RESET_ALL}")
    
    # Market info
    print(f"{Fore.YELLOW}{_safe_emoji('📊')} Loading market configuration...{Style.RESET_ALL}")
    market_info = get_market_info()
    print(f"{Fore.GREEN}{_safe_emoji('✅')} Market config loaded{Style.RESET_ALL}")
    print(f"Current Market Configuration: {market_info['name']}")
    print(f"Currency: {market_info['currency']}")
    print(f"Market Cap Range: {market_info['market_cap']}")
    print()
    
    # Show what to copy/paste
    print("COPY EVERYTHING BELOW THIS LINE:")
    print("-" * 80)
    
    # This would normally come from your trading script output
    print("================================================================")
    print(f"{Fore.YELLOW}{_safe_emoji('🕰️')} Checking market hours...{Style.RESET_ALL}")
    market_hours = MarketHours()
    print(f"{Fore.GREEN}{_safe_emoji('✅')} Market hours loaded{Style.RESET_ALL}")
    print(f"Daily Results — {market_hours.last_trading_date_str()}")
    print("================================================================")
    print()
    
    print("[ Price & Volume ]")
    print("Ticker            Close     % Chg          Volume")
    print("-------------------------------------------------")
    print("SPY              647.24    -0.29%      85,178,935")
    print("QQQ              576.06    +0.14%      68,342,532")
    print("IWM              237.77    +0.50%      47,542,498")
    print("^GSPTSE               —         —               —")
    print()
    
    # Load actual portfolio data for enhanced display
    try:
        print(f"{Fore.CYAN}💼 Initializing portfolio system...{Style.RESET_ALL}")
        
        # Load portfolio using modular components (same as main script)
        from data.repositories.csv_repository import CSVRepository
        from portfolio.portfolio_manager import PortfolioManager
        from portfolio.fund_manager import Fund, RepositorySettings

        if not data_dir:
            print(f"{Fore.RED}❌ Error: Data directory is required{Style.RESET_ALL}")
            print("Usage: python show_prompt.py --data-dir <path>")
            return
        
        print(f"{Fore.YELLOW}📂 Loading data repository...{Style.RESET_ALL}")
        data_dir = Path(data_dir)
        # Extract fund name from data directory path (e.g., trading_data/funds/Project Chimera -> Project Chimera)
        fund_name = data_dir.name if data_dir.name else 'Unknown'
        repository = CSVRepository(fund_name, str(data_dir))
        print(f"{Fore.GREEN}✅ Repository initialized{Style.RESET_ALL}")
        
        print(f"{Fore.YELLOW}\ud83d\udcca Creating portfolio manager...{Style.RESET_ALL}")
        # Create a default fund for the portfolio manager
        default_fund = Fund(
            id="default",
            name="Default Fund",
            description="Default fund for prompt generation",
            repository=RepositorySettings(type="csv", settings={"directory": str(data_dir)})
        )
        portfolio_manager = PortfolioManager(repository, default_fund)
        print(f"{Fore.GREEN}\u2705 Portfolio manager ready{Style.RESET_ALL}")

        print(f"{Fore.YELLOW}📄 Loading latest portfolio snapshot...{Style.RESET_ALL}")
        latest_snapshot = portfolio_manager.get_latest_portfolio()
        if latest_snapshot:
            print(f"{Fore.GREEN}✅ Latest snapshot loaded ({len(latest_snapshot.positions)} positions){Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}⚠️ No portfolio snapshot found{Style.RESET_ALL}")
        if latest_snapshot and latest_snapshot.positions:
            # Get portfolio snapshots for historical comparison
            print(f"{Fore.YELLOW}📈 Loading historical portfolio snapshots...{Style.RESET_ALL}")
            portfolio_snapshots = portfolio_manager.get_portfolio_snapshots(limit=10)
            print(f"{Fore.GREEN}✅ Loaded {len(portfolio_snapshots)} historical snapshots{Style.RESET_ALL}")

            # Convert to enhanced format with daily P&L (same logic as main script)
            print(f"{Fore.YELLOW}🗺️ Processing position data and calculating P&L...{Style.RESET_ALL}")
            enhanced_positions = []
            total_positions = len(latest_snapshot.positions)
            for i, position in enumerate(latest_snapshot.positions, 1):
                print(f"{Fore.CYAN}  📋 Processing {position.ticker} ({i}/{total_positions})...{Style.RESET_ALL}")
                pos_dict = {
                    'ticker': position.ticker,
                    'company': position.company or position.ticker,
                    'shares': float(position.shares),
                    'avg_price': float(position.avg_price),
                    'current_price': float(position.current_price) if position.current_price else float(position.avg_price),
                    'total_value': float(position.market_value) if position.market_value else 0,
                    'unrealized_pnl': float(position.unrealized_pnl) if position.unrealized_pnl else 0,
                    'cost_basis': float(position.cost_basis) if position.cost_basis else 0,
                    'opened_date': "N/A",  # Will be filled if available
                }

                # Calculate daily P&L using historical snapshots (same logic as main script)
                try:
                    daily_pnl_calculated = False
                    # Try to find daily P&L from multiple previous snapshots
                    for i in range(1, min(len(portfolio_snapshots), 4)):  # Check up to 3 previous snapshots
                        if len(portfolio_snapshots) > i:
                            previous_snapshot = portfolio_snapshots[-(i+1)]
                            # Find the same ticker in previous snapshot
                            prev_position = None
                            for prev_pos in previous_snapshot.positions:
                                if prev_pos.ticker == position.ticker:
                                    prev_position = prev_pos
                                    break

                            if prev_position and prev_position.unrealized_pnl is not None and position.unrealized_pnl is not None:
                                daily_pnl_change = position.unrealized_pnl - prev_position.unrealized_pnl
                                pos_dict['daily_pnl'] = f"${daily_pnl_change:.2f}"
                                daily_pnl_calculated = True
                                break

                    if not daily_pnl_calculated:
                        # If no historical data, show current P&L as daily change for new positions
                        if position.unrealized_pnl is not None and abs(position.unrealized_pnl) > 0.01:
                            pos_dict['daily_pnl'] = f"${position.unrealized_pnl:.2f}*"  # * indicates new position
                        else:
                            pos_dict['daily_pnl'] = "$0.00"
                except Exception as e:
                    logger.debug(f"Could not calculate daily P&L for {position.ticker}: {e}")
                    pos_dict['daily_pnl'] = "$0.00"

                # Multi-day P&L calculation using historical data (5-day preferred, but show 2-4 day if available)
                try:
                    period_pnl_calculated = False
                    
                    # First try for 5-day P&L (snapshots 4-7 days back)
                    for i in range(4, min(len(portfolio_snapshots), 8)):  # Look for snapshots 4-7 days back
                        if len(portfolio_snapshots) > i:
                            period_snapshot = portfolio_snapshots[-(i+1)]
                            # Find the same ticker in historical snapshot
                            period_position = None
                            for period_pos in period_snapshot.positions:
                                if period_pos.ticker == position.ticker:
                                    period_position = period_pos
                                    break

                            if period_position and period_position.unrealized_pnl is not None and position.unrealized_pnl is not None:
                                period_pnl_change = position.unrealized_pnl - period_position.unrealized_pnl
                                period_pct_change = ((position.current_price or position.avg_price) - (period_position.current_price or period_position.avg_price)) / (period_position.current_price or period_position.avg_price) * 100 if (period_position.current_price or period_position.avg_price) > 0 else 0
                                if period_pnl_change >= 0:
                                    pos_dict['five_day_pnl'] = f"${period_pnl_change:.2f} {period_pct_change:.1f}%"
                                else:
                                    pos_dict['five_day_pnl'] = f"${abs(period_pnl_change):.2f} {period_pct_change:.1f}%"
                                period_pnl_calculated = True
                                break
                    
                    # If no 5-day data, try for 2-4 day periods
                    if not period_pnl_calculated:
                        for days_back in [3, 2, 1]:  # Try 4-day, 3-day, 2-day periods
                            if len(portfolio_snapshots) > days_back:
                                period_snapshot = portfolio_snapshots[-(days_back+1)]
                                # Find the same ticker in historical snapshot
                                period_position = None
                                for period_pos in period_snapshot.positions:
                                    if period_pos.ticker == position.ticker:
                                        period_position = period_pos
                                        break

                                if period_position and period_position.unrealized_pnl is not None and position.unrealized_pnl is not None:
                                    period_pnl_change = position.unrealized_pnl - period_position.unrealized_pnl
                                    period_pct_change = ((position.current_price or position.avg_price) - (period_position.current_price or period_position.avg_price)) / (period_position.current_price or period_position.avg_price) * 100 if (period_position.current_price or period_position.avg_price) > 0 else 0
                                    # Add day prefix to indicate partial period
                                    days_label = days_back + 1  # +1 because we're looking at snapshots back
                                    if period_pnl_change >= 0:
                                        pos_dict['five_day_pnl'] = f"{days_label}d: ${period_pnl_change:.2f} {period_pct_change:.1f}%"
                                    else:
                                        pos_dict['five_day_pnl'] = f"{days_label}d: ${abs(period_pnl_change):.2f} {period_pct_change:.1f}%"
                                    period_pnl_calculated = True
                                    break
                            
                            if period_pnl_calculated:
                                break
                    
                    if not period_pnl_calculated:
                        pos_dict['five_day_pnl'] = "N/A"
                except Exception as e:
                    pos_dict['five_day_pnl'] = "N/A"

                enhanced_positions.append(pos_dict)

            print(f"{Fore.GREEN}✅ All positions processed successfully{Style.RESET_ALL}")
            
            # Convert to DataFrame for display
            print(f"{Fore.YELLOW}📊 Converting to analysis format...{Style.RESET_ALL}")
            portfolio_df = pd.DataFrame(enhanced_positions)
            print(f"{Fore.GREEN}✅ Portfolio data ready for analysis{Style.RESET_ALL}")
            cash = 0.0  # Will be loaded separately
        else:
            portfolio_df = pd.DataFrame()
            cash = 0.0

        # Calculate enhanced metrics
        print(f"{Fore.YELLOW}🗺️ Calculating portfolio metrics and risk analysis...{Style.RESET_ALL}")
        enhanced_df, total_portfolio_value = calculate_position_metrics(portfolio_df, cash)
        print(f"{Fore.CYAN}  ⚙️ Computing risk metrics...{Style.RESET_ALL}")
        risk_metrics = calculate_portfolio_risk_metrics(enhanced_df, total_portfolio_value, cash)
        print(f"{Fore.GREEN}✅ Portfolio analysis complete{Style.RESET_ALL}")

        print("[ Enhanced Portfolio Analysis ]")
        if not enhanced_df.empty:
            print(format_enhanced_portfolio_display(enhanced_df))
        else:
            print("No current holdings")
        print()
        
        # Risk metrics
        print("[ Portfolio Risk Metrics ]")
        print(f"Total Positions: {risk_metrics['total_positions']}")
        print(f"Largest Position: {risk_metrics['largest_position']} ({risk_metrics['concentration_risk']:.1f}%)")
        print(f"Cash Allocation: {risk_metrics['cash_allocation']:.1f}%")
        if risk_metrics['portfolio_volatility'] > 0:
            print(f"Portfolio Volatility: {risk_metrics['portfolio_volatility']:.1f}%")
        print()
        
        # Cash balance
        print(f"{Fore.YELLOW}💰 Loading cash balance data...{Style.RESET_ALL}")
        if ACTIVE_MARKET == "NORTH_AMERICAN":
            try:
                cash_balances = load_cash_balances(Path(data_dir))
                print(f"{Fore.GREEN}✅ Cash balances loaded{Style.RESET_ALL}")
                print(f"Cash Balances: {format_cash_display(cash_balances)}")
                print(f"Total (CAD equiv): ${cash_balances.total_cad_equivalent():,.2f}")
            except:
                print(f"{Fore.YELLOW}⚠️ Using default cash balance{Style.RESET_ALL}")
                print(f"Cash Balance: ${cash:,.2f}")
        else:
            print(f"Cash Balance: ${cash:,.2f}")
        print()
        
        # Portfolio summary
        if not enhanced_df.empty:
            total_pnl = enhanced_df['Total_PnL_Amount'].sum()
            daily_pnl = enhanced_df['Daily_PnL_Amount'].sum()
            total_equity = total_portfolio_value + cash
            
            # Calculate performance metrics
            total_pnl_percent = (total_pnl / (total_portfolio_value - total_pnl) * 100) if (total_portfolio_value - total_pnl) > 0 else 0
            # Daily P&L percentage should be 0% when daily P&L amount is 0
            daily_pnl_percent = 0 if daily_pnl == 0 else (daily_pnl / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
            
            print(f"[ Portfolio Summary ]")
            print(f"Total Portfolio Value: ${total_portfolio_value:,.2f}")
            print(f"Total P&L (since purchase): ${total_pnl:+,.2f} ({total_pnl_percent:+.1f}%)")
            print(f"Daily P&L (today's change): ${daily_pnl:+,.2f} ({daily_pnl_percent:+.1f}%)")
            print(f"Total Equity: ${total_equity:,.2f}")
            print()
            
            # Performance context
            if daily_pnl > 0:
                print(f"[ Daily Performance ]")
                print(f"{_safe_emoji('📈')} Portfolio gained ${daily_pnl:,.2f} today ({daily_pnl_percent:+.1f}%)")
            elif daily_pnl < 0:
                print(f"[ Daily Performance ]")
                print(f"📉 Portfolio lost ${abs(daily_pnl):,.2f} today ({daily_pnl_percent:+.1f}%)")
            else:
                print(f"[ Daily Performance ]")
                print(f"➡️ Portfolio unchanged today (${daily_pnl:+,.2f})")
            print()
            
            # Top performers analysis
            if len(enhanced_df) > 1:
                best_performer = enhanced_df.loc[enhanced_df['Total_PnL_Percent'].idxmax()]
                worst_performer = enhanced_df.loc[enhanced_df['Total_PnL_Percent'].idxmin()]
                
                print(f"[ Top Performers ]")
                print(f"🏆 Best: {best_performer['ticker']} ({best_performer['Total_PnL_Percent']:+.1f}%)")
                print(f"📉 Worst: {worst_performer['ticker']} ({worst_performer['Total_PnL_Percent']:+.1f}%)")
                print()
        
    except Exception as e:
        print(f"{Fore.RED}❌ Error loading portfolio data: {e}{Style.RESET_ALL}")
        print(f"[ Portfolio Snapshot ]")
        print("Empty DataFrame")
        print("Columns: [ticker, shares, stop_loss, buy_price, cost_basis]")
        print("Index: []")
        print()
        
        # Cash balance fallback
        print(f"{Fore.YELLOW}💰 Loading fallback cash balance...{Style.RESET_ALL}")
        if ACTIVE_MARKET == "NORTH_AMERICAN":
            try:
                cash_balances = load_cash_balances(Path(data_dir))
                print(f"{Fore.GREEN}✅ Cash balances loaded{Style.RESET_ALL}")
                print(f"Cash Balances: {format_cash_display(cash_balances)}")
                print(f"Total (CAD equiv): ${cash_balances.total_cad_equivalent():,.2f}")
            except:
                print(f"{Fore.YELLOW}⚠️ Using default fallback balance{Style.RESET_ALL}")
                print("Cash Balance: $289.05")
        else:
            print("Cash Balance: $289.05")
        print()
    
    # The key part - the instructions  
    print(f"{Fore.YELLOW}{_safe_emoji('📝')} Loading trading instructions...{Style.RESET_ALL}")
    instructions = get_daily_instructions()
    print(f"{Fore.GREEN}\u2705 Instructions loaded{Style.RESET_ALL}")
    print("[ Your Instructions ]")
    print(instructions)
    
    print(f"{Fore.GREEN}\u2728 Prompt generation complete!{Style.RESET_ALL}")
    print()
    print("-" * 80)
    print("COPY EVERYTHING ABOVE THIS LINE")
    print()
    print("Then paste it into your preferred LLM (ChatGPT, Claude, Gemini, etc.)")

def main():
    """Main function for show_prompt script."""
    parser = argparse.ArgumentParser(description="Show complete LLM prompt")
    parser.add_argument("--data-dir", type=str, required=True, help="Data directory path")
    args = parser.parse_args()
    
    show_complete_prompt(args.data_dir)


if __name__ == "__main__":
    main()
