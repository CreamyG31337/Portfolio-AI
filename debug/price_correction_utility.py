#!/usr/bin/env python3
"""
Price Correction Utility for LLM Micro-Cap Trading Bot

This utility corrects inaccurate prices in the portfolio CSV based on action type and timestamp:
- BUY/SELL actions: Use price at the exact timestamp
- HOLD actions: Use market close price for that date

The utility follows the principle that:
- Trade execution prices should reflect the actual price at the time of the trade
- Portfolio valuation should use closing prices for accurate daily P&L calculation
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz
import argparse
import sys
import os
from typing import Dict, List, Optional, Tuple
import warnings

# Suppress matplotlib warnings
warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib')

# Add parent directory to path to import from main project
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class PriceCorrectionUtility:
    """
    Utility for correcting inaccurate prices in portfolio CSV based on action type and timestamp.
    """
    
    def __init__(self, data_dir: str = "my trading"):
        """
        Initialize the price correction utility.
        
        Args:
            data_dir: Directory containing portfolio and trade data
        """
        self.data_dir = data_dir
        self.portfolio_file = os.path.join(data_dir, "llm_portfolio_update.csv")
        self.trade_log_file = os.path.join(data_dir, "llm_trade_log.csv")
        
        # Local timezone for display
        self.local_tz = pytz.timezone('America/Los_Angeles')
        
        # Load trade log data for BUY/SELL price lookup
        self.trade_log_data = self._load_trade_log()
        
        print(f"🔧 Price Correction Utility initialized")
        print(f"   Data directory: {self.data_dir}")
        print(f"   Portfolio file: {self.portfolio_file}")
        print(f"   Trade log file: {self.trade_log_file}")
        print(f"   Trade log records: {len(self.trade_log_data)}")
    
    def _load_trade_log(self) -> pd.DataFrame:
        """
        Load and parse trade log data for BUY/SELL price lookup.
        
        Returns:
            DataFrame with parsed trade log data
        """
        try:
            if not os.path.exists(self.trade_log_file):
                print(f"⚠️  Trade log file not found: {self.trade_log_file}")
                return pd.DataFrame()
            
            df = pd.read_csv(self.trade_log_file)
            if df.empty:
                return df
            
            # Parse timestamps
            df['Parsed_Date'] = df['Date'].apply(self.parse_timestamp)
            
            # Create a lookup key for matching trades
            df['lookup_key'] = df['Ticker'] + '_' + df['Parsed_Date'].dt.strftime('%Y-%m-%d %H:%M')
            
            return df
            
        except Exception as e:
            print(f"❌ Error loading trade log: {str(e)}")
            return pd.DataFrame()
    
    def parse_timestamp(self, timestamp_str: str) -> datetime:
        """
        Parse timestamp string from CSV, handling both PST and PDT.
        
        Args:
            timestamp_str: Timestamp string from CSV
            
        Returns:
            Timezone-aware datetime object
        """
        try:
            # Remove timezone suffix and parse
            clean_timestamp = timestamp_str.replace(' PST', '').replace(' PDT', '')
            dt = datetime.strptime(clean_timestamp, '%Y-%m-%d %H:%M:%S')
            
            # Determine if it's PST or PDT based on the original string
            if 'PST' in timestamp_str:
                return self.local_tz.localize(dt, is_dst=False)
            elif 'PDT' in timestamp_str:
                return self.local_tz.localize(dt, is_dst=True)
            else:
                # Default to current timezone
                return self.local_tz.localize(dt)
        except Exception as e:
            print(f"⚠️  Warning: Could not parse timestamp '{timestamp_str}': {e}")
            return datetime.now(self.local_tz)
    
    def get_trade_log_price(self, ticker: str, timestamp: datetime, action: str) -> Optional[float]:
        """
        Get the actual execution price from trade log for BUY/SELL actions.
        
        Args:
            ticker: Stock ticker symbol
            timestamp: Target timestamp
            action: Action type (BUY/SELL)
            
        Returns:
            Execution price from trade log or None if not found
        """
        if action not in ['BUY', 'SELL']:
            return None
        
        try:
            # Create lookup key
            lookup_key = ticker + '_' + timestamp.strftime('%Y-%m-%d %H:%M')
            
            # Find matching trade
            matching_trades = self.trade_log_data[self.trade_log_data['lookup_key'] == lookup_key]
            
            if not matching_trades.empty:
                if action == 'BUY':
                    return float(matching_trades['Price'].iloc[0])
                elif action == 'SELL':
                    # For SELL actions, we might need to calculate from PnL or have a separate column
                    # For now, assume we can derive from the trade data
                    return float(matching_trades['Price'].iloc[0])  # Placeholder
            
            return None
            
        except Exception as e:
            print(f"❌ Error getting trade log price for {ticker} at {timestamp}: {str(e)}")
            return None
    
    def get_price_at_timestamp(self, ticker: str, timestamp: datetime, action: str) -> Optional[float]:
        """
        Get the appropriate price for a ticker at a specific timestamp based on action.
        
        Args:
            ticker: Stock ticker symbol
            timestamp: Target timestamp
            action: Action type (BUY/SELL/HOLD)
            
        Returns:
            Appropriate price or None if not found
        """
        try:
            # For BUY/SELL actions, first try to get actual execution price from trade log
            if action in ['BUY', 'SELL']:
                trade_log_price = self.get_trade_log_price(ticker, timestamp, action)
                if trade_log_price is not None:
                    return trade_log_price
                
                # Fallback to intraday data if trade log doesn't have the price
                print(f"   ⚠️  No trade log price for {ticker} {action} at {timestamp.strftime('%Y-%m-%d %H:%M')}, using market data")
                
                # Fetch intraday data for the trading day
                trading_day = timestamp.date()
                start_time = datetime.combine(trading_day, datetime.min.time())
                end_time = start_time + timedelta(days=1)
                
                # Convert to UTC for yfinance
                start_utc = start_time.astimezone(pytz.UTC)
                end_utc = end_time.astimezone(pytz.UTC)
                
                stock = yf.Ticker(ticker)
                hist = stock.history(start=start_utc, end=end_utc, interval="1m")
                
                if not hist.empty:
                    # Convert back to local timezone
                    hist.index = hist.index.tz_convert(self.local_tz)
                    
                    # Find the closest time to our timestamp
                    time_diff = abs(hist.index - timestamp)
                    closest_idx = time_diff.argmin()
                    closest_time = hist.index[closest_idx]
                    
                    # If we're within 30 minutes of market hours, use that price
                    if abs((closest_time - timestamp).total_seconds()) < 1800:  # 30 minutes
                        return float(hist.iloc[closest_idx]['Close'])
            
            # For HOLD actions or if intraday data not available, use closing price
            return self.get_closing_price(ticker, timestamp)
            
        except Exception as e:
            print(f"❌ Error getting price for {ticker} at {timestamp}: {str(e)}")
            return None
    
    def get_closing_price(self, ticker: str, timestamp: datetime) -> Optional[float]:
        """
        Get the closing price for a ticker on a specific date.
        
        Args:
            ticker: Stock ticker symbol
            timestamp: Target date
            
        Returns:
            Closing price or None if not found
        """
        try:
            # Get historical data for a range around the target date
            start_date = timestamp.date() - timedelta(days=5)
            end_date = timestamp.date() + timedelta(days=2)
            
            stock = yf.Ticker(ticker)
            hist = stock.history(start=start_date, end=end_date)
            
            if hist.empty:
                return None
            
            # Find the closest trading day to our target date
            target_date = timestamp.date()
            hist_dates = hist.index.date
            
            # Look for exact date first
            if target_date in hist_dates:
                return float(hist.loc[hist.index.date == target_date, 'Close'].iloc[0])
            
            # Look for the most recent trading day before target
            before_dates = [d for d in hist_dates if d < target_date]
            if before_dates:
                latest_before = max(before_dates)
                return float(hist.loc[hist.index.date == latest_before, 'Close'].iloc[0])
            
            # Look for the closest date overall
            closest_date = min(hist_dates, key=lambda x: abs((x - target_date).days))
            return float(hist.loc[hist.index.date == closest_date, 'Close'].iloc[0])
            
        except Exception as e:
            print(f"❌ Error getting closing price for {ticker} on {timestamp.date()}: {str(e)}")
            return None
    
    def analyze_portfolio_accuracy(self) -> Dict:
        """
        Analyze the accuracy of prices in the portfolio CSV.
        
        Returns:
            Dictionary with analysis results
        """
        print("�� Analyzing portfolio price accuracy...")
        
        try:
            # Read portfolio data
            df = pd.read_csv(self.portfolio_file)
            
            # Parse timestamps
            df['Parsed_Date'] = df['Date'].apply(self.parse_timestamp)
            
            # Get unique tickers
            tickers = df['Ticker'].unique()
            
            analysis = {
                'total_records': len(df),
                'unique_tickers': len(tickers),
                'ticker_analysis': {},
                'issues_found': []
            }
            
            for ticker in tickers:
                print(f"   Analyzing {ticker}...")
                
                ticker_data = df[df['Ticker'] == ticker].copy()
                
                # Analyze each record
                issues = []
                corrections = []
                
                # zip(index, to_dict) preserves the index label captured in
                # corrections['index'] while supporting space-named columns.
                for idx, row in zip(ticker_data.index, ticker_data.to_dict('records')):
                    timestamp = row['Parsed_Date']
                    action = row['Action']
                    current_price = row['Current Price']
                    
                    # Get the correct price based on action and timestamp
                    correct_price = self.get_price_at_timestamp(ticker, timestamp, action)
                    
                    if correct_price is None:
                        issues.append(f"No price data available for {timestamp.strftime('%Y-%m-%d %H:%M')}")
                        continue
                    
                    # Check if prices match (within 1% tolerance)
                    if pd.notna(current_price) and current_price != 'NO DATA':
                        price_diff = abs(current_price - correct_price) / correct_price
                        if price_diff > 0.01:  # More than 1% difference
                            issues.append(f"Price mismatch on {timestamp.strftime('%Y-%m-%d %H:%M')}: "
                                        f"CSV={current_price:.2f}, Correct={correct_price:.2f} ({action})")
                            
                            corrections.append({
                                'index': idx,
                                'date': timestamp,
                                'action': action,
                                'current_price': current_price,
                                'correct_price': correct_price,
                                'difference': current_price - correct_price,
                                'difference_pct': price_diff * 100
                            })
                    else:
                        # Missing price data
                        issues.append(f"Missing price data for {timestamp.strftime('%Y-%m-%d %H:%M')} ({action})")
                        corrections.append({
                            'index': idx,
                            'date': timestamp,
                            'action': action,
                            'current_price': current_price,
                            'correct_price': correct_price,
                            'difference': None,
                            'difference_pct': None
                        })
                
                analysis['ticker_analysis'][ticker] = {
                    'records': len(ticker_data),
                    'issues': issues,
                    'corrections': corrections
                }
                
                if issues:
                    analysis['issues_found'].extend([f"{ticker}: {issue}" for issue in issues])
            
            return analysis
            
        except Exception as e:
            print(f"❌ Error analyzing portfolio: {str(e)}")
            return {'error': str(e)}
    
    def correct_portfolio_prices(self, dry_run: bool = True) -> Dict:
        """
        Correct inaccurate prices in the portfolio CSV.
        
        Args:
            dry_run: If True, only show what would be corrected without making changes
            
        Returns:
            Dictionary with correction results
        """
        print(f"🔧 {'Simulating' if dry_run else 'Correcting'} portfolio price corrections...")
        
        try:
            # Read portfolio data
            df = pd.read_csv(self.portfolio_file)
            original_df = df.copy()
            
            # Parse timestamps
            df['Parsed_Date'] = df['Date'].apply(self.parse_timestamp)
            
            corrections_made = 0
            corrections_log = []
            
            # Process each row
            # zip(index, to_dict) preserves the index label needed by df.loc[idx, ...]
            # while supporting the space-named columns accessed below.
            for idx, row in zip(df.index, df.to_dict('records')):
                ticker = row['Ticker']
                timestamp = row['Parsed_Date']
                action = row['Action']
                current_price = row['Current Price']
                
                # Get the correct price based on action and timestamp
                correct_price = self.get_price_at_timestamp(ticker, timestamp, action)
                
                if correct_price is None:
                    print(f"   ⚠️  No price data for {ticker} on {timestamp.strftime('%Y-%m-%d %H:%M')}")
                    continue
                
                # Check if correction is needed
                needs_correction = False
                
                if pd.isna(current_price) or current_price == 'NO DATA':
                    needs_correction = True
                    correction_type = "missing_data"
                elif pd.notna(current_price):
                    price_diff = abs(current_price - correct_price) / correct_price
                    if price_diff > 0.01:  # More than 1% difference
                        needs_correction = True
                        correction_type = "price_mismatch"
                
                if needs_correction:
                    # Calculate new values
                    shares = row['Shares']
                    new_total_value = shares * correct_price
                    new_pnl = (correct_price - row['Average Price']) * shares
                    
                    # Log the correction
                    correction_log = {
                        'ticker': ticker,
                        'date': timestamp.strftime('%Y-%m-%d %H:%M'),
                        'action': action,
                        'old_price': current_price,
                        'new_price': correct_price,
                        'old_total_value': row['Total Value'],
                        'new_total_value': new_total_value,
                        'old_pnl': row['PnL'],
                        'new_pnl': new_pnl,
                        'type': correction_type
                    }
                    corrections_log.append(correction_log)
                    
                    if not dry_run:
                        # Apply the correction with proper rounding
                        df.loc[idx, 'Current Price'] = round(correct_price, 2)
                        df.loc[idx, 'Total Value'] = round(new_total_value, 2)
                        df.loc[idx, 'PnL'] = round(new_pnl, 2)
                    
                    corrections_made += 1
                    
                    print(f"     📝 {timestamp.strftime('%Y-%m-%d %H:%M')} {action}: "
                          f"{current_price} → {correct_price:.2f} "
                          f"({correction_type})")
            
            # Save corrected data if not dry run
            if not dry_run and corrections_made > 0:
                # Create backup
                backup_file = f"{self.portfolio_file}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                original_df.to_csv(backup_file, index=False)
                print(f"💾 Created backup: {backup_file}")
                
                # Round all numeric columns to 2 decimal places before saving
                numeric_columns = ['Shares', 'Average Price', 'Cost Basis', 'Stop Loss', 'Current Price', 'Total Value', 'PnL']
                for col in numeric_columns:
                    if col in df.columns:
                        df[col] = df[col].round(2)
                
                # Save corrected data
                df.to_csv(self.portfolio_file, index=False)
                print(f"💾 Saved corrected portfolio to {self.portfolio_file}")
            
            return {
                'corrections_made': corrections_made,
                'corrections_log': corrections_log,
                'dry_run': dry_run
            }
            
        except Exception as e:
            print(f"❌ Error correcting portfolio: {str(e)}")
            return {'error': str(e)}
    
    def print_analysis_report(self, analysis: Dict) -> None:
        """
        Print a detailed analysis report.
        
        Args:
            analysis: Analysis results from analyze_portfolio_accuracy
        """
        print("\n�� Portfolio Price Accuracy Analysis Report")
        print("=" * 60)
        
        if 'error' in analysis:
            print(f"❌ Error: {analysis['error']}")
            return
        
        print(f"Total Records: {analysis['total_records']}")
        print(f"Unique Tickers: {analysis['unique_tickers']}")
        print(f"Issues Found: {len(analysis['issues_found'])}")
        print()
        
        # Summary by ticker
        print("📈 Summary by Ticker:")
        print("-" * 40)
        for ticker, data in analysis['ticker_analysis'].items():
            issues_count = len(data['issues'])
            corrections_count = len(data['corrections'])
            
            status = "❌" if issues_count > 0 else "✅"
            print(f"{status} {ticker}: {data['records']} records, {issues_count} issues, {corrections_count} corrections needed")
        
        print()
        
        # Detailed issues
        if analysis['issues_found']:
            print("🔍 Detailed Issues:")
            print("-" * 40)
            for issue in analysis['issues_found'][:10]:  # Show first 10 issues
                print(f"  • {issue}")
            
            if len(analysis['issues_found']) > 10:
                print(f"  ... and {len(analysis['issues_found']) - 10} more issues")
        
        print()

def main():
    """
    Main function with command line interface.
    """
    parser = argparse.ArgumentParser(description='Correct inaccurate prices in portfolio CSV')
    parser.add_argument('--data-dir', default='trading_data/funds/TEST', 
                       help='Data directory containing portfolio CSV')
    parser.add_argument('--analyze-only', action='store_true',
                       help='Only analyze prices without making corrections')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Show what would be corrected without making changes')
    parser.add_argument('--apply', action='store_true',
                       help='Actually apply the corrections (overrides --dry-run)')
    
    args = parser.parse_args()
    
    print("🔧 LLM Micro-Cap Trading Bot - Price Correction Utility")
    print("=" * 60)
    
    # Initialize utility
    utility = PriceCorrectionUtility(args.data_dir)
    
    # Analyze portfolio accuracy
    analysis = utility.analyze_portfolio_accuracy()
    utility.print_analysis_report(analysis)
    
    if args.analyze_only:
        print("✅ Analysis complete. Use --apply to make corrections.")
        return
    
    # Correct prices if requested
    if args.apply:
        print("\n🔧 Applying price corrections...")
        result = utility.correct_portfolio_prices(dry_run=False)
        
        if 'error' in result:
            print(f"❌ Error: {result['error']}")
        else:
            print(f"✅ Corrections applied: {result['corrections_made']} records updated")
    else:
        print("\n�� Simulating price corrections...")
        result = utility.correct_portfolio_prices(dry_run=True)
        
        if 'error' in result:
            print(f"❌ Error: {result['error']}")
        else:
            print(f"✅ Simulation complete: {result['corrections_made']} records would be updated")
            print("💡 Use --apply to actually make the corrections")

if __name__ == "__main__":
    main()