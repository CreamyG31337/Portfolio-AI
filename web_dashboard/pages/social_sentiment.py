#!/usr/bin/env python3
"""
Social Sentiment Dashboard
===========================

Streamlit page for viewing social sentiment data from StockTwits and Reddit.
Displays latest sentiment per ticker and alerts for extreme sentiment.
"""

import streamlit as st
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, timezone
import pandas as pd
import logging

# Try to import zoneinfo for timezone conversion (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
    HAS_ZONEINFO = True
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo
        HAS_ZONEINFO = True
    except ImportError:
        HAS_ZONEINFO = False

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth_utils import is_authenticated, get_user_email, is_admin, get_user_token, redirect_to_login
from navigation import render_navigation
from postgres_client import PostgresClient
from supabase_client import SupabaseClient
from aggrid_utils import display_aggrid_with_ticker_navigation
from streamlit_utils import CACHE_VERSION

logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="Social Sentiment",
    page_icon="💬",
    layout="wide"
)

# Check authentication
# Check authentication
if not is_authenticated():
    redirect_to_login("pages/social_sentiment.py")

# Refresh token if needed (auto-refresh before expiry)
from auth_utils import refresh_token_if_needed
if not refresh_token_if_needed():
    # Token refresh failed - session is invalid, redirect to login
    from auth_utils import logout_user
    logout_user(return_to="pages/social_sentiment.py")
    st.stop()

# Render navigation
render_navigation(show_ai_assistant=True, show_settings=True)

# Initialize Postgres client (with error handling)
@st.cache_resource
def get_postgres_client():
    """Get Postgres client instance, handling errors gracefully"""
    try:
        return PostgresClient()
    except Exception as e:
        logger.error(f"Failed to initialize PostgresClient: {e}")
        return None

# Initialize Supabase client (with error handling)
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

# Check if PostgreSQL is available
if postgres_client is None:
    st.error("⚠️ Social Sentiment Database Unavailable")
    st.info("""
    The social sentiment database is not available. This could be because:
    - PostgreSQL is not running
    - RESEARCH_DATABASE_URL is not configured
    - Database connection failed
    
    Check the logs or contact an administrator for assistance.
    """)
    st.stop()

# Header
st.title("💬 Social Sentiment")
st.caption(f"Logged in as: {get_user_email()}")

# Initialize session state for refresh
if 'refresh_key' not in st.session_state:
    st.session_state.refresh_key = 0

# Query functions
@st.cache_data(ttl=60, show_spinner=False)
def get_watchlist_tickers(_supabase_client, _refresh_key: int, _cache_version: str = "") -> List[Dict[str, Any]]:
    """Get all active tickers from watched_tickers table
    
    Returns:
        List of dictionaries with ticker, priority_tier, source, etc.
    """
    try:
        if _supabase_client is None:
            return []
        result = _supabase_client.supabase.table("watched_tickers")\
            .select("ticker, priority_tier, is_active, source, created_at")\
            .eq("is_active", True)\
            .order("priority_tier, ticker")\
            .execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error fetching watchlist: {e}", exc_info=True)
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_dynamic_watchlist_tickers(
    _supabase_client, 
    _postgres_client, 
    _refresh_key: int,
    _cache_version: str = ""
) -> List[Dict[str, Any]]:
    """Get dynamic watchlist tickers from multiple sources (trade log, congress trades, articles, sentiment alerts)
    
    Combines tickers from:
    - watched_tickers table (TRADELOG source)
    - congress_trades_enriched (last 30 days, CONGRESS source)
    - research_articles (last 30 days, ARTICLES source)
    - extreme sentiment alerts (EUPHORIC, FEARFUL - last 24 hours, EXTREME_ALERTS source)
    - bullish sentiment alerts (BULLISH - last 24 hours, BULLISH_ALERTS source)
    
    Assigns priority tiers based on source count and alerts:
    - Tier A: Has extreme sentiment alerts OR appears in 3+ sources
    - Tier B: Appears in 2 sources
    - Tier C: Appears in 1 source only
    
    Returns:
        List of dictionaries with ticker, priority_tier, source_count, sources, etc.
    """
    try:
        # Dictionary to track tickers and their sources
        ticker_data: Dict[str, Dict[str, Any]] = {}
        
        # 1. Get tickers from watched_tickers table (TRADELOG source)
        if _supabase_client:
            try:
                result = _supabase_client.supabase.table("watched_tickers")\
                    .select("ticker, priority_tier, is_active, source, created_at")\
                    .eq("is_active", True)\
                    .execute()
                
                if result.data:
                    for item in result.data:
                        ticker = item.get('ticker', '').upper().strip()
                        if ticker:
                            if ticker not in ticker_data:
                                ticker_data[ticker] = {
                                    'ticker': ticker,
                                    'sources': [],
                                    'source_count': 0,
                                    'priority_tier': item.get('priority_tier', 'C'),
                                    'created_at': item.get('created_at')
                                }
                            ticker_data[ticker]['sources'].append('TRADELOG')
                            ticker_data[ticker]['source_count'] = len(ticker_data[ticker]['sources'])
            except Exception as e:
                logger.warning(f"Error fetching watched_tickers: {e}")
        
        # 2. Get tickers from congress_trades_enriched (last 30 days)
        if _supabase_client:
            try:
                thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).date()
                result = _supabase_client.supabase.table("congress_trades_enriched")\
                    .select("ticker")\
                    .gte("transaction_date", thirty_days_ago.isoformat())\
                    .not_.is_("ticker", "null")\
                    .execute()
                
                if result.data:
                    congress_tickers = set()
                    for item in result.data:
                        ticker = item.get('ticker', '').upper().strip()
                        if ticker:
                            congress_tickers.add(ticker)
                    
                    for ticker in congress_tickers:
                        if ticker not in ticker_data:
                            ticker_data[ticker] = {
                                'ticker': ticker,
                                'sources': [],
                                'source_count': 0,
                                'priority_tier': 'C',
                                'created_at': None
                            }
                        if 'CONGRESS' not in ticker_data[ticker]['sources']:
                            ticker_data[ticker]['sources'].append('CONGRESS')
                            ticker_data[ticker]['source_count'] = len(ticker_data[ticker]['sources'])
            except Exception as e:
                logger.warning(f"Error fetching congress trades: {e}")
        
        # 3. Get tickers from research_articles (last 30 days)
        if _postgres_client:
            try:
                thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
                query = """
                    SELECT DISTINCT UNNEST(tickers) as ticker
                    FROM research_articles
                    WHERE fetched_at >= %s
                      AND tickers IS NOT NULL
                      AND array_length(tickers, 1) > 0
                """
                results = _postgres_client.execute_query(query, (thirty_days_ago.isoformat(),))
                
                if results:
                    article_tickers = set()
                    for row in results:
                        ticker = row.get('ticker', '').upper().strip()
                        if ticker:
                            article_tickers.add(ticker)
                    
                    for ticker in article_tickers:
                        if ticker not in ticker_data:
                            ticker_data[ticker] = {
                                'ticker': ticker,
                                'sources': [],
                                'source_count': 0,
                                'priority_tier': 'C',
                                'created_at': None
                            }
                        if 'ARTICLES' not in ticker_data[ticker]['sources']:
                            ticker_data[ticker]['sources'].append('ARTICLES')
                            ticker_data[ticker]['source_count'] = len(ticker_data[ticker]['sources'])
            except Exception as e:
                logger.warning(f"Error fetching research articles: {e}")
        
        # 4. Get tickers from extreme sentiment alerts (EUPHORIC, FEARFUL - last 24 hours)
        if _postgres_client:
            try:
                query = """
                    SELECT DISTINCT ticker
                    FROM social_metrics
                    WHERE sentiment_label IN ('EUPHORIC', 'FEARFUL')
                      AND created_at > NOW() - INTERVAL '24 hours'
                """
                results = _postgres_client.execute_query(query)
                
                if results:
                    extreme_alert_tickers = set()
                    for row in results:
                        ticker = row.get('ticker', '').upper().strip()
                        if ticker:
                            extreme_alert_tickers.add(ticker)
                    
                    for ticker in extreme_alert_tickers:
                        if ticker not in ticker_data:
                            ticker_data[ticker] = {
                                'ticker': ticker,
                                'sources': [],
                                'source_count': 0,
                                'priority_tier': 'A',  # Extreme alerts get Tier A
                                'created_at': None
                            }
                        if 'EXTREME_ALERTS' not in ticker_data[ticker]['sources']:
                            ticker_data[ticker]['sources'].append('EXTREME_ALERTS')
                            ticker_data[ticker]['source_count'] = len(ticker_data[ticker]['sources'])
            except Exception as e:
                logger.warning(f"Error fetching extreme sentiment alerts: {e}")
        
        # 5. Get tickers from bullish sentiment alerts (BULLISH - last 24 hours)
        if _postgres_client:
            try:
                query = """
                    SELECT DISTINCT ticker
                    FROM social_metrics
                    WHERE sentiment_label = 'BULLISH'
                      AND created_at > NOW() - INTERVAL '24 hours'
                """
                results = _postgres_client.execute_query(query)
                
                if results:
                    bullish_alert_tickers = set()
                    for row in results:
                        ticker = row.get('ticker', '').upper().strip()
                        if ticker:
                            bullish_alert_tickers.add(ticker)
                    
                    for ticker in bullish_alert_tickers:
                        if ticker not in ticker_data:
                            ticker_data[ticker] = {
                                'ticker': ticker,
                                'sources': [],
                                'source_count': 0,
                                'priority_tier': 'C',
                                'created_at': None
                            }
                        if 'BULLISH_ALERTS' not in ticker_data[ticker]['sources']:
                            ticker_data[ticker]['sources'].append('BULLISH_ALERTS')
                            ticker_data[ticker]['source_count'] = len(ticker_data[ticker]['sources'])
            except Exception as e:
                logger.warning(f"Error fetching bullish sentiment alerts: {e}")
        
        # Calculate priority tiers based on source count and alerts
        for ticker, data in ticker_data.items():
            # Extreme alerts always get Tier A
            if 'EXTREME_ALERTS' in data['sources']:
                data['priority_tier'] = 'A'
            else:
                source_count = data['source_count']
                if source_count >= 3:
                    data['priority_tier'] = 'A'
                elif source_count == 2:
                    data['priority_tier'] = 'B'
                else:
                    # Keep existing tier if from TRADELOG, otherwise C
                    if 'TRADELOG' not in data['sources']:
                        data['priority_tier'] = 'C'
                    # If TRADELOG exists, keep its original tier (already set above)
        
        # Convert to list and sort by priority tier, then ticker
        watchlist = list(ticker_data.values())
        watchlist.sort(key=lambda x: (x['priority_tier'], x['ticker']))
        
        return watchlist
        
    except Exception as e:
        logger.error(f"Error fetching dynamic watchlist: {e}", exc_info=True)
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_latest_sentiment_per_ticker(_client, _refresh_key: int, _cache_version: str = "") -> List[Dict[str, Any]]:
    """Get the most recent sentiment metric for each ticker/platform combination
    
    Returns:
        List of dictionaries with sentiment data (one per ticker-platform)
    """
    try:
        query = """
            SELECT DISTINCT ON (ticker, platform)
                ticker, platform, volume, sentiment_label, sentiment_score, 
                bull_bear_ratio, created_at
            FROM social_metrics
            ORDER BY ticker, platform, created_at DESC
        """
        results = _client.execute_query(query)
        return results
    except Exception as e:
        logger.error(f"Error fetching latest sentiment: {e}", exc_info=True)
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_extreme_sentiment_alerts(_client, _refresh_key: int, _cache_version: str = "") -> List[Dict[str, Any]]:
    """Get EUPHORIC or FEARFUL sentiment alerts from last 24 hours
    
    Returns:
        List of dictionaries with extreme sentiment data including id and analysis_session_id
    """
    try:
        query = """
            SELECT id, ticker, platform, sentiment_label, sentiment_score, 
                   analysis_session_id, created_at
            FROM social_metrics
            WHERE sentiment_label IN ('EUPHORIC', 'FEARFUL')
              AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
        """
        results = _client.execute_query(query)
        return results
    except Exception as e:
        logger.error(f"Error fetching extreme sentiment alerts: {e}", exc_info=True)
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_ai_analyses(_client, _refresh_key: int) -> List[Dict[str, Any]]:
    """Get latest AI sentiment analyses from research database
    
    Returns:
        List of dictionaries with AI analysis data
    """
    try:
        query = """
            SELECT ssa.*, ss.post_count, ss.total_engagement
            FROM social_sentiment_analysis ssa
            JOIN sentiment_sessions ss ON ssa.session_id = ss.id
            WHERE ssa.analyzed_at > NOW() - INTERVAL '7 days'
            ORDER BY ssa.analyzed_at DESC
            LIMIT 100
        """
        results = _client.execute_query(query)
        return results
    except Exception as e:
        logger.error(f"Error fetching AI analyses: {e}", exc_info=True)
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_extracted_tickers(_client, analysis_id: int) -> List[Dict[str, Any]]:
    """Get tickers extracted from a specific AI analysis
    
    Args:
        analysis_id: ID of the analysis record
        
    Returns:
        List of extracted ticker data
    """
    try:
        query = """
            SELECT * FROM extracted_tickers 
            WHERE analysis_id = %s 
            ORDER BY confidence DESC
        """
        results = _client.execute_query(query, (analysis_id,))
        return results
    except Exception as e:
        logger.error(f"Error fetching extracted tickers for analysis {analysis_id}: {e}", exc_info=True)
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_social_posts_for_session(_client, session_id: int) -> List[Dict[str, Any]]:
    """Get social posts for a specific sentiment session
    
    Args:
        session_id: ID of the sentiment session
        
    Returns:
        List of post data
    """
    try:
        query = """
            SELECT sp.*, sm.ticker, sm.platform
            FROM social_posts sp
            JOIN social_metrics sm ON sp.metric_id = sm.id
            WHERE sm.analysis_session_id = %s
            ORDER BY sp.engagement_score DESC
            LIMIT 10
        """
        results = _client.execute_query(query, (session_id,))
        return results
    except Exception as e:
        logger.error(f"Error fetching posts for session {session_id}: {e}", exc_info=True)
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_social_posts_for_metric(_client, metric_id: int) -> List[Dict[str, Any]]:
    """Get social posts for a specific metric
    
    Args:
        metric_id: ID of the social_metrics record
        
    Returns:
        List of post data
    """
    try:
        query = """
            SELECT sp.*, sm.ticker, sm.platform
            FROM social_posts sp
            JOIN social_metrics sm ON sp.metric_id = sm.id
            WHERE sp.metric_id = %s
            ORDER BY sp.engagement_score DESC
            LIMIT 10
        """
        results = _client.execute_query(query, (metric_id,))
        return results
    except Exception as e:
        logger.error(f"Error fetching posts for metric {metric_id}: {e}", exc_info=True)
        return []

# Helper function to format datetime for display
def format_datetime(dt) -> str:
    """Format datetime for display in local timezone"""
    if dt is None:
        return "N/A"
    
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except (ValueError, AttributeError, TypeError):
            return dt
    
    if not isinstance(dt, datetime):
        return str(dt)
    
    # Convert to local timezone if available
    if HAS_ZONEINFO:
        try:
            local_tz = ZoneInfo("America/Los_Angeles")  # Adjust to your timezone
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            local_dt = dt.astimezone(local_tz)
            return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except (ValueError, AttributeError, TypeError):
            pass
    
    return dt.strftime("%Y-%m-%d %H:%M:%S")

# Helper function to get sentiment color
def get_sentiment_color(label: Optional[str]) -> str:
    """Get color for sentiment label"""
    if not label:
        return "gray"
    
    label_upper = label.upper()
    color_map = {
        'EUPHORIC': 'green',
        'BULLISH': 'lightgreen',
        'NEUTRAL': 'gray',
        'BEARISH': 'lightcoral',
        'FEARFUL': 'red'
    }
    return color_map.get(label_upper, "gray")

# Main content area
try:
    # Refresh button
    col_refresh, col_spacer = st.columns([0.1, 0.9])
    with col_refresh:
        if st.button("🔄 Refresh", key="refresh_sentiment"):
            st.session_state.refresh_key += 1
            st.rerun()
    
    # Get dynamic watchlist (cached)
    watchlist_tickers = []
    if supabase_client or postgres_client:
        with st.spinner("Loading dynamic watchlist..."):
            watchlist_tickers = get_dynamic_watchlist_tickers(
                supabase_client, 
                postgres_client, 
                st.session_state.refresh_key,
                CACHE_VERSION
            )
    
    # Get alerts (cached)
    with st.spinner("Loading alerts..."):
        alerts = get_extreme_sentiment_alerts(postgres_client, st.session_state.refresh_key, CACHE_VERSION)
    
    # Display Watchlist Section
    st.header("📋 Watchlist")
    st.caption("Dynamic watchlist combining tickers from trade log, congress trades (30 days), research articles (30 days), extreme sentiment alerts (24h), and bullish sentiment alerts (24h)")
    
    if watchlist_tickers:
        watchlist_df = pd.DataFrame(watchlist_tickers)
        
        # Show watchlist summary
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Watchlist Tickers", len(watchlist_tickers))
        with col2:
            tier_a = len([t for t in watchlist_tickers if t.get('priority_tier') == 'A'])
            st.metric("Priority A", tier_a)
        with col3:
            tier_b = len([t for t in watchlist_tickers if t.get('priority_tier') == 'B'])
            st.metric("Priority B", tier_b)
        with col4:
            tier_c = len([t for t in watchlist_tickers if t.get('priority_tier') == 'C'])
            st.metric("Priority C", tier_c)
        
        # Show source count distribution
        source_counts = {}
        for t in watchlist_tickers:
            count = t.get('source_count', 0)
            source_counts[count] = source_counts.get(count, 0) + 1
        
        if source_counts:
            st.subheader("Source Distribution")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("3 Sources (Tier A)", source_counts.get(3, 0))
            with col2:
                st.metric("2 Sources (Tier B)", source_counts.get(2, 0))
            with col3:
                st.metric("1 Source (Tier C)", source_counts.get(1, 0))
        
        # Show watchlist table
        st.subheader("Watchlist Tickers")
        watchlist_display = pd.DataFrame([
            {
                'Ticker': t.get('ticker', 'N/A'),
                'Priority': t.get('priority_tier', 'C'),
                'Sources': ', '.join(t.get('sources', [])),
                'Source Count': t.get('source_count', 0)
            }
            for t in watchlist_tickers
        ])
        
        # Display watchlist with AgGrid for ticker navigation
        selected_ticker = display_aggrid_with_ticker_navigation(
            watchlist_display,
            ticker_column="Ticker",
            height=min(400, len(watchlist_display) * 35 + 50),
            fit_columns=True
        )
        
        # Handle ticker selection
        if selected_ticker:
            # Use session state to pass ticker to details page
            st.session_state['selected_ticker'] = selected_ticker
            st.switch_page("pages/ticker_details.py")
    else:
        if supabase_client is None and postgres_client is None:
            st.warning("⚠️ Database connections unavailable - cannot load watchlist")
        else:
            st.info("📭 No tickers found in watchlist. Tickers are dynamically populated from trade log, congress trades (last 30 days), research articles (last 30 days), extreme sentiment alerts (last 24 hours), and bullish sentiment alerts (last 24 hours).")
    
    st.markdown("---")
    
    # Display Alerts Section
    st.header("🚨 Extreme Sentiment Alerts")
    
    if alerts:
        for idx, alert in enumerate(alerts):
            ticker = alert.get('ticker', 'N/A')
            platform = alert.get('platform', 'N/A')
            sentiment_label = alert.get('sentiment_label', 'N/A')
            sentiment_score = alert.get('sentiment_score', 0.0)
            created_at = alert.get('created_at')
            time_str = format_datetime(created_at)
            metric_id = alert.get('id')
            session_id = alert.get('analysis_session_id')
            
            # Create container for alert with source link
            if sentiment_label == 'EUPHORIC':
                st.success(
                    f"**{ticker}** ({platform.upper()}) - {sentiment_label} "
                    f"(Score: {sentiment_score:.1f}) - {time_str}"
                )
            elif sentiment_label == 'FEARFUL':
                st.error(
                    f"**{ticker}** ({platform.upper()}) - {sentiment_label} "
                    f"(Score: {sentiment_score:.1f}) - {time_str}"
                )
            
            # Create columns for action buttons
            col_source, col_ticker = st.columns([0.5, 0.5])
            
            # Show expandable section with source posts
            # Try session_id first, then fall back to metric_id
            posts = []
            if postgres_client:
                if session_id:
                    posts = get_social_posts_for_session(postgres_client, session_id)
                
                # If no posts found via session_id, try metric_id
                if not posts and metric_id:
                    posts = get_social_posts_for_metric(postgres_client, metric_id)
            
            with col_source:
                # Always show expandable section if we have posts or metric_id
                if posts or metric_id:
                    with st.expander(f"🔗 View Source Posts ({len(posts) if posts else 0} posts)", expanded=False):
                        if posts:
                            st.caption(f"Showing {len(posts)} posts from this sentiment alert")
                            for post_idx, post in enumerate(posts[:5]):  # Show top 5 posts
                                with st.container():
                                    col_author, col_time = st.columns([0.7, 0.3])
                                    with col_author:
                                        st.write(f"**{post.get('author', 'Unknown')}**")
                                    with col_time:
                                        st.caption(format_datetime(post.get('posted_at')))
                                    
                                    st.write(post.get('content', ''))
                                    
                                    col_eng, col_url = st.columns([0.5, 0.5])
                                    with col_eng:
                                        st.caption(f"👍 {post.get('engagement_score', 0)} engagement")
                                    with col_url:
                                        if post.get('url'):
                                            st.markdown(f"[🔗 View Original Post]({post.get('url')})", unsafe_allow_html=True)
                                    
                                    if post_idx < len(posts[:5]) - 1:
                                        st.divider()
                        else:
                            st.info("No posts found for this alert. Posts may not have been extracted yet.")
                else:
                    st.caption("⚠️ No source posts available")
            
            with col_ticker:
                # Link to ticker details page
                if st.button("📊 View Ticker Details", key=f"alert_ticker_{idx}", use_container_width=True):
                    st.session_state['selected_ticker'] = ticker
                    st.switch_page("pages/ticker_details.py")
    else:
        st.info("✅ No extreme sentiment alerts in the last 24 hours")
    
    st.markdown("---")
    
    # Display AI Analysis Section
    st.header("🤖 AI Sentiment Analysis")
    
    # Get AI analyses (cached)
    with st.spinner("Loading AI analyses..."):
        ai_analyses = get_ai_analyses(postgres_client, st.session_state.refresh_key)
    
    if ai_analyses:
        # Show AI analysis summary
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            total_analyses = len(ai_analyses)
            st.metric("AI Analyses", total_analyses)
        with col2:
            avg_confidence = sum(a.get('confidence_score', 0) for a in ai_analyses) / len(ai_analyses)
            st.metric("Avg Confidence", f"{avg_confidence:.1%}")
        with col3:
            euphoric_count = sum(1 for a in ai_analyses if a.get('sentiment_label') == 'EUPHORIC')
            st.metric("Euphoric", euphoric_count)
        with col4:
            fearful_count = sum(1 for a in ai_analyses if a.get('sentiment_label') == 'FEARFUL')
            st.metric("Fearful", fearful_count)
        
        # AI Analysis table
        analysis_data = []
        for analysis in ai_analyses:
            # Get extracted tickers for this analysis
            extracted_tickers = get_extracted_tickers(postgres_client, analysis['id'])
            
            # Create platform link
            ticker = analysis.get('ticker', 'N/A')
            platform_raw = analysis.get('platform', 'N/A')
            platform_display = platform_raw
            
            if platform_raw and ticker and ticker != 'N/A':
                platform_lower = platform_raw.lower()
                if platform_lower == 'stocktwits':
                    # StockTwits doesn't support .TO/.V suffixes - use base ticker
                    base_ticker = ticker.upper()
                    for suffix in ['.TO', '.V', '.CN', '.NE', '.TSX']:
                        if base_ticker.endswith(suffix):
                            base_ticker = base_ticker[:-len(suffix)]
                            break
                    platform_display = f"[{platform_raw.upper()}](https://stocktwits.com/symbol/{base_ticker})"
                elif platform_lower == 'reddit':
                    platform_display = f"[{platform_raw.upper()}](https://www.reddit.com/search/?q=%24{ticker})"

            analysis_data.append({
                'Ticker': ticker,
                'Platform': platform_display,
                'AI Sentiment': analysis.get('sentiment_label', 'N/A'),
                'AI Score': f"{analysis.get('sentiment_score', 0):.1f}",
                'Confidence': f"{analysis.get('confidence_score', 0):.1%}",
                'Posts': analysis.get('post_count', 0),
                'Engagement': analysis.get('total_engagement', 0),
                'Tickers Found': len(extracted_tickers),
                'Analyzed': format_datetime(analysis.get('analyzed_at')),
                'analysis_id': analysis['id'],
                'session_id': analysis['session_id']
            })
        
        analysis_df = pd.DataFrame(analysis_data)
        
        # Display with expandable details
        for idx, row in analysis_df.iterrows():
            col1, col2, col3, col4, col5, col6 = st.columns([1,1,1,1,1,2])
            
            with col1:
                st.write(f"**{row['Ticker']}**")
            with col2:
                st.write(row['Platform'])
            with col3:
                sentiment_color = get_sentiment_color(row['AI Sentiment'])
                st.markdown(f"<span style='color:{sentiment_color}; font-weight:bold'>{row['AI Sentiment']}</span>", 
                          unsafe_allow_html=True)
            with col4:
                st.write(row['AI Score'])
            with col5:
                st.write(row['Confidence'])
            with col6:
                if st.button("📋 Details", key=f"details_{row['analysis_id']}"):
                    st.session_state[f"show_details_{row['analysis_id']}"] = True
            
            # Show details if requested
            if st.session_state.get(f"show_details_{row['analysis_id']}", False):
                with st.expander(f"AI Analysis Details for {row['Ticker']}", expanded=True):
                    # Get full analysis data
                    full_analysis = next((a for a in ai_analyses if a['id'] == row['analysis_id']), None)
                    if full_analysis:
                        st.subheader("Analysis Summary")
                        st.write(full_analysis.get('summary', 'No summary available'))
                        
                        st.subheader("Key Themes")
                        themes = full_analysis.get('key_themes', [])
                        if themes:
                            for theme in themes:
                                st.write(f"• {theme}")
                        else:
                            st.write("No themes identified")
                        
                        st.subheader("Detailed Reasoning")
                        st.write(full_analysis.get('reasoning', 'No reasoning provided'))
                        
                        # Show extracted tickers
                        extracted_tickers = get_extracted_tickers(postgres_client, row['analysis_id'])
                        if extracted_tickers:
                            st.subheader("Extracted Tickers")
                            ticker_data = []
                            for ticker in extracted_tickers:
                                ticker_data.append({
                                    'Ticker': ticker.get('ticker'),
                                    'Confidence': f"{ticker.get('confidence', 0):.1%}",
                                    'Company': ticker.get('company_name', 'Unknown'),
                                    'Primary': '✅' if ticker.get('is_primary') else '❌',
                                    'Context': ticker.get('context', '')[:100] + '...' if ticker.get('context') else ''
                                })
                            st.dataframe(pd.DataFrame(ticker_data), use_container_width=True, hide_index=True)
                        
                        # Show top posts
                        posts = get_social_posts_for_session(postgres_client, row['session_id'])
                        if posts:
                            st.subheader("Sample Posts")
                            for post in posts[:3]:  # Show top 3
                                with st.container():
                                    st.write(f"**{post.get('author', 'Unknown')}** - {format_datetime(post.get('posted_at'))}")
                                    st.write(post.get('content', '')[:300] + '...' if len(post.get('content', '')) > 300 else post.get('content', ''))
                                    col_a, col_b = st.columns(2)
                                    with col_a:
                                        st.caption(f"👍 {post.get('engagement_score', 0)} engagement")
                                    with col_b:
                                        if post.get('url'):
                                            st.caption(f"[View Original]({post.get('url')})")
                                    st.divider()
                    
                    if st.button("Close Details", key=f"close_{row['analysis_id']}"):
                        st.session_state[f"show_details_{row['analysis_id']}"] = False
                        st.rerun()
            
            st.markdown("---")
    else:
        st.info("🤖 No AI analyses available yet. AI analysis will be performed on sentiment sessions as data is collected.")
    
    st.markdown("---")
    
    # Get latest sentiment data (cached)
    with st.spinner("Loading sentiment data..."):
        latest_sentiment = get_latest_sentiment_per_ticker(postgres_client, st.session_state.refresh_key)
    
    # Display Latest Sentiment Table
    st.header("📊 Latest Sentiment by Ticker")
    
    # Show last refresh timestamp
    if latest_sentiment:
        newest_timestamp = max((row.get('created_at') for row in latest_sentiment), default=None)
        if newest_timestamp:
            st.caption(f"📅 Data last updated: {format_datetime(newest_timestamp)}")
    
    if not latest_sentiment:
        st.info("""
        📭 No social sentiment data available yet.
        
        Data is collected every 60 minutes (1 hour) by the automated scheduler. 
        Check back soon or ensure the `social_sentiment` job is running.
        """)
        st.stop()
    
    # Create watchlist ticker set for filtering
    watchlist_ticker_set = set([t.get('ticker') for t in watchlist_tickers]) if watchlist_tickers else set()
    
    # Filter option
    show_only_watchlist = st.checkbox("Show only watchlist tickers", value=True)
    
    # Batch fetch company names for all unique tickers
    unique_tickers = list(set([row.get('ticker') for row in latest_sentiment if row.get('ticker')]))
    company_names_map = {}
    
    if supabase_client and unique_tickers:
        try:
            # Batch query company names from securities table
            # Query in chunks of 50 (Supabase limit)
            for i in range(0, len(unique_tickers), 50):
                ticker_batch = unique_tickers[i:i+50]
                result = supabase_client.supabase.table("securities")\
                    .select("ticker, company_name")\
                    .in_("ticker", ticker_batch)\
                    .execute()
                
                if result.data:
                    for item in result.data:
                        ticker = item.get('ticker', '').upper()
                        company_name = item.get('company_name', '')
                        if company_name and company_name.strip() and company_name != 'Unknown':
                            company_names_map[ticker] = company_name.strip()
        except Exception as e:
            logger.warning(f"Error fetching company names: {e}")
    
    # Group data by ticker
    ticker_data = {}
    for row in latest_sentiment:
        ticker = row.get('ticker', 'N/A')
        if ticker == 'N/A':
            continue
        
        # Check if ticker is in watchlist
        in_watchlist = ticker in watchlist_ticker_set
        
        # Filter if requested
        if show_only_watchlist and not in_watchlist:
            continue
        
        if ticker not in ticker_data:
            ticker_upper = ticker.upper()
            company_name = company_names_map.get(ticker_upper, 'N/A')
            ticker_data[ticker] = {
                'ticker': ticker,
                'company': company_name,
                'in_watchlist': in_watchlist,
                'platforms': []
            }
        
        platform = row.get('platform', 'N/A')
        volume = row.get('volume', 0)
        sentiment_label = row.get('sentiment_label', 'N/A')
        sentiment_score = row.get('sentiment_score')
        bull_bear_ratio = row.get('bull_bear_ratio')
        created_at = row.get('created_at')
        
        ticker_data[ticker]['platforms'].append({
            'platform': platform,
            'volume': volume,
            'sentiment_label': sentiment_label,
            'sentiment_score': sentiment_score,
            'bull_bear_ratio': bull_bear_ratio,
            'created_at': created_at
        })
    
    # Prepare DataFrame with separate platform columns
    df_data = []
    sentiment_icons = {
        'BULLISH': '🚀',
        'BEARISH': '📉',
        'EUPHORIC': '🚀',
        'FEARFUL': '📉'
    }
    
    for ticker, data in ticker_data.items():
        platforms = data['platforms']
        
        # Initialize platform data
        stocktwits_data = None
        reddit_data = None
        latest_timestamp = None
        
        for p in platforms:
            platform = p['platform']
            sentiment_label = p['sentiment_label'] if p['sentiment_label'] else 'N/A'
            sentiment_icon = sentiment_icons.get(sentiment_label.upper(), '')
            
            # Format sentiment with icon
            if sentiment_icon:
                sentiment_display = f"{sentiment_icon} {sentiment_label}"
            else:
                sentiment_display = sentiment_label
            
            platform_info = {
                'sentiment': sentiment_display,
                'volume': p['volume'],
                'score': f"{p['sentiment_score']:.1f}" if p['sentiment_score'] is not None else "N/A",
                'bull_bear_ratio': p['bull_bear_ratio'],
                'created_at': p['created_at']
            }
            
            if platform == 'stocktwits':
                stocktwits_data = platform_info
            elif platform == 'reddit':
                reddit_data = platform_info
            
            # Track latest timestamp
            if p['created_at']:
                if latest_timestamp is None or p['created_at'] > latest_timestamp:
                    latest_timestamp = p['created_at']
        
        # Build row data
        row = {
            'Ticker': ticker,
            'Company': data['company'],
            'In Watchlist': '✅' if data['in_watchlist'] else '❌',
        }
        
        # Stocktwits columns
        if stocktwits_data:
            row['💬 Stocktwits Sentiment'] = stocktwits_data['sentiment']
            row['💬 Stocktwits Volume'] = stocktwits_data['volume']
            row['💬 Stocktwits Score'] = stocktwits_data['score']
            row['💬 Bull/Bear Ratio'] = f"{stocktwits_data['bull_bear_ratio']:.2f}" if stocktwits_data['bull_bear_ratio'] is not None else "N/A"
        else:
            row['💬 Stocktwits Sentiment'] = 'N/A'
            row['💬 Stocktwits Volume'] = 'N/A'
            row['💬 Stocktwits Score'] = 'N/A'
            row['💬 Bull/Bear Ratio'] = 'N/A'
        
        # Reddit columns
        if reddit_data:
            row['👽 Reddit Sentiment'] = reddit_data['sentiment']
            row['👽 Reddit Volume'] = reddit_data['volume']
            row['👽 Reddit Score'] = reddit_data['score']
        else:
            row['👽 Reddit Sentiment'] = 'N/A'
            row['👽 Reddit Volume'] = 'N/A'
            row['👽 Reddit Score'] = 'N/A'
        
        row['Last Updated'] = format_datetime(latest_timestamp)
        
        # Add AI analysis indicators
        ai_analysis = next((a for a in ai_analyses if a.get('ticker') == ticker), None)
        if ai_analysis:
            row['🤖 AI Status'] = '✅ Analyzed'
            row['🤖 AI Sentiment'] = ai_analysis.get('sentiment_label', 'N/A')
            row['🤖 AI Confidence'] = f"{ai_analysis.get('confidence_score', 0):.1%}"
        else:
            row['🤖 AI Status'] = '⏳ Pending'
            row['🤖 AI Sentiment'] = 'N/A'
            row['🤖 AI Confidence'] = 'N/A'
        
        df_data.append(row)
    
    df = pd.DataFrame(df_data)
    
    if df.empty:
        if show_only_watchlist:
            st.info("📭 No sentiment data available for watchlist tickers yet. The scheduler will collect data for these tickers every 60 minutes (1 hour).")
        else:
            st.info("📭 No sentiment data available.")
        st.stop()
    
    # Sort by ticker
    df = df.sort_values(['Ticker'])
    
    # Reorder columns for better readability
    column_order = [
        'Ticker',
        'Company',
        'In Watchlist',
        '🤖 AI Status',
        '🤖 AI Sentiment',
        '🤖 AI Confidence',
        '💬 Stocktwits Sentiment',
        '💬 Stocktwits Volume',
        '💬 Stocktwits Score',
        '💬 Bull/Bear Ratio',
        '👽 Reddit Sentiment',
        '👽 Reddit Volume',
        '👽 Reddit Score',
        'Last Updated'
    ]
    # Only include columns that exist in the DataFrame
    existing_columns = [col for col in column_order if col in df.columns]
    df = df[existing_columns]
    
    # Define sentiment color styling function
    def style_sentiment(val):
        """Apply background color based on sentiment label"""
        if not val or val == 'N/A':
            return ''
        
        # Extract sentiment label (handle format like "🚀 BULLISH" or just "BULLISH")
        sentiment_label = None
        for label in ['EUPHORIC', 'BULLISH', 'NEUTRAL', 'BEARISH', 'FEARFUL']:
            if label in val.upper():
                sentiment_label = label
                break
        
        if not sentiment_label:
            return ''
        
        color = get_sentiment_color(sentiment_label)
        # Use white text for better contrast
        return f'background-color: {color}; color: white; font-weight: bold;'
    
    # Get sentiment column names (including AI sentiment)
    sentiment_columns = [col for col in df.columns if 'Sentiment' in col]
    
    # Display dataframe with AgGrid for ticker navigation
    selected_ticker = display_aggrid_with_ticker_navigation(
        df,
        ticker_column="Ticker",
        height=min(600, len(df) * 35 + 50),
        fit_columns=True
    )
    
    # Handle ticker selection
    if selected_ticker:
        # Use session state to pass ticker to details page
        st.session_state['selected_ticker'] = selected_ticker
        st.switch_page("pages/ticker_details.py")
    
    # Show summary statistics
    st.markdown("---")
    st.subheader("📈 Summary Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_tickers = len(set(df['Ticker'].unique()))
        st.metric("Unique Tickers", total_tickers)
    
    with col2:
        total_metrics = len(df)
        st.metric("Total Metrics", total_metrics)
    
    with col3:
        # Count tickers with EUPHORIC sentiment (in any platform)
        sentiment_columns = [col for col in df.columns if 'Sentiment' in col]
        euphoric_mask = pd.Series([False] * len(df))
        for col in sentiment_columns:
            euphoric_mask |= df[col].str.contains('EUPHORIC', case=False, na=False)
        euphoric_count = euphoric_mask.sum()
        st.metric("Euphoric", euphoric_count)
    
    with col4:
        # Count tickers with FEARFUL sentiment (in any platform)
        sentiment_columns = [col for col in df.columns if 'Sentiment' in col]
        fearful_mask = pd.Series([False] * len(df))
        for col in sentiment_columns:
            fearful_mask |= df[col].str.contains('FEARFUL', case=False, na=False)
        fearful_count = fearful_mask.sum()
        st.metric("Fearful", fearful_count)

except Exception as e:
    logger.error(f"Error in social sentiment page: {e}", exc_info=True)
    st.error(f"❌ An error occurred: {str(e)}")
    st.info("Please check the logs or contact an administrator.")

