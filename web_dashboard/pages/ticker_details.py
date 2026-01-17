#!/usr/bin/env python3
"""
Ticker Details Page
===================

Comprehensive ticker information page that aggregates data from all databases
and provides external links to financial websites.
"""

import streamlit as st
import sys
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from auth_utils import is_authenticated, refresh_token_if_needed, is_admin, get_user_token, redirect_to_login
from navigation import render_navigation
from postgres_client import PostgresClient
from supabase_client import SupabaseClient
from ticker_utils import get_ticker_info, get_ticker_external_links, get_ticker_price_history
from chart_utils import create_ticker_price_chart

# Import from utils.db_utils - handle import error gracefully
try:
    from utils.db_utils import get_all_unique_tickers
except (ImportError, ModuleNotFoundError) as e:
    # Fallback: try importing directly if utils path doesn't work
    try:
        import importlib.util
        # Ensure parent_dir is in sys.path for db_utils dependencies
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))
        db_utils_path = parent_dir / "utils" / "db_utils.py"
        spec = importlib.util.spec_from_file_location("utils.db_utils", db_utils_path)
        db_utils = importlib.util.module_from_spec(spec)
        # Set __file__ and __package__ to help with relative imports
        db_utils.__file__ = str(db_utils_path)
        db_utils.__package__ = "utils"
        spec.loader.exec_module(db_utils)
        get_all_unique_tickers = db_utils.get_all_unique_tickers
    except Exception as import_error:
        logger.error(f"Failed to import get_all_unique_tickers: {e}, {import_error}", exc_info=True)
        # Define a fallback function
        def get_all_unique_tickers() -> list[str]:
            logger.warning("Using fallback get_all_unique_tickers - returning empty list")
            return []

# Page configuration
st.set_page_config(
    page_title="Ticker Details",
    page_icon="📊",
    layout="wide"
)

# Redirect to Flask version if available AND enabled
try:
    # CRITICAL: Restore session from cookies before checking preferences
    try:
        from auth_utils import ensure_session_restored
        ensure_session_restored()
    except Exception:
        pass

    from shared_navigation import is_page_migrated, get_page_url
    from user_preferences import get_user_preference
    
    # Only redirect if V2 is enabled AND page is migrated
    is_v2_enabled = get_user_preference('v2_enabled', default=False)
    
    if is_v2_enabled and is_page_migrated('ticker_details'):
        ticker = st.query_params.get("ticker", "")
        if ticker:
            url = f"{get_page_url('ticker_details')}?ticker={ticker}"
        else:
            url = get_page_url('ticker_details')
        st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)
        st.write("Redirecting to new ticker details page...")
        st.stop()
except (ImportError, Exception):
    pass  # Continue with Streamlit version if shared_navigation not available or error

# Check authentication
if not is_authenticated():
    redirect_to_login("pages/ticker_details.py")

# Refresh token if needed
if not refresh_token_if_needed():
    from auth_utils import logout_user
    logout_user(return_to="pages/ticker_details.py")
    st.stop()

# Render navigation
render_navigation(show_ai_assistant=True, show_settings=True)

# Initialize clients
@st.cache_resource
def get_postgres_client():
    """Get Postgres client instance"""
    try:
        return PostgresClient()
    except Exception as e:
        logger.error(f"Failed to initialize PostgresClient: {e}")
        return None

@st.cache_resource
def get_supabase_client():
    """Get Supabase client instance with role-based access"""
    try:
        # Admins use service_role to see all funds
        if is_admin():
            return SupabaseClient(use_service_role=True)
        
        # Regular users use their token to respect RLS
        user_token = get_user_token()
        if user_token:
            return SupabaseClient(user_token=user_token)
        else:
            logger.error("No user token available for non-admin user")
            return None
    except Exception as e:
        logger.error(f"Failed to initialize SupabaseClient: {e}")
        return None

postgres_client = get_postgres_client()
supabase_client = get_supabase_client()

# Get ticker from session state (set by navigation from other pages) or query parameters
ticker_from_session = st.session_state.get('selected_ticker', '')
query_params = st.query_params
ticker_from_query = query_params.get("ticker", "")

# Prefer session state, then query params
ticker = ticker_from_session or ticker_from_query

# Clear session state ticker after reading it
if ticker_from_session:
    st.session_state['selected_ticker'] = ''

# Get all available tickers for dropdown
all_tickers = get_all_unique_tickers()

# Ticker search box
col_search, col_spacer = st.columns([0.3, 0.7])
with col_search:
    search_ticker = st.selectbox(
        "Search Ticker",
        options=[""] + all_tickers,
        index=0 if not ticker else (all_tickers.index(ticker.upper()) + 1 if ticker.upper() in all_tickers else 0),
        placeholder="Select ticker symbol",
        key="ticker_search"
    )

# If user entered a new ticker, update query params
if search_ticker and search_ticker != ticker:
    st.query_params["ticker"] = search_ticker
    st.rerun()

# Use the ticker from query params or search
current_ticker = ticker.upper().strip() if ticker else search_ticker

if not current_ticker:
    st.title("📊 Ticker Details")
    st.info("Enter a ticker symbol above to view detailed information.")
    st.stop()

# Fetch ticker information
@st.cache_data(ttl=60)
def fetch_ticker_data(ticker_symbol: str):
    """Fetch ticker data with caching - ticker_symbol is part of cache key"""
    # Get clients inside the cached function
    pg_client = get_postgres_client()
    sb_client = get_supabase_client()
    return get_ticker_info(ticker_symbol, sb_client, pg_client)

# Check if clients are available
if not postgres_client and not supabase_client:
    st.error("⚠️ Unable to connect to databases. Please check your configuration.")
    st.stop()

# Helper function to format dates safely
def format_date_safe(date_val):
    """Safely format a date value that might be string or datetime"""
    if not date_val:
        return 'N/A'
    if isinstance(date_val, str):
        return date_val[:10]  # Return first 10 chars (YYYY-MM-DD)
    try:
        return date_val.strftime('%Y-%m-%d')  # Format datetime object
    except (AttributeError, ValueError):
        return str(date_val)[:10]

try:
    with st.spinner(f"Loading information for {current_ticker}..."):
        ticker_data = fetch_ticker_data(current_ticker)
except Exception as e:
    logger.error(f"Error fetching ticker data for {current_ticker}: {e}", exc_info=True)
    st.error(f"❌ Error loading ticker data: {str(e)}")
    st.info("Please try again or contact support if the problem persists.")
    st.stop()

# Header
st.title(f"📊 {current_ticker}")

# Basic Info Section
basic_info = ticker_data.get('basic_info')

# If no basic info, try fetching from yfinance
if not basic_info:
    try:
        import yfinance as yf
        with st.spinner(f"Looking up {current_ticker} from Yahoo Finance..."):
            ticker_obj = yf.Ticker(current_ticker)
            info = ticker_obj.info
            
            if info and info.get('symbol'):
                # Extract fields with multiple fallback attempts
                company_name = (
                    info.get('longName') or 
                    info.get('shortName') or 
                    info.get('displayName') or 
                    current_ticker
                )
                
                # Sector - try multiple fields
                sector = (
                    info.get('sector') or 
                    info.get('sectorDisp') or 
                    info.get('sectorKey')
                )
                
                # Industry - try multiple fields
                industry = (
                    info.get('industry') or 
                    info.get('industryDisp') or 
                    info.get('industryKey')
                )
                
                # Currency
                currency = info.get('currency') or info.get('financialCurrency') or 'USD'
                
                # Exchange
                exchange = (
                    info.get('exchange') or 
                    info.get('exchangeName') or 
                    info.get('fullExchangeName')
                )
                
                # Create basic_info structure from yfinance data
                basic_info = {
                    'ticker': current_ticker,
                    'company_name': company_name,
                    'sector': sector if sector else None,
                    'industry': industry if industry else None,
                    'currency': currency,
                    'exchange': exchange if exchange else None
                }
                
                # Save to database for future lookups
                if supabase_client:
                    try:
                        supabase_client.supabase.table("securities").insert(basic_info).execute()
                        st.success(f"✅ Saved {current_ticker} ({basic_info['company_name']}) to database")
                        logger.info(f"Saved ticker {current_ticker} to securities table from yfinance")
                    except Exception as insert_error:
                        # If insert fails (e.g., duplicate), just log it - we still have the data
                        logger.warning(f"Could not save {current_ticker} to database: {insert_error}")
                        st.info(f"ℹ️ Fetched {current_ticker} info from Yahoo Finance")
                else:
                    st.info(f"ℹ️ Fetched {current_ticker} info from Yahoo Finance. Database not available to save.")
            else:
                st.warning(f"⚠️ Could not find ticker information for {current_ticker}")
    except Exception as e:
        logger.warning(f"Error fetching from yfinance for {current_ticker}: {e}")
        st.warning(f"⚠️ Could not find ticker information for {current_ticker}")

if basic_info:
    # Check if we have incomplete data (None values for sector/industry)
    if (basic_info.get('sector') is None or basic_info.get('industry') is None):
        try:
            import yfinance as yf
            logger.info(f"Re-fetching {current_ticker} from yfinance due to incomplete data")
            
            ticker_obj = yf.Ticker(current_ticker)
            info = ticker_obj.info
            
            if info and info.get('symbol'):
                # Try to get missing fields
                sector = basic_info.get('sector') or info.get('sector') or info.get('sectorDisp') or info.get('sectorKey')
                industry = basic_info.get('industry') or info.get('industry') or info.get('industryDisp') or info.get('industryKey')
                
                # Update if we got new data
                if sector or industry:
                    basic_info['sector'] = sector
                    basic_info['industry'] = industry
                    
                    # Update database
                    if supabase_client:
                        try:
                            supabase_client.supabase.table("securities")\
                                .update({'sector': sector, 'industry': industry})\
                                .eq('ticker', current_ticker)\
                                .execute()
                            logger.info(f"Updated {current_ticker} with sector/industry from yfinance")
                        except Exception as update_error:
                            logger.warning(f"Could not update {current_ticker}: {update_error}")
        except Exception as e:
            logger.warning(f"Error re-fetching data for {current_ticker}: {e}")
    
    company_name = basic_info.get('company_name', 'N/A')
    sector = basic_info.get('sector') or 'N/A'
    industry = basic_info.get('industry') or 'N/A'
    currency = basic_info.get('currency', 'USD')
    exchange = basic_info.get('exchange', 'N/A')

    st.header(f"{company_name}")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Sector", sector)
    with col2:
        st.metric("Industry", industry)
    with col3:
        st.metric("Currency", currency)

    if exchange != 'N/A':
        st.caption(f"Exchange: {exchange}")
else:
    st.info(f"Basic information not found for {current_ticker} in database.")

# External Links Section
st.header("🔗 External Links")
external_links = get_ticker_external_links(
    current_ticker,
    exchange=basic_info.get('exchange') if basic_info else None
)

# Display links in columns
cols = st.columns(4)
link_items = list(external_links.items())
for i, (name, url) in enumerate(link_items):
    with cols[i % 4]:
        st.markdown(f"[{name}]({url})")

st.markdown("---")

# Portfolio Data Section
portfolio_data = ticker_data.get('portfolio_data')
if portfolio_data and (portfolio_data.get('has_positions') or portfolio_data.get('has_trades')):
    st.header("💼 Portfolio Data")

    # Current Positions
    if portfolio_data.get('has_positions'):
        positions = portfolio_data.get('positions', [])
        if positions:
            st.subheader("Current Positions")
            # Get latest position for each fund
            latest_positions = {}
            for pos in positions:
                fund = pos.get('fund', 'Unknown')
                if fund not in latest_positions:
                    latest_positions[fund] = pos
                else:
                    # Keep the most recent
                    if pos.get('date', '') > latest_positions[fund].get('date', ''):
                        latest_positions[fund] = pos

            pos_df = pd.DataFrame([
                {
                    'Fund': pos.get('fund', 'N/A'),
                    'Shares': f"{(pos.get('shares') or 0):,.2f}",
                    'Price': f"${(pos.get('price') or 0):.2f}",
                    'Cost Basis': f"${(pos.get('cost_basis') or 0):.2f}",
                    'P&L': f"${(pos.get('pnl') or 0):.2f}",
                    'Date': format_date_safe(pos.get('date'))
                }
                for pos in latest_positions.values()
            ])
            st.dataframe(pos_df, use_container_width=True, hide_index=True)

    # Trade History
    if portfolio_data.get('has_trades'):
        trades = portfolio_data.get('trades', [])
        if trades:
            st.subheader("Recent Trade History")
            trade_df = pd.DataFrame([
                {
                    'Date': format_date_safe(trade.get('date')),
                    'Action': trade.get('action', 'N/A'),
                    'Shares': f"{(trade.get('shares') or 0):,.2f}",
                    'Price': f"${(trade.get('price') or 0):.2f}",
                    'Fund': trade.get('fund', 'N/A'),
                    'Reason': trade.get('reason', 'N/A')[:50] if trade.get('reason') else 'N/A'
                }
                for trade in trades[:20]  # Show last 20 trades
            ])
            st.dataframe(trade_df, use_container_width=True, hide_index=True)
else:
    st.info(f"No portfolio data found for {current_ticker}.")

st.markdown("---")

# Price History Chart Section
st.header("📈 Price History")
try:
    # Chart controls (moved before data fetch so we can use selected range)
    col1, col2 = st.columns([3, 1])
    with col1:
        time_range = st.selectbox(
            "Time Range",
            options=['3m', '6m', '1y', '2y', '5y'],
            format_func=lambda x: {
                '3m': '3 Months',
                '6m': '6 Months', 
                '1y': '1 Year',
                '2y': '2 Years',
                '5y': '5 Years'
            }[x],
            index=0
        )
        
        # Convert range to days
        range_days = {
            '3m': 90,
            '6m': 180,
            '1y': 365,
            '2y': 730,
            '5y': 1825
        }[time_range]
        
        use_solid = st.checkbox("📱 Solid Lines Only (for mobile)", value=False, 
                               help="Use solid lines instead of dashed for better mobile readability")
    
    # Fetch price history data with selected range
    with st.spinner(f"Loading price history for {current_ticker}..."):
        price_history_df = get_ticker_price_history(
            current_ticker,
            supabase_client,
            days=range_days
        )
    
    if not price_history_df.empty:
        # Downsample if needed
        from chart_utils import downsample_price_data
        price_history_df = downsample_price_data(price_history_df, range_days)
        
        # All benchmarks available (S&P 500 visible, others in legend)
        all_benchmarks = ['sp500', 'qqq', 'russell2000', 'vti']
        
        # Get congress trades for the chart (from ticker_data, filtered to match chart date range)
        congress_trades_for_chart = []
        if 'congress_trades' in ticker_data and ticker_data['congress_trades']:
            # Filter congress trades to match the chart's selected range
            from datetime import date, timedelta
            chart_start_date = date.today() - timedelta(days=range_days)
            for trade in ticker_data['congress_trades']:
                trade_date_str = trade.get('transaction_date')
                if trade_date_str:
                    try:
                        trade_date = pd.to_datetime(trade_date_str).date()
                        if trade_date >= chart_start_date:
                            congress_trades_for_chart.append(trade)
                    except Exception:
                        continue
        
        # Create chart
        fig = create_ticker_price_chart(
            price_history_df,
            current_ticker,
            show_benchmarks=all_benchmarks,
            show_weekend_shading=True,
            use_solid_lines=use_solid,
            congress_trades=congress_trades_for_chart if congress_trades_for_chart else None
        )
        
        st.plotly_chart(fig, use_container_width=True, key=f"ticker_price_chart_{current_ticker}")
        
        # Show data summary
        if len(price_history_df) > 0:
            first_price = price_history_df['price'].iloc[0]
            last_price = price_history_df['price'].iloc[-1]
            price_change = last_price - first_price
            price_change_pct = (price_change / first_price * 100) if first_price > 0 else 0
            
            # Dynamic label based on range
            range_labels = {
                '3m': 'Change (3M)',
                '6m': 'Change (6M)',
                '1y': 'Change (1Y)',
                '2y': 'Change (2Y)',
                '5y': 'Change (5Y)'
            }
            change_label = range_labels.get(time_range, 'Change (3M)')
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("First Price", f"${first_price:.2f}")
            with col2:
                st.metric("Last Price", f"${last_price:.2f}")
            with col3:
                st.metric(change_label, f"{price_change_pct:+.2f}%")
    else:
        st.info(f"⚠️ No price history data available for {current_ticker}. This may be because:")
        st.markdown("""
        - The ticker is not in our portfolio database
        - The ticker symbol may be invalid
        - Historical data may not be available from external sources
        """)
except Exception as e:
    logger.error(f"Error loading price history for {current_ticker}: {e}", exc_info=True)
    st.error(f"❌ Error loading price history: {str(e)}")
    st.info("Please try again or contact support if the problem persists.")

st.markdown("---")

# Research Articles Section
research_articles = ticker_data.get('research_articles', [])
if research_articles:
    st.header("📚 Research Articles")
    st.caption(f"Found {len(research_articles)} articles mentioning {current_ticker} (last 30 days)")

    for article in research_articles[:10]:  # Show top 10
        with st.expander(f"{article.get('title', 'Untitled')[:80]}..."):
            col1, col2 = st.columns([3, 1])
            with col1:
                if article.get('summary'):
                    st.write(article.get('summary', '')[:500] + '...' if len(article.get('summary', '')) > 500 else article.get('summary', ''))
                if article.get('url'):
                    st.markdown(f"[Read Full Article]({article.get('url')})")
            with col2:
                st.caption(f"Source: {article.get('source', 'Unknown')}")
                if article.get('published_at'):
                    published_date = format_date_safe(article.get('published_at'))
                    st.caption(f"Published: {published_date}")
                if article.get('sentiment'):
                    st.caption(f"Sentiment: {article.get('sentiment', 'N/A')}")
else:
    st.info(f"No research articles found for {current_ticker} (last 30 days).")

st.markdown("---")

# Social Sentiment Section
social_sentiment = ticker_data.get('social_sentiment')
if social_sentiment:
    st.header("💬 Social Sentiment")

    latest_metrics = social_sentiment.get('latest_metrics', [])
    if latest_metrics:
        st.subheader("Latest Metrics")
        metrics_df = pd.DataFrame([
            {
                'Platform': metric.get('platform', 'N/A').title(),
                'Sentiment': metric.get('sentiment_label', 'N/A'),
                'Score': f"{(metric.get('sentiment_score') or 0):.2f}",
                'Volume': metric.get('volume') or 0,
                'Bull/Bear Ratio': f"{(metric.get('bull_bear_ratio') or 0):.2f}" if metric.get('bull_bear_ratio') is not None else 'N/A',
                'Last Updated': format_date_safe(metric.get('created_at')) if metric.get('created_at') else 'N/A'
            }
            for metric in latest_metrics
        ])
        st.dataframe(metrics_df, use_container_width=True, hide_index=True)

    alerts = social_sentiment.get('alerts', [])
    if alerts:
        st.subheader("Recent Alerts (Last 24 Hours)")
        for alert in alerts:
            sentiment_label = alert.get('sentiment_label', 'N/A')
            sentiment_score = alert.get('sentiment_score') or 0
            if sentiment_label == 'EUPHORIC':
                st.success(f"**{alert.get('platform', 'Unknown').title()}** - {sentiment_label} (Score: {sentiment_score:.2f})")
            elif sentiment_label == 'FEARFUL':
                st.error(f"**{alert.get('platform', 'Unknown').title()}** - {sentiment_label} (Score: {sentiment_score:.2f})")
            elif sentiment_label == 'BULLISH':
                st.info(f"**{alert.get('platform', 'Unknown').title()}** - {sentiment_label} (Score: {sentiment_score:.2f})")
else:
    st.info(f"No social sentiment data available for {current_ticker}.")

st.markdown("---")

# Congress Trades Section
congress_trades = ticker_data.get('congress_trades', [])
if congress_trades:
    st.header("🏛️ Congress Trades")
    st.caption(f"Found {len(congress_trades)} recent trades by politicians (last 30 days)")

    trades_df = pd.DataFrame([
        {
            'Date': format_date_safe(trade.get('transaction_date')),
            'Politician': trade.get('politician', 'N/A'),
            'Chamber': trade.get('chamber', 'N/A'),
            'Type': trade.get('type', 'N/A'),
            'Amount': trade.get('amount', 'N/A'),
            'Party': trade.get('party', 'N/A')
        }
        for trade in congress_trades[:20]  # Show last 20
    ])
    st.dataframe(trades_df, use_container_width=True, hide_index=True)
else:
    st.info(f"No congress trades found for {current_ticker} (last 30 days).")

st.markdown("---")

# Watchlist Status Section
watchlist_status = ticker_data.get('watchlist_status')
if watchlist_status:
    st.header("📋 Watchlist Status")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", "✅ In Watchlist" if watchlist_status.get('is_active') else "❌ Not Active")
    with col2:
        st.metric("Priority Tier", watchlist_status.get('priority_tier', 'N/A'))
    with col3:
        st.metric("Source", watchlist_status.get('source', 'N/A'))
else:
    st.info(f"{current_ticker} is not in the watchlist.")

# Footer
st.markdown("---")
st.caption(f"Data last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

