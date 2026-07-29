from flask import Blueprint, render_template, request, session, jsonify, Response, stream_with_context
import logging
from typing import Optional, Dict, List, Any
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone, date
import time

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from auth import require_auth
from flask_auth_utils import get_user_email_flask, get_user_id_flask
from flask_cache_utils import cache_data
from user_preferences import get_user_ai_model, get_user_preference
from flask_data_utils import (
    get_available_funds_flask, get_current_positions_flask, get_trade_log_flask,
    get_cash_balances_flask, calculate_portfolio_value_over_time_flask,
    get_fund_thesis_data_flask, calculate_performance_metrics_flask,
    get_supabase_client_flask
)
from ai_context_builder import (
    format_holdings, format_thesis, format_trades,
    format_performance_metrics, format_cash_balances,
    format_insider_trades, format_congress_trades, format_etf_context,
    aggregate_etf_changes, parse_etf_ticker_from_article_url,
)
from ollama_client import load_model_config, check_ollama_health, list_available_models
from searxng_client import check_searxng_health, get_searxng_client
from chat_context import ContextItemType
from ai_chat_handler import ChatHandler

logger = logging.getLogger(__name__)

ai_bp = Blueprint('ai', __name__)

# ============================================================================
# Market-Hours-Aware Cache TTL (AI Context Only)
# ============================================================================

def _get_ai_context_cache_ttl() -> int:
    """Get cache TTL for AI context based on market hours.

    Returns:
        - 600 (10 min) during market hours when prices change
        - 21600 (6 hours) when market closed (data static until next open)
    """
    try:
        from market_data.market_hours import MarketHours
        if MarketHours().is_market_open():
            return 600   # 10 minutes during market hours
        return 21600     # 6 hours when market closed
    except Exception as e:
        logger.warning(f"Error checking market hours for cache TTL: {e}")
        return 600       # Default to 10 min if check fails


# ============================================================================
# Cached Helper Functions
# ============================================================================

def _coerce_bool_flag(value: Any, default: bool = True) -> bool:
    """Parse JSON/form booleans reliably (avoids truthy string \"false\")."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("0", "false", "no", "off"):
            return False
        if lowered in ("1", "true", "yes", "on"):
            return True
    return bool(value)


def _portfolio_ticker_list(positions_df: Any) -> List[str]:
    """Unique uppercased tickers from a positions DataFrame."""
    if positions_df is None or getattr(positions_df, "empty", True):
        return []
    ticker_col = "ticker" if "ticker" in positions_df.columns else "symbol"
    return [
        str(t).strip().upper()
        for t in positions_df[ticker_col].dropna().unique().tolist()
        if str(t).strip()
    ]


def _congress_lookup_tickers(portfolio_tickers: List[str]) -> List[str]:
    """Expand portfolio tickers for US congress_trades (strip exchange suffixes)."""
    lookup: set[str] = set()
    for raw in portfolio_tickers:
        upper = str(raw).strip().upper()
        if not upper:
            continue
        lookup.add(upper)
        if "." in upper:
            lookup.add(upper.split(".", 1)[0])
    return sorted(lookup)


def _get_reference_data_supabase_client():
    """Supabase client for global reference tables (congress/insider trades).

    Congress and insider data are not fund-scoped; service role avoids empty
    results when the browser JWT is missing or stale for RLS.
    """
    try:
        from supabase_client import SupabaseClient
        return SupabaseClient(use_service_role=True)
    except Exception as e:
        logger.warning(f"Error creating service-role Supabase client: {e}")
        return get_supabase_client_flask()


def _get_insider_trades_for_portfolio(fund: str, days: int = 7) -> List[Dict]:
    """Get insider trades for portfolio tickers from last N days."""
    try:
        positions_df = get_current_positions_flask(fund)
        portfolio_tickers = _portfolio_ticker_list(positions_df)
        if not portfolio_tickers:
            return []

        client = _get_reference_data_supabase_client()
        if not client:
            return []
        
        # Calculate date range
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)
        
        # Query insider trades
        result = client.supabase.table("insider_trades")\
            .select("ticker, insider_name, insider_title, transaction_date, disclosure_date, type, shares, price_per_share, value")\
            .in_("ticker", portfolio_tickers)\
            .gte("transaction_date", start_date.isoformat())\
            .lte("transaction_date", end_date.isoformat())\
            .order("transaction_date", desc=True)\
            .limit(100)\
            .execute()
        
        return result.data if result.data else []
    except Exception as e:
        logger.warning(f"Error fetching insider trades: {e}")
        return []


def _get_congress_trades_for_portfolio(fund: str, days: int = 30) -> List[Dict]:
    """Get recent congress trades for portfolio tickers (default 30d — disclosure lag)."""
    try:
        positions_df = get_current_positions_flask(fund)
        portfolio_tickers = _portfolio_ticker_list(positions_df)
        if not portfolio_tickers:
            return []

        lookup_tickers = _congress_lookup_tickers(portfolio_tickers)
        if not lookup_tickers:
            return []

        client = _get_reference_data_supabase_client()
        if not client:
            return []

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        query = client.supabase.table("congress_trades_enriched")\
            .select("ticker, politician, chamber, party, state, transaction_date, type, amount, owner")\
            .in_("ticker", lookup_tickers)\
            .neq("quality_status", "garbage")\
            .gte("transaction_date", start_date.isoformat())\
            .lte("transaction_date", end_date.isoformat())\
            .order("transaction_date", desc=True)

        result = query.limit(50).execute()

        return result.data if result.data else []
    except Exception as e:
        logger.warning(f"Error fetching congress trades: {e}")
        return []


def _empty_etf_context(days: int = 7) -> Dict[str, Any]:
    return {
        "etf_summary": [],
        "ticker_summary": [],
        "recent_trades": [],
        "etf_articles": [],
        "days": days,
    }


def _filter_etf_analysis_articles(
    articles: List[Dict[str, Any]],
    portfolio_tickers: List[str],
    active_etfs: set[str],
    max_articles: int = 8,
) -> List[Dict[str, Any]]:
    """Keep ETF Analysis articles relevant to portfolio holdings or active ETFs."""
    portfolio_set = {t.strip().upper() for t in portfolio_tickers if t}
    if not portfolio_set:
        return []

    def _article_sort_key(article: Dict[str, Any]) -> str:
        fetched = article.get("fetched_at") or article.get("published_at") or ""
        return str(fetched)

    matched: List[Dict[str, Any]] = []
    seen_etfs: set[str] = set()

    for article in sorted(articles, key=_article_sort_key, reverse=True):
        raw_tickers = article.get("tickers") or []
        if isinstance(raw_tickers, str):
            raw_tickers = [raw_tickers]
        art_ticker_set = {str(t).strip().upper() for t in raw_tickers if t}
        overlap = sorted(art_ticker_set.intersection(portfolio_set))

        etf_from_url = parse_etf_ticker_from_article_url(str(article.get("url") or ""))
        url_relevant = bool(etf_from_url and etf_from_url in active_etfs)

        if not overlap and not url_relevant:
            continue

        etf_ticker = etf_from_url
        if not etf_ticker and article.get("title"):
            title = str(article["title"])
            if " Holdings Analysis" in title:
                etf_ticker = title.split(" Holdings Analysis", 1)[0].strip().upper()

        dedupe_key = etf_ticker or str(article.get("title") or article.get("id") or "")
        if dedupe_key in seen_etfs:
            continue
        seen_etfs.add(dedupe_key)

        matched.append({
            "etf_ticker": etf_ticker,
            "title": article.get("title"),
            "summary": article.get("summary"),
            "sentiment": article.get("sentiment"),
            "matched_holdings": overlap,
            "published_at": article.get("published_at"),
            "fetched_at": article.get("fetched_at"),
        })
        if len(matched) >= max_articles:
            break

    return matched


def _get_etf_context_for_portfolio(fund: str, days: int = 7) -> Dict[str, Any]:
    """Fetch ETF activity summaries, notable trades, and nightly ETF Analysis articles."""
    empty = _empty_etf_context(days)
    try:
        positions_df = get_current_positions_flask(fund)
        if positions_df.empty:
            return empty

        ticker_col = 'ticker' if 'ticker' in positions_df.columns else 'symbol'
        portfolio_tickers = [
            str(t).strip().upper()
            for t in positions_df[ticker_col].dropna().unique().tolist()
            if str(t).strip()
        ]
        if not portfolio_tickers:
            return empty

        try:
            from postgres_client import PostgresClient
            from research_repository import ResearchRepository

            pc = PostgresClient()
        except Exception as e:
            logger.warning(f"Error creating Postgres client for ETF context: {e}")
            return empty

        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        changes: List[Dict[str, Any]] = []
        try:
            rows = pc.execute_query(
                """
                SELECT date, etf_ticker, holding_ticker, share_change, percent_change,
                       action, shares_before, shares_after
                FROM etf_holdings_changes
                WHERE holding_ticker = ANY(%s)
                  AND date >= %s AND date <= %s
                ORDER BY ABS(share_change) DESC
                """,
                (portfolio_tickers, start_date.isoformat(), end_date.isoformat()),
            )
            changes = list(rows or [])
        except Exception as e:
            logger.warning(f"Error fetching ETF holdings changes: {e}")

        aggregates = aggregate_etf_changes(changes)
        active_etfs = {row["etf_ticker"] for row in aggregates.get("etf_summary", [])}

        recent_trades: List[Dict[str, Any]] = []
        for row in changes[:50]:
            recent_trades.append({
                "trade_date": row.get("date"),
                "etf_ticker": row.get("etf_ticker"),
                "holding_ticker": row.get("holding_ticker"),
                "trade_type": row.get("action"),
                "shares_change": row.get("share_change"),
                "shares_after": row.get("shares_after"),
                "percent_change": row.get("percent_change"),
            })

        etf_articles: List[Dict[str, Any]] = []
        try:
            repo = ResearchRepository(postgres_client=pc)
            raw_articles = repo.get_recent_articles(
                limit=30,
                days=days,
                article_type="ETF Analysis",
            )
            etf_articles = _filter_etf_analysis_articles(
                raw_articles,
                portfolio_tickers,
                active_etfs,
            )
        except Exception as e:
            logger.warning(f"Error fetching ETF Analysis articles: {e}")

        return {
            "etf_summary": aggregates.get("etf_summary", []),
            "ticker_summary": aggregates.get("ticker_summary", []),
            "recent_trades": recent_trades,
            "etf_articles": etf_articles,
            "days": days,
        }
    except Exception as e:
        logger.warning(f"Error fetching ETF context: {e}")
        return empty


def _get_etf_trades_for_portfolio(fund: str, days: int = 7) -> List[Dict]:
    """Backward-compatible wrapper: returns detail trade rows from ETF context."""
    ctx = _get_etf_context_for_portfolio(fund, days=days)
    return ctx.get("recent_trades", [])


@cache_data(ttl=300)
def _get_context_data_packet(user_id: str, fund: str):
    """Get context data packet with caching (300s TTL)"""
    logger.info(f"Refreshing context data for {user_id}/{fund}")
    
    timings = {}
    total_start = time.time()
    
    # Fetch all components
    t0 = time.time()
    positions_df = get_current_positions_flask(fund)
    timings['positions'] = round((time.time() - t0) * 1000, 1)
    
    t0 = time.time()
    trades_df = get_trade_log_flask(limit=100, fund=fund)
    timings['trades'] = round((time.time() - t0) * 1000, 1)
    
    try:
        t0 = time.time()
        metrics = calculate_performance_metrics_flask(fund)
        portfolio_df = calculate_portfolio_value_over_time_flask(fund, days=365)
        timings['metrics+portfolio'] = round((time.time() - t0) * 1000, 1)
    except Exception as e:
        logger.warning(f"Error loading metrics: {e}")
        metrics = None
        portfolio_df = None
        timings['metrics+portfolio'] = 'error'
        
    try:
        t0 = time.time()
        cash = get_cash_balances_flask(fund)
        timings['cash'] = round((time.time() - t0) * 1000, 1)
    except Exception as e:
        logger.warning(f"Error loading cash: {e}")
        cash = None
        timings['cash'] = 'error'
        
    try:
        t0 = time.time()
        thesis_data = get_fund_thesis_data_flask(fund)
        timings['thesis'] = round((time.time() - t0) * 1000, 1)
    except Exception as e:
        logger.warning(f"Error loading thesis: {e}")
        thesis_data = None
        timings['thesis'] = 'error'
    
    # Fetch trade data (last 7 days)
    try:
        t0 = time.time()
        insider_trades = _get_insider_trades_for_portfolio(fund, days=7)
        timings['insider_trades'] = round((time.time() - t0) * 1000, 1)
    except Exception as e:
        logger.warning(f"Error loading insider trades: {e}")
        insider_trades = []
        timings['insider_trades'] = 'error'
    
    try:
        t0 = time.time()
        congress_trades = _get_congress_trades_for_portfolio(fund, days=30)
        timings['congress_trades'] = round((time.time() - t0) * 1000, 1)
    except Exception as e:
        logger.warning(f"Error loading congress trades: {e}")
        congress_trades = []
        timings['congress_trades'] = 'error'
    
    try:
        t0 = time.time()
        etf_context = _get_etf_context_for_portfolio(fund, days=7)
        timings['etf_context'] = round((time.time() - t0) * 1000, 1)
    except Exception as e:
        logger.warning(f"Error loading ETF context: {e}")
        etf_context = _empty_etf_context(7)
        timings['etf_context'] = 'error'
    
    timings['total_data_fetch'] = round((time.time() - total_start) * 1000, 1)
    logger.info(f"[PERF] Context data fetch timings (ms): {timings}")
        
    return {
        'positions_df': positions_df,
        'trades_df': trades_df,
        'metrics': metrics,
        'portfolio_df': portfolio_df,
        'cash': cash,
        'thesis_data': thesis_data,
        'insider_trades': insider_trades,
        'congress_trades': congress_trades,
        'congress_trades_days': 30,
        'etf_context': etf_context,
        '_timings': timings
    }


def _build_context_from_packet(
    fund: str,
    data_packet: Dict[str, Any],
    include_thesis: bool,
    include_trades: bool,
    include_price_volume: bool,
    include_fundamentals: bool,
    include_insider_trades: bool = True,
    include_congress_trades: bool = True,
    include_etf_trades: bool = True,
    include_intelligence_pulse: bool = True,
) -> tuple:
    """Build context string from a pre-fetched data packet.
    
    Returns:
        tuple: (context_string, format_timings_dict)
    """
    import pandas as pd
    format_timings = {}
    total_format_start = time.time()
    
    # Guard against None from cache/data layer to avoid AttributeError/TypeError (e.g. len(None))
    positions_df = data_packet.get('positions_df')
    trades_df = data_packet.get('trades_df')
    # #region agent log
    try:
        _debug_log_preview("ai_routes:_build_context_from_packet:entry", "data_packet df types", {"positions_type": type(positions_df).__name__ if positions_df is not None else "None", "trades_type": type(trades_df).__name__ if trades_df is not None else "None", "hypothesisId": "B"})
    except Exception:
        pass
    # #endregion
    if positions_df is None:
        positions_df = pd.DataFrame()
    if trades_df is None:
        trades_df = pd.DataFrame()
    metrics = data_packet.get('metrics')
    portfolio_df = data_packet['portfolio_df']
    cash = data_packet['cash']
    thesis_data = data_packet['thesis_data']
    insider_trades = data_packet.get('insider_trades', [])
    congress_trades = data_packet.get('congress_trades', [])
    etf_context = data_packet.get('etf_context') or _empty_etf_context()

    context_parts = []

    if include_intelligence_pulse:
        t0 = time.time()
        try:
            from ai_intelligence_pulse import build_and_format_intelligence_pulse

            pulse_text = build_and_format_intelligence_pulse(fund)
            if pulse_text:
                context_parts.append(pulse_text)
        except Exception as e:
            logger.warning(f"Error building intelligence pulse: {e}")
        format_timings['format_intelligence_pulse'] = round((time.time() - t0) * 1000, 1)

    if not positions_df.empty:
        t0 = time.time()
        holdings_text = format_holdings(
            positions_df,
            fund,
            trades_df=trades_df,
            include_price_volume=include_price_volume,
            include_fundamentals=include_fundamentals
        )
        format_timings['format_holdings'] = round((time.time() - t0) * 1000, 1)
        context_parts.append(holdings_text)

    if metrics:
        t0 = time.time()
        context_parts.append(format_performance_metrics(metrics, portfolio_df))
        format_timings['format_metrics'] = round((time.time() - t0) * 1000, 1)

    if cash:
        t0 = time.time()
        context_parts.append(format_cash_balances(cash))
        format_timings['format_cash'] = round((time.time() - t0) * 1000, 1)

    if include_thesis and thesis_data:
        t0 = time.time()
        context_parts.append(format_thesis(thesis_data))
        format_timings['format_thesis'] = round((time.time() - t0) * 1000, 1)

    if include_trades and not trades_df.empty:
        t0 = time.time()
        context_parts.append(format_trades(trades_df, limit=100))
        format_timings['format_trades'] = round((time.time() - t0) * 1000, 1)

    if include_insider_trades and insider_trades:
        t0 = time.time()
        context_parts.append(format_insider_trades(insider_trades, limit=50))
        format_timings['format_insider_trades'] = round((time.time() - t0) * 1000, 1)

    if include_congress_trades and congress_trades:
        t0 = time.time()
        congress_days = int(data_packet.get('congress_trades_days') or 30)
        context_parts.append(format_congress_trades(congress_trades, limit=50, days=congress_days))
        format_timings['format_congress_trades'] = round((time.time() - t0) * 1000, 1)

    if include_etf_trades:
        t0 = time.time()
        context_parts.append(format_etf_context(etf_context, detail_limit=50))
        format_timings['format_etf_context'] = round((time.time() - t0) * 1000, 1)

    format_timings['total_format'] = round((time.time() - total_format_start) * 1000, 1)
    
    context_string = "\n\n---\n\n".join(context_parts) if context_parts else "No context data available"
    return context_string, format_timings


def _get_preview_context_string(
    user_id: str,
    fund: str,
    include_thesis: bool,
    include_trades: bool,
    include_price_volume: bool,
    include_fundamentals: bool,
    include_insider_trades: bool = True,
    include_congress_trades: bool = True,
    include_etf_trades: bool = True,
    include_intelligence_pulse: bool = True,
) -> tuple:
    """Build preview context string with market-hours-aware caching.

    Cache TTL:
    - 10 min during market hours (data changes)
    - 6 hours when market closed (data static)

    Cache key includes all toggle parameters, so different configurations
    get separate cache entries.

    Returns:
        tuple: (context_string, all_timings_dict)
    """
    from flask_cache_utils import _get_cache, _make_cache_key

    # Generate cache key from all parameters
    cache_key = _make_cache_key(
        '_get_preview_context_string',
        (user_id, fund, include_thesis, include_trades, include_price_volume,
         include_fundamentals, include_insider_trades, include_congress_trades,
         include_etf_trades, include_intelligence_pulse),
        {}
    )

    # Try cache first
    cache = _get_cache()
    try:
        cached_value = cache.get(cache_key)
        if cached_value is not None:
            logger.debug(f"[PERF] AI context cache HIT for {fund}")
            return cached_value
    except Exception as e:
        logger.warning(f"Cache get error: {e}")

    # Cache miss - generate context
    logger.debug(f"[PERF] AI context cache MISS for {fund} - generating...")

    data_packet = _get_context_data_packet(user_id, fund)
    data_timings = data_packet.get('_timings', {})

    context_string, format_timings = _build_context_from_packet(
        fund=fund,
        data_packet=data_packet,
        include_thesis=include_thesis,
        include_trades=include_trades,
        include_price_volume=include_price_volume,
        include_fundamentals=include_fundamentals,
        include_insider_trades=include_insider_trades,
        include_congress_trades=include_congress_trades,
        include_etf_trades=include_etf_trades,
        include_intelligence_pulse=include_intelligence_pulse,
    )

    # Combine all timings
    all_timings = {
        'data_fetch': data_timings,
        'formatting': format_timings
    }
    logger.info(f"[PERF] Context generation complete - timings (ms): {all_timings}")

    result = (context_string, all_timings)

    # Cache with dynamic TTL based on market hours.
    # Degraded pulse (research DB down / empty candidates) must not stick for 6h
    # after the cash session closes — that masked Chimera empties while an older
    # Webull cache still looked fine.
    ttl = _get_ai_context_cache_ttl()
    if include_intelligence_pulse and (
        "Market: (unavailable" in context_string
        or "Top candidates (0)" in context_string
    ):
        ttl = min(ttl, 90)
    try:
        cache.set(cache_key, result, timeout=ttl)
        logger.debug(f"[PERF] AI context cached for {fund} with TTL={ttl}s")
    except Exception as e:
        logger.warning(f"Cache set error: {e}")

    return result

@cache_data(ttl=30)
def _get_cached_ollama_health():
    """Check Ollama health with 30s cache"""
    return check_ollama_health()

@cache_data(ttl=30)
def _get_cached_searxng_health():
    """Check SearXNG health with 30s cache"""
    return check_searxng_health()

@cache_data(ttl=30)
def _get_cached_ollama_models():
    """Get available Ollama models with 30s cache"""
    return list_available_models()

@cache_data(ttl=30)
def _get_formatted_ai_models():
    """Get formatted AI models list with 30s cache"""
    try:
        from ai_service_keys import get_model_display_name
    except ImportError:
        def get_model_display_name(m): return m

    try:
        all_models = list_available_models()
    except Exception as e:
        logger.error("list_available_models failed for model picker: %s", e, exc_info=True)
        all_models = []

    formatted_models = []
    for model in all_models:
        try:
            if model.startswith("glm-"):
                # Only expose GLM in the selectable list when the API key is set
                try:
                    from glm_config import get_zhipu_api_key
                    if not get_zhipu_api_key():
                        continue
                except ImportError:
                    continue
                display_name = "GLM " + model[4:].replace("-", " ") if len(model) > 4 else model
                formatted_models.append({"id": model, "name": display_name, "type": "glm"})
                continue

            # Check for web-based AI models
            try:
                from webai_wrapper import is_webai_model
                is_webai = is_webai_model(model)
            except ImportError:
                is_webai = False

            display_name = model
            if is_webai:
                try:
                    display_name = get_model_display_name(model)
                    # Add sparkle to webai models if not already there
                    if 'AI' in display_name:
                         display_name = f"✨ {display_name}"
                except Exception:
                    pass

            formatted_models.append({
                'id': model,
                'name': display_name,
                'type': 'webai' if is_webai else 'ollama'
            })
        except Exception as e:
            logger.warning("Skipping model %r in formatted list: %s", model, e)

    return formatted_models

# ============================================================================
# Page Routes
# ============================================================================

@ai_bp.route('/ai_assistant')
@require_auth
def ai_assistant_page():
    """AI Assistant chat interface page (Flask v2)"""
    try:
        user_email = get_user_email_flask()
        default_model = get_user_ai_model()
        
        # Get available funds (cached)
        available_funds = get_available_funds_flask()
        
        # Get available models (cached)
        ollama_models = _get_cached_ollama_models()
        ollama_available = _get_cached_ollama_health()
        searxng_available = _get_cached_searxng_health()
        
        # Get model configuration for context limits
        model_config = load_model_config()
        
        # Check for WebAI models
        try:
            from webai_wrapper import get_webai_models
            webai_models = get_webai_models()
            has_webai = True
        except (ImportError, FileNotFoundError):
            webai_models = []
            has_webai = False
        
        # Get navigation context
        from app import get_navigation_context  # Import here to avoid circular import
        nav_context = get_navigation_context(current_page='ai_assistant')

        # Prewarm default context data for fast initial load
        try:
            if available_funds:
                default_fund = available_funds[0]
                _get_context_data_packet(get_user_id_flask(), default_fund)
        except Exception as e:
            logger.debug(f"Context prewarm skipped: {e}")
        
        return render_template('ai_assistant.html',
                             user_email=user_email,
                             default_model=default_model,
                             ollama_models=ollama_models,
                             ollama_available=ollama_available,
                             searxng_available=searxng_available,
                             webai_models=webai_models,
                             has_webai=has_webai,
                             model_config=model_config,
                             **nav_context)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Error loading AI assistant page: {e}\n{tb}")
        # Show full stack trace on page for debugging
        return f'''<!DOCTYPE html>
<html>
<head><title>Error - AI Assistant</title></head>
<body style="background:#1a1a2e;color:#eee;font-family:monospace;padding:20px;">
<h1 style="color:#ff6b6b;">❌ Failed to load AI Assistant Page</h1>
<h2 style="color:#feca57;">Exception: {type(e).__name__}</h2>
<pre style="background:#16213e;padding:20px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;">{e}</pre>
<h3 style="color:#54a0ff;">Stack Trace:</h3>
<pre style="background:#16213e;padding:20px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;">{tb}</pre>
<p><a href="/" style="color:#5f27cd;">← Back to Dashboard</a></p>
</body>
</html>''', 500

# ============================================================================
# API Endpoints
# ============================================================================

@ai_bp.route('/api/v2/ai/search', methods=['POST'])
@require_auth
def api_ai_search():
    """Perform web search"""
    try:
        data = request.get_json()
        query = data.get('query')
        
        if not query:
            return jsonify({"error": "No query provided"}), 400
            
        client = get_searxng_client()
        
        if not client:
            return jsonify({"error": "Search is unavailable"}), 503
            
        results = client.search(query)
        return jsonify({"results": results})
        
    except Exception as e:
        logger.error(f"Error performing search: {e}")
        return jsonify({"error": str(e)}), 500

# #region agent log
def _debug_log_preview(location: str, message: str, data: dict) -> None:
    import json
    _path = r"c:\Users\cream\OneDrive\Documents\LLM-Micro-Cap-trading-bot\.cursor\debug.log"
    try:
        with open(_path, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"location": location, "message": message, "data": data, "timestamp": __import__("time").time(), "sessionId": "debug-session"}) + "\n")
    except Exception:
        pass
# #endregion

@ai_bp.route('/api/v2/ai/preview_context', methods=['POST'])
@require_auth
def api_ai_preview_context():
    """Preview the AI context (debug mode) - Shows the raw data tables sent to LLM"""
    try:
        data = request.get_json()
        fund = data.get('fund')
        
        if not fund:
            return jsonify({"error": "No fund specified"}), 400

        user_id = get_user_id_flask()
        # #region agent log
        _debug_log_preview("ai_routes:api_ai_preview_context:entry", "preview_context request", {"fund": fund, "user_id": str(user_id)[:8] if user_id else None, "hypothesisId": "A"})
        # #endregion

        include_pv = data.get('include_price_volume', True)
        include_fund = data.get('include_fundamentals', True)
        include_thesis = data.get('include_thesis', False)
        include_trades = data.get('include_trades', False)
        include_insider_trades = _coerce_bool_flag(data.get('include_insider_trades'), True)
        include_congress_trades = _coerce_bool_flag(data.get('include_congress_trades'), True)
        include_etf_trades = _coerce_bool_flag(data.get('include_etf_trades'), True)
        include_intelligence_pulse = _coerce_bool_flag(
            data.get('include_intelligence_pulse'), True
        )

        context_string, timings = _get_preview_context_string(
            user_id=user_id,
            fund=fund,
            include_thesis=include_thesis,
            include_trades=include_trades,
            include_price_volume=include_pv,
            include_fundamentals=include_fund,
            include_insider_trades=include_insider_trades,
            include_congress_trades=include_congress_trades,
            include_etf_trades=include_etf_trades,
            include_intelligence_pulse=include_intelligence_pulse,
        )
        # #region agent log
        _debug_log_preview("ai_routes:api_ai_preview_context:after_build", "context_string result", {"type": type(context_string).__name__ if context_string is not None else "NoneType", "len": len(context_string) if context_string is not None else None, "hypothesisId": "A"})
        # #endregion
        # Normalize to str and safe char_count to avoid "object of type 'NoneType' has no len()"
        if context_string is None:
            context_string = ""
        char_count = len(context_string)

        return jsonify({
            "success": True,
            "context": context_string,
            "char_count": char_count,
            "timings": timings  # Performance timings for browser console
        })

    except Exception as e:
        logger.error(f"Error generating context preview: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@ai_bp.route('/api/v2/ai/models', methods=['GET'])
@require_auth
def api_ai_models():
    """Get available AI models with user's preferred default"""
    formatted_models: list[dict[str, str]] = []
    default_model: Optional[str] = None
    errors: list[str] = []

    try:
        formatted_models = _get_formatted_ai_models()
    except Exception as e:
        logger.error("Error formatting AI models: %s", e, exc_info=True)
        errors.append("models_unavailable")

    try:
        default_model = get_user_ai_model()
    except Exception as e:
        logger.warning("Error resolving user default AI model: %s", e, exc_info=True)
        errors.append("default_model_unavailable")
        try:
            from model_registry import get_primary_model
            default_model = get_primary_model()
        except Exception:
            default_model = None

    if not formatted_models and default_model:
        formatted_models = [{
            "id": default_model,
            "name": default_model,
            "type": "glm" if str(default_model).startswith("glm-") else "ollama",
        }]

    if not formatted_models:
        return jsonify({
            "error": "No AI models available",
            "details": errors,
        }), 503

    model_ids = [m["id"] for m in formatted_models if m.get("id")]
    if default_model and model_ids and default_model not in model_ids:
        from model_registry import resolve_ai_model_preference
        default_model = resolve_ai_model_preference(default_model, model_ids)

    payload: dict[str, object] = {
        "models": formatted_models,
        "default_model": default_model,
    }
    if errors:
        payload["warnings"] = errors
    return jsonify(payload)

@ai_bp.route('/api/v2/ai/context/build', methods=['POST'])
@require_auth
def api_ai_context_build():
    """Build context string with portfolio data tables (called by JS before chat)"""
    try:
        data = request.get_json()
        fund = data.get('fund')
        
        logger.info(f"[Context Build] Request received for fund: {fund}")
        
        if not fund:
            logger.warning("[Context Build] No fund specified, returning empty context")
            return jsonify({"context_string": "", "char_count": 0})

        user_id = get_user_id_flask()
        data_packet = _get_context_data_packet(user_id, fund)
        positions_df = data_packet['positions_df']
        trades_df = data_packet['trades_df']

        logger.info(f"[Context Build] Positions count: {len(positions_df) if positions_df is not None else 0}")
        logger.info(f"[Context Build] Trades count: {len(trades_df) if trades_df is not None else 0}")

        include_pv = data.get('include_price_volume', True)
        include_fund = data.get('include_fundamentals', True)
        include_insider_trades = _coerce_bool_flag(data.get('include_insider_trades'), True)
        include_congress_trades = _coerce_bool_flag(data.get('include_congress_trades'), True)
        include_etf_trades = _coerce_bool_flag(data.get('include_etf_trades'), True)
        include_intelligence_pulse = _coerce_bool_flag(
            data.get('include_intelligence_pulse'), True
        )

        context_string, _format_timings = _build_context_from_packet(
            fund=fund,
            data_packet=data_packet,
            include_thesis=data.get('include_thesis', False),
            include_trades=data.get('include_trades', False),
            include_price_volume=include_pv,
            include_fundamentals=include_fund,
            include_insider_trades=include_insider_trades,
            include_congress_trades=include_congress_trades,
            include_etf_trades=include_etf_trades,
            include_intelligence_pulse=include_intelligence_pulse,
        )
        context_parts = context_string.split("\n\n---\n\n") if context_string else []
        
        logger.info(f"[Context Build] Final context length: {len(context_string)} chars, {len(context_parts)} parts")
        
        return jsonify({
            "context_string": context_string,
            "char_count": len(context_string)
        })
        
    except Exception as e:
        logger.error(f"Error building context: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@ai_bp.route('/api/v2/ai/context', methods=['GET', 'POST'])
@require_auth
def api_ai_context():
    """Get or update context items"""
    try:
        import json as json_lib
        
        user_id = get_user_id_flask()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        
        # Initialize context in session if needed
        if 'ai_context_items' not in session:
            session['ai_context_items'] = []
        
        if request.method == 'GET':
            # Return current context items
            context_items = session.get('ai_context_items', [])
            # Convert to serializable format
            items = []
            for item_dict in context_items:
                items.append({
                    'item_type': item_dict['item_type'],
                    'fund': item_dict.get('fund'),
                    'metadata': item_dict.get('metadata', {})
                })
            return jsonify({"items": items})
        
        elif request.method == 'POST':
            # Add or remove context item
            data = request.get_json()
            action = data.get('action')  # 'add', 'remove', or 'clear'
            
            # Handle clear action first
            if action == 'clear':
                session['ai_context_items'] = []
                return jsonify({"success": True, "message": "All items cleared"})
            
            # For add/remove actions, validate item_type
            item_type_str = data.get('item_type')
            fund = data.get('fund')
            metadata = data.get('metadata', {})
            
            try:
                item_type = ContextItemType(item_type_str)
            except ValueError:
                return jsonify({"error": f"Invalid item type: {item_type_str}"}), 400
            
            context_items = session.get('ai_context_items', [])
            
            # Create item dict for comparison
            item_dict = {
                'item_type': item_type_str,
                'fund': fund,
                'metadata': metadata
            }
            
            if action == 'add':
                # Check if already exists
                if item_dict not in context_items:
                    context_items.append(item_dict)
                    session['ai_context_items'] = context_items
                    return jsonify({"success": True, "message": "Item added"})
                else:
                    return jsonify({"success": False, "message": "Item already exists"})
            
            elif action == 'remove':
                if item_dict in context_items:
                    context_items.remove(item_dict)
                    session['ai_context_items'] = context_items
                    return jsonify({"success": True, "message": "Item removed"})
                else:
                    return jsonify({"success": False, "message": "Item not found"})
            
            else:
                return jsonify({"error": f"Invalid action: {action}"}), 400
    
    except Exception as e:
        logger.error(f"Error managing context: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@ai_bp.route('/api/v2/ai/repository', methods=['POST'])
@require_auth
def api_ai_repository():
    """Search research repository (RAG)"""
    try:
        from ollama_client import get_ollama_client
        from research_repository import ResearchRepository
        
        if not check_ollama_health():
            return jsonify({"error": "Ollama unavailable (required for embeddings)"}), 503
        
        data = request.get_json()
        user_query = data.get('query', '')
        max_results = data.get('max_results', 3)
        min_similarity = data.get('min_similarity', 0.6)
        
        # Generate embedding
        client = get_ollama_client()
        if not client:
            return jsonify({"error": "Ollama client not available"}), 503
        
        query_embedding = client.generate_embedding(user_query)
        if not query_embedding:
            return jsonify({"error": "Failed to generate embedding"}), 500
        
        # Search repository
        repo = ResearchRepository()
        articles = repo.search_similar_articles(
            query_embedding=query_embedding,
            limit=max_results,
            min_similarity=min_similarity
        )
        
        return jsonify({
            "success": True,
            "articles": articles
        })
    
    except Exception as e:
        logger.error(f"Error searching repository: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@ai_bp.route('/api/v2/ai/portfolio-intelligence', methods=['POST'])
@require_auth
def api_ai_portfolio_intelligence():
    """Check portfolio news from research repository"""
    try:
        from research_repository import ResearchRepository
        
        data = request.get_json()
        fund = data.get('fund')
        
        if not fund:
            return jsonify({"error": "Fund is required"}), 400
        
        # Initialize repository
        repo = ResearchRepository()
        
        # Get portfolio tickers
        portfolio_tickers = set()
        positions_df = get_current_positions_flask(fund)
        if not positions_df.empty and 'ticker' in positions_df.columns:
            portfolio_tickers = {t.strip().upper() for t in positions_df['ticker'].dropna().unique()}
        
        if not portfolio_tickers:
            return jsonify({
                "success": False,
                "message": "No positions found in current portfolio to check.",
                "matching_articles": []
            })
        
        # Fetch recent articles
        recent_articles = repo.get_recent_articles(limit=50, days=7)
        
        # Filter for holdings
        matching_articles = []
        seen_titles = set()
        
        for article in recent_articles:
            article_tickers = article.get('tickers')
            if not article_tickers:
                continue
            
            art_ticker_set = {t.upper() for t in article_tickers}
            matches = art_ticker_set.intersection(portfolio_tickers)
            
            if matches and article['title'] not in seen_titles:
                matching_articles.append({
                    'title': article.get('title'),
                    'matched_holdings': list(matches),
                    'summary': article.get('summary', 'No summary'),
                    'conclusion': article.get('conclusion', 'N/A'),
                    'source': article.get('source', 'Unknown'),
                    'published_at': article.get('published_at', '')
                })
                seen_titles.add(article['title'])
        
        return jsonify({
            "success": True,
            "matching_articles": matching_articles,
            "count": len(matching_articles)
        })
    
    except Exception as e:
        logger.error(f"Error checking portfolio news: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@ai_bp.route('/api/v2/ai/chat/session', methods=['GET'])
@require_auth
def api_ai_chat_session():
    """Load persisted AI Assistant transcript for the current user + fund."""
    try:
        from ai_assistant_session import load_chat

        user_id = get_user_id_flask()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        fund = (request.args.get("fund") or "").strip()
        if not fund:
            return jsonify({"error": "fund is required"}), 400
        try:
            from ai_assistant_clients import user_can_access_fund

            if not user_can_access_fund(fund):
                return jsonify({"error": "Fund not accessible"}), 403
        except Exception:
            # Fall through — service still scopes by user_id.
            pass
        data = load_chat(user_id, fund)
        return jsonify({"ok": True, **data})
    except Exception as e:
        logger.error("api_ai_chat_session failed: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@ai_bp.route('/api/v2/ai/chat/append', methods=['POST'])
@require_auth
def api_ai_chat_append():
    """Append completed turns (or replace with a capped full list) for user+fund."""
    try:
        from ai_assistant_session import append_turns, replace_messages

        user_id = get_user_id_flask()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        data = request.get_json(silent=True) or {}
        fund = str(data.get("fund") or "").strip()
        if not fund:
            return jsonify({"error": "fund is required"}), 400
        try:
            from ai_assistant_clients import user_can_access_fund

            if not user_can_access_fund(fund):
                return jsonify({"error": "Fund not accessible"}), 403
        except Exception:
            pass
        model = data.get("model")
        # Prefer append of new turns; accept full messages[] replace from client.
        if isinstance(data.get("turns"), list) and data.get("turns"):
            out = append_turns(user_id, fund, data["turns"], model=model)
        elif isinstance(data.get("messages"), list):
            out = replace_messages(user_id, fund, data["messages"], model=model)
        else:
            return jsonify({"error": "turns or messages required"}), 400
        return jsonify({"ok": True, **out})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("api_ai_chat_append failed: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@ai_bp.route('/api/v2/ai/chat/clear', methods=['POST'])
@require_auth
def api_ai_chat_clear():
    """Clear persisted transcript for user+fund and reset WebAI disk session."""
    try:
        from ai_assistant_session import clear_chat, reset_webai_session

        user_id = get_user_id_flask()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        data = request.get_json(silent=True) or {}
        fund = str(data.get("fund") or request.args.get("fund") or "").strip()
        if not fund:
            return jsonify({"error": "fund is required"}), 400
        try:
            from ai_assistant_clients import user_can_access_fund

            if not user_can_access_fund(fund):
                return jsonify({"error": "Fund not accessible"}), 403
        except Exception:
            pass
        clear_chat(user_id, fund)
        reset_webai_session(user_id)
        return jsonify({"ok": True, "fund": fund, "messages": []})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("api_ai_chat_clear failed: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@ai_bp.route('/api/v2/ai/chat', methods=['POST'])
@require_auth
def api_ai_chat():
    """Handle chat message and stream AI response"""
    try:
        user_id = get_user_id_flask()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401
        
        data = request.get_json()
        user_query = data.get('query', '')
        model = data.get('model')
        fund = data.get('fund')
        context_items = data.get('context_items', [])
        conversation_history = data.get('conversation_history', [])
        search_results = data.get('search_results')
        repository_articles = data.get('repository_articles')
        
        if not user_query:
            return jsonify({"error": "Query is required"}), 400
        
        # Use pre-built context string if provided, otherwise build it
        context_string = data.get('context_string', '')
        
        # Backend protection: If first message and context is empty, wait briefly
        is_first_message = len(conversation_history) <= 1
        if is_first_message and not context_string and not context_items:
            logger.warning("First message with empty context, waiting for context to be available...")
            import time
            # Wait up to 5 seconds for context items
            for attempt in range(50):  # 50 * 100ms = 5 seconds
                if 'ai_context_items' in session and session['ai_context_items']:
                    context_items = session['ai_context_items']
                    logger.info(f"Backend found {len(context_items)} context items after waiting")
                    break
                time.sleep(0.1)
            
            if not context_items:
                logger.warning("No context available after waiting, proceeding without context")
        
        # Build context if not provided
        if not context_string and context_items:
            handler = ChatHandler(user_id=user_id, model=model, fund=fund)
            options = {
                'include_price_volume': data.get('include_price_volume', True),
                'include_fundamentals': data.get('include_fundamentals', True),
                'include_insider_trades': data.get('include_insider_trades', True),
                'include_congress_trades': data.get('include_congress_trades', True),
                'include_etf_trades': data.get('include_etf_trades', True)
            }
            context_string = handler.build_context(context_items, options)
        
        # Extract include_search preference (defaults to True for backward compatibility)
        include_search = data.get('include_search', True)
        
        # Use ChatHandler to route to appropriate backend
        handler = ChatHandler(user_id=user_id, model=model, fund=fund)
        return handler.handle_chat(
            query=user_query,
            context_string=context_string,
            conversation_history=conversation_history,
            search_results=search_results,
            repository_articles=repository_articles,
            include_search=include_search
        )
    
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
