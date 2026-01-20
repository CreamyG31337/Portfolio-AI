#!/usr/bin/env python3
"""
Signals Routes
==============

Flask routes for the Technical Signals dashboard page.
Provides signal analysis for individual tickers and watchlist overview.
"""

from flask import Blueprint, render_template, request, jsonify
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
import sys
from pathlib import Path

# Add parent directory to path to allow importing from root
sys.path.append(str(Path(__file__).parent.parent))

from auth import require_auth
from supabase_client import SupabaseClient
from flask_auth_utils import get_user_email_flask, get_auth_token
from flask_cache_utils import cache_resource, cache_data
from cache_version import get_cache_version
from auth import is_admin
from market_data.data_fetcher import MarketDataFetcher
from web_dashboard.signals.signal_engine import SignalEngine

logger = logging.getLogger('signals')

signals_bp = Blueprint('signals', __name__)

# Cached database clients
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

# Cached helper functions
@cache_data(ttl=300)
def get_cached_watchlist_signals(
    _supabase_client,
    _refresh_key: int = 0,
    _cache_version: str = ""
) -> List[Dict[str, Any]]:
    """Get signals for all watchlist tickers (cached)"""
    try:
        # Get watchlist from watched_tickers table
        watchlist = []
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
                            watchlist.append({
                                'ticker': ticker,
                                'priority_tier': item.get('priority_tier', 'C'),
                                'created_at': item.get('created_at')
                            })
            except Exception as e:
                logger.warning(f"Error fetching watched_tickers: {e}")
        
        if not watchlist:
            return []
        
        if not watchlist:
            return []
        
        # Get latest signals for each ticker from database
        signal_engine = SignalEngine()
        data_fetcher = MarketDataFetcher()
        results = []
        
        for ticker_data in watchlist:
            ticker = ticker_data.get('ticker')
            if not ticker:
                continue
            
            try:
                # Try to get from database first
                signal_result = _supabase_client.supabase.table("signal_analysis")\
                    .select("*")\
                    .eq("ticker", ticker.upper())\
                    .order("analysis_date", desc=True)\
                    .limit(1)\
                    .execute()
                
                if signal_result.data and len(signal_result.data) > 0:
                    # Use cached signal from database
                    signal = signal_result.data[0]
                    results.append({
                        'ticker': ticker,
                        'overall_signal': signal.get('overall_signal', 'HOLD'),
                        'confidence': signal.get('confidence_score', 0.0),
                        'fear_level': signal.get('fear_risk_signal', {}).get('fear_level', 'LOW') if isinstance(signal.get('fear_risk_signal'), dict) else 'LOW',
                        'risk_score': signal.get('fear_risk_signal', {}).get('risk_score', 0.0) if isinstance(signal.get('fear_risk_signal'), dict) else 0.0,
                        'trend': signal.get('structure_signal', {}).get('trend', 'NEUTRAL') if isinstance(signal.get('structure_signal'), dict) else 'NEUTRAL',
                        'analysis_date': signal.get('analysis_date'),
                        'cached': True
                    })
                else:
                    # Calculate on the fly if not in database
                    price_data = data_fetcher.fetch_price_data(ticker, period="6mo")
                    if not price_data.df.empty:
                        signals = signal_engine.evaluate(ticker, price_data.df)
                        results.append({
                            'ticker': ticker,
                            'overall_signal': signals.get('overall_signal', 'HOLD'),
                            'confidence': signals.get('confidence', 0.0),
                            'fear_level': signals.get('fear_risk', {}).get('fear_level', 'LOW'),
                            'risk_score': signals.get('fear_risk', {}).get('risk_score', 0.0),
                            'trend': signals.get('structure', {}).get('trend', 'NEUTRAL'),
                            'analysis_date': signals.get('analysis_date'),
                            'cached': False
                        })
            except Exception as e:
                logger.warning(f"Error processing {ticker}: {e}")
                continue
        
        return results
    except Exception as e:
        logger.error(f"Error fetching watchlist signals: {e}", exc_info=True)
        return []


# ============================================================================
# Page Routes
# ============================================================================

@signals_bp.route('/signals')
@require_auth
def signals_page():
    """Technical Signals overview page"""
    try:
        user_email = get_user_email_flask()
        
        # Get navigation context
        from app import get_navigation_context
        nav_context = get_navigation_context(current_page='signals')
        
        # Get newest signal timestamp for display
        supabase_client = get_supabase_client()
        newest_timestamp = "N/A"
        if supabase_client:
            try:
                result = supabase_client.supabase.table("signal_analysis")\
                    .select("analysis_date")\
                    .order("analysis_date", desc=True)\
                    .limit(1)\
                    .execute()
                if result.data and len(result.data) > 0:
                    newest_timestamp = result.data[0].get('analysis_date', 'N/A')
            except Exception:
                pass
        
        return render_template('signals.html',
                             user_email=user_email,
                             newest_timestamp=newest_timestamp,
                             **nav_context)
    except Exception as e:
        logger.error(f"Error rendering signals page: {e}", exc_info=True)
        return jsonify({"error": "Failed to load signals page"}), 500


# ============================================================================
# API Routes
# ============================================================================

@signals_bp.route('/api/signals/analyze/<ticker>')
@require_auth
def api_analyze_ticker(ticker: str):
    """Analyze a single ticker and return signals"""
    try:
        ticker = ticker.upper().strip()
        
        # Fetch price data
        data_fetcher = MarketDataFetcher()
        price_data = data_fetcher.fetch_price_data(ticker, period="6mo")
        
        if price_data.df.empty:
            return jsonify({
                'success': False,
                'error': f'No price data available for {ticker}'
            }), 404
        
        # Generate signals
        signal_engine = SignalEngine()
        signals = signal_engine.evaluate(ticker, price_data.df)
        
        return jsonify({
            'success': True,
            'data': signals
        })
    except Exception as e:
        logger.error(f"Error analyzing ticker {ticker}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@signals_bp.route('/api/signals/watchlist')
@require_auth
def api_watchlist_signals():
    """Get signals for all watchlist tickers"""
    try:
        refresh_key = int(request.args.get('refresh_key', 0))
        cache_version = get_cache_version()
        
        supabase_client = get_supabase_client()
        if not supabase_client:
            return jsonify({
                'success': False,
                'error': 'Database connection unavailable'
            }), 503
        
        signals = get_cached_watchlist_signals(
            supabase_client,
            refresh_key,
            cache_version
        )
        
        # Calculate summary metrics
        total = len(signals)
        buy_count = len([s for s in signals if s.get('overall_signal') == 'BUY'])
        sell_count = len([s for s in signals if s.get('overall_signal') == 'SELL'])
        hold_count = len([s for s in signals if s.get('overall_signal') == 'HOLD'])
        watch_count = len([s for s in signals if s.get('overall_signal') == 'WATCH'])
        
        fear_low = len([s for s in signals if s.get('fear_level') == 'LOW'])
        fear_moderate = len([s for s in signals if s.get('fear_level') == 'MODERATE'])
        fear_high = len([s for s in signals if s.get('fear_level') == 'HIGH'])
        fear_extreme = len([s for s in signals if s.get('fear_level') == 'EXTREME'])
        
        return jsonify({
            'success': True,
            'data': signals,
            'summary': {
                'total': total,
                'buy': buy_count,
                'sell': sell_count,
                'hold': hold_count,
                'watch': watch_count,
                'fear_low': fear_low,
                'fear_moderate': fear_moderate,
                'fear_high': fear_high,
                'fear_extreme': fear_extreme
            }
        })
    except Exception as e:
        logger.error(f"Error fetching watchlist signals: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@signals_bp.route('/api/signals/fear_risk/<ticker>')
@require_auth
def api_fear_risk(ticker: str):
    """Get fear/risk indicators for a ticker"""
    try:
        ticker = ticker.upper().strip()
        
        # Fetch price data
        data_fetcher = MarketDataFetcher()
        price_data = data_fetcher.fetch_price_data(ticker, period="6mo")
        
        if price_data.df.empty:
            return jsonify({
                'success': False,
                'error': f'No price data available for {ticker}'
            }), 404
        
        # Generate fear/risk signal only
        from web_dashboard.signals.fear_risk_signal import FearRiskSignal
        fear_risk_signal = FearRiskSignal()
        fear_risk = fear_risk_signal.evaluate(price_data.df)
        
        return jsonify({
            'success': True,
            'data': fear_risk
        })
    except Exception as e:
        logger.error(f"Error calculating fear/risk for {ticker}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@signals_bp.route('/api/signals/history/<ticker>')
@require_auth
def api_signal_history(ticker: str):
    """Get historical signal analysis for a ticker"""
    try:
        ticker = ticker.upper().strip()
        limit = int(request.args.get('limit', 30))
        
        supabase_client = get_supabase_client()
        if not supabase_client:
            return jsonify({
                'success': False,
                'error': 'Database connection unavailable'
            }), 503
        
        result = supabase_client.supabase.table("signal_analysis")\
            .select("*")\
            .eq("ticker", ticker)\
            .order("analysis_date", desc=True)\
            .limit(limit)\
            .execute()
        
        return jsonify({
            'success': True,
            'data': result.data if result.data else []
        })
    except Exception as e:
        logger.error(f"Error fetching signal history for {ticker}: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
