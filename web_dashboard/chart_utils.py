#!/usr/bin/env python3
"""
Chart utilities for creating performance graphs with Plotly.

Features:
- Portfolio value and normalized performance charts
- Benchmark comparison (S&P 500, QQQ, Russell 2000, VTI)
- Weekend shading to highlight market closures
- P&L by position charts
- Trade timeline charts
"""

import sys
from pathlib import Path

# Add parent directory to path for imports from root (utils, config, etc.)
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

import pandas as pd
import plotly.graph_objs as go
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime, timedelta
import yfinance as yf
from utils.market_holidays import MarketHolidays
try:
    from log_handler import log_execution_time
except ImportError:
    log_execution_time = lambda x=None: lambda f: f


# Benchmark configuration
BENCHMARK_CONFIG = {
    'sp500': {'ticker': '^GSPC', 'name': 'S&P 500', 'color': '#ff7f0e'},
    'qqq': {'ticker': 'QQQ', 'name': 'Nasdaq-100 (QQQ)', 'color': '#2ca02c'},
    'russell2000': {'ticker': '^RUT', 'name': 'Russell 2000', 'color': '#d62728'},
    'vti': {'ticker': 'VTI', 'name': 'Total Market (VTI)', 'color': '#9467bd'}
}

# Initialize the holiday utility
MARKET_HOLIDAYS = MarketHolidays()


def _add_holiday_shading(fig: go.Figure, start_date: datetime, end_date: datetime,
                         market: str = 'us',
                         holiday_color: Optional[str] = 'rgba(211, 211, 211, 0.3)') -> None:
    """Add shading for market holidays using the centralized utility."""
    holidays_in_range = MARKET_HOLIDAYS.get_holidays_for_range(start_date.date(), end_date.date(), market=market)

    for holiday_date in holidays_in_range:
        start_shade = datetime.combine(holiday_date, datetime.min.time())
        end_shade = start_shade + timedelta(days=1)

        holiday_name = MARKET_HOLIDAYS.get_holiday_name(holiday_date) or "Holiday"

        fig.add_vrect(
            x0=start_shade,
            x1=end_shade,
            fillcolor=holiday_color,
            layer="below",
            line_width=0,
            annotation_text=holiday_name,
            annotation_position="top left",
            annotation_font_size=10,
            annotation_font_color="gray"
        )


# Theme-aware chart helpers
# NOTE: Currently only create_ticker_price_chart() has full theme support.
# Other chart functions (create_portfolio_value_chart, create_pnl_chart, etc.)
# still use hardcoded 'plotly_white' template. To add theme support to other charts,
# add a 'theme' parameter and use get_chart_theme_config() and apply_theme_to_layout().
def get_chart_theme_config(theme: Optional[str] = 'system') -> Dict[str, any]:
    """
    Get theme configuration for Plotly charts.
    
    This is the main helper function for making charts theme-aware. Use it to get
    all theme-related colors and settings, then apply them to your chart.
    
    Args:
        theme: User theme preference ('dark', 'light', or 'system')
              - 'dark': Use dark mode
              - 'light': Use light mode  
              - 'system': Default to light mode (server-side can't detect OS preference)
              - None or empty string: Defaults to 'system'
        
    Returns:
        Dictionary with theme configuration:
        - is_dark: bool - Whether dark mode should be used
        - template: str - Plotly template name ('plotly_dark' or 'plotly_white')
        - weekend_shading_color: str - RGBA color for weekend shading
        - baseline_line_color: str - Color for baseline reference lines
        - legend_bg_color: str - RGBA color for legend background
        
    Example - Basic usage:
        from user_preferences import get_user_theme
        
        theme = get_user_theme() or 'system'
        config = get_chart_theme_config(theme)
        
        fig = go.Figure()
        # ... add traces ...
        fig.update_layout(
            template=config['template'],
            legend=dict(bgcolor=config['legend_bg_color'])
        )
        return fig
        
    Example - With weekend shading:
        config = get_chart_theme_config(theme)
        _add_weekend_shading(fig, start_date, end_date, 
                            weekend_color=config['weekend_shading_color'])
        
    Example - With baseline line:
        config = get_chart_theme_config(theme)
        fig.add_hline(y=100, line_color=config['baseline_line_color'])
    """
    # Ensure theme is never None or empty
    if not theme or theme.strip() == '':
        theme = 'system'
    
    # Theme color definitions
    theme_configs = {
        'light': {
            'is_dark': False,
            'template': 'plotly_white',
            'paper_bgcolor': 'white',
            'plot_bgcolor': 'white',
            'font_color': 'rgb(31, 41, 55)',
            'grid_color': 'rgb(229, 231, 235)',
            'weekend_shading_color': 'rgba(128, 128, 128, 0.1)',
            'baseline_line_color': 'gray',
            'legend_bg_color': 'rgba(255, 255, 255, 0.8)'
        },
        'dark': {
            'is_dark': True,
            'template': 'plotly_dark',
            'paper_bgcolor': 'rgb(31, 41, 55)',
            'plot_bgcolor': 'rgb(31, 41, 55)',
            'font_color': 'rgb(209, 213, 219)',
            'grid_color': 'rgb(55, 65, 81)',
            'weekend_shading_color': 'rgba(50, 50, 50, 0.3)',
            'baseline_line_color': 'rgba(200, 200, 200, 0.7)',
            'legend_bg_color': 'rgba(31, 41, 55, 0.8)'
        },
        'midnight-tokyo': {
            'is_dark': True,
            'template': 'plotly_dark',
            'paper_bgcolor': '#24283b',
            'plot_bgcolor': '#24283b',
            'font_color': '#c0caf5',
            'grid_color': '#3b4261',
            'weekend_shading_color': 'rgba(125, 207, 255, 0.08)',
            'baseline_line_color': '#7dcfff',
            'legend_bg_color': 'rgba(36, 40, 59, 0.9)'
        },
        'abyss': {
            'is_dark': True,
            'template': 'plotly_dark',
            'paper_bgcolor': '#0f1c2e',
            'plot_bgcolor': '#0f1c2e',
            'font_color': '#a9b1d6',
            'grid_color': '#1a2b42',
            'weekend_shading_color': 'rgba(65, 166, 181, 0.08)',
            'baseline_line_color': '#41a6b5',
            'legend_bg_color': 'rgba(15, 28, 46, 0.9)'
        }
    }
    
    # Default to 'light' if theme not found
    config = theme_configs.get(theme, theme_configs['light'])
    
    return config


def apply_theme_to_layout(fig: go.Figure, theme: str = 'system', 
                          legend_bg_color: Optional[str] = None) -> go.Figure:
    """
    Apply theme-aware styling to a Plotly figure's layout.
    
    This is a convenience function that updates the template and legend background
    based on the theme. Use this after creating your chart but before returning it.
    
    Args:
        fig: Plotly figure to update
        theme: User theme preference ('dark', 'light', or 'system')
        legend_bg_color: Optional custom legend background color (overrides theme default)
        
    Returns:
        Updated figure (modifies in place, but returns for chaining)
        
    Example:
        fig = go.Figure()
        # ... add traces ...
        fig = apply_theme_to_layout(fig, theme='dark')
        return fig
    """
    config = get_chart_theme_config(theme)
    
    # Update template
    fig.update_layout(template=config['template'])
    
    # Update legend background if legend exists
    if fig.layout.legend:
        legend_bg = legend_bg_color or config['legend_bg_color']
        fig.update_layout(legend=dict(bgcolor=legend_bg))
    
    return fig


def _adjust_to_market_close(df: pd.DataFrame, date_column: str = 'date') -> pd.DataFrame:
    """Adjust datetime values to market close time (13:00 PST) for proper alignment.
    
    This matches the console app's approach where all data points are set to
    market close time, ensuring dots align correctly with weekend shading.
    
    Args:
        df: DataFrame with date column
        date_column: Name of the date column to adjust
        
    Returns:
        DataFrame with adjusted datetime values
    """
    df = df.copy()
    df[date_column] = pd.to_datetime(df[date_column])
    
    # Adjust each date to 13:00 (1 PM PST - market close time)
    adjusted_dates = []
    for dt in df[date_column]:
        date_only = dt.date() if hasattr(dt, 'date') else pd.Timestamp(dt).date()
        # Set to market close time: 13:00 PST
        market_close = datetime.combine(date_only, datetime.min.time()) + timedelta(hours=13)
        adjusted_dates.append(market_close)
    
    df[date_column] = adjusted_dates
    return df


def _filter_trading_days(df: pd.DataFrame, date_column: str = 'date', market: str = 'us') -> pd.DataFrame:
    """Remove weekends and holidays from dataset using the centralized utility."""
    if df.empty or date_column not in df.columns:
        return df

    df = df.copy()
    # Use errors='coerce' to handle invalid date strings gracefully (converts to NaT)
    df[date_column] = pd.to_datetime(df[date_column], errors='coerce')

    # Use the is_trading_day method from the utility
    # Handle NaT values gracefully: treat them as non-trading days (filter them out)
    trading_days_mask = df[date_column].apply(
        lambda x: False if pd.isna(x) else MARKET_HOLIDAYS.is_trading_day(x.date(), market=market)
    )

    return df[trading_days_mask]


def _add_weekend_shading(fig: go.Figure, start_date: datetime, end_date: datetime, 
                        is_dark: bool = False, weekend_color: Optional[str] = None) -> None:
    """Add light gray shading for weekends (Saturday 00:00 to Monday 00:00).
    
    This matches the console app's approach for consistent weekend visualization.
    Shades the entire weekend period when markets are closed.
    
    Args:
        fig: Plotly figure to add shading to
        start_date: Start date for shading
        end_date: End date for shading
        is_dark: If True, use darker shading color for dark mode (deprecated, use weekend_color)
        weekend_color: Optional custom weekend shading color (overrides is_dark)
    """
    # Theme-aware weekend shading color
    if weekend_color is None:
        weekend_color = "rgba(200, 200, 200, 0.15)" if is_dark else "rgba(128, 128, 128, 0.1)"
    
    # Normalize to date-only (midnight) to avoid time component misalignment
    start_date_only = start_date.date() if isinstance(start_date, datetime) else start_date
    end_date_only = end_date.date() if isinstance(end_date, datetime) else end_date
    
    # Convert pandas Timestamp to date if needed
    if hasattr(start_date_only, 'date'):
        start_date_only = start_date_only.date()
    if hasattr(end_date_only, 'date'):
        end_date_only = end_date_only.date()
    
    # Handle case where chart starts on a Sunday - shade the weekend that includes it
    start_weekday = start_date_only.weekday()
    if start_weekday == 6:  # Sunday
        # Shade from previous Saturday 00:00 to Monday 00:00 (entire weekend)
        previous_saturday = start_date_only - timedelta(days=1)
        saturday_midnight = datetime.combine(previous_saturday, datetime.min.time())
        monday_midnight = datetime.combine(start_date_only + timedelta(days=1), datetime.min.time())
        
        fig.add_vrect(
            x0=saturday_midnight,
            x1=monday_midnight,
            fillcolor=weekend_color,
            layer="below",
            line_width=0,
        )
    
    # Iterate through all dates to find Saturdays (start of weekends)
    current_date = start_date_only
    while current_date <= end_date_only:
        weekday = current_date.weekday()
        
        if weekday == 5:  # Saturday (start of weekend)
            # Shade from Saturday 00:00 to Monday 00:00 (entire weekend)
            saturday_midnight = datetime.combine(current_date, datetime.min.time())
            monday_midnight = datetime.combine(current_date + timedelta(days=2), datetime.min.time())
            
            fig.add_vrect(
                x0=saturday_midnight,
                x1=monday_midnight,
                fillcolor=weekend_color,
                layer="below",
                line_width=0,
            )
            # Skip to Monday (we've covered the weekend)
            current_date += timedelta(days=2)
        else:
            current_date += timedelta(days=1)


@log_execution_time()
def _fetch_benchmark_data(ticker: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
    """Fetch benchmark data with database caching.
    
    Cache-first approach:
    1. Check database cache
    2. If cache hit and recent, use cached data
    3. If cache miss or stale, fetch from Yahoo Finance and cache
    """
    client = None  # Initialize to avoid NameError
    try:
        # Try to get from cache first
        try:
            from streamlit_utils import get_supabase_client
            client = get_supabase_client()
            
            if client:
                cached_data = client.get_benchmark_data(ticker, start_date, end_date)
                
                if cached_data and len(cached_data) > 0:
                    # Convert to DataFrame
                    data = pd.DataFrame(cached_data)
                    data['Date'] = pd.to_datetime(data['date'])
                    data = data.rename(columns={'close': 'Close'})
                    
                    # Check if data is recent enough (has data within 1 day of end_date)
                    max_cached_date = data['Date'].max()
                    # Normalize timezones for comparison
                    if max_cached_date.tzinfo is None and end_date.tzinfo is not None:
                        max_cached_date = max_cached_date.replace(tzinfo=end_date.tzinfo)
                    elif max_cached_date.tzinfo is not None and end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=max_cached_date.tzinfo)
                    
                    days_diff = (end_date - max_cached_date).days
                    
                    if days_diff <= 1:
                        # Cache hit with recent data - use it
                        print(f"📦 Using cached benchmark data for {ticker}")
                        
                        # Normalize to 100 baseline
                        baseline_data = data[data['Date'].dt.date <= start_date.date()]
                        if not baseline_data.empty:
                            baseline_close = baseline_data['Close'].iloc[-1]
                        else:
                            baseline_close = data['Close'].iloc[0]
                        
                        # Validate baseline_close to avoid division by zero
                        if pd.isna(baseline_close) or baseline_close == 0:
                            print(f"⚠️ Invalid baseline close ({baseline_close}) for {ticker}, fetching fresh data")
                        else:
                            data['normalized'] = (data['Close'] / baseline_close) * 100
                            # Filter to trading days only for consistency and performance
                            data = _filter_trading_days(data, 'Date')
                            # Normalize to noon (12:00) to match portfolio data
                            data['Date'] = data['Date'].dt.normalize() + timedelta(hours=12)
                            return data[['Date', 'Close', 'normalized']]
                    else:
                        print(f"⚠️ Cached data for {ticker} is stale ({days_diff} days old), fetching fresh data")
        except Exception as cache_error:
            print(f"Cache lookup failed (will fetch from API): {cache_error}")
        
        # Cache miss or stale - fetch from Yahoo Finance
        print(f"🌐 Fetching benchmark data from Yahoo Finance: {ticker}")
        
        # Add buffer days to ensure we get data
        buffer_start = start_date - timedelta(days=5)
        buffer_end = end_date + timedelta(days=2)
        
        data = yf.download(ticker, start=buffer_start, end=buffer_end, progress=False, auto_adjust=False)
        
        if data.empty:
            return None
        
        data = data.reset_index()
        
        # Handle MultiIndex columns from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        
        # Find the baseline close price at or near portfolio start date
        data['Date'] = pd.to_datetime(data['Date'])
        
        # Store in cache for future use
        try:
            if client:
                # Validate required columns exist before accessing
                required_cols = ['Date', 'Close']
                optional_cols = ['Open', 'High', 'Low', 'Volume']
                available_cols = [col for col in required_cols + optional_cols if col in data.columns]
                
                if 'Date' in available_cols and 'Close' in available_cols:
                    cache_rows = data[available_cols].to_dict('records')
                    client.cache_benchmark_data(ticker, cache_rows)
                else:
                    print(f"⚠️ Missing required columns for caching {ticker}")
        except Exception as cache_store_error:
            print(f"Failed to cache benchmark data: {cache_store_error}")
        
        # Get close on start date (or nearest previous trading day)
        baseline_data = data[data['Date'].dt.date <= start_date.date()]
        if not baseline_data.empty:
            baseline_close = baseline_data['Close'].iloc[-1]
        else:
            baseline_close = data['Close'].iloc[0]
        
        # Validate baseline_close to avoid division by zero
        if pd.isna(baseline_close) or baseline_close == 0:
            print(f"❌ Error: Invalid baseline close ({baseline_close}) for {ticker}")
            return None
        
        # Normalize to 100 baseline
        data['normalized'] = (data['Close'] / baseline_close) * 100
        
        # Filter to trading days only for consistency and performance
        data = _filter_trading_days(data, 'Date')
        
        # Normalize to noon (12:00) to match portfolio data
        data['Date'] = data['Date'].dt.normalize() + timedelta(hours=12)
        
        return data[['Date', 'Close', 'normalized']]
        
    except Exception as e:
        print(f"Error fetching benchmark {ticker}: {e}")
        return None



@log_execution_time()
def create_portfolio_value_chart(
    portfolio_df: pd.DataFrame,
    fund_name: Optional[str] = None,
    show_normalized: bool = False,
    show_benchmarks: Optional[List[str]] = None,
    show_weekend_shading: bool = True,
    use_solid_lines: bool = False,
    display_currency: Optional[str] = None,
    market: str = 'us'
) -> go.Figure:
    """Create a line chart showing portfolio value/performance over time.
    
    Args:
        portfolio_df: DataFrame with portfolio data (date, value, performance_index, etc)
        fund_name: Optional fund name for title
        show_normalized: If True, shows performance index (baseline 100) instead of raw value
        show_benchmarks: List of benchmark keys to display (e.g., ['sp500', 'qqq'])
        show_weekend_shading: If True, adds gray shading for weekends
        display_currency: Optional display currency (defaults to user preference)
    """
    # Get display currency
    if display_currency is None:
        try:
            from streamlit_utils import get_user_display_currency
            display_currency = get_user_display_currency()
        except ImportError:
            display_currency = 'CAD'
    if portfolio_df.empty or 'date' not in portfolio_df.columns:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # Sort by date
    df = portfolio_df.sort_values('date').copy()
    df['date'] = pd.to_datetime(df['date'])
    
    # Filter out non-trading days
    df = _filter_trading_days(df, 'date', market=market)

    # For normalized view, ensure all days before first investment show at 100
    # Days with cost_basis = 0 should have performance_index = 100 (baseline)
    if show_normalized and 'performance_index' in df.columns and 'cost_basis' in df.columns:
        # Find first investment day
        first_investment = df[df['cost_basis'] > 0]
        if not first_investment.empty:
            first_investment_date = first_investment['date'].min()
            # Ensure all days before first investment have performance_index = 100
            pre_investment_mask = df['date'] < first_investment_date
            df.loc[pre_investment_mask, 'performance_index'] = 100.0
    
    # Create the chart
    fig = go.Figure()
    
    # Determine which column to use for y-axis
    if show_normalized and 'performance_index' in df.columns:
        y_col = 'performance_index'
        y_label = "Performance Index (Baseline 100)"
        chart_name = "Portfolio"
        # Add reference line at 100
        fig.add_hline(y=100, line_dash="dash", line_color="gray", 
                      annotation_text="Baseline", annotation_position="right")
    elif 'value' in df.columns:
        y_col = 'value'
        y_label = f"Portfolio Value ({display_currency})"
        chart_name = "Portfolio Value"
    elif 'total_value' in df.columns:
        y_col = 'total_value'
        y_label = f"Portfolio Value ({display_currency})"
        chart_name = "Portfolio Value"
    else:
        fig = go.Figure()
        fig.add_annotation(
            text="No value data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # Calculate return percentage for label
    if len(df) > 1 and 'performance_pct' in df.columns:
        current_return = df['performance_pct'].iloc[-1]
        label_suffix = f" ({current_return:+.2f}%)"
    else:
        label_suffix = ""
    
    # Add portfolio trace
    # DEBUG: Log what we're about to plot
    import logging
    logger = logging.getLogger(__name__)
    if y_col == 'performance_index' and len(df) > 0:
        first_10_y = df[y_col].head(10).tolist()
        logger.info(f"[DEBUG] create_portfolio_value_chart - Plotting {y_col}, first 10 values: {first_10_y}, df shape: {df.shape}, columns: {list(df.columns)}")
    
    fig.add_trace(go.Scatter(
        x=df['date'],
        y=df[y_col],
        mode='lines+markers',
        name=f'{chart_name}{label_suffix}',
        line=dict(color='#1f77b4', width=3),
        marker=dict(size=4),
        hovertemplate='%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>'
    ))
    
    # Add benchmarks if requested (only for normalized view)
    if show_normalized and show_benchmarks and 'performance_index' in df.columns:
        import time
        import logging
        logger = logging.getLogger(__name__)
        benchmark_start = time.time()
        
        # CRITICAL: Use the first day where portfolio actually has investment for benchmark baseline
        # This ensures benchmarks normalize to the same baseline date as the portfolio
        # The portfolio's first investment day is where performance_index = 100 (baseline)
        # Benchmarks must use this same date for fair comparison
        
        # Find the first investment day (where cost_basis > 0)
        # This is the date where portfolio baseline = 100
        if 'cost_basis' in df.columns:
            first_investment = df[df['cost_basis'] > 0]
            if not first_investment.empty:
                # Use first investment day as baseline date for benchmarks
                baseline_date = first_investment['date'].min()
                logger.debug(f"Using first investment day {baseline_date.date()} as benchmark baseline")
            else:
                # Fallback: no investment data, use first date
                baseline_date = df['date'].min()
                logger.warning("No investment data found, using min date as baseline")
        else:
            # If cost_basis not available, try to infer from performance_index
            # First day where performance_index = 100 should be the baseline
            # But this is less reliable - cost_basis is the source of truth
            baseline_date = df['date'].min()
            logger.warning("cost_basis column not available, using min date as baseline")
        
        # Use baseline_date for benchmark normalization, but fetch data from portfolio date range
        start_date = df['date'].min()  # Fetch benchmark data from portfolio start
        end_date = df['date'].max()
        
        # Both portfolio and benchmark data use noon (12:00) timestamps for consistency
        # Portfolio data normalized to noon in streamlit_utils.py line 925
        # Benchmark data normalized to noon after fetching/caching
        start_date_normalized = pd.Timestamp(start_date).normalize()  # Set to 00:00:00
        end_date_normalized = pd.Timestamp(end_date).normalize() + timedelta(days=1)  # Include full end date
        
        for bench_key in show_benchmarks:
            if bench_key not in BENCHMARK_CONFIG:
                continue
            
            bench_t0 = time.time()
            config = BENCHMARK_CONFIG[bench_key]
            # CRITICAL: Use baseline_date (first investment day) for benchmark normalization
            # This ensures benchmark normalizes to 100 on the same day as portfolio baseline
            # _fetch_benchmark_data uses start_date to find baseline_close for normalization
            bench_data = _fetch_benchmark_data(config['ticker'], baseline_date, end_date)
            bench_fetch_time = time.time() - bench_t0
            logger.info(f"⏱️ create_portfolio_value_chart - Fetch benchmark {bench_key}: {bench_fetch_time:.2f}s")
            
            if bench_data is not None and not bench_data.empty:
                # Convert bench_data dates to datetime, preserving actual timestamps
                # Don't normalize - use actual time from database to match portfolio data
                bench_data['Date'] = pd.to_datetime(bench_data['Date'])
                # Remove timezone if present for consistency
                if bench_data['Date'].dt.tz is not None:
                    bench_data['Date'] = bench_data['Date'].dt.tz_convert(None)
                
                # Filter out any NaT values before date range filtering
                bench_data = bench_data[bench_data['Date'].notna()].copy()
                
                # Filter to portfolio date range - compare dates, not timestamps
                # Convert Timestamp to datetime64 for type compatibility with Series
                start_dt64 = start_date_normalized.to_datetime64()
                end_dt64 = end_date_normalized.to_datetime64()
                bench_data = bench_data[
                    (bench_data['Date'] >= start_dt64) & 
                    (bench_data['Date'] < end_dt64)
                ]
                
                if not bench_data.empty:
                    # Calculate benchmark return for label
                    bench_return = bench_data['normalized'].iloc[-1] - 100
                    
                    # Use solid or dashed lines based on preference
                    line_style = {} if use_solid_lines else {'dash': 'dash'}
                    
                    # S&P 500 visible by default, others hidden in legend
                    visibility = True if bench_key == 'sp500' else 'legendonly'
                    
                    fig.add_trace(go.Scatter(
                        x=bench_data['Date'],
                        y=bench_data['normalized'],
                        mode='lines',
                        name=f"{config['name']} ({bench_return:+.2f}%)",
                        line=dict(color=config['color'], width=3, **line_style),
                        opacity=0.8,
                        visible=visibility,
                        hovertemplate='%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>'
                    ))
        
        benchmark_total_time = time.time() - benchmark_start
        logger.info(f"⏱️ create_portfolio_value_chart - All benchmarks: {benchmark_total_time:.2f}s")
    
    # Add weekend and holiday shading
    if show_weekend_shading and len(df) > 1:
        start_date = df['date'].min()
        end_date = df['date'].max()

        # Weekend shading
        _add_weekend_shading(fig, start_date, end_date)

        # Holiday shading
        _add_holiday_shading(fig, start_date, end_date, market=market)
    
    # Title
    title = f"Portfolio {'Performance' if show_normalized else 'Value'} Over Time"
    if fund_name:
        title += f" - {fund_name}"
    if show_benchmarks and show_normalized:
        title += " vs Benchmarks"
    
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title=y_label,
        hovermode='x unified',
        template='plotly_white',
        height=500,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255, 255, 255, 0.8)"
        )
    )
    
    return fig


def create_performance_by_fund_chart(funds_data: Dict[str, float], display_currency: Optional[str] = None) -> go.Figure:
    """Create a bar chart showing performance by fund"""
    # Get display currency
    if display_currency is None:
        try:
            from streamlit_utils import get_user_display_currency
            display_currency = get_user_display_currency()
        except ImportError:
            display_currency = 'CAD'
    
    if not funds_data:
        fig = go.Figure()
        fig.add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    funds = list(funds_data.keys())
    values = list(funds_data.values())
    
    # Color bars based on positive/negative
    colors = ['#10b981' if v >= 0 else '#ef4444' for v in values]
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=funds,
        y=values,
        marker_color=colors,
        text=[f"${v:,.2f}" for v in values],
        textposition='outside'
    ))
    
    fig.update_layout(
        title="Performance by Fund",
        xaxis_title="Fund",
        yaxis_title=f"Value ({display_currency})",
        template='plotly_white',
        height=400
    )
    
    return fig


@log_execution_time()
def create_pnl_chart(positions_df: pd.DataFrame, fund_name: Optional[str] = None, display_currency: Optional[str] = None, dividend_data: Optional[list] = None) -> go.Figure:
    """Create a bar chart showing P&L by position (unrealized + dividends)
    
    Visualization logic:
    - Positive total P&L with positive unrealized: Overlay bars (green unrealized + gold dividends, both above axis)
    - Positive total P&L with negative unrealized: Overlay bars (red loss below axis + gold dividends above axis)
      - Red bar shows the unrealized loss (negative value, appears below axis)
      - Gold bar shows dividends (positive value, appears above axis)
      - Both bars align vertically at the same x position (ticker)
      - This makes it visually clear that dividends are offsetting the loss
    - Negative total P&L: Single red bar below axis
    
    Args:
        positions_df: DataFrame with position data including unrealized P&L
        fund_name: Optional fund name for chart title
        display_currency: Currency code for labels (e.g. 'CAD', 'USD')
        dividend_data: Optional pre-fetched dividend data to avoid duplicate DB calls.
                      Expected format: list of dicts from fetch_dividend_log()
    """
    # Get display currency
    if display_currency is None:
        try:
            from streamlit_utils import get_user_display_currency
            display_currency = get_user_display_currency()
        except ImportError:
            display_currency = 'CAD'
    
    # Check for either pnl or unrealized_pnl column
    pnl_col = None
    if 'unrealized_pnl' in positions_df.columns:
        pnl_col = 'unrealized_pnl'
    elif 'pnl' in positions_df.columns:
        pnl_col = 'pnl'
    
    if positions_df.empty or pnl_col is None:
        fig = go.Figure()
        fig.add_annotation(
            text="No P&L data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # Aggregate dividend data by ticker if provided
    dividends_by_ticker = {}
    if dividend_data:
        try:
            div_df = pd.DataFrame(dividend_data)
            if not div_df.empty and 'ticker' in div_df.columns and 'net_amount' in div_df.columns:
                dividends_by_ticker = div_df.groupby('ticker')['net_amount'].sum().to_dict()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not process dividend data for P&L chart: {e}")
    
    # Create a copy and add dividend data
    df = positions_df.copy()
    df['dividends'] = df['ticker'].map(dividends_by_ticker).fillna(0)
    df['total_pnl'] = df[pnl_col] + df['dividends']
    
    # Sort by total P&L
    df = df.sort_values('total_pnl', ascending=False)
    
    # Limit to top/bottom 20 for readability
    if len(df) > 40:
        top = df.head(20)
        bottom = df.tail(20)
        df = pd.concat([top, bottom]).sort_values('total_pnl', ascending=False)
    
    # Split data by TOTAL P&L (not unrealized):
    # 1. Positive total P&L -> winners (green or red+gold)
    # 2. Negative total P&L -> losers (red)
    
    df_positive_total = df[df['total_pnl'] >= 0].copy()
    df_negative_total = df[df['total_pnl'] < 0].copy()
    
    fig = go.Figure()
    
    # For POSITIVE TOTAL P&L: Check if we can use stacked bars
    if not df_positive_total.empty:
        # Further split: positive unrealized (stackable green) vs negative unrealized (show loss below, dividends above)
        df_stackable_green = df_positive_total[df_positive_total[pnl_col] >= 0]
        df_net_positive = df_positive_total[df_positive_total[pnl_col] < 0]  # Negative unrealized but positive total
        
        # Stackable green: positive unrealized + dividends on top
        if not df_stackable_green.empty:
            fig.add_trace(go.Bar(
                name='Unrealized P&L (gain)',
                x=df_stackable_green['ticker'],
                y=df_stackable_green[pnl_col],
                marker_color='#10b981',
                hovertemplate='<b>%{x}</b><br>Unrealized P&L: $%{y:,.2f}<extra></extra>',
                showlegend=True
            ))
            
            # Dividends bar (gold) - only if there are any dividends
            # Stack on top of unrealized P&L by setting base to unrealized P&L value
            if (df_stackable_green['dividends'] > 0).any():
                fig.add_trace(go.Bar(
                    name='Dividends (LTM)',
                    x=df_stackable_green['ticker'],
                    y=df_stackable_green['dividends'],
                    base=df_stackable_green[pnl_col],  # Stack on top of unrealized P&L
                    marker_color='#f59e0b',
                    hovertemplate='<b>%{x}</b><br>Dividends: $%{y:,.2f}<br>Total P&L: $%{customdata[0]:,.2f}<extra></extra>',
                    customdata=df_stackable_green[['total_pnl']],  # Include total for hover
                    showlegend=True
                ))
        
        # Negative unrealized BUT positive total (dividends overcame loss)
        # Show red bar below axis (loss) and gold bar above axis (dividends)
        # With overlay mode, they'll appear at the same x position, aligned vertically
        if not df_net_positive.empty:
            # Red bar showing unrealized loss (negative value, appears below axis)
            fig.add_trace(go.Bar(
                name='Unrealized P&L (loss)',
                x=df_net_positive['ticker'],
                y=df_net_positive[pnl_col],  # Negative value - will appear below axis
                marker_color='#ef4444',
                hovertemplate='<b>%{x}</b><br>Unrealized P&L: $%{y:,.2f}<extra></extra>',
                showlegend=True,
                width=0.6  # Narrower width for better visual distinction when overlaid
            ))
            
            # Gold bar showing net total (dividends minus loss, positive value, appears above axis)
            if (df_net_positive['dividends'] > 0).any():
                fig.add_trace(go.Bar(
                    name='Dividends (LTM) - offset loss',
                    x=df_net_positive['ticker'],
                    y=df_net_positive['total_pnl'],  # Net total after offsetting loss - shows actual profit
                    marker_color='#f59e0b',
                    customdata=df_net_positive[[pnl_col, 'dividends']],  # Include both loss and dividends for hover
                    hovertemplate='<b>%{x}</b><br>Unrealized P&L: $%{customdata[0]:,.2f}<br>Dividends: $%{customdata[1]:,.2f}<br>Total P&L: $%{y:,.2f}<extra></extra>',
                    showlegend=True,
                    width=0.6  # Narrower width for better visual distinction when overlaid
                ))
    
    # For NEGATIVE TOTAL P&L: Show single red bar
    if not df_negative_total.empty:
        fig.add_trace(go.Bar(
            name='Total P&L (loss)',
            x=df_negative_total['ticker'],
            y=df_negative_total['total_pnl'],
            marker_color='#ef4444',
            customdata=df_negative_total[[pnl_col, 'dividends']],
            hovertemplate='<b>%{x}</b><br>Unrealized P&L: $%{customdata[0]:,.2f}<br>Dividends: $%{customdata[1]:,.2f}<br>Total: $%{y:,.2f}<extra></extra>',
            showlegend=True
        ))
    
    # Add text labels showing total P&L
    for _, row in df.iterrows():
        # For positions with negative unrealized but positive total, show label at top of dividend bar
        if row['total_pnl'] >= 0 and row[pnl_col] < 0:
            # Label goes at top of dividend bar (above axis)
            label_y = row['dividends']
            yshift = 10
        else:
            # For other positions, label at top/bottom of total bar
            label_y = row['total_pnl']
            yshift = 10 if row['total_pnl'] >= 0 else -15
        
        fig.add_annotation(
            x=row['ticker'],
            y=label_y,
            text=f"${row['total_pnl']:,.2f}",
            showarrow=False,
            yshift=yshift,
            font=dict(size=10, color='#374151')
        )
    
    title = "P&L by Position"
    if fund_name:
        title += f" - {fund_name}"
    
    # Use 'overlay' mode to allow bars at the same x position
    # For loss+dividend positions: red bar (negative) appears below axis, gold bar (positive) appears above axis
    # Both bars align vertically at the same x position (ticker)
    # For positive unrealized positions: green and gold bars will overlap (acceptable trade-off)
    fig.update_layout(
        title=title,
        xaxis_title="Ticker",
        yaxis_title=f"P&L ({display_currency})",
        template='plotly_white',
        height=500,
        barmode='overlay',  # Overlay mode allows negative/positive bars at same x position on opposite sides of axis
        xaxis={
            'tickangle': -45,
            'categoryorder': 'array',
            'categoryarray': df['ticker'].tolist()  # Explicitly set order based on sorted df
        },
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    
    return fig


def create_currency_exposure_chart(positions_df: pd.DataFrame, fund_name: Optional[str] = None) -> go.Figure:
    """Create a pie chart showing USD vs CAD stock holdings exposure"""
    if positions_df.empty or 'currency' not in positions_df.columns or 'market_value' not in positions_df.columns:
        fig = go.Figure()
        fig.add_annotation(
            text="No currency data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # Clean currency column: filter NaN, None, empty strings, and string 'nan'
    # Make a copy to avoid modifying the original dataframe
    df = positions_df.copy()
    
    # Convert currency column to string and clean invalid values
    import logging
    logger = logging.getLogger(__name__)
    
    # Check for missing currencies
    missing_currency_mask = df['currency'].isna()
    if missing_currency_mask.any():
        invalid_count = missing_currency_mask.sum()
        invalid_tickers = df.loc[missing_currency_mask, 'ticker'].tolist() if 'ticker' in df.columns else ['unknown']
        logger.warning(f"[Currency Chart] Found {invalid_count} positions with missing currency (tickers: {invalid_tickers[:10]}...). Defaulting to USD.")
        df.loc[missing_currency_mask, 'currency'] = 'USD'
    
    df['currency'] = df['currency'].astype(str).str.strip().str.upper()
    
    # Replace empty strings and 'NAN' with USD (default)
    invalid_currencies = ['', 'NAN', 'NONE', 'NULL']
    invalid_mask = df['currency'].isin(invalid_currencies)
    
    # Log warning if invalid currencies were found
    if invalid_mask.any():
        invalid_count = invalid_mask.sum()
        invalid_tickers = df.loc[invalid_mask, 'ticker'].tolist() if 'ticker' in df.columns else ['unknown']
        logger.warning(f"[Currency Chart] Found {invalid_count} positions with invalid currency values (tickers: {invalid_tickers[:10]}...). Defaulting to USD.")
    
    df.loc[invalid_mask, 'currency'] = 'USD'
    
    # Group by currency and sum market values
    currency_totals = df.groupby('currency')['market_value'].sum().reset_index()
    currency_totals = currency_totals.sort_values('market_value', ascending=False)
    
    # Calculate percentages
    total_value = currency_totals['market_value'].sum()
    currency_totals['percentage'] = (currency_totals['market_value'] / total_value * 100).round(1)
    
    # Color scheme: Blue for USD, Red for CAD
    colors = []
    for curr in currency_totals['currency']:
        if curr == 'USD':
            colors.append('#3b82f6')  # Blue
        elif curr == 'CAD':
            colors.append('#ef4444')  # Red
        else:
            colors.append('#9ca3af')  # Gray for others
    
    fig = go.Figure()
    
    fig.add_trace(go.Pie(
        labels=currency_totals['currency'],
        values=currency_totals['market_value'],
        marker=dict(colors=colors),
        textinfo='label+percent',
        hovertemplate='<b>%{label}</b><br>Value: $%{value:,.2f}<br>%{percent}<extra></extra>'
    ))
    
    title = "Currency Exposure (Stock Holdings)"
    if fund_name:
        title += f" - {fund_name}"
    
    fig.update_layout(
        title=title,
        template='plotly_white',
        height=400,
        showlegend=True
    )
    
    return fig


def create_sector_allocation_chart(positions_df: pd.DataFrame, fund_name: Optional[str] = None, display_currency: Optional[str] = None) -> go.Figure:
    """Create a pie chart showing sector allocation of portfolio holdings
    
    Args:
        positions_df: DataFrame with columns: ticker, market_value, currency, sector (optional)
        fund_name: Optional fund name for title
        display_currency: Currency to convert all values to (e.g., 'CAD', 'USD')
    """
    if positions_df.empty or 'ticker' not in positions_df.columns or 'market_value' not in positions_df.columns:
        fig = go.Figure()
        fig.add_annotation(
            text="No position data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # Get display currency if not provided
    if display_currency is None:
        try:
            from streamlit_utils import get_user_display_currency
            display_currency = get_user_display_currency()
        except ImportError:
            display_currency = 'CAD'
    
    # Fetch exchange rates if we have currency column
    import logging
    logger = logging.getLogger(__name__)
    
    rate_map = {}
    if 'currency' in positions_df.columns:
        try:
            from streamlit_utils import fetch_latest_rates_bulk
            # Check for missing currencies and log them
            missing_currency_mask = positions_df['currency'].isna()
            if missing_currency_mask.any():
                missing_tickers = positions_df.loc[missing_currency_mask, 'ticker'].tolist()
                logger.warning(f"[Sector Chart] Found {missing_currency_mask.sum()} positions with missing currency (tickers: {missing_tickers[:10]}...). These will use 1.0 conversion rate.")
            
            # Get unique currencies, excluding NaN
            all_currencies = positions_df['currency'].dropna().astype(str).str.upper().unique().tolist()
            if all_currencies:
                rate_map = fetch_latest_rates_bulk(all_currencies, display_currency)
                logger.info(f"[Sector Chart] Fetched exchange rates for {len(rate_map)} currencies")
            else:
                logger.warning(f"[Sector Chart] No valid currencies found in positions_df, skipping currency conversion")
        except Exception as e:
            logger.error(f"[Sector Chart] Could not fetch exchange rates for sector allocation: {e}", exc_info=True)
    
    def get_rate(curr):
        if not curr or pd.isna(curr):
            logger.warning(f"[Sector Chart] Missing currency value, using 1.0 (no conversion)")
            return 1.0
        rate = rate_map.get(str(curr).upper(), 1.0)
        if rate == 1.0 and str(curr).upper() != display_currency.upper():
            logger.warning(f"[Sector Chart] Exchange rate not found for {curr}->{display_currency}, using 1.0 (no conversion)")
        return rate
    
    # Use sector data from database if available, otherwise fetch from yfinance
    # Check for both flat 'sector' column and nested 'securities' dict
    has_sector_column = 'sector' in positions_df.columns
    has_securities_column = 'securities' in positions_df.columns
    
    import logging
    logger = logging.getLogger(__name__)
    logger.debug(f"[Sector Chart] has_sector_column={has_sector_column}, has_securities_column={has_securities_column}")
    logger.debug(f"[Sector Chart] DataFrame columns: {list(positions_df.columns)}")
    if not positions_df.empty:
        logger.debug(f"[Sector Chart] Sample row: {positions_df.iloc[0].to_dict()}")
    
    sector_data = []
    for idx, row in positions_df.iterrows():
        ticker = row['ticker']
        raw_market_value = row['market_value']
        market_value = float(raw_market_value or 0)
        
        # Log first few rows to debug
        if idx < 5:
            logger.info(f"[Sector Chart] Row {idx}: ticker={ticker}, raw_market_value={raw_market_value} (type={type(raw_market_value)}), market_value={market_value}")
        
        # Convert market_value to display currency
        if 'currency' in row and rate_map:
            currency = row.get('currency')
            if not currency or pd.isna(currency):
                logger.warning(f"[Sector Chart] Missing currency for {ticker}, skipping currency conversion")
            else:
                rate = get_rate(currency)
                market_value = market_value * rate
        
        logger.debug(f"[Sector Chart] {ticker}: market_value={market_value}, currency={row.get('currency', 'N/A')}")
        
        # First, try to use sector from database (faster and more reliable)
        # Handle nested securities dict (from Supabase join)
        sector = None
        if has_securities_column and isinstance(row.get('securities'), dict):
            sector = row['securities'].get('sector')
            logger.debug(f"[Sector Chart] {ticker}: sector from nested securities={sector}")
        elif has_sector_column:
            sector = row.get('sector')
            logger.debug(f"[Sector Chart] {ticker}: sector from flat column={sector}")
        
        # Check if sector is valid (not None, not empty string, not NaN)
        if pd.isna(sector) or sector == '' or sector is None:
            sector = None
        
        # If sector not in database or is null, try fetching from yfinance
        if not sector:
            logger.info(f"[Sector Chart] Sector not found in database for {ticker}, fetching from yfinance")
            try:
                import yfinance as yf
                stock = yf.Ticker(ticker)
                info = stock.info
                
                # Get sector (will be None for ETFs or if data unavailable)
                sector = info.get('sector', 'Unknown')
                if not sector or sector == '':
                    logger.info(f"[Sector Chart] yfinance returned empty sector for {ticker}, categorizing as Other/ETF")
                    sector = 'Other/ETF'
                else:
                    logger.info(f"[Sector Chart] Retrieved sector '{sector}' from yfinance for {ticker}")
            except Exception as e:
                # If we can't fetch data, categorize as Unknown
                logger.warning(f"[Sector Chart] Failed to fetch sector from yfinance for {ticker}: {e}, categorizing as Unknown")
                sector = 'Unknown'
        
        sector_data.append({
            'ticker': ticker,
            'sector': sector,
            'market_value': market_value
        })
    
    if not sector_data:
        fig = go.Figure()
        fig.add_annotation(
            text="Unable to fetch sector data",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # Aggregate by sector
    sector_df = pd.DataFrame(sector_data)
    
    # Log before aggregation to see raw data
    logger.info(f"[Sector Chart] Total positions processed: {len(sector_df)}")
    logger.info(f"[Sector Chart] Sample sector_data (first 5): {sector_data[:5]}")
    logger.info(f"[Sector Chart] Market value sum before aggregation: {sector_df['market_value'].sum()}")
    logger.info(f"[Sector Chart] Market value stats: min={sector_df['market_value'].min()}, max={sector_df['market_value'].max()}, mean={sector_df['market_value'].mean()}")
    
    sector_totals = sector_df.groupby('sector')['market_value'].sum().reset_index()
    sector_totals = sector_totals.sort_values('market_value', ascending=False)
    
    logger.info(f"[Sector Chart] Aggregated {len(sector_totals)} sectors: {sector_totals.to_dict('records')}")
    logger.info(f"[Sector Chart] Total market value after aggregation: {sector_totals['market_value'].sum()}")
    
    # Color palette for sectors
    sector_colors = {
        'Technology': '#3b82f6',
        'Financial Services': '#10b981',
        'Healthcare': '#ef4444',
        'Consumer Cyclical': '#f59e0b',
        'Industrials': '#8b5cf6',
        'Energy': '#f97316',
        'Basic Materials': '#06b6d4',
        'Consumer Defensive': '#84cc16',
        'Real Estate': '#ec4899',
        'Communication Services': '#6366f1',
        'Utilities': '#14b8a6',
        'Other/ETF': '#9ca3af',
        'Unknown': '#6b7280'
    }
    
    colors = [sector_colors.get(sector, '#9ca3af') for sector in sector_totals['sector']]
    
    fig = go.Figure()
    
    # Convert to lists and ensure numeric types
    labels_list = sector_totals['sector'].tolist()
    values_list = sector_totals['market_value'].tolist()
    
    # Log the actual values being passed to Plotly
    logger.info(f"[Sector Chart] Plotly input - labels: {labels_list}")
    logger.info(f"[Sector Chart] Plotly input - values: {values_list}")
    logger.info(f"[Sector Chart] Values type: {type(values_list[0]) if values_list else 'empty'}")
    logger.info(f"[Sector Chart] Values sum: {sum(values_list)}")
    
    fig.add_trace(go.Pie(
        labels=labels_list,
        values=values_list,
        marker=dict(colors=colors),
        textinfo='label+percent',
        hovertemplate='<b>%{label}</b><br>Value: $%{value:,.2f}<br>%{percent}<extra></extra>'
    ))
    
    title = "Sector Allocation"
    if fund_name:
        title += f" - {fund_name}"
    
    fig.update_layout(
        title=title,
        template='plotly_white',
        height=500,
        showlegend=True,
        margin=dict(l=20, r=20, t=50, b=20),  # Center the pie chart with equal left/right margins
        autosize=True
    )
    
    return fig


def create_trades_timeline_chart(trades_df: pd.DataFrame, fund_name: Optional[str] = None,
                                  show_weekend_shading: bool = True, display_currency: Optional[str] = None) -> go.Figure:
    """Create a timeline chart showing trades over time"""
    # Get display currency
    if display_currency is None:
        try:
            from streamlit_utils import get_user_display_currency
            display_currency = get_user_display_currency()
        except ImportError:
            display_currency = 'CAD'
    required_cols = ['date', 'action', 'shares', 'price']
    if trades_df.empty or not all(col in trades_df.columns for col in required_cols):
        fig = go.Figure()
        fig.add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # Group by date and type
    df = trades_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    
    # Adjust dates to market close time (13:00 PST) for proper alignment with weekend shading
    df = _adjust_to_market_close(df, 'date')
    
    df['trade_value'] = df['shares'] * df['price']
    
    # Separate buys and sells
    buys = df[df['action'].str.upper() == 'BUY'].groupby('date')['trade_value'].sum()
    sells = df[df['action'].str.upper() == 'SELL'].groupby('date')['trade_value'].sum()
    
    fig = go.Figure()
    
    if not buys.empty:
        fig.add_trace(go.Scatter(
            x=buys.index,
            y=buys.values,
            mode='markers',
            name='Buys',
            marker=dict(color='#10b981', size=10, symbol='triangle-up')
        ))
    
    if not sells.empty:
        fig.add_trace(go.Scatter(
            x=sells.index,
            y=sells.values,
            mode='markers',
            name='Sells',
            marker=dict(color='#ef4444', size=10, symbol='triangle-down')
        ))
    
    # Add weekend shading
    if show_weekend_shading and len(df) > 0:
        _add_weekend_shading(fig, df['date'].min(), df['date'].max())
    
    title = "Trades Timeline"
    if fund_name:
        title += f" - {fund_name}"
    
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title=f"Trade Value ({display_currency})",
        hovermode='x unified',
        template='plotly_white',
        height=400
    )
    
    return fig


@log_execution_time()
def create_ticker_price_chart(
    ticker_df: pd.DataFrame,
    ticker_symbol: str,
    show_benchmarks: Optional[List[str]] = None,
    show_weekend_shading: bool = True,
    use_solid_lines: bool = False,
    theme: str = 'system',
    market: str = 'us',
    congress_trades: Optional[List[Dict[str, Any]]] = None
) -> go.Figure:
    """Create a price history chart for an individual ticker with benchmark comparisons.
    
    Args:
        ticker_df: DataFrame with columns: date, price, normalized (baseline 100)
        ticker_symbol: Ticker symbol for display
        show_benchmarks: List of benchmark keys to display (e.g., ['sp500', 'qqq'])
        show_weekend_shading: If True, adds gray shading for weekends
        use_solid_lines: If True, uses solid lines for benchmarks instead of dashed
        theme: User theme preference ('dark', 'light', or 'system'). Defaults to 'system'.
              Use 'dark' for dark mode, 'light' for light mode, or 'system' to default to light.
        congress_trades: Optional list of congress trade dictionaries to display as markers
        
    Returns:
        Plotly Figure object
    """
    fig = go.Figure()
    
    if ticker_df.empty or 'date' not in ticker_df.columns or 'normalized' not in ticker_df.columns:
        fig.add_annotation(
            text="No price data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    # Sort by date
    df = ticker_df.sort_values('date').copy()
    df['date'] = pd.to_datetime(df['date'])
    
    # Filter out non-trading days
    df = _filter_trading_days(df, 'date', market=market)

    # Adjust dates to market close time (13:00 PST) for proper alignment with weekend shading
    df = _adjust_to_market_close(df, 'date')
    
    # Calculate return percentage for label (from baseline 100)
    if len(df) > 1:
        last_value = df['normalized'].iloc[-1]
        ticker_return = last_value - 100  # Return from baseline
        label_suffix = f" ({ticker_return:+.2f}%)"
    else:
        label_suffix = ""
    
    # Add ticker trace
    fig.add_trace(go.Scatter(
        x=df['date'],
        y=df['normalized'],
        mode='lines+markers',
        name=f'{ticker_symbol}{label_suffix}',
        line=dict(color='#1f77b4', width=3),
        marker=dict(size=4),
        hovertemplate=f'{ticker_symbol}<br>%{{x|%Y-%m-%d}}<br>%{{y:,.2f}}<extra></extra>'
    ))
    
    # Add benchmarks if requested
    if show_benchmarks and len(df) > 0:
        import time
        import logging
        logger = logging.getLogger(__name__)
        benchmark_start = time.time()
        
        start_date = df['date'].min()
        end_date = df['date'].max()
        
        # Normalize to date-only (midnight) for comparison with benchmark data
        start_date_normalized = pd.Timestamp(start_date).normalize()
        end_date_normalized = pd.Timestamp(end_date).normalize() + timedelta(days=1)
        
        for bench_key in show_benchmarks:
            if bench_key not in BENCHMARK_CONFIG:
                continue
            
            bench_t0 = time.time()
            config = BENCHMARK_CONFIG[bench_key]
            bench_data = _fetch_benchmark_data(config['ticker'], start_date, end_date)
            bench_fetch_time = time.time() - bench_t0
            logger.info(f"⏱️ create_ticker_price_chart - Fetch benchmark {bench_key}: {bench_fetch_time:.2f}s")
            
            if bench_data is not None and not bench_data.empty:
                # Normalize bench_data dates to midnight for comparison
                bench_data['Date'] = pd.to_datetime(bench_data['Date'])
                if bench_data['Date'].dt.tz is not None:
                    bench_data['Date'] = bench_data['Date'].dt.tz_convert(None)
                bench_data['Date'] = bench_data['Date'].dt.normalize()
                
                # Filter out any NaT values before date range filtering
                bench_data = bench_data[bench_data['Date'].notna()].copy()
                
                # Filter to ticker date range
                start_dt64 = start_date_normalized.to_datetime64()
                end_dt64 = end_date_normalized.to_datetime64()
                bench_data = bench_data[
                    (bench_data['Date'] >= start_dt64) & 
                    (bench_data['Date'] < end_dt64)
                ]
                
                if not bench_data.empty:
                    # Calculate benchmark return for label (from baseline 100)
                    bench_last = bench_data['normalized'].iloc[-1]
                    bench_return = bench_last - 100  # Return from baseline
                    
                    # Use solid or dashed lines based on preference
                    line_style = {} if use_solid_lines else {'dash': 'dash'}
                    
                    # S&P 500 visible by default, others hidden in legend
                    visibility = True if bench_key == 'sp500' else 'legendonly'
                    
                    fig.add_trace(go.Scatter(
                        x=bench_data['Date'],
                        y=bench_data['normalized'],
                        mode='lines',
                        name=f"{config['name']} ({bench_return:+.2f}%)",
                        line=dict(color=config['color'], width=3, **line_style),
                        opacity=0.8,
                        visible=visibility,
                        hovertemplate='%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>'
                    ))
        
        benchmark_total_time = time.time() - benchmark_start
        logger.info(f"⏱️ create_ticker_price_chart - All benchmarks: {benchmark_total_time:.2f}s")
    
    # Add congress trades markers if provided
    if congress_trades and len(df) > 0:
        # Create date lookup for price values
        date_to_price = dict(zip(df['date'], df['normalized']))
        
        for trade in congress_trades:
            trade_date_str = trade.get('transaction_date')
            if not trade_date_str:
                continue
            
            try:
                # Parse and align trade date
                trade_date = pd.to_datetime(trade_date_str).normalize()
                
                # Find closest price date (in case trade date doesn't match exactly)
                # Convert df dates to normalized for comparison
                def date_diff(date_val):
                    date_normalized = pd.to_datetime(date_val).normalize()
                    return abs((date_normalized - trade_date).total_seconds())
                
                closest_date = min(df['date'], key=date_diff)
                closest_date_normalized = pd.to_datetime(closest_date).normalize()
                days_diff = abs((closest_date_normalized - trade_date).days)
                if days_diff > 7:  # Skip if more than 7 days away
                    continue
                
                # Get price at that date
                y_value = date_to_price.get(closest_date, df['normalized'].iloc[-1])
                
                trade_type = trade.get('type', 'Unknown')
                politician = trade.get('politician', 'Unknown')
                amount = trade.get('amount', 'N/A')
                chamber = trade.get('chamber', '')
                
                # Color based on trade type
                if trade_type == 'Purchase':
                    color = '#2ca02c'  # Green
                    symbol = 'triangle-up'
                elif trade_type == 'Sale':
                    color = '#d62728'  # Red
                    symbol = 'triangle-down'
                else:
                    color = '#9467bd'  # Purple
                    symbol = 'diamond'
                
                # Add scatter marker
                fig.add_trace(go.Scatter(
                    x=[closest_date],
                    y=[y_value],
                    mode='markers',
                    name=f"Congress {trade_type}",
                    marker=dict(
                        size=12,
                        color=color,
                        symbol=symbol,
                        line=dict(width=2, color='white')
                    ),
                    hovertemplate=f'<b>Congress Trade</b><br>' +
                                f'Date: {trade_date_str}<br>' +
                                f'Type: {trade_type}<br>' +
                                f'Politician: {politician}<br>' +
                                f'Chamber: {chamber}<br>' +
                                f'Amount: {amount}<extra></extra>',
                    showlegend=False,  # Don't clutter legend, just show on hover
                    legendgroup='congress_trades'
                ))
            except Exception as e:
                # Skip trades with invalid dates
                continue
    
    # Get theme configuration (ensure theme is never None)
    theme = theme or 'system'
    theme_config = get_chart_theme_config(theme)
    
    # Add weekend and holiday shading
    if show_weekend_shading and len(df) > 1:
        start_date = df['date'].min()
        end_date = df['date'].max()

        # Weekend shading
        _add_weekend_shading(fig, start_date, end_date,
                            weekend_color=theme_config['weekend_shading_color'])

        # Holiday shading
        _add_holiday_shading(fig, start_date, end_date, market=market,
                            holiday_color=theme_config['weekend_shading_color'])
    
    # Add baseline reference line with theme-aware color
    fig.add_hline(
        y=100,
        line_dash="dash",
        line_color=theme_config['baseline_line_color'],
        opacity=0.5,
        annotation_text="Baseline (0%)",
        annotation_position="right"
    )
    
    # Title
    title = f"{ticker_symbol} Price History vs Benchmarks"
    
    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Performance Index (Baseline 100)",
        hovermode='x unified',
        template=theme_config['template'],
        height=500,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor=theme_config['legend_bg_color']
        )
    )
    
    return fig


def downsample_price_data(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Downsample price data to maintain ~90 data points regardless of time range.
    
    Args:
        df: DataFrame with columns: date, price, normalized
        days: Number of days in the time range
        
    Returns:
        Downsampled DataFrame with approximately 90 data points
    """
    if df.empty or len(df) <= 90:
        return df
    
    # Calculate interval to get ~90 points
    if days <= 90:
        interval = 1  # Daily for 3 months
    elif days <= 180:
        interval = 2  # Every 2 days for 6 months
    elif days <= 365:
        interval = 4  # Every 4 days for 1 year
    elif days <= 730:
        interval = 8  # Every 8 days for 2 years
    else:
        interval = 20  # Every 20 days for 5 years
    
    # Sort by date and take every Nth row
    df_sorted = df.sort_values('date').reset_index(drop=True)
    downsampled = df_sorted.iloc[::interval].copy()
    
    # Always include the last row to show current price
    if len(downsampled) > 0 and len(df_sorted) > 0:
        last_original_date = df_sorted.iloc[-1]['date']
        last_downsampled_date = downsampled.iloc[-1]['date']
        if last_downsampled_date != last_original_date:
            downsampled = pd.concat([downsampled, df_sorted.iloc[[-1]]], ignore_index=True)
    
    return downsampled.sort_values('date').reset_index(drop=True)


def get_available_benchmarks() -> Dict[str, str]:
    """Return available benchmark options for UI."""
    return {key: config['name'] for key, config in BENCHMARK_CONFIG.items()}
def create_individual_holdings_chart(
    holdings_df: pd.DataFrame,
    fund_name: Optional[str] = None,
    show_benchmarks: Optional[List[str]] = None,
    show_weekend_shading: bool = True,
    use_solid_lines: bool = False
) -> go.Figure:
    """Create a chart showing individual stock performance vs benchmarks.
    
    Args:
        holdings_df: DataFrame with columns: ticker, date, performance_index
        fund_name: Optional fund name for title
        show_benchmarks: List of benchmark keys to display
        show_weekend_shading: Add weekend shading
        
    Returns:
        Plotly Figure object
    """
    fig = go.Figure()
    
    if holdings_df.empty:
        fig.add_annotation(
            text="No holdings data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        return fig
    
    # Get date range
    start_date = pd.to_datetime(holdings_df['date']).min()
    end_date = pd.to_datetime(holdings_df['date']).max()
    
    # Color palette for stocks
    stock_colors = [
        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
        '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
        '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5'
    ]
    
    # Plot each stock
    tickers = holdings_df['ticker'].unique()
    for idx, ticker in enumerate(sorted(tickers)):
        ticker_data = holdings_df[holdings_df['ticker'] == ticker].copy()
        ticker_data = ticker_data.sort_values('date')
        ticker_data['date'] = pd.to_datetime(ticker_data['date'])
        
        # Adjust dates to market close time (13:00 PST) for proper alignment with weekend shading
        ticker_data = _adjust_to_market_close(ticker_data, 'date')
        
        if len(ticker_data) < 2:
            continue  # Skip if insufficient data
        
        # Calculate return for label
        final_perf = ticker_data['performance_index'].iloc[-1]
        stock_return = final_perf - 100
        
        color = stock_colors[idx % len(stock_colors)]
        
        fig.add_trace(go.Scatter(
            x=ticker_data['date'],
            y=ticker_data['performance_index'],
            mode='lines',
            name=f"{ticker} ({stock_return:+.2f}%)",
            line=dict(color=color, width=1.5),
            hovertemplate=f'{ticker}<br>%{{x|%Y-%m-%d}}<br>%{{y:,.2f}}<extra></extra>'
        ))
    
    # Add benchmarks
    if show_benchmarks:
        # Normalize to date-only (midnight) for comparison with benchmark data
        # Benchmark data from Yahoo Finance uses midnight timestamps, while portfolio
        # dates are at 13:00 (market close). Normalizing ensures same-day data is included.
        start_date_normalized = pd.Timestamp(start_date).normalize()  # Set to 00:00:00
        end_date_normalized = pd.Timestamp(end_date).normalize() + timedelta(days=1)  # Include full end date
        
        for bench_key in show_benchmarks:
            if bench_key not in BENCHMARK_CONFIG:
                continue
                
            config = BENCHMARK_CONFIG[bench_key]
            bench_data = _fetch_benchmark_data(config['ticker'], start_date, end_date)
            
            if bench_data is not None and not bench_data.empty:
                # Normalize bench_data dates to midnight for comparison
                # Handle both timezone-aware and timezone-naive datetimes safely
                bench_data['Date'] = pd.to_datetime(bench_data['Date'])
                # Remove timezone if present, then normalize to midnight
                if bench_data['Date'].dt.tz is not None:
                    bench_data['Date'] = bench_data['Date'].dt.tz_convert(None)
                bench_data['Date'] = bench_data['Date'].dt.normalize()
                
                # Filter out any NaT values before date range filtering
                bench_data = bench_data[bench_data['Date'].notna()].copy()
                
                # Filter to portfolio date range - compare dates, not timestamps
                # Convert Timestamp to datetime64 for type compatibility with Series
                start_dt64 = start_date_normalized.to_datetime64()
                end_dt64 = end_date_normalized.to_datetime64()
                bench_data = bench_data[
                    (bench_data['Date'] >= start_dt64) & 
                    (bench_data['Date'] < end_dt64)
                ]
                
                if not bench_data.empty:
                    bench_return = bench_data['normalized'].iloc[-1] - 100
                    
                    # Use solid or dashed lines based on preference
                    line_style = {} if use_solid_lines else {'dash': 'dash'}
                    
                    # S&P 500 visible by default, others hidden in legend
                    visibility = True if bench_key == 'sp500' else 'legendonly'
                    
                    fig.add_trace(go.Scatter(
                        x=bench_data['Date'],
                        y=bench_data['normalized'],
                        mode='lines',
                        name=f"{config['name']} ({bench_return:+.2f}%)",
                        line=dict(color=config['color'], width=3, **line_style),
                        opacity=0.8,
                        visible=visibility,
                        hovertemplate='%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>'
                    ))
    
    # Add weekend shading
    if show_weekend_shading:
        _add_weekend_shading(fig, start_date, end_date)
    
    # Add baseline reference
    fig.add_hline(
        y=100,
        line_dash="dash",
        line_color="gray",
        opacity=0.5,
        annotation_text="Baseline (0%)",
        annotation_position="right"
    )
    
    # Layout
    title = f"Individual Stock Performance"
    if fund_name:
        title += f" - {fund_name}"
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center'),
        xaxis_title="Date",
        yaxis_title="Performance Index (Baseline 100)",
        hovermode='x unified',
        height=600,
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255, 255, 255, 0.8)"
        )
    )
    
    return fig


def create_investor_allocation_chart(investors_df: pd.DataFrame, fund_name: Optional[str] = None) -> go.Figure:
    """Create a pie chart showing investor allocation by contribution amount
    
    Args:
        investors_df: DataFrame with columns: contributor_display, net_contribution, ownership_pct
                     contributor_display is already privacy-masked (Investor 1, Investor 2, etc.)
        fund_name: Optional fund name for title
    
    Returns:
        Plotly Figure object
    """
    if investors_df.empty or 'contributor_display' not in investors_df.columns or 'net_contribution' not in investors_df.columns:
        fig = go.Figure()
        fig.add_annotation(
            text="No investor data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
        return fig
    
    # Color palette for investors (varied colors)
    investor_colors = [
        '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
        '#06b6d4', '#84cc16', '#ec4899', '#6366f1', '#14b8a6',
        '#f97316', '#a855f7', '#22c55e', '#eab308', '#f43f5e'
    ]
    
    # Assign colors cycling through palette
    colors = [investor_colors[i % len(investor_colors)] for i in range(len(investors_df))]
    
    fig = go.Figure()
    
    fig.add_trace(go.Pie(
        labels=investors_df['contributor_display'],
        values=investors_df['ownership_pct'],  # Use ownership % (NAV-based), not dollar amounts
        marker=dict(colors=colors),
        textinfo='label+percent',
        hovertemplate='<b>%{label}</b><br>Investment: $%{value:,.2f}<br>%{percent}<extra></extra>'
    ))
    
    title = "Investor Allocation"
    if fund_name:
        title += f" - {fund_name}"
    
    fig.update_layout(
        title=title,
        template='plotly_white',
        height=500,
        showlegend=True
    )
    
    return fig
