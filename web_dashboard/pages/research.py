#!/usr/bin/env python3
"""
Research Repository Viewer
===========================

Streamlit page for viewing research articles collected by automated jobs.
Provides statistics, filtering, and detailed article views.
"""

import streamlit as st
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta, date, timezone
import pandas as pd
import logging
import time

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
from research_repository import ResearchRepository
from postgres_client import PostgresClient
from ollama_client import get_ollama_client, check_ollama_health
from settings import get_summarizing_model
from file_parsers import extract_text_from_file
from streamlit_utils import get_available_funds, render_sidebar_fund_selector
from ticker_utils import render_ticker_link
from research_utils import normalize_ticker, escape_markdown

logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="Research Repository",
    page_icon="📚",
    layout="wide"
)

# Check authentication
# Check authentication
if not is_authenticated():
    redirect_to_login("pages/research.py")

# Refresh token if needed (auto-refresh before expiry)
from auth_utils import refresh_token_if_needed
if not refresh_token_if_needed():
    # Token refresh failed - session is invalid, redirect to login
    from auth_utils import logout_user
    logout_user(return_to="pages/research.py")
    st.stop()

# Render navigation
render_navigation(show_ai_assistant=True, show_settings=True)

# Initialize repository (with error handling)
@st.cache_resource
def get_research_repository():
    """Get research repository instance, handling errors gracefully"""
    try:
        return ResearchRepository()
    except Exception as e:
        logger.error(f"Failed to initialize ResearchRepository: {e}")
        return None

repo = get_research_repository()

# Check if PostgreSQL is available
if repo is None:
    st.error("⚠️ Research Repository Database Unavailable")
    st.info("""
    The research repository database is not available. This could be because:
    - PostgreSQL is not running
    - RESEARCH_DATABASE_URL is not configured
    - Database connection failed
    
    Check the logs or contact an administrator for assistance.
    """)
    st.stop()

# Header
st.title("📚 Research Repository")
st.caption(f"Logged in as: {get_user_email()}")

# Initialize session state for filters
if 'refresh_key' not in st.session_state:
    st.session_state.refresh_key = 0
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1

# Initialize reanalysis model (default to current summarizing model)
if 'reanalysis_model' not in st.session_state:
    st.session_state.reanalysis_model = get_summarizing_model()

# Re-analysis function
def reanalyze_article(article_id: str, model_name: str) -> tuple[bool, str]:
    """Re-analyze an article with a specified AI model.
    
    Args:
        article_id: UUID of the article to re-analyze
        model_name: Name of the Ollama model to use
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        from ollama_client import generate_summary, get_ollama_client
        
        # Check repository is available
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
        query = """
            SELECT id, title, content, ticker, sector
            FROM research_articles
            WHERE id = %s
        """
        articles = repo.client.execute_query(query, (article_id,))
        
        if not articles:
            return False, "Article not found"
        
        article = articles[0]
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
                from research_utils import validate_ticker_format, normalize_ticker
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
            from supabase_client import SupabaseClient
            
            # Use role-based access for security
            if is_admin():
                client = SupabaseClient(use_service_role=True)
            else:
                user_token = get_user_token()
                if user_token:
                    client = SupabaseClient(user_token=user_token)
                else:
                    logger.warning("No user token available, skipping owned tickers")
                    client = None
            
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
        from scheduler.jobs import calculate_relevance_score
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

# Helper function to convert UTC to local timezone
def to_local_time(utc_dt: datetime) -> datetime:
    """Convert UTC datetime to local timezone"""
    if utc_dt is None:
        return None
    if isinstance(utc_dt, str):
        utc_dt = datetime.fromisoformat(utc_dt.replace('Z', '+00:00'))
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    
    # Convert to local timezone (user's system timezone)
    if HAS_ZONEINFO:
        try:
            # Get system timezone
            import time
            local_tz = ZoneInfo(time.tzname[0] if time.daylight == 0 else time.tzname[1])
            return utc_dt.astimezone(local_tz)
        except Exception:
            # Fallback to UTC if timezone detection fails
            return utc_dt
    else:
        # Fallback: just return UTC if zoneinfo not available
        return utc_dt

# Sidebar filters
with st.sidebar:
    st.header("🔍 Filters")
    
    # Date range filter
    date_range_option = st.selectbox(
        "Date Range",
        ["All time", "Last 7 days", "Last 30 days", "Last 90 days", "Custom"],
        index=0
    )
    
    start_date = None
    end_date = None
    use_date_filter = True
    
    if date_range_option == "All time":
        use_date_filter = False
        # Set wide range for query (but won't be used)
        start_date = date.today() - timedelta(days=3650)  # 10 years ago
        end_date = date.today() + timedelta(days=1)  # Tomorrow
    elif date_range_option == "Custom":
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=date.today() - timedelta(days=30))
        with col2:
            end_date = st.date_input("End Date", value=date.today())
    else:
        days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}[date_range_option]
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
    
    # Convert to datetime for query (use UTC timezone)
    if use_date_filter:
        # Start of day in UTC
        start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        # End of day in UTC - use start of next day for inclusive end
        end_datetime = datetime.combine(end_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
    else:
        # For "All time", use None to skip date filtering
        start_datetime = None
        end_datetime = None
    
    # Fund selector (for context and uploads)
    st.markdown("---")
    st.header("📊 Fund Context")
    fund_context = render_sidebar_fund_selector(
        label="Active Fund",
        key="fund_context_selector",
        help_text="Select the fund you're working with. This will be used when uploading reports."
    )
    if fund_context:
        st.info(f"📊 Working with: **{fund_context}**")
    
    st.markdown("---")
    
    # Article type filter
    article_type = st.selectbox(
        "Article Type",
        ["All", "Market News", "Ticker News", "Earnings", "Opportunity Discovery", "Research Report", "Reddit Discovery", "Alpha Research", "ETF Change", "Seeking Alpha Symbol"],
        index=0
    )
    article_type_filter = None if article_type == "All" else article_type
    
    # Ticker filter (searchable dropdown)
    selected_ticker = "All"
    try:
        tickers = repo.get_unique_tickers()
        ticker_options = ["All"] + tickers
        selected_ticker = st.selectbox(
            "🏷️ Ticker",
            ticker_options,
            index=0,
            help="Filter by ticker symbol"
        )
        ticker_filter = None if selected_ticker == "All" else selected_ticker
    except Exception as e:
        logger.error(f"Error getting tickers: {e}")
        ticker_filter = None
    
    # Search text filter
    search_text = st.text_input("🔍 Search", placeholder="Search in title, summary, content...")
    search_filter = search_text.strip() if search_text else None
    
    # Owned tickers filter
    filter_owned_tickers = st.checkbox(
        "📊 Only owned tickers",
        value=False,
        help="Show only articles related to tickers owned in any production fund"
    )
    
    # Hidden filters (for debugging - uncomment to re-enable)
    # Source filter
    source_filter = None
    # selected_source = "All"
    # try:
    #     sources = repo.get_unique_sources()
    #     source_options = ["All"] + sources
    #     selected_source = st.selectbox("Source", source_options, index=0)
    #     source_filter = None if selected_source == "All" else selected_source
    # except Exception as e:
    #     logger.error(f"Error getting sources: {e}")
    #     source_filter = None
    
    # Embedding status filter (for RAG debugging)
    embedding_filter = None
    # embedding_status = st.selectbox(
    #     "Embedding Status",
    #     ["All", "Embedded", "Pending"],
    #     index=0,
    #     help="Filter by whether articles have been embedded for AI search (RAG)"
    # )
    # embedding_filter = None if embedding_status == "All" else (embedding_status == "Embedded")
    
    # Results per page
    results_per_page = st.selectbox("Results per page", [10, 20, 50, 100], index=1)
    
    # Admin-only: Model selector for re-analysis
    if is_admin():
        st.markdown("---")
        st.header("🔧 Admin Tools")
        
        # Upload Report Section
        with st.expander("📤 Upload Report", expanded=False):
            st.info("💡 **Note:** Files are saved to organized folders. The processing job will automatically add date prefixes and process them.")
            
            # Report type selection
            report_type = st.radio(
                "Report Type",
                options=["Ticker-specific", "Market", "Fund-specific"],
                help="Select the type of research report",
                key="upload_report_type"
            )
            
            # Get ticker or fund based on type
            ticker_input = None
            selected_fund = None
            
            if report_type == "Ticker-specific":
                ticker_input = st.text_input(
                    "Ticker Symbol",
                    placeholder="GANX",
                    help="Enter the ticker symbol this report is about",
                    key="upload_ticker"
                ).strip().upper()
                
                if not ticker_input:
                    st.warning("⚠️ Please enter a ticker symbol")
            elif report_type == "Fund-specific":
                try:
                    from research_report_service import get_available_funds
                    available_funds = get_available_funds()
                    if available_funds:
                        selected_fund = st.selectbox(
                            "📊 Fund",
                            options=available_funds,
                            help="Select the fund this report is prepared for",
                            key="upload_fund_selector"
                        )
                    else:
                        st.warning("⚠️ No funds configured. Please check research_funds_config.json")
                        selected_fund = None
                except Exception as e:
                    logger.error(f"Error loading funds: {e}")
                    st.error(f"Error loading funds: {e}")
                    selected_fund = None
            
            # File uploader - support multiple files for bulk upload
            uploaded_files = st.file_uploader(
                "Upload PDF(s)", 
                type=['pdf'], 
                accept_multiple_files=True,
                help="Select one or multiple PDF files. You can select multiple files at once for bulk upload."
            )
            
            if uploaded_files:
                # Validate inputs
                if report_type == "Ticker-specific" and not ticker_input:
                    st.error("⚠️ Please enter a ticker symbol")
                elif report_type == "Fund-specific" and not selected_fund:
                    st.error("⚠️ Please select a fund")
                else:
                    file_count = len(uploaded_files)
                    upload_label = f"💾 Save {file_count} File{'s' if file_count > 1 else ''}" if file_count > 0 else "💾 Save File"
                    
                    if st.button(upload_label, type="primary"):
                        try:
                            from pathlib import Path
                            from research_report_service import ensure_research_folder, sanitize_filename
                            
                            # Ensure Research folder exists
                            research_base = ensure_research_folder()
                            
                            if report_type == "Ticker-specific":
                                target_folder = research_base / ticker_input
                            elif report_type == "Market":
                                from research_report_service import get_market_folder
                                market_folder = get_market_folder()
                                target_folder = research_base / market_folder
                            else:  # Fund-specific
                                from research_report_service import get_fund_folder
                                fund_folder = get_fund_folder(selected_fund)
                                if fund_folder:
                                    target_folder = research_base / fund_folder
                                else:
                                    st.error(f"⚠️ Invalid fund: {selected_fund}. Please check research_funds_config.json")
                                    st.stop()  # Stop execution on error
                            
                            # Create folder if it doesn't exist
                            target_folder.mkdir(parents=True, exist_ok=True)
                            
                            # Process all uploaded files
                            saved_files = []
                            skipped_files = []
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            for idx, uploaded_file in enumerate(uploaded_files):
                                try:
                                    # Update progress
                                    progress = (idx + 1) / len(uploaded_files)
                                    progress_bar.progress(progress)
                                    
                                    # Sanitize filename before saving
                                    sanitized_name = sanitize_filename(uploaded_file.name)
                                    status_text.text(f"Processing {idx + 1}/{len(uploaded_files)}: {uploaded_file.name} → {sanitized_name}")
                                    
                                    # Check if file already exists (using sanitized name)
                                    file_path = target_folder / sanitized_name
                                    
                                    if file_path.exists():
                                        skipped_files.append(f"{uploaded_file.name} (already exists as {sanitized_name})")
                                        logger.info(f"File already exists, skipping: {sanitized_name}")
                                        continue
                                    
                                    # Save file with sanitized name (job will add date prefix later)
                                    with open(file_path, "wb") as f:
                                        f.write(uploaded_file.getbuffer())
                                    
                                    saved_files.append(f"{uploaded_file.name} → {sanitized_name}")
                                    
                                except Exception as e:
                                    logger.error(f"Error saving file {uploaded_file.name}: {e}", exc_info=True)
                                    skipped_files.append(f"{uploaded_file.name} (error: {str(e)})")
                                
                            # Clear progress indicators
                            progress_bar.empty()
                            status_text.empty()
                            
                            # Show results
                            if saved_files:
                                st.success(f"✅ Saved {len(saved_files)} file(s) to: `{target_folder.relative_to(Path(__file__).parent.parent.parent)}`")
                                
                                if len(saved_files) <= 5:
                                    for filename in saved_files:
                                        st.caption(f"  • {filename}")
                                else:
                                    st.caption(f"  • {saved_files[0]} ... and {len(saved_files) - 1} more")
                            
                            if skipped_files:
                                st.warning(f"⚠️ Skipped {len(skipped_files)} file(s) (already exist or errors)")
                            
                            if saved_files:
                                st.info("ℹ️ The processing job will automatically add date prefixes and process these files.")
                            
                            # Small delay then rerun to clear uploader
                            if saved_files:
                                time.sleep(2)
                                st.rerun()
                            
                        except Exception as e:
                            st.error(f"Error saving files: {e}")
                            logger.error(f"Bulk upload error: {e}", exc_info=True)
        
        st.markdown("---")
        
        from ollama_client import list_available_models
        
        if check_ollama_health():
            try:
                models = list_available_models()
                if models:
                    # Get current default model
                    default_model = get_summarizing_model()
                    
                    # Ensure default model is in the list
                    if default_model not in models:
                        model_options = [default_model] + models
                        default_index = 0
                    else:
                        model_options = models
                        default_index = model_options.index(default_model) if default_model in model_options else 0
                    
                    selected_model = st.selectbox(
                        "Re-Analysis Model",
                        options=model_options,
                        index=default_index,
                        help="Select AI model to use when re-analyzing articles (default: current summarizing model)",
                        key="admin_reanalysis_model"
                    )
                    st.session_state.reanalysis_model = selected_model
                    
                    # Re-Analyze Selected button
                    if st.button("🔄 Re-Analyze Selected", key="sidebar_reanalyze", type="primary", use_container_width=True):
                        selected_ids = list(st.session_state.get('selected_articles', set()))
                        
                        if not selected_ids:
                            st.warning("No articles selected. Select articles using checkboxes.")
                        else:
                            # Need to get articles to show titles - use a simple query
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            success_count = 0
                            error_count = 0
                            
                            for idx, article_id in enumerate(selected_ids):
                                status_text.text(f"Re-analyzing article {idx + 1}/{len(selected_ids)}...")
                                
                                success, message = reanalyze_article(article_id, selected_model)
                                
                                if success:
                                    success_count += 1
                                else:
                                    error_count += 1
                                
                                progress_bar.progress((idx + 1) / len(selected_ids))
                            
                            progress_bar.empty()
                            status_text.empty()
                            
                            if success_count > 0:
                                st.success(f"✅ Re-analyzed {success_count} article(s)")
                                st.session_state.refresh_key += 1
                                st.session_state.selected_articles = set()
                            
                            if error_count > 0:
                                st.error(f"❌ Failed to re-analyze {error_count} article(s)")
                else:
                    st.warning("No models available. Pull a model first (e.g., `ollama pull llama3`)")
                    st.session_state.reanalysis_model = get_summarizing_model()
            except Exception as e:
                logger.error(f"Error listing models: {e}")
                st.error(f"Error loading models: {e}")
                st.session_state.reanalysis_model = get_summarizing_model()
        else:
            st.warning("Ollama not available")
            st.session_state.reanalysis_model = get_summarizing_model()
    
    st.markdown("---")
    
    # Reset pagination when filters change
    filter_key = f"{date_range_option}_{article_type}_{selected_ticker}_{search_filter or ''}_{filter_owned_tickers}"
    if 'last_filter_key' not in st.session_state or st.session_state.last_filter_key != filter_key:
        st.session_state.current_page = 1
        st.session_state.last_filter_key = filter_key
    
    # Refresh button
    if st.button("🔄 Refresh", use_container_width=True):
        st.session_state.refresh_key += 1
        st.session_state.current_page = 1  # Reset to first page
        st.rerun()

# Cached data fetching functions
@st.cache_data(ttl=60, show_spinner=False)
def get_cached_statistics(_repo, refresh_key: int):
    """Get article statistics with caching (60s TTL)"""
    return _repo.get_article_statistics(days=90)

@st.cache_data(ttl=300, show_spinner=False)
def get_cached_owned_tickers(_refresh_key: int):
    """Get owned tickers from all production funds with caching (5min TTL)
    
    Returns normalized tickers (uppercase, trimmed) for consistent comparison.
    """
    try:
        from supabase_client import SupabaseClient
        from research_utils import normalize_ticker
        
        # Use role-based access for security
        if is_admin():
            client = SupabaseClient(use_service_role=True)
        else:
            user_token = get_user_token()
            if user_token:
                client = SupabaseClient(user_token=user_token)
            else:
                logger.warning("No user token available, cannot fetch owned tickers")
                return set()
        
        if not client:
            return set()
        
        # Get production funds
        funds_result = client.supabase.table("funds")\
            .select("name")\
            .eq("is_production", True)\
            .execute()
        
        if not funds_result.data:
            return set()
        
        prod_funds = [f['name'] for f in funds_result.data]
        logger.debug(f"Checking production funds: {prod_funds}")
        
        positions_result = client.supabase.table("latest_positions")\
            .select("ticker, fund")\
            .in_("fund", prod_funds)\
            .execute()
        
        if positions_result.data:
            # Normalize all tickers for consistent comparison
            owned_tickers = set()
            fund_ticker_map = {}  # Debug: track which fund has which tickers
            for pos in positions_result.data:
                ticker = pos.get('ticker')
                fund = pos.get('fund')
                if ticker:
                    normalized = normalize_ticker(ticker)
                    if normalized:
                        owned_tickers.add(normalized)
                        # Track fund-ticker mapping for debug
                        if fund not in fund_ticker_map:
                            fund_ticker_map[fund] = set()
                        fund_ticker_map[fund].add(normalized)
            
            # Debug logging
            logger.debug(f"Found {len(owned_tickers)} unique owned tickers")
            for fund, tickers in fund_ticker_map.items():
                logger.debug(f"  {fund}: {sorted(tickers)[:10]}{'...' if len(tickers) > 10 else ''}")
            
            return owned_tickers
        
        return set()
    except Exception as e:
        logger.warning(f"Could not fetch owned tickers: {e}")
        return set()

@st.cache_data(ttl=60, show_spinner=False)
def get_cached_embedding_stats(_repo, refresh_key: int):
    """Get embedding statistics with caching (60s TTL)"""
    try:
        embedding_stats_query = "SELECT COUNT(*) as total, COUNT(embedding) as embedded FROM research_articles"
        result = _repo.client.execute_query(embedding_stats_query)
        if result:
            return result[0]['total'], result[0]['embedded']
        return 0, 0
    except Exception:
        return 0, 0

@st.cache_data(ttl=30, show_spinner=False)
def get_cached_articles(
    _repo,
    refresh_key: int,
    use_date_filter: bool,
    start_datetime_str: str,
    end_datetime_str: str,
    article_type_filter: str,
    source_filter: str,
    search_filter: str,
    embedding_filter: bool,
    tickers_filter_json: str,
    results_per_page: int,
    offset: int
):
    """Get articles with caching (30s TTL for fresher data during active use)
    
    Args:
        tickers_filter_json: JSON-encoded list of tickers to filter by, or empty string for no filter
    """
    import json
    
    # Parse tickers filter from JSON (needed for cache key serialization)
    tickers_filter = None
    if tickers_filter_json:
        try:
            tickers_filter = json.loads(tickers_filter_json)
        except (json.JSONDecodeError, TypeError):
            tickers_filter = None
    
    try:
        if use_date_filter and start_datetime_str and end_datetime_str:
            start_dt = datetime.fromisoformat(start_datetime_str)
            end_dt = datetime.fromisoformat(end_datetime_str)
            articles = _repo.get_articles_by_date_range(
                start_date=start_dt,
                end_date=end_dt,
                article_type=article_type_filter if article_type_filter else None,
                source=source_filter if source_filter else None,
                search_text=search_filter if search_filter else None,
                embedding_filter=embedding_filter,
                tickers_filter=tickers_filter,
                limit=results_per_page,
                offset=offset
            )
        else:
            articles = _repo.get_all_articles(
                article_type=article_type_filter if article_type_filter else None,
                source=source_filter if source_filter else None,
                search_text=search_filter if search_filter else None,
                embedding_filter=embedding_filter,
                tickers_filter=tickers_filter,
                limit=results_per_page,
                offset=offset
            )
        return articles
    except Exception as e:
        logger.error(f"Error fetching articles: {e}", exc_info=True)
        return []

@st.cache_data(ttl=30, show_spinner=False)
def get_cached_article_count(
    _repo,
    refresh_key: int,
    use_date_filter: bool,
    start_datetime_str: str,
    end_datetime_str: str,
    article_type_filter: str,
    source_filter: str,
    search_filter: str,
    embedding_filter: bool,
    tickers_filter_json: str
):
    """Get total article count with caching (30s TTL)
    
    Args:
        tickers_filter_json: JSON-encoded list of tickers to filter by, or empty string for no filter
    """
    import json
    
    # Parse tickers filter from JSON (needed for cache key serialization)
    tickers_filter = None
    if tickers_filter_json:
        try:
            tickers_filter = json.loads(tickers_filter_json)
        except (json.JSONDecodeError, TypeError):
            tickers_filter = None
    
    try:
        if use_date_filter and start_datetime_str and end_datetime_str:
            start_dt = datetime.fromisoformat(start_datetime_str)
            end_dt = datetime.fromisoformat(end_datetime_str)
            count = _repo.get_article_count(
                start_date=start_dt,
                end_date=end_dt,
                article_type=article_type_filter if article_type_filter else None,
                source=source_filter if source_filter else None,
                search_text=search_filter if search_filter else None,
                embedding_filter=embedding_filter,
                tickers_filter=tickers_filter
            )
        else:
            count = _repo.get_article_count(
                article_type=article_type_filter if article_type_filter else None,
                source=source_filter if source_filter else None,
                search_text=search_filter if search_filter else None,
                embedding_filter=embedding_filter,
                tickers_filter=tickers_filter
            )
        return count
    except Exception as e:
        logger.error(f"Error fetching article count: {e}", exc_info=True)
        return 0

# Main content area
try:
    # Get statistics (cached)
    with st.spinner("Loading statistics..."):
        stats = get_cached_statistics(repo, st.session_state.refresh_key)
    
    # Statistics dashboard
    st.header("📊 Statistics")
    
    # Get embedding statistics (cached)
    total_articles, embedded_articles = get_cached_embedding_stats(repo, st.session_state.refresh_key)
    embedding_pct = (embedded_articles / total_articles * 100) if total_articles > 0 else 0
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Total Articles", total_articles)
    
    with col2:
        type_counts = stats.get('by_type', {})
        market_news = type_counts.get('market_news', 0)
        st.metric("Market News", market_news)
    
    with col3:
        ticker_news = type_counts.get('ticker_news', 0)
        st.metric("Ticker News", ticker_news)
    
    with col4:
        earnings = type_counts.get('earnings', 0)
        st.metric("Earnings", earnings)
    
    with col5:
        st.metric("Embedded (RAG)", f"{embedded_articles}", delta=f"{embedding_pct:.0f}%")
    
    # Charts
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        if stats.get('by_source'):
            source_data = stats['by_source']
            if source_data:
                source_df = pd.DataFrame(list(source_data.items()), columns=['Source', 'Count'])
                source_df = source_df.sort_values('Count', ascending=False).head(10)
                st.bar_chart(source_df.set_index('Source'))
                st.caption("Top 10 Sources")
    
    with col_chart2:
        if stats.get('by_day'):
            day_data = stats['by_day']
            if day_data:
                day_df = pd.DataFrame(list(day_data.items()), columns=['Date', 'Count'])
                day_df['Date'] = pd.to_datetime(day_df['Date'])
                day_df = day_df.sort_values('Date')
                st.line_chart(day_df.set_index('Date'))
                st.caption("Articles by Day (Last 90 days)")
    
    st.markdown("---")
    
    # Get filtered articles (cached)
    with st.spinner("Loading articles..."):
        import json as json_lib
        
        # Calculate pagination
        page = st.session_state.get('current_page', 1)
        offset = (page - 1) * results_per_page
        
        # Convert datetime to ISO string for cache key (or empty string if None)
        start_dt_str = start_datetime.isoformat() if start_datetime else ""
        end_dt_str = end_datetime.isoformat() if end_datetime else ""
        
        # Pre-fetch owned tickers if filter is enabled (for database-level filtering)
        tickers_filter_json = ""
        if filter_owned_tickers:
            owned_tickers = get_cached_owned_tickers(st.session_state.refresh_key)
            if owned_tickers:
                # Convert set to sorted list for consistent caching
                tickers_filter_json = json_lib.dumps(sorted(list(owned_tickers)))
            else:
                # No owned tickers found, pass empty list to get no results
                tickers_filter_json = "[]"
        
        articles = get_cached_articles(
            repo,
            st.session_state.refresh_key,
            use_date_filter,
            start_dt_str,
            end_dt_str,
            article_type_filter or "",
            source_filter or "",
            search_filter or "",
            embedding_filter,
            tickers_filter_json,
            results_per_page,
            offset
        )
        
        # Fetch total count for pagination
        total_count = get_cached_article_count(
            repo,
            st.session_state.refresh_key,
            use_date_filter,
            start_dt_str,
            end_dt_str,
            article_type_filter or "",
            source_filter or "",
            search_filter or "",
            embedding_filter,
            tickers_filter_json
        )
        
        # Apply specific ticker filter client-side (dropdown selection - for single ticker)
        if ticker_filter:
            articles = [
                a for a in articles 
                if (a.get('tickers') and ticker_filter in a.get('tickers', [])) 
                   or a.get('ticker') == ticker_filter
            ]
            # Note: When ticker_filter is applied client-side, total_count is not accurate
            # We'll show the filtered count instead
            total_count = len(articles)
        
        # Calculate pagination info
        total_pages = max(1, (total_count + results_per_page - 1) // results_per_page)
        article_count = len(articles)
        has_more = page < total_pages
    
    # Results header
    st.header("📄 Articles")
    
    # Legend for article type and status emojis
    with st.expander("📋 Legend: Article Type & Status Icons", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Article Type Icons:**")
            st.markdown("""
            - 📰 **Market News** - General market news and updates
            - 🔍 **Ticker News** - News specific to a ticker
            - 💡 **Opportunity Discovery** - Discovered investment opportunities
            - 📤 **Research Report** - Manually uploaded research reports
            - 💰 **Earnings** - Earnings reports and announcements
            - 📄 **General** - Other articles
            """)
        
        with col2:
            st.markdown("**Status Icons:**")
            st.markdown("""
            - 🧠 **AI Processed** - Article has been analyzed and embedded for AI search
            - ⏳ **Pending** - Article is waiting for AI processing
            - ✅ **Owned Ticker** - Article mentions ticker(s) owned in your portfolio
            """)
    
    # Show owned tickers count when filter is active
    if filter_owned_tickers:
        owned_tickers = get_cached_owned_tickers(st.session_state.refresh_key)
        if owned_tickers:
            ticker_list = sorted(list(owned_tickers))
            st.caption(f"📊 Filtering to {len(owned_tickers)} owned ticker(s): {', '.join(ticker_list[:15])}{'...' if len(owned_tickers) > 15 else ''}")
            
            # Debug expander for troubleshooting
            with st.expander("🔍 Debug: Owned Tickers Filter", expanded=False):
                st.write(f"**Total owned tickers:** {len(owned_tickers)}")
                st.write(f"**Tickers:** {', '.join(ticker_list)}")
                
                # Check for specific ticker
                from research_utils import normalize_ticker as normalize_ticker_func
                test_ticker = st.text_input("Test ticker match", value="COST", key="debug_test_ticker")
                if test_ticker:
                    normalized_test = normalize_ticker_func(test_ticker)
                    if normalized_test and normalized_test in owned_tickers:
                        st.success(f"✅ '{test_ticker}' -> '{normalized_test}' FOUND in owned tickers")
                    else:
                        st.error(f"❌ '{test_ticker}' -> '{normalized_test}' NOT FOUND in owned tickers")
                        # Show similar tickers
                        if normalized_test:
                            similar = [t for t in ticker_list if normalized_test.upper() in t.upper() or t.upper() in normalized_test.upper()]
                            if similar:
                                st.info(f"Similar tickers found: {similar}")
        else:
            st.warning("⚠️ No owned tickers found. Make sure you have positions in production funds.")
    
    if not articles:
        st.info("No articles found matching your filters. Try adjusting your search criteria.")
    else:
        # Initialize selected articles in session state
        if 'selected_articles' not in st.session_state:
            st.session_state.selected_articles = set()
        
        # Admin selection controls (minimal, no batch actions section)
        if is_admin():
            current_page_ids = {article['id'] for article in articles}
            selected_count = len(st.session_state.selected_articles)
            page_selected_count = len(current_page_ids & st.session_state.selected_articles)
            
            # Show selection status
            if selected_count > 0:
                st.caption(f"📌 {selected_count} selected ({page_selected_count} on this page)")
            
            # Selection buttons in a row
            sel_col1, sel_col2, sel_col3 = st.columns(3)
            
            with sel_col1:
                # Select All Results (Global)
                if st.button("🌍 Select All Results", key="select_global_btn", use_container_width=True, 
                           help="Select ALL articles matching current filters (across all pages)"):
                    with st.spinner("Selecting all..."):
                        # Re-run query to get ALL matching IDs
                        if use_date_filter:
                            all_matching = repo.get_articles_by_date_range(
                                start_date=start_datetime,
                                end_date=end_datetime,
                                article_type=article_type_filter,
                                source=source_filter,
                                search_text=search_filter,
                                embedding_filter=embedding_filter,
                                limit=10000,
                                offset=0
                            )
                        else:
                            all_matching = repo.get_all_articles(
                                article_type=article_type_filter,
                                source=source_filter,
                                search_text=search_filter,
                                embedding_filter=embedding_filter,
                                limit=10000,
                                offset=0
                            )
                        
                        all_ids = {a['id'] for a in all_matching}
                        st.session_state.selected_articles.update(all_ids)
                        
                        # Sync visible checkboxes
                        for article_id in current_page_ids:
                            st.session_state[f"select_{article_id}"] = True
                    st.rerun()
            
            with sel_col2:
                # Add Page (Current Page)
                if st.button("☑️ Add Page", key="select_page_btn", use_container_width=True,
                           help="Add all articles on this page to current selection"):
                    st.session_state.selected_articles.update(current_page_ids)
                    # Sync checkbox widget states
                    for article_id in current_page_ids:
                        st.session_state[f"select_{article_id}"] = True
                    st.rerun()
            
            with sel_col3:
                # Clear All
                if st.button("✖️ Clear All", key="clear_selection_btn", use_container_width=True,
                           help="Clear all selections"):
                    # Clear all checkbox states
                    for article_id in st.session_state.selected_articles:
                        if f"select_{article_id}" in st.session_state:
                            st.session_state[f"select_{article_id}"] = False
                    st.session_state.selected_articles = set()
                    st.rerun()
        
        # Pagination controls - Enhanced with total count and jump-to-page
        st.markdown("---")
        
        # Display pagination info and controls
        col_info, col_nav = st.columns([2, 3])
        
        with col_info:
            st.markdown(f"**Page {page} of {total_pages}** | Total results: **{total_count:,}** | Showing: **{len(articles)}**")
        
        with col_nav:
            nav_col1, nav_col2, nav_col3, nav_col4 = st.columns([1, 1, 1, 0.6])
            
            with nav_col1:
                if page > 1:
                    if st.button("◀ Previous", use_container_width=True):
                        st.session_state.current_page = page - 1
                        st.rerun()
            
            with nav_col2:
                if has_more:
                    if st.button("Next ▶", use_container_width=True):
                        st.session_state.current_page = page + 1
                        st.rerun()
            
            with nav_col3:
                # Jump to page input - using text_input to avoid auto-refresh on +/-
                jump_page_str = st.text_input(
                    "Jump to page",
                    value=str(page),
                    key="jump_page_input",
                    label_visibility="collapsed",
                    placeholder=f"Page (1-{total_pages})"
                )
                # Parse and validate
                try:
                    jump_page = int(jump_page_str)
                    jump_page = max(1, min(jump_page, total_pages))  # Clamp to valid range
                except (ValueError, TypeError):
                    jump_page = page  # Default to current page if invalid
            
            with nav_col4:
                if st.button("Go", use_container_width=True):
                    if jump_page != page:
                        st.session_state.current_page = jump_page
                        st.rerun()
        
        # Export button
        if st.button("📥 Export to CSV", use_container_width=False):
            # Get all matching articles (without pagination) for export
            export_articles = repo.get_articles_by_date_range(
                start_date=start_datetime,
                end_date=end_datetime,
                article_type=article_type_filter,
                source=source_filter,
                search_text=search_filter,
                limit=10000,  # Large limit for export
                offset=0
            )
            
            if export_articles:
                # Prepare DataFrame
                export_data = []
                for article in export_articles:
                    export_data.append({
                        'Title': article.get('title', ''),
                        'Source': article.get('source', ''),
                        'Type': article.get('article_type', ''),
                        'Published': article.get('published_at', ''),
                        'Fetched': article.get('fetched_at', ''),
                        'URL': article.get('url', ''),
                        'Summary': article.get('summary', '')[:500] if article.get('summary') else '',
                        'Tickers': ', '.join(article.get('tickers', [])) if isinstance(article.get('tickers'), list) else (article.get('ticker', '') or ''),
                        'Sector': article.get('sector', ''),
                        'Relevance Score': article.get('relevance_score', '')
                    })
                
                df_export = pd.DataFrame(export_data)
                csv = df_export.to_csv(index=False)
                st.download_button(
                    label="⬇️ Download CSV",
                    data=csv,
                    file_name=f"research_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            else:
                st.warning("No articles to export")
        
        st.markdown("---")
        
        # Cache admin status once (avoid repeated function calls)
        user_is_admin = is_admin()
        
        # Define fragment ONCE outside the loop for admin actions (major performance win)
        if user_is_admin:
            @st.fragment
            def render_admin_actions(article_id: str, article_title: str, article: dict):
                """Fragment for admin actions - only this section re-renders on button click"""
                # Fund assignment for uploaded reports
                article_type = article.get('article_type', '')
                if article_type == "uploaded_report":
                    st.markdown("**📊 Fund Assignment**")
                    try:
                        funds = get_available_funds()
                        current_fund = article.get('fund')
                        
                        # Create options: current fund (if set), blank option, then other funds
                        fund_options = []
                        if current_fund:
                            fund_options.append(current_fund)
                        fund_options.append("")  # Blank option to clear fund
                        for fund in funds:
                            if fund != current_fund:
                                fund_options.append(fund)
                        
                        # Find index of current fund (or blank if None)
                        default_index = 0 if current_fund else 1
                        
                        selected_fund = st.selectbox(
                            "Change Fund",
                            options=fund_options,
                            index=default_index,
                            key=f"fund_select_{article_id}",
                            help="Select a fund for this uploaded report, or leave blank for general use"
                        )
                        
                        # Always show save button for uploaded reports
                        new_fund = selected_fund if selected_fund else None
                        if st.button("💾 Save Fund", key=f"save_fund_{article_id}", type="primary", use_container_width=True):
                            if new_fund == current_fund:
                                st.info("No changes to save")
                            elif repo.update_article_fund(article_id, new_fund):
                                st.success(f"✅ Fund updated to: {new_fund if new_fund else 'None (general)'}")
                                st.session_state.refresh_key += 1
                                st.rerun()
                            else:
                                st.error("❌ Failed to update fund")
                    except Exception as e:
                        logger.error(f"Error loading funds for fund selector: {e}")
                        st.warning("Could not load funds list")
                
                st.markdown("---")
                
                # Delete button
                if st.button("🗑️ Delete", key=f"del_{article_id}", type="secondary", use_container_width=True):
                    if repo.delete_article(article_id):
                        st.success(f"✅ Deleted: {article_title}")
                        st.session_state.refresh_key += 1
                    else:
                        st.error("❌ Failed to delete article")
        
        # Helper to format article metadata (reduces duplication)
        def format_article_metadata(article: dict) -> str:
            """Build metadata HTML string for faster single-render."""
            parts = []
            parts.append(f"**Source:** {article.get('source', 'N/A')}")
            parts.append(f"**Type:** {article.get('article_type', 'N/A')}")
            # Tickers - show as clickable links
            tickers = article.get('tickers')
            if tickers:
                if isinstance(tickers, list):
                    # Convert each ticker to a clickable link
                    clickable_tickers = [render_ticker_link(ticker, ticker) for ticker in tickers]
                    parts.append(f"**Tickers:** {', '.join(clickable_tickers)}")
                else:
                    parts.append(f"**Tickers:** {render_ticker_link(str(tickers), str(tickers))}")
            elif article.get('ticker'):
                ticker = article.get('ticker')
                parts.append(f"**Ticker:** {render_ticker_link(ticker, ticker)}")
            
            if article.get('sector'):
                parts.append(f"**Sector:** {article.get('sector')}")
            
            return "  \n".join(parts)  # Markdown line breaks
        
        def format_article_dates(article: dict) -> str:
            """Build date metadata HTML string."""
            parts = []
            if article.get('published_at'):
                pub_date = article['published_at']
                if isinstance(pub_date, str):
                    pub_date = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                pub_date_local = to_local_time(pub_date)
                parts.append(f"**Published:** {pub_date_local.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if article.get('fetched_at'):
                fetch_date = article['fetched_at']
                if isinstance(fetch_date, str):
                    fetch_date = datetime.fromisoformat(fetch_date.replace('Z', '+00:00'))
                fetch_date_local = to_local_time(fetch_date)
                parts.append(f"**Fetched:** {fetch_date_local.strftime('%Y-%m-%d %H:%M:%S')}")
            
            if article.get('relevance_score'):
                parts.append(f"**Relevance:** {article['relevance_score']:.2f}")
            
            return "  \n".join(parts)
        
        def render_article_content(article: dict, show_admin_actions: bool):
            """Render article content inside expander (shared by admin/non-admin paths)."""
            
            # Special UI for Reddit Discovery
            if article.get('article_type') == 'reddit_discovery':
                st.info(f"👽 **Reddit Discovery** | Source: {article.get('title', '').split(']')[0][1:] if ']' in article.get('title', '') else 'Reddit'}")
                
            col_info1, col_info2 = st.columns(2)
            
            with col_info1:
                # Show standard metadata but highlight Reddit specifics
                if article.get('article_type') == 'reddit_discovery':
                     st.metric("Confidence Score", f"{article.get('relevance_score', 0.0):.2f}")
                else:
                    st.markdown(format_article_metadata(article))
                
                # Add ticker navigation buttons below metadata
                tickers = article.get('tickers') or ([article.get('ticker')] if article.get('ticker') else [])
                if tickers and isinstance(tickers, list):
                    st.caption("Click ticker to view details:")
                    # Create a row of ticker buttons
                    ticker_cols = st.columns(min(len(tickers), 5))  # Max 5 per row
                    for idx, ticker in enumerate(tickers[:5]):  # Limit to first 5
                        with ticker_cols[idx]:
                            if st.button(f"📊 {ticker}", key=f"ticker_{article['id']}_{ticker}", use_container_width=True):
                                st.session_state['selected_ticker'] = ticker
                                st.switch_page("pages/ticker_details.py")
            
            with col_info2:
                st.markdown(format_article_dates(article))
            
            # URL links (original + archive if available)
            if article.get('url'):
                # Construct proper URL for research reports
                article_url = article['url']
                # If it's a research report, prepend /research/ to match Caddyfile route
                if article.get('article_type') == 'Research Report' and not article_url.startswith('http'):
                    # URL is stored as relative path from Research folder (e.g., "GANX/file.pdf")
                    # Caddyfile serves /research/* from root /ai-trading
                    # So /research/GANX/file.pdf maps to /ai-trading/research/GANX/file.pdf
                    # Handle legacy URLs that might have "Research/" prefix
                    if article_url.startswith('Research/'):
                        article_url = article_url[9:]  # Remove "Research/" prefix
                    article_url = f"/research/{article_url}"
                
                st.link_button("🔗 Open Original Article", article_url, use_container_width=True)
                
                # Archive status and link
                archive_url = article.get('archive_url')
                archive_submitted_at = article.get('archive_submitted_at')
                archive_checked_at = article.get('archive_checked_at')
                
                if archive_url:
                    # Successfully archived - show link
                    st.link_button("🔓 View Archived Version (Paywall Bypass)", archive_url, use_container_width=True, type="secondary")
                elif archive_submitted_at:
                    # Submitted but not yet archived
                    from datetime import datetime, timezone
                    if isinstance(archive_submitted_at, str):
                        archive_submitted_at = datetime.fromisoformat(archive_submitted_at.replace('Z', '+00:00'))
                    
                    # Check if recently submitted (within last 10 minutes)
                    time_since_submission = datetime.now(timezone.utc) - archive_submitted_at
                    if time_since_submission.total_seconds() < 600:  # 10 minutes
                        st.info("⏳ **Archiving in progress...** Check back in a few minutes for paywall bypass link.")
                    elif archive_checked_at:
                        # Checked but no URL found - likely failed
                        st.warning("🔒 **Paywalled** - Archive service unable to bypass. Original source requires subscription.")
                    else:
                        # Submitted but not checked yet
                        st.info("⏳ **Submitted for archiving** - Will check archive status shortly.")
            
            # Admin actions
            if show_admin_actions:
                render_admin_actions(article['id'], article.get('title', 'Article'), article)
            
            st.markdown("---")
            
            # Sentiment Badge (if available)
            sentiment = article.get('sentiment')
            sentiment_score = article.get('sentiment_score')
            if sentiment:
                sentiment_colors = {
                    'VERY_BULLISH': '🟢',
                    'BULLISH': '🟡',
                    'NEUTRAL': '⚪',
                    'BEARISH': '🟠',
                    'VERY_BEARISH': '🔴'
                }
                sentiment_icon = sentiment_colors.get(sentiment, '⚪')
                score_text = f" (Score: {sentiment_score:.1f})" if sentiment_score is not None else ""
                st.markdown(f"**Sentiment:** {sentiment_icon} {sentiment}{score_text}")
            
            # Summary
            if article.get('summary'):
                header = "🧠 AI Analysis & Reasoning" if article.get('article_type') == 'reddit_discovery' else "Summary"
                st.subheader(header)
                # Escape special characters to prevent Streamlit from interpreting them as Markdown/LaTeX
                summary_text = escape_markdown(article['summary'])
                st.write(summary_text)
            
            # Chain of Thought Analysis (if available)
            if article.get('claims') or article.get('fact_check') or article.get('conclusion'):
                st.markdown("---")
                st.subheader("🔍 Chain of Thought Analysis")
                
                # Claims
                claims = article.get('claims')
                if claims:
                    if isinstance(claims, list) and len(claims) > 0:
                        st.markdown("**📋 Claims Identified:**")
                        for i, claim in enumerate(claims[:10], 1):  # Show first 10
                            st.markdown(f"{i}. {claim}")
                        if len(claims) > 10:
                            st.caption(f"... and {len(claims) - 10} more claims")
                    elif isinstance(claims, str):
                        st.markdown("**📋 Claims:**")
                        st.write(claims)
                
                # Fact Check
                fact_check = article.get('fact_check')
                if fact_check:
                    st.markdown("**✅ Fact Check:**")
                    st.write(fact_check)
                
                # Conclusion
                conclusion = article.get('conclusion')
                if conclusion:
                    st.markdown("**💡 Conclusion:**")
                    st.write(conclusion)
            
            # Content (if available and different from summary)
            if article.get('content') and article.get('content') != article.get('summary'):
                with st.expander("📄 Full Content", expanded=False):
                    content = article['content']
                    chars_per_page = 5000  # Characters per page to prevent browser performance issues
                    
                    # Initialize page tracking in session state for this article
                    page_key = f"content_page_{article['id']}"
                    if page_key not in st.session_state:
                        st.session_state[page_key] = 0
                    
                    current_page = st.session_state[page_key]
                    total_pages = (len(content) + chars_per_page - 1) // chars_per_page  # Ceiling division
                    
                    # Show pagination info if content is long
                    if total_pages > 1:
                        st.info(f"📄 **Long article detected** - Content split into {total_pages} pages ({chars_per_page:,} characters per page)")
                        
                        # Calculate start and end indices for current page
                        start_idx = current_page * chars_per_page
                        end_idx = min(start_idx + chars_per_page, len(content))
                        
                        # Display current page content
                        st.write(content[start_idx:end_idx])
                        
                        # Pagination controls
                        st.markdown("---")
                        col1, col2, col3 = st.columns([1, 2, 1])
                        
                        with col1:
                            if current_page > 0:
                                if st.button("◀ Previous", key=f"prev_{article['id']}", use_container_width=True):
                                    st.session_state[page_key] = current_page - 1
                                    st.rerun()
                        
                        with col2:
                            st.markdown(f"<div style='text-align: center; padding-top: 8px;'><b>Page {current_page + 1} of {total_pages}</b><br/><small>Characters {start_idx + 1:,} - {end_idx:,} of {len(content):,}</small></div>", unsafe_allow_html=True)
                        
                        with col3:
                            if current_page < total_pages - 1:
                                if st.button("Next ▶", key=f"next_{article['id']}", use_container_width=True):
                                    st.session_state[page_key] = current_page + 1
                                    st.rerun()
                    else:
                        # Content fits on one page - display directly
                        st.write(content)
        
        # Get owned tickers for ownership indicator (cached)
        owned_tickers = get_cached_owned_tickers(st.session_state.refresh_key)
        
        # Display articles
        for idx, article in enumerate(articles):
            # Build enhanced title with job icon + status icon
            # Job icon shows which job created the article
            article_type = article.get('article_type', '')
            job_icon_map = {
                # New format (spaces, no underscores)
                'Market News': '📰',
                'Ticker News': '🔍',
                'Opportunity Discovery': '💡',
                'Research Report': '📤',
                'Earnings': '💰',
                'General': '📄',
                'Reddit Discovery': '👽',
                'Alpha Research': '💎',
                'ETF Change': '📊',
                'Seeking Alpha Symbol': '📈',
                # Legacy support (underscores)
                'market_news': '📰',
                'ticker_news': '🔍',
                'opportunity_discovery': '💡',
                'research_report': '📤',
                'uploaded_report': '📤',
                'earnings': '💰',
                'general': '📄',
                'reddit_discovery': '👽',
                'alpha_research': '💎',
                'etf_change': '📊',
                'seeking_alpha_symbol': '📈'
            }
            job_icon = job_icon_map.get(article_type, '📄')
            
            # Status icon shows AI processing state
            has_embedding = article.get('has_embedding', False)
            status_icon = "🧠" if has_embedding else "⏳"
            
            # Check if article has owned tickers
            article_tickers = article.get('tickers', [])
            if not article_tickers and article.get('ticker'):
                article_tickers = [article.get('ticker')]
            
            has_owned_ticker = False
            if owned_tickers and article_tickers:
                # Normalize article tickers and check if any match owned tickers
                normalized_article_tickers = set()
                for ticker in article_tickers:
                    if ticker:
                        normalized = normalize_ticker(ticker)
                        if normalized:
                            normalized_article_tickers.add(normalized)
                
                # Check for overlap
                if normalized_article_tickers & owned_tickers:
                    has_owned_ticker = True
            
            # Ownership indicator
            ownership_indicator = "✅ " if has_owned_ticker else ""
            
            # Combine both icons
            icon_badge = f"{job_icon}{status_icon} {ownership_indicator}"
            
            # Format tickers (show first 2 tickers max for display)
            tickers = article.get('tickers', [])
            if tickers and isinstance(tickers, list):
                ticker_list = tickers[:2]
                ticker_str = ", ".join(ticker_list)
                if len(tickers) > 2:
                    ticker_str += f" +{len(tickers)-2}"
            elif article.get('ticker'):
                ticker_list = [article.get('ticker')]
                ticker_str = article.get('ticker')
            else:
                ticker_list = []
                ticker_str = ""
            
            # Create clickable ticker links for display
            clickable_ticker_links = []
            if ticker_list:
                for ticker in ticker_list:
                    clickable_ticker_links.append(render_ticker_link(ticker, ticker))
                clickable_ticker_display = ", ".join(clickable_ticker_links)
                if tickers and isinstance(tickers, list) and len(tickers) > 2:
                    clickable_ticker_display += f" +{len(tickers)-2}"
            else:
                clickable_ticker_display = ""
            
            # Show fund for uploaded reports
            fund = article.get('fund')
            fund_badge = ""
            if fund and article_type == "uploaded_report":
                fund_badge = f" | 📊 Fund: {fund}"
            
            # Format short date (e.g., "Dec 25")
            pub_date = article.get('published_at') or article.get('fetched_at')
            if pub_date:
                if isinstance(pub_date, str):
                    pub_date = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                date_str = pub_date.strftime("%b %d")
            else:
                date_str = ""
            
            # Build title: Title | Date | Fund (if uploaded report) - ticker removed from title
            title_parts = []
            title_parts.append(article.get('title', 'Untitled')[:60])
            if date_str:
                title_parts.append(date_str)
            
            expander_title = f"{icon_badge}{' | '.join(title_parts)}{fund_badge}"
            
            if user_is_admin:
                # Admin view with checkbox, clickable ticker, and expander
                col_check, col_ticker, col_expander = st.columns([0.05, 0.08, 0.87])
                with col_check:
                    article_id = article['id']
                    checkbox_key = f"select_{article_id}"
                    is_selected = article_id in st.session_state.selected_articles
                    
                    # Initialize checkbox state if not present (avoids value/session state conflict)
                    if checkbox_key not in st.session_state:
                        st.session_state[checkbox_key] = is_selected
                    
                    def make_checkbox_callback(aid):
                        def callback():
                            if st.session_state[f"select_{aid}"]:
                                st.session_state.selected_articles.add(aid)
                            else:
                                st.session_state.selected_articles.discard(aid)
                        return callback
                    
                    st.checkbox(
                        "",
                        key=checkbox_key,
                        label_visibility="collapsed",
                        on_change=make_checkbox_callback(article_id)
                    )
                
                with col_ticker:
                    if clickable_ticker_display:
                        st.markdown(clickable_ticker_display)
                
                with col_expander:
                    with st.expander(expander_title, expanded=False):
                        render_article_content(article, show_admin_actions=True)
            else:
                # Non-admin view - clickable ticker and expander
                col_ticker, col_expander = st.columns([0.08, 0.92])
                with col_ticker:
                    if clickable_ticker_display:
                        st.markdown(clickable_ticker_display)
                
                with col_expander:
                    with st.expander(expander_title, expanded=False):
                        render_article_content(article, show_admin_actions=False)
        
        # Bottom pagination controls - duplicate for easy navigation after scrolling
        st.markdown("---")
        
        # Display pagination info and controls
        col_info_bottom, col_nav_bottom = st.columns([2, 3])
        
        with col_info_bottom:
            st.markdown(f"**Page {page} of {total_pages}** | Total results: **{total_count:,}** | Showing: **{len(articles)}**")
        
        with col_nav_bottom:
            nav_col1_bottom, nav_col2_bottom, nav_col3_bottom, nav_col4_bottom = st.columns([1, 1, 1, 0.6])
            
            with nav_col1_bottom:
                if page > 1:
                    if st.button("◀ Previous", use_container_width=True, key="prev_bottom"):
                        st.session_state.current_page = page - 1
                        st.rerun()
            
            with nav_col2_bottom:
                if has_more:
                    if st.button("Next ▶", use_container_width=True, key="next_bottom"):
                        st.session_state.current_page = page + 1
                        st.rerun()
            
            with nav_col3_bottom:
                # Jump to page input - using text_input to avoid auto-refresh on +/-
                jump_page_str_bottom = st.text_input(
                    "Jump to page",
                    value=str(page),
                    key="jump_page_input_bottom",
                    label_visibility="collapsed",
                    placeholder=f"Page (1-{total_pages})"
                )
                # Parse and validate
                try:
                    jump_page_bottom = int(jump_page_str_bottom)
                    jump_page_bottom = max(1, min(jump_page_bottom, total_pages))  # Clamp to valid range
                except (ValueError, TypeError):
                    jump_page_bottom = page  # Default to current page if invalid
            
            with nav_col4_bottom:
                if st.button("Go", use_container_width=True, key="go_bottom"):
                    if jump_page_bottom != page:
                        st.session_state.current_page = jump_page_bottom
                        st.rerun()


except Exception as e:
    logger.error(f"Error loading research articles: {e}", exc_info=True)
    st.error(f"❌ Error loading articles: {e}")
    st.info("Please try refreshing the page or contact an administrator if the problem persists.")

