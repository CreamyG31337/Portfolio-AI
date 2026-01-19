#!/usr/bin/env python3
"""
Social Sentiment Routes
=======================

Flask routes for the Social Sentiment dashboard page.
Migrated from Streamlit to Flask following the established pattern.
"""

from flask import Blueprint, render_template, request, jsonify
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any
import sys
from pathlib import Path

# Add parent directory to path to allow importing from root
sys.path.append(str(Path(__file__).parent.parent))

from auth import require_auth
from postgres_client import PostgresClient
from supabase_client import SupabaseClient
from flask_auth_utils import get_user_email_flask, get_auth_token
from flask_cache_utils import cache_resource, cache_data
from user_preferences import get_user_preference
from cache_version import get_cache_version
from auth import is_admin

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

logger = logging.getLogger('social_sentiment')

social_sentiment_bp = Blueprint('social_sentiment', __name__)

# Cached database clients
@cache_resource
def get_postgres_client():
    """Get Postgres client instance, handling errors gracefully"""
    try:
        return PostgresClient()
    except Exception as e:
        logger.error(f"Failed to initialize PostgresClient: {e}")
        return None

@cache_resource
def get_supabase_client():
    """Get Supabase client instance with role-based access"""
    try:
        # Admins use service_role to see all funds
        if is_admin():
            return SupabaseClient(use_service_role=True)
        
        # Regular users use their token to respect RLS
        user_token = get_auth_token()
        if user_token:
            return SupabaseClient(user_token=user_token)
        else:
            logger.error("No user token available for non-admin user")
            return None
    except Exception as e:
        logger.error(f"Failed to initialize SupabaseClient: {e}")
        return None

# Helper functions
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

# Cached data fetching functions
@cache_data(ttl=60)
def get_cached_dynamic_watchlist(
    _supabase_client,
    _postgres_client,
    _refresh_key: int = 0,
    _cache_version: str = ""
) -> List[Dict[str, Any]]:
    """Get dynamic watchlist tickers from multiple sources (cached)"""
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
        
        # Convert to list and sort by priority tier, then ticker
        watchlist = list(ticker_data.values())
        watchlist.sort(key=lambda x: (x['priority_tier'], x['ticker']))
        
        return watchlist
        
    except Exception as e:
        logger.error(f"Error fetching dynamic watchlist: {e}", exc_info=True)
        return []

@cache_data(ttl=60)
def get_cached_extreme_alerts(
    _client,
    _refresh_key: int = 0,
    _cache_version: str = ""
) -> List[Dict[str, Any]]:
    """Get EUPHORIC or FEARFUL sentiment alerts from last 24 hours (cached)"""
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

@cache_data(ttl=60)
def get_cached_ai_analyses(
    _client,
    _refresh_key: int = 0
) -> List[Dict[str, Any]]:
    """Get latest AI sentiment analyses from research database (cached)"""
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

@cache_data(ttl=60)
def get_cached_latest_sentiment(
    _client,
    _refresh_key: int = 0,
    _cache_version: str = ""
) -> List[Dict[str, Any]]:
    """Get the most recent sentiment metric for each ticker/platform combination (cached)"""
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

# Main route
@social_sentiment_bp.route('/social_sentiment')
@require_auth
def social_sentiment_page():
    """Social Sentiment Dashboard page"""
    try:
        from app import get_navigation_context  # Import here to avoid circular import
        
        user_email = get_user_email_flask()
        user_theme = get_user_preference('theme', default='system')
        refresh_key = int(request.args.get('refresh_key', 0))
        cache_version = get_cache_version()
        
        # Get database clients
        postgres_client = get_postgres_client()
        supabase_client = get_supabase_client()
        
        # Check if PostgreSQL is available
        if postgres_client is None:
            nav_context = get_navigation_context(current_page='social_sentiment')
            return render_template('social_sentiment.html',
                                 user_email=user_email,
                                 user_theme=user_theme,
                                 error="Social Sentiment Database Unavailable",
                                 error_message="The social sentiment database is not available. Check the logs or contact an administrator.",
                                 refresh_key=refresh_key,
                                 **nav_context)
        
        # Get initial data summaries for template
        watchlist_tickers = get_cached_dynamic_watchlist(
            supabase_client,
            postgres_client,
            refresh_key,
            cache_version
        )
        
        alerts = get_cached_extreme_alerts(postgres_client, refresh_key, cache_version)
        ai_analyses = get_cached_ai_analyses(postgres_client, refresh_key)
        latest_sentiment = get_cached_latest_sentiment(postgres_client, refresh_key, cache_version)
        
        # Calculate summary statistics
        watchlist_summary = {
            'total': len(watchlist_tickers),
            'tier_a': len([t for t in watchlist_tickers if t.get('priority_tier') == 'A']),
            'tier_b': len([t for t in watchlist_tickers if t.get('priority_tier') == 'B']),
            'tier_c': len([t for t in watchlist_tickers if t.get('priority_tier') == 'C'])
        }
        
        ai_summary = {
            'total': len(ai_analyses),
            'avg_confidence': sum(a.get('confidence_score', 0) for a in ai_analyses) / len(ai_analyses) if ai_analyses else 0,
            'euphoric': sum(1 for a in ai_analyses if a.get('sentiment_label') == 'EUPHORIC'),
            'fearful': sum(1 for a in ai_analyses if a.get('sentiment_label') == 'FEARFUL')
        }
        
        # Get newest timestamp for data freshness indicator
        newest_timestamp = None
        if latest_sentiment:
            timestamps = [row.get('created_at') for row in latest_sentiment if row.get('created_at')]
            if timestamps:
                newest_timestamp = max(timestamps)
        
        nav_context = get_navigation_context(current_page='social_sentiment')
        
        return render_template('social_sentiment.html',
                             user_email=user_email,
                             user_theme=user_theme,
                             refresh_key=refresh_key,
                             watchlist_summary=watchlist_summary,
                             alerts_count=len(alerts),
                             ai_summary=ai_summary,
                             newest_timestamp=newest_timestamp,
                             **nav_context)
        
    except Exception as e:
        logger.error(f"Error in social sentiment page: {e}", exc_info=True)
        from app import get_navigation_context
        user_email = get_user_email_flask()
        user_theme = get_user_preference('theme', default='system')
        nav_context = get_navigation_context(current_page='social_sentiment')
        return render_template('social_sentiment.html',
                             user_email=user_email,
                             user_theme=user_theme,
                             error="Error loading page",
                             error_message=str(e),
                             refresh_key=0,
                             **nav_context), 500

# API Endpoints
@social_sentiment_bp.route('/api/social_sentiment/watchlist')
@require_auth
def api_watchlist():
    """API endpoint for dynamic watchlist tickers"""
    try:
        refresh_key = int(request.args.get('refresh_key', 0))
        cache_version = get_cache_version()
        
        postgres_client = get_postgres_client()
        supabase_client = get_supabase_client()
        
        watchlist = get_cached_dynamic_watchlist(
            supabase_client,
            postgres_client,
            refresh_key,
            cache_version
        )
        
        return jsonify({
            'success': True,
            'data': watchlist
        })
    except Exception as e:
        logger.error(f"Error in watchlist API: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@social_sentiment_bp.route('/api/social_sentiment/alerts')
@require_auth
def api_alerts():
    """API endpoint for extreme sentiment alerts"""
    try:
        refresh_key = int(request.args.get('refresh_key', 0))
        cache_version = get_cache_version()
        
        postgres_client = get_postgres_client()
        if postgres_client is None:
            return jsonify({'success': False, 'error': 'Postgres client unavailable'}), 500
        
        alerts = get_cached_extreme_alerts(postgres_client, refresh_key, cache_version)
        
        # Format alerts for frontend
        formatted_alerts = []
        for alert in alerts:
            formatted_alerts.append({
                'id': alert.get('id'),
                'ticker': alert.get('ticker'),
                'platform': alert.get('platform'),
                'sentiment_label': alert.get('sentiment_label'),
                'sentiment_score': alert.get('sentiment_score'),
                'analysis_session_id': alert.get('analysis_session_id'),
                'created_at': format_datetime(alert.get('created_at')),
                'created_at_raw': alert.get('created_at').isoformat() if alert.get('created_at') else None
            })
        
        return jsonify({
            'success': True,
            'data': formatted_alerts
        })
    except Exception as e:
        logger.error(f"Error in alerts API: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@social_sentiment_bp.route('/api/social_sentiment/ai_analyses')
@require_auth
def api_ai_analyses():
    """API endpoint for AI sentiment analyses"""
    try:
        refresh_key = int(request.args.get('refresh_key', 0))
        
        postgres_client = get_postgres_client()
        if postgres_client is None:
            return jsonify({'success': False, 'error': 'Postgres client unavailable'}), 500
        
        analyses = get_cached_ai_analyses(postgres_client, refresh_key)
        
        # Format analyses for frontend
        formatted_analyses = []
        for analysis in analyses:
            formatted_analyses.append({
                'id': analysis.get('id'),
                'ticker': analysis.get('ticker'),
                'platform': analysis.get('platform'),
                'sentiment_label': analysis.get('sentiment_label'),
                'sentiment_score': analysis.get('sentiment_score'),
                'confidence_score': analysis.get('confidence_score'),
                'post_count': analysis.get('post_count'),
                'total_engagement': analysis.get('total_engagement'),
                'session_id': analysis.get('session_id'),
                'analyzed_at': format_datetime(analysis.get('analyzed_at')),
                'analyzed_at_raw': analysis.get('analyzed_at').isoformat() if analysis.get('analyzed_at') else None
            })
        
        return jsonify({
            'success': True,
            'data': formatted_analyses
        })
    except Exception as e:
        logger.error(f"Error in AI analyses API: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@social_sentiment_bp.route('/api/social_sentiment/latest_sentiment')
@require_auth
def api_latest_sentiment():
    """API endpoint for latest sentiment per ticker"""
    try:
        refresh_key = int(request.args.get('refresh_key', 0))
        cache_version = get_cache_version()
        show_only_watchlist = request.args.get('show_only_watchlist', 'false') == 'true'
        
        postgres_client = get_postgres_client()
        supabase_client = get_supabase_client()
        
        if postgres_client is None:
            return jsonify({'success': False, 'error': 'Postgres client unavailable'}), 500
        
        latest_sentiment = get_cached_latest_sentiment(postgres_client, refresh_key, cache_version)
        ai_analyses = get_cached_ai_analyses(postgres_client, refresh_key)
        
        # Get watchlist for filtering
        watchlist_tickers = []
        if show_only_watchlist:
            watchlist_tickers = get_cached_dynamic_watchlist(
                supabase_client,
                postgres_client,
                refresh_key,
                cache_version
            )
        watchlist_ticker_set = set([t.get('ticker') for t in watchlist_tickers]) if watchlist_tickers else set()
        
        # Get company names for all unique tickers
        unique_tickers = list(set([row.get('ticker') for row in latest_sentiment if row.get('ticker')]))
        company_names_map = {}
        
        if supabase_client and unique_tickers:
            try:
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
        
        # Group data by ticker and format for AgGrid
        ticker_data = {}
        for row in latest_sentiment:
            ticker = row.get('ticker', 'N/A')
            if ticker == 'N/A':
                continue
            
            # Filter if requested
            if show_only_watchlist and ticker not in watchlist_ticker_set:
                continue
            
            if ticker not in ticker_data:
                ticker_upper = ticker.upper()
                company_name = company_names_map.get(ticker_upper, 'N/A')
                ticker_data[ticker] = {
                    'Ticker': ticker,
                    'Company': company_name,
                    'In Watchlist': '✅' if ticker in watchlist_ticker_set else '❌',
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
        
        # Batch fetch logo URLs for all tickers (caching-friendly pattern)
        unique_tickers_list = list(ticker_data.keys())
        logo_urls_map = {}
        if unique_tickers_list:
            try:
                from web_dashboard.utils.logo_utils import get_ticker_logo_urls
                logo_urls_map = get_ticker_logo_urls(unique_tickers_list)
            except Exception as e:
                logger.warning(f"Error fetching logo URLs: {e}")
        
        # Prepare DataFrame-like structure for AgGrid
        sentiment_icons = {
            'BULLISH': '🚀',
            'BEARISH': '📉',
            'EUPHORIC': '🚀',
            'FEARFUL': '📉'
        }
        
        df_data = []
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
            logo_url = logo_urls_map.get(ticker)
            row = {
                'Ticker': ticker,
                'Company': data['Company'],
                'In Watchlist': data['In Watchlist'],
                '_logo_url': logo_url  # Logo URL for frontend (caching-friendly)
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
        
        return jsonify({
            'success': True,
            'data': df_data
        })
    except Exception as e:
        logger.error(f"Error in latest sentiment API: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@social_sentiment_bp.route('/api/social_sentiment/ai_details/<int:analysis_id>')
@require_auth
def api_ai_details(analysis_id: int):
    """API endpoint for detailed AI analysis"""
    try:
        postgres_client = get_postgres_client()
        if postgres_client is None:
            return jsonify({'success': False, 'error': 'Postgres client unavailable'}), 500
        
        # Get full analysis
        query = """
            SELECT ssa.*, ss.post_count, ss.total_engagement
            FROM social_sentiment_analysis ssa
            JOIN sentiment_sessions ss ON ssa.session_id = ss.id
            WHERE ssa.id = %s
        """
        results = postgres_client.execute_query(query, (analysis_id,))
        
        if not results:
            return jsonify({'success': False, 'error': 'Analysis not found'}), 404
        
        analysis = results[0]
        
        # Get extracted tickers
        ticker_query = """
            SELECT * FROM extracted_tickers 
            WHERE analysis_id = %s 
            ORDER BY confidence DESC
        """
        extracted_tickers = postgres_client.execute_query(ticker_query, (analysis_id,))
        
        # Get posts for session
        session_id = analysis.get('session_id')
        posts_query = """
            SELECT sp.*, sm.ticker, sm.platform
            FROM social_posts sp
            JOIN social_metrics sm ON sp.metric_id = sm.id
            WHERE sm.analysis_session_id = %s
            ORDER BY sp.engagement_score DESC
            LIMIT 10
        """
        posts = postgres_client.execute_query(posts_query, (session_id,)) if session_id else []
        
        return jsonify({
            'success': True,
            'data': {
                'analysis': {
                    'id': analysis.get('id'),
                    'ticker': analysis.get('ticker'),
                    'platform': analysis.get('platform'),
                    'sentiment_label': analysis.get('sentiment_label'),
                    'sentiment_score': analysis.get('sentiment_score'),
                    'confidence_score': analysis.get('confidence_score'),
                    'summary': analysis.get('summary'),
                    'key_themes': analysis.get('key_themes', []),
                    'reasoning': analysis.get('reasoning'),
                    'post_count': analysis.get('post_count'),
                    'total_engagement': analysis.get('total_engagement'),
                    'analyzed_at': format_datetime(analysis.get('analyzed_at'))
                },
                'extracted_tickers': [
                    {
                        'ticker': t.get('ticker'),
                        'confidence': t.get('confidence'),
                        'company_name': t.get('company_name'),
                        'is_primary': t.get('is_primary'),
                        'context': t.get('context')
                    }
                    for t in extracted_tickers
                ],
                'posts': [
                    {
                        'author': p.get('author'),
                        'content': p.get('content'),
                        'engagement_score': p.get('engagement_score'),
                        'url': p.get('url'),
                        'posted_at': format_datetime(p.get('posted_at'))
                    }
                    for p in posts[:3]  # Top 3 posts
                ]
            }
        })
    except Exception as e:
        logger.error(f"Error in AI details API: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@social_sentiment_bp.route('/api/social_sentiment/posts/<int:metric_id>')
@require_auth
def api_posts_by_metric(metric_id: int):
    """API endpoint for social posts by metric ID"""
    try:
        postgres_client = get_postgres_client()
        if postgres_client is None:
            return jsonify({'success': False, 'error': 'Postgres client unavailable'}), 500
        
        query = """
            SELECT sp.*, sm.ticker, sm.platform
            FROM social_posts sp
            JOIN social_metrics sm ON sp.metric_id = sm.id
            WHERE sp.metric_id = %s
            ORDER BY sp.engagement_score DESC
            LIMIT 10
        """
        results = postgres_client.execute_query(query, (metric_id,))
        
        formatted_posts = []
        for post in results:
            formatted_posts.append({
                'author': post.get('author'),
                'content': post.get('content'),
                'engagement_score': post.get('engagement_score'),
                'url': post.get('url'),
                'posted_at': format_datetime(post.get('posted_at')),
                'ticker': post.get('ticker'),
                'platform': post.get('platform')
            })
        
        return jsonify({
            'success': True,
            'data': formatted_posts
        })
    except Exception as e:
        logger.error(f"Error in posts API: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@social_sentiment_bp.route('/api/social_sentiment/posts/session/<int:session_id>')
@require_auth
def api_posts_by_session(session_id: int):
    """API endpoint for social posts by session ID"""
    try:
        postgres_client = get_postgres_client()
        if postgres_client is None:
            return jsonify({'success': False, 'error': 'Postgres client unavailable'}), 500
        
        query = """
            SELECT sp.*, sm.ticker, sm.platform
            FROM social_posts sp
            JOIN social_metrics sm ON sp.metric_id = sm.id
            WHERE sm.analysis_session_id = %s
            ORDER BY sp.engagement_score DESC
            LIMIT 10
        """
        results = postgres_client.execute_query(query, (session_id,))
        
        formatted_posts = []
        for post in results:
            formatted_posts.append({
                'author': post.get('author'),
                'content': post.get('content'),
                'engagement_score': post.get('engagement_score'),
                'url': post.get('url'),
                'posted_at': format_datetime(post.get('posted_at')),
                'ticker': post.get('ticker'),
                'platform': post.get('platform')
            })
        
        return jsonify({
            'success': True,
            'data': formatted_posts
        })
    except Exception as e:
        logger.error(f"Error in posts by session API: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
