from flask import Blueprint, render_template, request, g, jsonify
import logging
from datetime import datetime, timedelta, date, timezone
from typing import Optional, List, Dict, Any
import sys
from pathlib import Path

# Add parent directory to path to allow importing from root
# This ensures we can import modules like 'auth', 'supabase_client', etc.
sys.path.append(str(Path(__file__).parent.parent))

from auth import require_auth, require_admin
from research_repository import ResearchRepository
from user_preferences import get_user_preference
from flask_auth_utils import get_user_email_flask, get_auth_token, get_user_id_flask
from flask_cache_utils import cache_resource, cache_data
# Note: get_navigation_context imported inside function to avoid circular import

logger = logging.getLogger('research')

research_bp = Blueprint('research', __name__)

# Log blueprint registration
logger.debug("[RESEARCH] Research blueprint loaded")

# Cached repository instance (resource caching)
@cache_resource
def get_research_repository():
    """Get research repository instance, cached for application lifetime"""
    return ResearchRepository()

# Cached helper functions for data fetching
@cache_data(ttl=300)
def get_cached_unique_tickers(repo: ResearchRepository):
    """Get unique tickers with caching (5min TTL)"""
    try:
        return repo.get_unique_tickers()
    except Exception as e:
        logger.error(f"Error fetching unique tickers: {e}", exc_info=True)
        return []

@cache_data(ttl=60)
def get_cached_statistics(repo: ResearchRepository):
    """Get article statistics with caching (60s TTL)"""
    try:
        return repo.get_article_statistics(days=90)
    except Exception as e:
        logger.error(f"Error fetching statistics: {e}", exc_info=True)
        return {
            'total_count': 0,
            'by_type': {},
            'by_source': {},
            'by_day': {}
        }

@cache_data(ttl=60)
def get_cached_embedding_stats(repo: ResearchRepository):
    """Get embedding statistics with caching (60s TTL)"""
    try:
        embedding_stats_query = "SELECT COUNT(*) as total, COUNT(embedding) as embedded FROM research_articles"
        result = repo.client.execute_query(embedding_stats_query)
        if result:
            return result[0]['total'], result[0]['embedded']
        return 0, 0
    except Exception as e:
        logger.error(f"Error fetching embedding stats: {e}", exc_info=True)
        return 0, 0

@cache_data(ttl=30)
def get_cached_articles(
    repo: ResearchRepository,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    article_type_filter: Optional[str],
    search_filter: Optional[str],
    ticker_filter: Optional[str],
    per_page: int,
    offset: int
):
    """Get articles with caching (30s TTL for fresher data during active use)"""
    try:
        tickers_filter = [ticker_filter] if ticker_filter else None
        
        if start_date and end_date:
            articles = repo.get_articles_by_date_range(
                start_date=start_date,
                end_date=end_date,
                article_type=article_type_filter,
                search_text=search_filter,
                tickers_filter=tickers_filter,
                limit=per_page,
                offset=offset
            )
        else:
            articles = repo.get_all_articles(
                article_type=article_type_filter,
                search_text=search_filter,
                tickers_filter=tickers_filter,
                limit=per_page,
                offset=offset
            )
        
        # Ensure articles is a list (not None)
        if articles is None:
            return []
        
        # Filter out any None articles and ensure valid structure
        articles = [a for a in articles if a is not None]
        
        # Ensure each article has tickers field
        for article in articles:
            if 'tickers' not in article or article['tickers'] is None:
                article['tickers'] = []
        
        return articles
    except Exception as e:
        logger.error(f"Error fetching articles: {e}", exc_info=True)
        return []

@research_bp.route('/research')
@require_auth
def research_dashboard():
    """Research Repository Dashboard"""
    logger.debug("[RESEARCH] Route /research accessed")
    try:
        # Get cached repository instance
        logger.debug("[RESEARCH] Getting ResearchRepository (cached)")
        repo = get_research_repository()
        logger.debug("[RESEARCH] ResearchRepository retrieved successfully")
        
        # Parse query parameters for filters
        # Date Range
        date_range_option = request.args.get('date_range', 'Last 30 days')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        # Calculate dates
        start_date = None
        end_date = None
        
        if date_range_option == "All time":
            start_date = None
            end_date = None
        elif date_range_option == "Custom" and start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1)
            except ValueError:
                date_range_option = 'Last 30 days' # Fallback
                
        if not start_date and date_range_option != "All time":
            # Default or standard ranges
            days_map = {
                "Last 7 days": 7,
                "Last 30 days": 30,
                "Last 90 days": 90
            }
            days = days_map.get(date_range_option, 30)
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=days)
            
        # Other filters
        article_type = request.args.get('article_type', 'All')
        article_type_filter = None if article_type == 'All' else article_type
        
        ticker = request.args.get('ticker', 'All')
        ticker_filter = None if ticker == 'All' else ticker
        
        search_text = request.args.get('search', '').strip()
        search_filter = search_text if search_text else None
        
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        offset = (page - 1) * per_page
        
        # Owned tickers filter (simplified for V1: passing boolean if checked)
        only_owned = request.args.get('only_owned') == 'true'
        
        # Fetch tickers for dropdown (cached)
        unique_tickers = get_cached_unique_tickers(repo)
        
        # Fetch statistics (cached)
        stats = get_cached_statistics(repo)
        total_articles, embedded_articles = get_cached_embedding_stats(repo)
        embedding_pct = (embedded_articles / total_articles * 100) if total_articles > 0 else 0
            
        # Fetch Articles (cached)
        articles = get_cached_articles(
            repo=repo,
            start_date=start_date,
            end_date=end_date,
            article_type_filter=article_type_filter,
            search_filter=search_filter,
            ticker_filter=ticker_filter,
            per_page=per_page,
            offset=offset
        )
        
        logger.info(f"Research dashboard: Fetched {len(articles)} valid articles")
            
        # Get common context
        from app import get_navigation_context  # Import here to avoid circular import
        from searxng_client import check_searxng_health
        user_email = get_user_email_flask()
        user_theme = get_user_preference('theme', default='system')
        nav_context = get_navigation_context(current_page='research')
        searxng_available = check_searxng_health()

        logger.debug(f"[RESEARCH] Rendering template with {len(articles)} articles, {len(unique_tickers)} tickers")
        
        return render_template(
            'research.html',
            articles=articles,
            unique_tickers=unique_tickers,
            stats=stats,
            total_articles=total_articles,
            embedded_articles=embedded_articles,
            embedding_pct=embedding_pct,
            filters={
                'date_range': date_range_option,
                'start_date': start_date_str,
                'end_date': end_date_str,
                'article_type': article_type,
                'ticker': ticker,
                'search': search_text,
                'only_owned': only_owned,
                'page': page
            },
            user_email=user_email,
            user_theme=user_theme,
            searxng_available=searxng_available,
            **nav_context
        )
        
    except Exception as e:
        logger.error(f"Error in research dashboard: {e}", exc_info=True)
        # Return error page with details
        from app import get_navigation_context  # Import here to avoid circular import
        user_email = get_user_email_flask()
        user_theme = get_user_preference('theme', default='system')
        nav_context = get_navigation_context(current_page='research')
        
        return render_template(
            'error.html' if Path('templates/error.html').exists() else 'base.html', 
            error_title="Research Repository Error",
            error_message=str(e),
            error_details="Please check the logs for more information.",
            user_email=user_email,
            user_theme=user_theme,
            **nav_context
        ), 500


def reanalyze_article_flask(article_id: str, model_name: str) -> tuple[bool, str]:
    """Re-analyze an article with a specified AI model (Flask version).
    
    Args:
        article_id: UUID of the article to re-analyze
        model_name: Name of the Ollama model to use
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        from ollama_client import get_ollama_client, check_ollama_health, generate_summary
        from research_utils import validate_ticker_format, normalize_ticker
        from scheduler.jobs import calculate_relevance_score
        from supabase_client import SupabaseClient
        
        # Check repository is available
        repo = get_research_repository()
        if repo is None:
            return False, "Research repository is not available"
        
        # Check backend: Web-based AI uses cookie service; GLM uses Z.AI (requires key); others use Ollama
        try:
            from webai_wrapper import is_webai_model
            is_webai = is_webai_model(model_name)
        except ImportError:
            is_webai = False
        is_glm = model_name and str(model_name).startswith("glm-")
        if is_webai:
            try:
                from webai_wrapper import check_cookie_config
                config_status = check_cookie_config()
                if not config_status.get("status", False):
                    return False, "Web-based AI cookies not configured. Configure cookies via AI Settings."
            except ImportError:
                return False, "Web-based AI support not available"
        elif is_glm:
            try:
                from glm_config import get_zhipu_api_key
                if not get_zhipu_api_key():
                    return False, "GLM API key not set. Add ZHIPU_API_KEY or save via AI Settings."
            except ImportError:
                return False, "GLM support not available"
        else:
            # Ollama models require Ollama to be available
            if not check_ollama_health():
                return False, "Ollama is not available. Please check the connection."
        
        # Get article from repository
        # Query handles both old (ticker) and new (tickers) schema
        query = """
            SELECT id, title, content, 
                   COALESCE(tickers, ARRAY[ticker]) as tickers, 
                   sector
            FROM research_articles
            WHERE id = %s
        """
        articles = repo.client.execute_query(query, (article_id,))
        
        if not articles:
            return False, "Article not found"
        
        article = articles[0]
        # Normalize ticker data (handle both array and single value)
        if 'tickers' in article and article['tickers'] is not None:
            if not isinstance(article['tickers'], list):
                article['tickers'] = [article['tickers']] if article['tickers'] else []
        else:
            article['tickers'] = []
        
        content = article.get('content', '')
        
        if not content:
            return False, "Article has no content to analyze"
        
        # Generate summary with specified model (routes to appropriate backend automatically)
        summary_data = generate_summary(content, model=model_name)
        
        if not summary_data:
            return False, "Failed to generate summary"
        
        # Extract summary text
        extracted_tickers = []
        extracted_sector = None
        if isinstance(summary_data, str):
            summary = summary_data
        elif isinstance(summary_data, dict):
            summary = summary_data.get("summary", "")
            tickers = summary_data.get("tickers", [])
            sectors = summary_data.get("sectors", [])
            
            # Extract all validated tickers
            extracted_tickers = []
            if tickers:
                for ticker in tickers:
                    # Validate format only (trust AI inference for company name -> ticker conversion)
                    if not validate_ticker_format(ticker):
                        logger.warning(f"Rejected invalid ticker format: {ticker} - skipping")
                        continue
                    normalized = normalize_ticker(ticker)
                    if normalized:
                        extracted_tickers.append(normalized)
            
            extracted_sector = sectors[0] if sectors else None
        else:
            return False, "Invalid summary data format"
        
        if not summary:
            return False, "Generated summary is empty"
        
        # Get owned tickers for relevance scoring
        owned_tickers = []
        try:
            # Try to get user token for Supabase client
            user_token = get_auth_token()
            user_id = get_user_id_flask()
            
            # Use service role for admin users, user token for regular users
            # For simplicity, try user token first, fallback to service role
            client = None
            if user_token:
                try:
                    client = SupabaseClient(user_token=user_token)
                except Exception:
                    pass
            
            # Fallback to service role if user token failed
            if not client:
                client = SupabaseClient(use_service_role=True)
            
            if client:
                # Get production funds directly from Supabase (matching pattern from scheduler/jobs.py)
                funds_result = client.supabase.table("funds")\
                    .select("name")\
                    .eq("is_production", True)\
                    .execute()
                
                if funds_result.data:
                    prod_funds = [f['name'] for f in funds_result.data]
                    positions_result = client.supabase.table("latest_positions")\
                        .select("ticker")\
                        .in_("fund", prod_funds)\
                        .execute()
                    if positions_result.data:
                        owned_tickers = [pos['ticker'] for pos in positions_result.data if pos.get('ticker')]
        except Exception as e:
            logger.warning(f"Could not fetch owned tickers for relevance scoring: {e}")
        
        # Calculate relevance_score based on what was extracted
        calculated_relevance = calculate_relevance_score(extracted_tickers, extracted_sector, owned_tickers=owned_tickers)
        
        # Generate embedding (Ollama only; skip if unavailable, e.g. when using WebAI/GLM without Ollama)
        embedding = None
        ollama_client = get_ollama_client()
        if ollama_client:
            embedding = ollama_client.generate_embedding(content[:6000])
            if not embedding:
                logger.warning(f"Failed to generate embedding for article {article_id}, continuing without embedding")
                embedding = None
        
        # Update article in database (including Chain of Thought fields)
        success = repo.update_article_analysis(
            article_id=article_id,
            summary=summary,
            tickers=extracted_tickers if extracted_tickers else None,
            sector=extracted_sector,
            embedding=embedding,
            relevance_score=calculated_relevance,
            claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
            fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
            conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
            sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
            sentiment_score=summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None
        )
        
        if success:
            return True, f"Article re-analyzed successfully with {model_name}"
        else:
            return False, "Failed to update article in database"
            
    except Exception as e:
        logger.error(f"Error re-analyzing article {article_id}: {e}", exc_info=True)
        return False, f"Error: {str(e)}"


@research_bp.route('/api/research/models', methods=['GET'])
@require_auth
def get_available_models():
    """Get list of available AI models for re-analysis (Ollama, WebAI, GLM)"""
    try:
        from ollama_client import list_available_models
        
        # Get all available models (includes Ollama, WebAI, and GLM if configured)
        # Note: WebAI and GLM models don't require Ollama to be available
        models = list_available_models(include_hidden=False)
        
        # Get default model
        from settings import get_summarizing_model
        default_model = get_summarizing_model()
        
        return jsonify({
            "success": True,
            "models": models,
            "default_model": default_model
        })
    except Exception as e:
        logger.error(f"Error fetching available models: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
            "models": []
        }), 500


@research_bp.route('/api/research/delete', methods=['POST'])
@require_admin
def delete_article_endpoint():
    """Delete a single research article by ID (admin only)."""
    try:
        data = request.get_json() or {}
        article_id = data.get("article_id")

        if not article_id:
            return jsonify({"success": False, "error": "article_id is required"}), 400

        repo = get_research_repository()
        if repo is None:
            return jsonify({"success": False, "error": "Research repository is not available"}), 500

        deleted = repo.delete_article(article_id)
        if deleted:
            logger.info(f"[RESEARCH] Article {article_id} deleted by admin")
            return jsonify({"success": True})

        logger.warning(f"[RESEARCH] Article {article_id} not found for deletion")
        return jsonify({"success": False, "error": "Article not found"}), 404

    except Exception as e:
        logger.error(f"Error in delete article endpoint: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/api/research/reanalyze', methods=['POST'])
@require_auth
def reanalyze_article_endpoint():
    """Re-analyze an article with a specified AI model"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        article_id = data.get('article_id')
        model_name = data.get('model_name')
        
        if not article_id:
            return jsonify({"success": False, "error": "article_id is required"}), 400
        
        if not model_name:
            return jsonify({"success": False, "error": "model_name is required"}), 400
        
        success, message = reanalyze_article_flask(article_id, model_name)
        
        if success:
            return jsonify({
                "success": True,
                "message": message
            })
        else:
            return jsonify({
                "success": False,
                "error": message
            }), 500
            
    except Exception as e:
        logger.error(f"Error in reanalyze endpoint: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@research_bp.route('/api/research/reanalyze/stream', methods=['POST'])
@require_auth
def reanalyze_article_stream():
    """Re-analyze an article with Server-Sent Events streaming progress"""
    from flask import Response, stream_with_context
    import queue
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data provided"}), 400
        
        article_id = data.get('article_id')
        model_name = data.get('model_name')
        
        if not article_id:
            return jsonify({"success": False, "error": "article_id is required"}), 400
        
        if not model_name:
            return jsonify({"success": False, "error": "model_name is required"}), 400
        
        def generate_sse_events():
            """Generator that yields Server-Sent Events"""
            import json
            from ollama_client import check_ollama_health, generate_summary_streaming, get_ollama_client
            from research_utils import validate_ticker_format, normalize_ticker
            from scheduler.jobs import calculate_relevance_score
            from supabase_client import SupabaseClient
            
            try:
                # Check repository
                repo = get_research_repository()
                if repo is None:
                    yield f"data: {json.dumps({'error': 'Research repository not available'})}\n\n"
                    return
                
                # Check backend: Web-based AI uses cookie service; GLM uses Z.AI (requires key); others use Ollama
                try:
                    from webai_wrapper import is_webai_model
                    is_webai = is_webai_model(model_name)
                except ImportError:
                    is_webai = False
                is_glm = model_name and str(model_name).startswith("glm-")
                if is_webai:
                    try:
                        from webai_wrapper import check_cookie_config
                        config_status = check_cookie_config()
                        if not config_status.get("status", False):
                            yield f"data: {json.dumps({'error': 'Web-based AI cookies not configured. Configure cookies via AI Settings.'})}\n\n"
                            return
                    except ImportError:
                        yield f"data: {json.dumps({'error': 'Web-based AI support not available'})}\n\n"
                        return
                elif is_glm:
                    try:
                        from glm_config import get_zhipu_api_key
                        if not get_zhipu_api_key():
                            yield f"data: {json.dumps({'error': 'GLM API key not set. Add ZHIPU_API_KEY or save via AI Settings.'})}\n\n"
                            return
                    except ImportError:
                        yield f"data: {json.dumps({'error': 'GLM support not available'})}\n\n"
                        return
                else:
                    if not check_ollama_health():
                        yield f"data: {json.dumps({'error': 'Ollama is not available'})}\n\n"
                        return

                # Send initial status
                yield f"data: {json.dumps({'status': 'fetching', 'message': 'Fetching article...'})}\n\n"
                
                # Get article
                query = """
                    SELECT id, title, content, 
                           COALESCE(tickers, ARRAY[ticker]) as tickers, 
                           sector
                    FROM research_articles
                    WHERE id = %s
                """
                articles = repo.client.execute_query(query, (article_id,))
                
                if not articles:
                    yield f"data: {json.dumps({'error': 'Article not found'})}\n\n"
                    return
                
                article = articles[0]
                if 'tickers' in article and article['tickers'] is not None:
                    if not isinstance(article['tickers'], list):
                        article['tickers'] = [article['tickers']] if article['tickers'] else []
                else:
                    article['tickers'] = []
                
                content = article.get('content', '')
                if not content:
                    yield f"data: {json.dumps({'error': 'Article has no content'})}\n\n"
                    return
                
                # Initialize AI model (Ollama or Z.AI for glm-*)
                yield f"data: {json.dumps({'status': 'initializing', 'message': 'Initializing AI model...'})}\n\n"

                def progress_callback(tokens, progress):
                    nonlocal progress_queue
                    progress_queue.put({
                        "status": "generating",
                        "message": f"Generating summary... {progress}%",
                        "progress": progress,
                        "tokens": tokens,
                    })

                progress_queue = queue.Queue()

                yield f"data: {json.dumps({'status': 'generating', 'message': 'Generating summary...', 'progress': 0})}\n\n"

                summary_data = generate_summary_streaming(
                    content, model=model_name, progress_callback=progress_callback
                )
                
                # Drain progress queue and send all updates
                while not progress_queue.empty():
                    progress_update = progress_queue.get()
                    yield f"data: {json.dumps(progress_update)}\n\n"
                
                if not summary_data:
                    yield f"data: {json.dumps({'error': 'Failed to generate summary'})}\n\n"
                    return
                
                # Extract data
                yield f"data: {json.dumps({'status': 'processing', 'message': 'Processing summary data...', 'progress': 100})}\n\n"
                
                extracted_tickers = []
                extracted_sector = None
                if isinstance(summary_data, str):
                    summary = summary_data
                elif isinstance(summary_data, dict):
                    summary = summary_data.get("summary", "")
                    tickers = summary_data.get("tickers", [])
                    sectors = summary_data.get("sectors", [])
                    
                    extracted_tickers = []
                    if tickers:
                        for ticker in tickers:
                            if not validate_ticker_format(ticker):
                                continue
                            normalized = normalize_ticker(ticker)
                            if normalized:
                                extracted_tickers.append(normalized)
                    
                    extracted_sector = sectors[0] if sectors else None
                else:
                    yield f"data: {json.dumps({'error': 'Invalid summary format'})}\n\n"
                    return
                
                if not summary:
                    yield f"data: {json.dumps({'error': 'Generated summary is empty'})}\n\n"
                    return
                
                # Get owned tickers for relevance
                owned_tickers = []
                try:
                    user_token = get_auth_token()
                    client = None
                    if user_token:
                        try:
                            client = SupabaseClient(user_token=user_token)
                        except Exception:
                            pass
                    
                    if not client:
                        client = SupabaseClient(use_service_role=True)
                    
                    if client:
                        funds_result = client.supabase.table("funds").select("name").eq("is_production", True).execute()
                        if funds_result.data:
                            prod_funds = [f['name'] for f in funds_result.data]
                            positions_result = client.supabase.table("latest_positions").select("ticker").in_("fund", prod_funds).execute()
                            if positions_result.data:
                                owned_tickers = [pos['ticker'] for pos in positions_result.data if pos.get('ticker')]
                except Exception as e:
                    logger.warning(f"Could not fetch owned tickers: {e}")
                
                # Calculate relevance
                calculated_relevance = calculate_relevance_score(extracted_tickers, extracted_sector, owned_tickers=owned_tickers)
                
                # Generate embedding (Ollama only; skip if unavailable, e.g. when using GLM without Ollama)
                yield f"data: {json.dumps({'status': 'embedding', 'message': 'Generating embedding...'})}\n\n"
                _ollama = get_ollama_client()
                embedding = _ollama.generate_embedding(content[:6000]) if _ollama else None
                if not embedding:
                    logger.warning(f"Failed to generate embedding for article {article_id}")
                    embedding = None
                
                # Update database
                yield f"data: {json.dumps({'status': 'saving', 'message': 'Saving to database...'})}\n\n"
                
                success = repo.update_article_analysis(
                    article_id=article_id,
                    summary=summary,
                    tickers=extracted_tickers if extracted_tickers else None,
                    sector=extracted_sector,
                    embedding=embedding,
                    relevance_score=calculated_relevance,
                    claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
                    fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
                    conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
                    sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
                    sentiment_score=summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None
                )
                
                if success:
                    yield f"data: {json.dumps({'status': 'complete', 'message': f'Successfully re-analyzed with {model_name}', 'success': True})}\n\n"
                else:
                    yield f"data: {json.dumps({'error': 'Failed to update database'})}\n\n"
                
            except Exception as e:
                logger.error(f"Error in SSE stream: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return Response(
            stream_with_context(generate_sse_events()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
        
    except Exception as e:
        logger.error(f"Error in reanalyze stream endpoint: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@research_bp.route('/api/research/search', methods=['POST'])
@require_auth
def api_research_search():
    """Perform SearXNG search"""
    try:
        data = request.get_json() or {}
        query = data.get('query', '').strip()
        search_type = data.get('search_type', 'news')
        time_range = data.get('time_range')
        max_results = int(data.get('max_results', 10))

        if not query:
            return jsonify({"success": False, "error": "Query is required"}), 400

        from searxng_client import get_searxng_client, check_searxng_health

        if not check_searxng_health():
            return jsonify({"success": False, "error": "SearXNG is not available"}), 503

        client = get_searxng_client()
        if not client:
            return jsonify({"success": False, "error": "SearXNG client not initialized"}), 503

        # Perform search based on type
        if search_type == 'news':
            results = client.search_news(query=query, time_range=time_range, max_results=max_results)
        elif search_type == 'web':
            results = client.search_web(query=query, time_range=time_range, max_results=max_results)
        else:
            results = client.search(query=query, time_range=time_range, max_results=max_results)

        if results.get('error'):
            return jsonify({"success": False, "error": results.get('error')}), 500

        return jsonify({
            "success": True,
            "results": results.get('results', []),
            "query": results.get('query', query),
            "number_of_results": results.get('number_of_results', 0)
        })

    except Exception as e:
        logger.error(f"Error performing search: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/api/research/scrape', methods=['POST'])
@require_auth
def api_research_scrape():
    """Scrape article content from URL"""
    try:
        data = request.get_json() or {}
        url = data.get('url', '').strip()

        if not url:
            return jsonify({"success": False, "error": "URL is required"}), 400

        from research_utils import extract_article_content

        extracted = extract_article_content(url)

        if not extracted.get('success'):
            error = extracted.get('error', 'Unknown error')
            return jsonify({
                "success": False,
                "error": error,
                "title": extracted.get('title', ''),
                "source": extracted.get('source', ''),
                "published_at": extracted.get('published_at')
            }), 400

        return jsonify({
            "success": True,
            "title": extracted.get('title', ''),
            "content": extracted.get('content', ''),
            "source": extracted.get('source', ''),
            "published_at": extracted.get('published_at')
        })

    except Exception as e:
        logger.error(f"Error scraping article: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/api/research/summarize', methods=['POST'])
@require_auth
def api_research_summarize():
    """Generate AI summary for article content"""
    try:
        data = request.get_json() or {}
        content = data.get('content', '').strip()
        model = data.get('model')

        if not content:
            return jsonify({"success": False, "error": "Content is required"}), 400

        from ollama_client import get_ollama_client, check_ollama_health
        from settings import get_summarizing_model

        if not check_ollama_health():
            return jsonify({"success": False, "error": "Ollama is not available"}), 503

        client = get_ollama_client()
        if not client:
            return jsonify({"success": False, "error": "Ollama client not initialized"}), 503

        # Use provided model or default
        model_name = model or get_summarizing_model()

        summary_data = client.generate_summary(content, model=model_name)

        if not summary_data:
            return jsonify({"success": False, "error": "Failed to generate summary"}), 500

        # Handle both string and dict formats
        if isinstance(summary_data, str):
            return jsonify({
                "success": True,
                "summary": summary_data,
                "model": model_name
            })
        elif isinstance(summary_data, dict):
            return jsonify({
                "success": True,
                "summary": summary_data.get("summary", ""),
                "tickers": summary_data.get("tickers", []),
                "sectors": summary_data.get("sectors", []),
                "sentiment": summary_data.get("sentiment"),
                "sentiment_score": summary_data.get("sentiment_score"),
                "claims": summary_data.get("claims", []),
                "fact_check": summary_data.get("fact_check"),
                "conclusion": summary_data.get("conclusion"),
                "logic_check": summary_data.get("logic_check"),
                "relationships": summary_data.get("relationships", []),
                "model": model_name
            })
        else:
            return jsonify({"success": False, "error": "Invalid summary format"}), 500

    except Exception as e:
        logger.error(f"Error generating summary: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/api/research/analyze', methods=['POST'])
@require_auth
def api_research_analyze():
    """Perform full AI analysis with ticker extraction and validation"""
    try:
        data = request.get_json() or {}
        content = data.get('content', '').strip()
        model = data.get('model')

        if not content:
            return jsonify({"success": False, "error": "Content is required"}), 400

        from ollama_client import get_ollama_client, check_ollama_health
        from settings import get_summarizing_model
        from research_utils import validate_ticker_format, normalize_ticker

        if not check_ollama_health():
            return jsonify({"success": False, "error": "Ollama is not available"}), 503

        client = get_ollama_client()
        if not client:
            return jsonify({"success": False, "error": "Ollama client not initialized"}), 503

        # Use provided model or default
        model_name = model or get_summarizing_model()

        summary_data = client.generate_summary(content, model=model_name)

        if not summary_data:
            return jsonify({"success": False, "error": "Failed to generate analysis"}), 500

        # Handle both string and dict formats
        if isinstance(summary_data, str):
            return jsonify({
                "success": True,
                "summary": summary_data,
                "tickers": [],
                "sectors": [],
                "model": model_name
            })
        elif isinstance(summary_data, dict):
            # Extract and validate tickers (same as jobs_research.py)
            raw_tickers = summary_data.get("tickers", [])
            extracted_tickers = []

            for ticker in raw_tickers:
                if not validate_ticker_format(ticker):
                    logger.debug(f"Rejected invalid ticker format: {ticker}")
                    continue
                normalized = normalize_ticker(ticker)
                if normalized:
                    extracted_tickers.append(normalized)

            # Extract sector
            sectors = summary_data.get("sectors", [])
            extracted_sector = sectors[0] if sectors else None

            return jsonify({
                "success": True,
                "summary": summary_data.get("summary", ""),
                "tickers": extracted_tickers,
                "sectors": sectors,
                "sector": extracted_sector,
                "sentiment": summary_data.get("sentiment"),
                "sentiment_score": summary_data.get("sentiment_score"),
                "claims": summary_data.get("claims", []),
                "fact_check": summary_data.get("fact_check"),
                "conclusion": summary_data.get("conclusion"),
                "logic_check": summary_data.get("logic_check"),
                "relationships": summary_data.get("relationships", []),
                "model": model_name
            })
        else:
            return jsonify({"success": False, "error": "Invalid analysis format"}), 500

    except Exception as e:
        logger.error(f"Error performing analysis: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/api/research/save', methods=['POST'])
@require_auth
def api_research_save():
    """Save article to research repository following exact code path from jobs_research.py"""
    try:
        data = request.get_json() or {}
        url = data.get('url', '').strip()
        title = data.get('title', '').strip()
        content = data.get('content', '').strip()
        summary_data = data.get('summary_data', {})
        model = data.get('model')

        if not url or not title or not content:
            return jsonify({"success": False, "error": "URL, title, and content are required"}), 400

        repo = get_research_repository()
        if not repo:
            return jsonify({"success": False, "error": "Research repository not available"}), 500

        # Check for duplicate URLs
        if repo.article_exists(url):
            return jsonify({"success": False, "error": "Article with this URL already exists"}), 409

        # Follow exact code path from jobs_research.py (lines 290-383)
        from ollama_client import get_ollama_client
        from research_utils import validate_ticker_format, normalize_ticker, extract_source_from_url
        from scheduler.jobs_common import calculate_relevance_score

        # Extract and validate tickers
        raw_tickers = summary_data.get("tickers", [])
        extracted_tickers = []

        for ticker in raw_tickers:
            if not validate_ticker_format(ticker):
                logger.debug(f"Rejected invalid ticker format: {ticker}")
                continue
            normalized = normalize_ticker(ticker)
            if normalized:
                extracted_tickers.append(normalized)

        # Extract sector
        sectors = summary_data.get("sectors", [])
        extracted_sector = sectors[0] if sectors else None

        # Extract summary
        summary = summary_data.get("summary", "")

        # Calculate relevance score (no owned_tickers check for manual saves)
        relevance_score = calculate_relevance_score(extracted_tickers, extracted_sector, owned_tickers=None)

        # Generate embedding (if Ollama available)
        embedding = None
        ollama_client = get_ollama_client()
        if ollama_client:
            try:
                embedding = ollama_client.generate_embedding(content[:6000])
            except Exception as e:
                logger.warning(f"Failed to generate embedding: {e}")
                embedding = None

        # Extract all Chain of Thought fields
        claims = summary_data.get("claims")
        fact_check = summary_data.get("fact_check")
        conclusion = summary_data.get("conclusion")
        sentiment = summary_data.get("sentiment")
        sentiment_score = summary_data.get("sentiment_score")
        logic_check = summary_data.get("logic_check")

        # Extract source from URL if not provided
        source = summary_data.get("source") or extract_source_from_url(url)

        # Extract published_at if available
        published_at = summary_data.get("published_at")

        # Save article
        article_id = repo.save_article(
            tickers=extracted_tickers if extracted_tickers else None,
            sector=extracted_sector,
            article_type="Market News",  # Default type, could be made configurable
            title=title,
            url=url,
            summary=summary,
            content=content,
            source=source,
            published_at=published_at,
            relevance_score=relevance_score,
            embedding=embedding,
            claims=claims,
            fact_check=fact_check,
            conclusion=conclusion,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            logic_check=logic_check
        )

        if article_id:
            logger.info(f"[RESEARCH] Article saved via search interface: {article_id}")
            return jsonify({
                "success": True,
                "article_id": article_id,
                "message": "Article saved successfully"
            })
        else:
            return jsonify({"success": False, "error": "Failed to save article"}), 500

    except Exception as e:
        logger.error(f"Error saving article: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

