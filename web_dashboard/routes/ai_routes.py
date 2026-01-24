from flask import Blueprint, render_template, request, session, jsonify, Response, stream_with_context
import logging
from typing import Optional, Dict, List, Any
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from auth import require_auth
from flask_auth_utils import get_user_email_flask, get_user_id_flask
from flask_cache_utils import cache_data
from user_preferences import get_user_theme, get_user_ai_model, get_user_preference
from flask_data_utils import (
    get_available_funds_flask, get_current_positions_flask, get_trade_log_flask,
    get_cash_balances_flask, calculate_portfolio_value_over_time_flask,
    get_fund_thesis_data_flask, calculate_performance_metrics_flask
)
from ai_context_builder import (
    format_holdings, format_thesis, format_trades,
    format_performance_metrics, format_cash_balances
)
from ollama_client import load_model_config, check_ollama_health, list_available_models
from searxng_client import check_searxng_health, get_searxng_client
from chat_context import ContextItemType
from ai_chat_handler import ChatHandler

logger = logging.getLogger(__name__)

ai_bp = Blueprint('ai', __name__)

# ============================================================================
# Cached Helper Functions
# ============================================================================

@cache_data(ttl=300)
def _get_context_data_packet(user_id: str, fund: str):
    """Get context data packet with caching (300s TTL)"""
    logger.info(f"Refreshing context data for {user_id}/{fund}")
    
    # Fetch all components
    positions_df = get_current_positions_flask(fund)
    trades_df = get_trade_log_flask(limit=100, fund=fund)
    
    try:
        metrics = calculate_performance_metrics_flask(fund)
        portfolio_df = calculate_portfolio_value_over_time_flask(fund, days=365)
    except Exception as e:
        logger.warning(f"Error loading metrics: {e}")
        metrics = None
        portfolio_df = None
        
    try:
        cash = get_cash_balances_flask(fund)
    except Exception as e:
        logger.warning(f"Error loading cash: {e}")
        cash = None
        
    try:
        thesis_data = get_fund_thesis_data_flask(fund)
    except Exception as e:
        logger.warning(f"Error loading thesis: {e}")
        thesis_data = None
        
    return {
        'positions_df': positions_df,
        'trades_df': trades_df,
        'metrics': metrics,
        'portfolio_df': portfolio_df,
        'cash': cash,
        'thesis_data': thesis_data
    }


def _build_context_from_packet(
    fund: str,
    data_packet: Dict[str, Any],
    include_thesis: bool,
    include_trades: bool,
    include_price_volume: bool,
    include_fundamentals: bool
) -> str:
    """Build context string from a pre-fetched data packet."""
    positions_df = data_packet['positions_df']
    trades_df = data_packet['trades_df']
    metrics = data_packet['metrics']
    portfolio_df = data_packet['portfolio_df']
    cash = data_packet['cash']
    thesis_data = data_packet['thesis_data']

    context_parts = []

    if not positions_df.empty:
        holdings_text = format_holdings(
            positions_df,
            fund,
            trades_df=trades_df,
            include_price_volume=include_price_volume,
            include_fundamentals=include_fundamentals
        )
        context_parts.append(holdings_text)

    if metrics:
        context_parts.append(format_performance_metrics(metrics, portfolio_df))

    if cash:
        context_parts.append(format_cash_balances(cash))

    if include_thesis and thesis_data:
        context_parts.append(format_thesis(thesis_data))

    if include_trades and not trades_df.empty:
        context_parts.append(format_trades(trades_df, limit=100))

    return "\n\n---\n\n".join(context_parts) if context_parts else "No context data available"


def _get_preview_context_string(
    user_id: str,
    fund: str,
    include_thesis: bool,
    include_trades: bool,
    include_price_volume: bool,
    include_fundamentals: bool
) -> str:
    """Build preview context string from cached data."""
    data_packet = _get_context_data_packet(user_id, fund)
    return _build_context_from_packet(
        fund=fund,
        data_packet=data_packet,
        include_thesis=include_thesis,
        include_trades=include_trades,
        include_price_volume=include_price_volume,
        include_fundamentals=include_fundamentals
    )

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

    all_models = list_available_models()
    formatted_models = []
    for model in all_models:
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
            except:
                pass
        
        formatted_models.append({
            'id': model,
            'name': display_name,
            'type': 'webai' if is_webai else 'ollama'
        })
    
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
        user_theme = get_user_theme() or 'system'
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
                             user_theme=user_theme,
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
        
        include_pv = data.get('include_price_volume', True)
        include_fund = data.get('include_fundamentals', True)
        include_thesis = data.get('include_thesis', False)
        include_trades = data.get('include_trades', False)

        context_string = _get_preview_context_string(
            user_id=user_id,
            fund=fund,
            include_thesis=include_thesis,
            include_trades=include_trades,
            include_price_volume=include_pv,
            include_fundamentals=include_fund
        )
        
        return jsonify({
            "success": True, 
            "context": context_string,
            "char_count": len(context_string)
        })
        
    except Exception as e:
        logger.error(f"Error generating context preview: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@ai_bp.route('/api/v2/ai/models', methods=['GET'])
@require_auth
def api_ai_models():
    """Get available AI models with user's preferred default"""
    try:
        formatted_models = _get_formatted_ai_models()
        default_model = get_user_ai_model()
        return jsonify({
            "models": formatted_models,
            "default_model": default_model
        })
    except Exception as e:
        logger.error(f"Error fetching AI models: {e}")
        return jsonify({"error": str(e)}), 500

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

        context_string = _build_context_from_packet(
            fund=fund,
            data_packet=data_packet,
            include_thesis=data.get('include_thesis', False),
            include_trades=data.get('include_trades', False),
            include_price_volume=include_pv,
            include_fundamentals=include_fund
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
                'include_fundamentals': data.get('include_fundamentals', True)
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
