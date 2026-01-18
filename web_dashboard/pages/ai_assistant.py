#!/usr/bin/env python3
"""
AI Assistant Chat Interface
===========================

Streamlit page for AI-powered portfolio investigation.
Users can chat with AI about their portfolio data.
"""

import streamlit as st
import sys
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import pandas as pd
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from auth_utils import is_authenticated, get_user_id, redirect_to_login
from chat_context import ChatContextManager, ContextItem, ContextItemType # Added ContextItem
from ollama_client import get_ollama_client, check_ollama_health, list_available_models
from searxng_client import get_searxng_client, check_searxng_health
from search_utils import (
    format_search_results, build_search_query, should_trigger_search, detect_research_intent, get_company_name_from_db, filter_relevant_results
)
from ai_context_builder import (
    format_holdings, format_thesis, format_trades, format_performance_metrics,
    format_cash_balances
)
from ai_prompts import get_system_prompt
from user_preferences import get_user_ai_model, set_user_ai_model
from streamlit_utils import (
    get_current_positions, get_trade_log, get_cash_balances,
    calculate_portfolio_value_over_time, get_fund_thesis_data, get_available_funds,
    calculate_performance_metrics, render_sidebar_fund_selector
)
from research_repository import ResearchRepository
from research_utils import escape_markdown

logger = logging.getLogger(__name__)

# Import WebAI wrapper at module level with error handling
try:
    from webai_wrapper import PersistentConversationSession
    HAS_WEBAI = True
except ImportError:
    HAS_WEBAI = False
    PersistentConversationSession = None
    logger.warning("WebAI package not available. WebAI Pro will be disabled.")

# Import model display names from keys file
try:
    from ai_service_keys import get_model_display_name, get_model_display_name_short
    HAS_MODEL_KEYS = True
except (ImportError, FileNotFoundError, KeyError, ValueError) as e:
    HAS_MODEL_KEYS = False
    # Fallback functions if keys file not available
    def get_model_display_name(model_id: str) -> str:
        # Fallback: use generic names if keys not available
        # Never expose service name in code - use webai_wrapper for model list
        try:
            from webai_wrapper import get_webai_models
            webai_models = get_webai_models()
            # Generate generic names based on model suffix
            for wm in webai_models:
                if model_id == wm:
                    suffix = wm.split("-", 1)[-1] if "-" in wm else wm
                    return f"AI {suffix.replace('-', ' ').title()}"
        except ImportError:
            pass
        return "AI Model"
    def get_model_display_name_short() -> str:
        # Fallback: use generic name if keys not available
        return "AI Pro"
    # Log warning but don't crash
    logger.debug(f"Model display keys file not available: {e}. Using fallback names.")

# Page configuration
st.set_page_config(
    page_title="AI Assistant",
    page_icon="🧠",  # Match navigation.py emoji
    layout="wide"
)

# Custom CSS for right sidebar and chat container styling
st.markdown("""
<style>
    /* Right sidebar container - make it sticky */
    .quick-research-sidebar {
        position: sticky;
        top: 3.5rem;
        max-height: calc(100vh - 4rem);
        overflow-y: auto;
        padding-left: 1rem;
        border-left: 2px solid rgba(128, 128, 128, 0.2);
    }
    
    /* Chat container - scrollable with fixed height */
    .chat-container {
        max-height: calc(100vh - 300px);
        min-height: 400px;
        overflow-y: auto;
        overflow-x: hidden;
        padding: 1rem;
        margin-bottom: 1rem;
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 0.5rem;
        display: flex;
        flex-direction: column;
    }
    
    /* Prevent child elements from breaking out of container */
    .chat-container > div {
        flex-shrink: 0;
    }
    
    /* Auto-scroll to bottom behavior */
    .chat-container::-webkit-scrollbar {
        width: 8px;
    }
    
    .chat-container::-webkit-scrollbar-track {
        background: rgba(128, 128, 128, 0.1);
        border-radius: 4px;
    }
    
    .chat-container::-webkit-scrollbar-thumb {
        background: rgba(128, 128, 128, 0.3);
        border-radius: 4px;
    }
    
    .chat-container::-webkit-scrollbar-thumb:hover {
        background: rgba(128, 128, 128, 0.5);
    }
    
    /* Dark mode support */
    @media (prefers-color-scheme: dark) {
        .quick-research-sidebar {
            border-left-color: rgba(128, 128, 128, 0.3);
        }
        .chat-container {
            border-color: rgba(128, 128, 128, 0.3);
        }
    }
    
    /* Improve scrolling on mobile */
    @media (max-width: 768px) {
        .quick-research-sidebar {
            position: relative;
            border-left: none;
            border-top: 2px solid rgba(128, 128, 128, 0.2);
            padding-left: 0;
            padding-top: 1rem;
        }
        .chat-container {
            height: 60vh;
        }
    }
</style>

<script>
    // Auto-scroll chat container to bottom on load and updates
    function scrollChatToBottom() {
        const chatContainer = document.querySelector('.chat-container');
        if (chatContainer) {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
    }
    
    // Run on page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', scrollChatToBottom);
    } else {
        scrollChatToBottom();
    }
    
    // Also run after delays to catch dynamic content
    setTimeout(scrollChatToBottom, 100);
    setTimeout(scrollChatToBottom, 300);
    setTimeout(scrollChatToBottom, 500);
    setTimeout(scrollChatToBottom, 1000);
    
    // Watch for DOM changes in the chat container
    const observer = new MutationObserver(scrollChatToBottom);
    const observeChatContainer = () => {
        const chatContainer = document.querySelector('.chat-container');
        if (chatContainer) {
            observer.observe(chatContainer, { childList: true, subtree: true });
        } else {
            // Retry after a short delay if container not found yet
            setTimeout(observeChatContainer, 100);
        }
    };
    observeChatContainer();
</script>
""", unsafe_allow_html=True)

# Check authentication
if not is_authenticated():
    redirect_to_login("pages/ai_assistant.py")

# Refresh token if needed (auto-refresh before expiry)
from auth_utils import refresh_token_if_needed
if not refresh_token_if_needed():
    # Token refresh failed - session is invalid, redirect to login
    from auth_utils import logout_user
    logout_user(return_to="pages/ai_assistant.py")
    st.stop()

# Initialize chat context manager
if 'chat_context' not in st.session_state:
    st.session_state.chat_context = ChatContextManager()

chat_context = st.session_state.chat_context

# Handle clear context pending from Clear Chat button
if st.session_state.get('clear_context_pending', False):
    chat_context.clear_all()
    st.session_state.clear_context_pending = False

# Initialize conversation history
if 'chat_messages' not in st.session_state:
    st.session_state.chat_messages: list[dict[str, str]] = []

# Limit conversation history to prevent context overflow
MAX_CONVERSATION_HISTORY = 20  # Keep last N messages (10 exchanges)

# ============================================================================
# PERFORMANCE OPTIMIZATION: Cached Helper Functions
# ============================================================================

@st.cache_data(ttl=30, show_spinner=False)
def get_cached_ollama_health() -> bool:
    """Check Ollama health with 30s cache to avoid hitting service on every page load."""
    return check_ollama_health()

@st.cache_data(ttl=30, show_spinner=False)
def get_cached_searxng_health() -> bool:
    """Check SearXNG health with 30s cache to avoid hitting service on every page load."""
    return check_searxng_health()

@st.cache_data(ttl=60, show_spinner=False)
def get_portfolio_tickers_list(fund: str) -> list[str]:
    """Get portfolio tickers with 60s cache to avoid DB queries on every page load."""
    try:
        df = get_current_positions(fund)
        if not df.empty and 'ticker' in df.columns:
            return sorted(df['ticker'].unique().tolist())
    except Exception:
        pass
    return []

# ============================================================================
# Token estimation (rough approximation: 1 token ≈ 4 characters for English)
def estimate_tokens(text: str) -> int:
    """Estimate token count from text (rough approximation)."""
    if not text:
        return 0
    # Simple approximation: 1 token ≈ 4 characters for English text
    return len(text) // 4

def calculate_context_size(
    system_prompt: str,
    context_string: str,
    conversation_history: list[dict[str, str]],
    current_prompt: str
) -> dict[str, Any]:
    """Calculate total context size and token estimates.
    
    Returns:
        Dictionary with size information:
        - total_chars: Total characters
        - total_tokens: Estimated tokens
        - system_prompt_tokens: System prompt tokens
        - context_tokens: Context data tokens
        - history_tokens: Conversation history tokens
        - prompt_tokens: Current prompt tokens
        - context_window: Model context window size
        - usage_percent: Percentage of context window used
    """
    system_tokens = estimate_tokens(system_prompt)
    context_tokens = estimate_tokens(context_string)

    # Calculate history tokens
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history])
    history_tokens = estimate_tokens(history_text)

    prompt_tokens = estimate_tokens(current_prompt)

    total_tokens = system_tokens + context_tokens + history_tokens + prompt_tokens
    total_chars = len(system_prompt) + len(context_string) + len(history_text) + len(current_prompt)

    
    # Get model context window from config (depends on model type)
    context_window = 4096  # Default for unknown models
    
    # Try to load from model_config.json
    try:
        import json
        from pathlib import Path
        config_path = Path(__file__).parent / "model_config.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Check if model exists in config
            if selected_model in config.get('models', {}):
                model_config = config['models'][selected_model]
                context_window = model_config.get('num_ctx', context_window)
            else:
                # If not in config, use default from default_config
                context_window = config.get('default_config', {}).get('num_ctx', 4096)
    except Exception:
        # If config loading fails, fall back to defaults
        context_window = 4096

    usage_percent = (total_tokens / context_window * 100) if context_window > 0 else 0

    return {
        'total_chars': total_chars,
        'total_tokens': total_tokens,
        'system_prompt_tokens': system_tokens,
        'context_tokens': context_tokens,
        'history_tokens': history_tokens,
        'prompt_tokens': prompt_tokens,
        'context_window': context_window,
        'usage_percent': usage_percent
    }

# ============================================================================
# Context Building Function (must be defined before sidebar code uses it)
# ============================================================================

def build_context_string_internal() -> str:
    """Build formatted context string from selected items.
    
    Note: This is defined early to avoid NameError when called from sidebar caching logic.
    It references variables that will be available when called (chat_context, selected_fund, etc.)
    """
    items = chat_context.get_items()
    if not items:
        return ""

    context_parts = []

    for item in items:
        fund = item.fund or selected_fund

        try:
            if item.item_type == ContextItemType.HOLDINGS:
                positions_df = get_current_positions(fund)
                # Get trades_df for opened date lookup
                trades_df_for_holdings = get_trade_log(limit=1000, fund=fund) if fund else None
                # Get toggle values from sidebar (use session state or default to True)
                include_pv = st.session_state.get('toggle_price_volume', True)
                include_fund = st.session_state.get('toggle_fundamentals', True)
                context_parts.append(
                    format_holdings(
                        positions_df,
                        fund or "Unknown",
                        trades_df=trades_df_for_holdings,
                        include_price_volume=include_pv,
                        include_fundamentals=include_fund
                    )
                )

            elif item.item_type == ContextItemType.THESIS:
                thesis_data = get_fund_thesis_data(fund or "")
                if thesis_data:
                    context_parts.append(format_thesis(thesis_data))

            elif item.item_type == ContextItemType.TRADES:
                limit = item.metadata.get('limit', 100)
                trades_df = get_trade_log(limit=limit, fund=fund)
                context_parts.append(format_trades(trades_df, limit))

            elif item.item_type == ContextItemType.METRICS:
                portfolio_df = calculate_portfolio_value_over_time(fund, days=365) if fund else None
                metrics = calculate_performance_metrics(fund) if fund else {}
                context_parts.append(format_performance_metrics(metrics, portfolio_df))

            elif item.item_type == ContextItemType.CASH_BALANCES:
                cash = get_cash_balances(fund) if fund else {}
                context_parts.append(format_cash_balances(cash))

            elif item.item_type == ContextItemType.SEARCH_RESULTS:
                # Search results are added dynamically when user queries
                # This is handled in the query processing section
                pass

        except Exception as e:
            st.warning(f"Error loading {item.item_type.value}: {e}")
            continue

    return "\n\n---\n\n".join(context_parts)

# ============================================================================

# Header
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown("# 🧠 AI Portfolio Assistant")
with col2:
    if st.button("🔄 Clear Chat", use_container_width=True):
        st.session_state.chat_messages = []
        st.session_state.suggested_prompt = None
        # Reset webai session if it exists
        if 'webai_session' in st.session_state:
            try:
                st.session_state.webai_session.reset_sync()
            except Exception as e:
                logger.warning(f"Error resetting webai session: {e}")
                # Clean up broken session
                try:
                    del st.session_state['webai_session']
                    del st.session_state['webai_user_id']
                except:
                    pass
        # Clear context items will be done after chat_context is initialized
        if 'clear_context_pending' not in st.session_state:
            st.session_state.clear_context_pending = True
        st.rerun()

# Initialize suggested_prompt if it doesn't exist
if 'suggested_prompt' not in st.session_state:
    st.session_state.suggested_prompt = None

# Check Ollama connection (cached) - but don't block WebAI users yet
ollama_available = get_cached_ollama_health()

# Check SearXNG connection (cached, non-blocking)
searxng_available = get_cached_searxng_health()
searxng_client = get_searxng_client()

# Sidebar - Navigation, Settings and Context
from navigation import render_navigation
render_navigation(show_ai_assistant=False, show_settings=True)  # Don't show AI Assistant link on this page

with st.sidebar:
    st.header("⚙️ Model")

    # Get available models and system default
    available_models = list_available_models()
    default_model = get_user_ai_model()

    # Ensure default model is in the list
    if default_model not in available_models:
        available_models.insert(0, default_model)

    # Format model names for display (show friendly names instead of technical identifiers)
    def format_model_name(model: str) -> str:
        """Format model name using keys file."""
        try:
            from webai_wrapper import is_webai_model
            is_webai = is_webai_model(model)
        except ImportError:
            is_webai = False
        if HAS_MODEL_KEYS and is_webai:
            try:
                return get_model_display_name(model)
            except (KeyError, FileNotFoundError):
                pass
        return model
    
    def get_model_value(display_name: str) -> str:
        """Get model identifier from display name (reverse lookup)."""
        if HAS_MODEL_KEYS:
            # Try to find matching model by checking all known webai models
            try:
                from webai_wrapper import get_webai_models
                for model_id in get_webai_models():
                    try:
                        if get_model_display_name(model_id) == display_name:
                            return model_id
                    except (KeyError, FileNotFoundError):
                        continue
            except ImportError:
                pass
        return display_name
    
    # Create display names for dropdown
    display_models = [format_model_name(m) for m in available_models]
    display_default = format_model_name(default_model) if default_model in available_models else display_models[0]
    
    # Callback to save model preference
    def on_model_change():
        new_display = st.session_state.ai_model_selector
        new_model = get_model_value(new_display)
        set_user_ai_model(new_model)
        st.toast(f"Model saved: {format_model_name(new_model)}")

    # Model selection dropdown
    selected_display = st.selectbox(
        "AI Model",
        options=display_models,
        index=display_models.index(display_default) if display_default in display_models else 0,
        help="Select the AI model for analysis",
        key="ai_model_selector",
        on_change=on_model_change
    )
    
    # Convert back to internal model name
    selected_model = get_model_value(selected_display)

    # Check model-specific requirements
    try:
        from webai_wrapper import is_webai_model, get_webai_models
        is_selected_webai = is_webai_model(selected_model)
        webai_model_list = get_webai_models()
    except ImportError:
        is_selected_webai = False
        webai_model_list = []
    
    # Check if GLM model
    is_glm_model = selected_model.startswith("glm-")
    
    if is_selected_webai:
        # WebAI models use web-based API
        if HAS_MODEL_KEYS:
            try:
                display_name = get_model_display_name(selected_model)
                # Build description with display name from keys
                # Map by model suffix (position in model list)
                emoji_list = ["⚡", "🧠", "✨"]
                context_list = [
                    "Fast responses with 1M token context",
                    "Advanced reasoning with 2M token context",
                    "Latest model with 2M token context"
                ]
                idx = webai_model_list.index(selected_model) if selected_model in webai_model_list else -1
                emoji = emoji_list[idx] if 0 <= idx < len(emoji_list) else "🤖"
                context = context_list[idx] if 0 <= idx < len(context_list) else "Web-based AI model"
                st.caption(f"ℹ️ {emoji} {display_name} - {context}")
            except (KeyError, FileNotFoundError):
                st.caption(f"ℹ️ Web-based AI model with persistent conversations")
        else:
            st.caption(f"ℹ️ Web-based AI model with persistent conversations")
        # WebAI doesn't need Ollama
        if not HAS_WEBAI:
            st.error("❌ WebAI package not installed. Install with: pip install the required webapi package")
            st.stop()
    elif is_glm_model:
        # GLM models (Zhipu AI)
        try:
            from glm_config import get_zhipu_api_key
            has_glm_key = bool(get_zhipu_api_key())
        except ImportError:
            has_glm_key = False
        
        if not has_glm_key:
            st.error("❌ GLM API key not configured. Please configure in AI Settings.")
            st.stop()
        
        # Display GLM model details
        if selected_model == "glm-4.7":
            st.caption("ℹ️ 🧠 GLM-4.7 - Advanced reasoning with 128K context")
        elif selected_model == "glm-4.5-air":
            st.caption("ℹ️ ⚡ GLM-4.5 Air - Fast responses with 128K context")
        else:
            st.caption(f"ℹ️ 🤖 {selected_model} - Zhipu AI model with large context")
    else:
        # Ollama models require Ollama to be running
        if not ollama_available:
            st.error("❌ Cannot connect to Ollama API. Please check if Ollama is running.")
            model_name = get_model_display_name_short() if HAS_MODEL_KEYS else "AI Pro"
            st.info(f"💡 Tip: Try selecting '{model_name}' to use the web-based model instead.")
            st.stop()
        
        client = get_ollama_client()
        if client:
            desc = client.get_model_description(selected_model)
            if desc:
                st.caption(f"ℹ️ {desc}")

    st.markdown("---")
    
    # Fund selection in sidebar
    st.header("📊 Data Source")
    selected_fund = render_sidebar_fund_selector(
        label="Fund",
        key="fund_selector",
        help_text="Select fund for AI analysis"
    )
    
    if selected_fund is None:
        st.warning("No funds available")
        st.stop()
    
    # Clear chat when fund changes
    if 'previous_fund' not in st.session_state:
        st.session_state.previous_fund = selected_fund
    elif st.session_state.previous_fund != selected_fund:
        st.session_state.chat_messages = []
        st.session_state.suggested_prompt = None
        st.session_state.previous_fund = selected_fund
        st.rerun()

    st.markdown("---")

    # Context selection - Simplified UI
    st.header("📋 Analysis Context")

    # Get current context items for this fund
    context_items = chat_context.get_items()
    current_types = {item.item_type for item in context_items if item.fund == selected_fund}

    # Core context (always included)
    st.caption("✅ **Always Included:** Holdings (with Daily P&L & Sector), Performance Metrics, Cash Balances")

    # Auto-enable core items
    include_holdings = True
    include_metrics = True
    include_cash = True

    # Optional context
    st.markdown("**Optional:**")

    # Thesis toggle
    include_thesis = st.checkbox(
        "Investment Thesis",
        value=ContextItemType.THESIS in current_types,
        help="Include your investment strategy and pillars",
        key="toggle_thesis"
    )

    # Trades toggle (optional)
    include_trades = st.checkbox(
        "Recent Trades",
        value=ContextItemType.TRADES in current_types,
        help="Include recent trading activity (last 50 trades)",
        key="toggle_trades"
    )

    st.markdown("---")

    # Portfolio Table Options
    st.header("📊 Portfolio Table Options")
    st.caption("Customize which portfolio data tables to include")

    include_price_volume = st.checkbox(
        "Price & Volume Table",
        value=True,  # Default ON
        help="Include Price & Volume data (Close, % Chg, Volume, Avg Vol)",
        key="toggle_price_volume"
    )

    include_fundamentals = st.checkbox(
        "Company Fundamentals Table",
        value=True,  # Default ON
        help="Include Company Fundamentals (Sector, Industry, Mkt Cap, P/E, etc.)",
        key="toggle_fundamentals"
    )

    st.markdown("---")

    # Web Search section
    st.header("🔍 Web Search")
    if searxng_available:
        st.success("✅ SearXNG available")
        include_search = st.checkbox(
            "Enable Web Search",
            value=True,
            help="Search the web for relevant information when answering questions",
            key="toggle_search"
        )



        # Portfolio Intelligence Section
        st.markdown("### 🧠 Portfolio Intelligence")
        
        if st.button("🔍 Check Portfolio News", help="Scan local research repository for noteworthy updates on your holdings (past 7 days)", use_container_width=True):
            with st.spinner("Scanning research repository for portfolio updates..."):
                try:
                    # Initialize repository
                    repo = ResearchRepository()
                    
                    # Get portfolio tickers
                    portfolio_tickers = set()
                    if current_fund:
                        positions_df = get_current_positions(current_fund)
                        if not positions_df.empty and 'ticker' in positions_df.columns:
                            # Clean and collect tickers
                            portfolio_tickers = {t.strip().upper() for t in positions_df['ticker'].dropna().unique()}
                    
                    if not portfolio_tickers:
                        st.warning("No positions found in current portfolio to check.")
                    else:
                        # Fetch recent articles
                        recent_articles = repo.get_recent_articles(limit=50, days=7)
                        
                        # Filter for holdings
                        matching_articles = []
                        seen_titles = set()
                        
                        for article in recent_articles:
                            # Check if article mentions any portfolio ticker
                            article_tickers = article.get('tickers')
                            if not article_tickers:
                                continue
                                
                            # Convert article tickers to set of strings for intersection
                            art_ticker_set = {t.upper() for t in article_tickers}
                            
                            # Find intersection
                            matches = art_ticker_set.intersection(portfolio_tickers)
                            
                            if matches and article['title'] not in seen_titles:
                                article['matched_holdings'] = list(matches)
                                matching_articles.append(article)
                                seen_titles.add(article['title'])
                        
                        if matching_articles:
                            # Format context for AI
                            article_context = "Here are recent research articles found for the user's portfolio holdings:\n\n"
                            for i, art in enumerate(matching_articles[:10], 1):  # Limit to top 10 relevant
                                article_context += f"{i}. Title: {art.get('title')}\n"
                                article_context += f"   Holdings: {', '.join(art.get('matched_holdings'))}\n"
                                article_context += f"   Summary: {art.get('summary', 'No summary')}\n"
                                article_context += f"   Conclusion: {art.get('conclusion', 'N/A')}\n"
                                article_context += "\n"
                            
                            # Set suggestion for the user to send
                            st.session_state.suggested_prompt = (
                                "Review the following recent research articles about my portfolio holdings. "
                                "Identify any noteworthy events, risks, or opportunities that strictly require my attention.\n\n"
                                f"{article_context}"
                            )
                            st.toast(f"Found {len(matching_articles)} relevant articles. Prompt ready!")
                            st.rerun()
                        else:
                            st.info(f"No recent articles found in the repository for your {len(portfolio_tickers)} holdings (past 7 days).")
                            
                except Exception as e:
                    logger.error(f"Error checking portfolio news: {e}")
                    st.error(f"Failed to check portfolio news: {e}")

        # Search settings expander
        with st.expander("🎛️ Search Settings"):
            min_relevance_score = st.slider(
                "Minimum Relevance Score",
                min_value=0.0,
                max_value=1.0,
                value=0.3,
                step=0.05,
                help="Lower = more results, higher = only highly relevant results. Used for ticker and market searches.",
                key="min_relevance_score"
            )

            filter_general_queries = st.checkbox(
                "Filter general queries",
                value=False,
                help="Apply relevance filtering to general knowledge queries. Usually better to leave this off.",
                key="filter_general_queries"
            )

            st.caption("ℹ️ Ticker searches are always filtered for relevance")
    else:
        st.warning("⚠️ SearXNG unavailable")
        st.caption("Web search will be disabled. SearXNG may be starting up or not configured.")
        include_search = False
        min_relevance_score = 0.3
        filter_general_queries = False

    st.markdown("---")

    # Research Knowledge section
    st.header("🧠 Research Knowledge")

    # Check if Ollama is available (needed for embeddings) AND not using WebAI
    # WebAI users might not have Ollama running
    if ollama_available and not is_selected_webai:
        include_repository = st.checkbox(
            "Use Research Repository",
            value=True,
            help="Search your saved research repository for relevant information",
            key="toggle_repository"
        )

        if include_repository:
            with st.expander("🎛️ Repository Settings"):
                repository_max_results = st.slider(
                    "Max articles to retrieve",
                    min_value=1,
                    max_value=10,
                    value=3,
                    help="Number of similar articles to include in context",
                    key="repository_max_results"
                )

                repository_min_similarity = st.slider(
                    "Minimum similarity score",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.6,
                    step=0.05,
                    help="Lower = more diverse results, higher = only very similar articles",
                    key="repository_min_similarity"
                )
    elif is_selected_webai:
        st.info("ℹ️ Repository search requires Ollama for embeddings. Not available with WebAI models.")
        include_repository = False
        repository_max_results = 3
        repository_min_similarity = 0.6
    else:
        st.warning("⚠️ Repository search requires Ollama")
        include_repository = False
        repository_max_results = 3
        repository_min_similarity = 0.6


    # =========================================================================
    # CONTEXT SYNCHRONIZATION LOGIC
    # =========================================================================
    # This section syncs the UI checkboxes with the ChatContextManager's internal
    # state (stored in st.session_state.context_items as a Set[ContextItem]).
    #
    # HOW IT WORKS:
    # 1. current_types (line 197) gets the set of ContextItemType enums currently
    #    stored for the selected_fund
    # 2. Each checkbox uses `ContextItemType.X in current_types` as its initial value
    # 3. When checkbox state changes, we add/remove the corresponding ContextItem
    #
    # WHY METADATA MATTERS:
    # ContextItem implements __eq__ and __hash__ using (item_type, fund, metadata).
    # This means add_item and remove_item MUST use IDENTICAL metadata for the
    # same item type, or the removal will fail silently (item not found in set).
    # For example: TRADES uses metadata={'limit': 50} - both add and remove must match.
    #
    # DEBUGGING CHECKLIST if checkboxes don't work:
    # 1. Verify checkbox key is unique (e.g., "toggle_holdings")
    # 2. Check that current_types correctly contains the ContextItemType
    # 3. Ensure metadata in add_item matches metadata in remove_item exactly
    # 4. Confirm selected_fund is not None (logic only runs if selected_fund truthy)
    # =========================================================================
    if selected_fund:
        # HOLDINGS - no metadata required
        if include_holdings and ContextItemType.HOLDINGS not in current_types:
            chat_context.add_item(ContextItemType.HOLDINGS, fund=selected_fund)
        elif not include_holdings and ContextItemType.HOLDINGS in current_types:
            chat_context.remove_item(ContextItemType.HOLDINGS, fund=selected_fund)

        # THESIS - no metadata required
        if include_thesis and ContextItemType.THESIS not in current_types:
            chat_context.add_item(ContextItemType.THESIS, fund=selected_fund)
        elif not include_thesis and ContextItemType.THESIS in current_types:
            chat_context.remove_item(ContextItemType.THESIS, fund=selected_fund)

        # TRADES - uses metadata for limit; add/remove MUST use same metadata!
        if include_trades and ContextItemType.TRADES not in current_types:
            chat_context.add_item(ContextItemType.TRADES, fund=selected_fund, metadata={'limit': 50})
        elif not include_trades and ContextItemType.TRADES in current_types:
            chat_context.remove_item(ContextItemType.TRADES, fund=selected_fund, metadata={'limit': 50})

        # METRICS - no metadata required
        if include_metrics and ContextItemType.METRICS not in current_types:
            chat_context.add_item(ContextItemType.METRICS, fund=selected_fund)
        elif not include_metrics and ContextItemType.METRICS in current_types:
            chat_context.remove_item(ContextItemType.METRICS, fund=selected_fund)

        # CASH_BALANCES - no metadata required
        if include_cash and ContextItemType.CASH_BALANCES not in current_types:
            chat_context.add_item(ContextItemType.CASH_BALANCES, fund=selected_fund)
        elif not include_cash and ContextItemType.CASH_BALANCES in current_types:
            chat_context.remove_item(ContextItemType.CASH_BALANCES, fund=selected_fund)

    # Handle search context
    if include_search and searxng_available:
        if ContextItemType.SEARCH_RESULTS not in current_types:
            chat_context.add_item(ContextItemType.SEARCH_RESULTS, fund=selected_fund)
    elif not include_search and ContextItemType.SEARCH_RESULTS in current_types:
        chat_context.remove_item(ContextItemType.SEARCH_RESULTS, fund=selected_fund)

    # =========================================================================
    # PERFORMANCE OPTIMIZATION: Cache context string in session state
    # =========================================================================
    # The footer displays context usage stats, which requires building the
    # context string. Building it on EVERY page render is expensive (triggers
    # all DB queries). Instead, we cache it in session state and only rebuild
    # when the context items actually change (detected via fingerprint).
    # =========================================================================

    # Initialize cache if needed
    if 'context_items_fingerprint' not in st.session_state:
        st.session_state.context_items_fingerprint = None
        st.session_state.cached_context_string = ""

    # Create fingerprint of current context items (for change detection)
    updated_items = chat_context.get_items()
    # Include fund, type, and metadata in fingerprint for accurate change detection
    current_fingerprint = str(sorted([
        (item.item_type.value, item.fund, tuple(sorted(item.metadata.items())) if item.metadata else ())
        for item in updated_items
    ]))

    # Rebuild context string only if context items changed
    if st.session_state.context_items_fingerprint != current_fingerprint:
        start_time = time.time()
        logger.info(f"[PERFORMANCE] Starting context build for ai_assistant")
        
        st.session_state.cached_context_string = build_context_string_internal()
        
        duration = time.time() - start_time
        logger.info(f"[PERFORMANCE] Context build took {duration:.2f} seconds")
        
        # Log to browser console using a small script
        # Use st.components.v1.html for a hidden script element as it's cleaner than st.markdown with unsafe_allow_html
        import streamlit.components.v1 as components
        components.html(
            f"""
            <script>
                console.log("[AI Assistant] Context build took {duration:.2f} seconds");
                console.log("[AI Assistant] Fingerprint updated: {current_fingerprint}");
            </script>
            """,
            height=0,
            width=0
        )
        
        st.session_state.context_items_fingerprint = current_fingerprint
        
        # Trigger rerun to update footer with new context size
        st.rerun()

    # Show count
    if updated_items:
        st.caption(f"✅ {len(updated_items)} data source(s) selected")
        if st.button("🗑️ Clear All", use_container_width=True, key="clear_all"):
            chat_context.clear_all()
            st.rerun()

# Main layout: Left column for chat, right column for quick research
main_col, right_col = st.columns([7, 3])

# Right Column: Quick Research Tools (styled as sidebar)
with right_col:
    # Wrap everything in a container with the CSS class
    with st.container():
        st.markdown('<div class="quick-research-sidebar">', unsafe_allow_html=True)

        if searxng_available:
            st.markdown("#### 🔍 Quick Research")
            st.caption("Select tickers to analyze")

            # Get portfolio tickers for ticker-specific queries (cached)
            portfolio_tickers_list = []
            if selected_fund:
                portfolio_tickers_list = get_portfolio_tickers_list(selected_fund)

            # Unified Ticker Selection
            col_sel1, col_sel2 = st.columns([2, 1])
            with col_sel1:
                selected_tickers = st.multiselect(
                    "Select Tickers:",
                    options=portfolio_tickers_list,
                    placeholder="Tickers...",
                    key="multi_select_tickers",
                    label_visibility="collapsed"
                )
            with col_sel2:
                custom_ticker = st.text_input(
                    "Custom",
                    placeholder="NVDA",
                    label_visibility="collapsed",
                    key="custom_ticker_input"
                ).strip().upper()

            # Combine selections
            active_tickers = list(selected_tickers)
            if custom_ticker and custom_ticker not in active_tickers:
                active_tickers.append(custom_ticker)

            # Check if text_area key exists in session state - if so, we need to update it manually
            # to ensure the widget reflects the new value immediately
            def set_suggested_prompt(prompt_text):
                st.session_state.suggested_prompt = prompt_text
                # Force update of the text area widget key
                st.session_state.editable_prompt_area = prompt_text
                st.rerun()

            st.markdown("---")
            st.caption("**Quick Actions:**")

            # Ticker-Specific Actions
            if active_tickers:
                st.markdown("**📈 Ticker Analysis:**")

                # Research Button
                btn_label = f"🔍 Research {active_tickers[0]}" if len(active_tickers) == 1 else f"🔍 Research ({len(active_tickers)})"
                if st.button(btn_label, use_container_width=True, key="btn_research_ticker"):
                    if len(active_tickers) == 1:
                        set_suggested_prompt(f"Research {active_tickers[0]} - latest news and analysis")
                    else:
                        tickers_str = ", ".join(active_tickers)
                        set_suggested_prompt(f"Research the following stocks: {tickers_str}. Provide latest news for each.")

                # Analysis Button
                btn_label = f"📊 Analyze {active_tickers[0]}" if len(active_tickers) == 1 else f"📊 Analyze ({len(active_tickers)})"
                if st.button(btn_label, use_container_width=True, key="btn_stock_analysis"):
                    if len(active_tickers) == 1:
                        set_suggested_prompt(f"Analyze {active_tickers[0]} stock - recent performance and outlook")
                    else:
                        tickers_str = ", ".join(active_tickers)
                        set_suggested_prompt(f"Analyze and compare the outlooks for: {tickers_str}")

                # Compare Button (only show if multiple tickers)
                if len(active_tickers) >= 2:
                    if st.button("📈 Compare Stocks", use_container_width=True, key="btn_compare_stocks"):
                        tickers_str = " and ".join(active_tickers)
                        set_suggested_prompt(f"Compare {tickers_str} stocks. Which is a better investment?")

                # Earnings Button
                btn_label = f"💰 Earnings {active_tickers[0]}" if len(active_tickers) == 1 else f"💰 Earnings ({len(active_tickers)})"
                if st.button(btn_label, use_container_width=True, key="btn_earnings"):
                    if len(active_tickers) == 1:
                        set_suggested_prompt(f"Find recent earnings news for {active_tickers[0]}")
                    else:
                        tickers_str = ", ".join(active_tickers)
                        set_suggested_prompt(f"Find recent earnings reports for: {tickers_str}")

                st.markdown("---")

            # General Prompts
            st.markdown("**🌐 General Prompts:**")

            # Portfolio Analysis button (restores initial prompt)
            if st.button("📊 Portfolio Analysis", use_container_width=True, key="btn_portfolio_analysis"):
                # Generate the default analysis prompt
                default_prompt = chat_context.generate_prompt()
                set_suggested_prompt(default_prompt)

            # Market News
            if st.button("📰 Market News", use_container_width=True, key="btn_market_news"):
                set_suggested_prompt("What's the latest stock market news today?")

            # Sector News
            if st.button("💼 Sector News", use_container_width=True, key="btn_sector_news"):
                if selected_fund:
                    # Get top sectors from current holdings, weighted by portfolio allocation
                    try:
                        positions_df = get_current_positions(selected_fund)
                        if not positions_df.empty and 'sector' in positions_df.columns and 'market_value' in positions_df.columns:
                            # Group by sector and sum market values, then get top 5
                            sector_weights = positions_df.groupby('sector')['market_value'].sum().sort_values(ascending=False)
                            top_sectors = sector_weights.head(5).index.tolist()
                            
                            if top_sectors:
                                sectors_str = ", ".join(top_sectors)
                                set_suggested_prompt(f"What's happening in these sectors today: {sectors_str}? Provide news and analysis for each.")
                            else:
                                logger.warning("Sector News: No sectors found in positions data (after filtering)")
                                set_suggested_prompt("What's happening in the stock market sectors today?")
                        else:
                            logger.warning(f"Sector News: positions_df missing required columns. Empty={positions_df.empty}, Has sector={'sector' in positions_df.columns}, Has market_value={'market_value' in positions_df.columns}")
                            set_suggested_prompt("What's happening in the stock market sectors today?")
                    except Exception as e:
                        logger.error(f"Sector News: Error loading positions data: {e}", exc_info=True)
                        set_suggested_prompt("What's happening in the stock market sectors today?")
                else:
                    set_suggested_prompt("What's happening in the stock market sectors today?")
        else:
            st.info("🔍 Quick Research requires SearXNG to be available.")

        st.markdown('</div>', unsafe_allow_html=True)

# Left Column: Chat
with main_col:
    st.markdown("### 💬 Chat")

    # Start Analysis Workflow vs Standard Chat
    user_query = None

    # Show editable prompt area if a button was clicked
    if 'suggested_prompt' in st.session_state and st.session_state.suggested_prompt:
        st.markdown("### ✏️ Edit Your Prompt")
        st.caption("Review and edit the prompt below, then click Send.")

        # Editable prompt area
        # Initialize widget state if not present
        if "editable_prompt_area" not in st.session_state:
            st.session_state.editable_prompt_area = st.session_state.suggested_prompt

        editable_prompt = st.text_area(
            "Prompt",
            height=100,
            help="You can edit this prompt before sending",
            label_visibility="collapsed",
            key="editable_prompt_area"
        )

        col1, col2, col3 = st.columns([1, 1, 4])
        with col1:
            if st.button("📤 Send", type="primary", use_container_width=True, key="send_edited_prompt"):
                user_query = editable_prompt
                # Clear the suggested prompt after sending (will hide UI on next rerun)
                st.session_state.suggested_prompt = None
                # Don't call st.rerun() here - let the query be processed below
        with col2:
            if st.button("❌ Cancel", use_container_width=True, key="cancel_edited_prompt"):
                st.session_state.suggested_prompt = None
                st.rerun()

        st.markdown("---")

    # Display conversation history in scrollable container (chronological order)
    if st.session_state.chat_messages:
        # Create scrollable chat container
        st.markdown('<div class="chat-container">', unsafe_allow_html=True)

        # Display messages in chronological order (oldest first)
        for message in st.session_state.chat_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        st.markdown('</div>', unsafe_allow_html=True)

        # Retry Button Logic (Only if last message was from assistant)
        if st.session_state.chat_messages[-1]['role'] == 'assistant':
            if st.button("🔄 Retry Last Response"):
                # Remove last assistant message
                st.session_state.chat_messages.pop()
                # Get the previous user message to re-run
                if st.session_state.chat_messages and st.session_state.chat_messages[-1]['role'] == 'user':
                    last_user_msg = st.session_state.chat_messages[-1]
                    user_query = last_user_msg['content']
                    # DON'T pop the user message - it's already in history
                    # Set a flag to indicate this is a retry (don't re-append user message)
                    st.session_state.is_retry = True
                    # Don't call st.rerun() here - let the query be processed below

    # If no messages yet and no suggested prompt active, show the "Start Analysis" workflow
    if updated_items and not st.session_state.chat_messages and not st.session_state.get('suggested_prompt'):
        st.info(f"✨ Ready to analyze {len(updated_items)} data source(s) from {selected_fund if selected_fund else 'N/A'}")

        with st.container():
            st.markdown("### 🚀 Start Analysis")
            st.caption("Review and edit the prompt below, then click Run to start.")

            # Generate default prompt
            default_prompt = chat_context.generate_prompt()

            # Editable prompt area
            initial_query = st.text_area(
                "Analysis Prompt",
                value=default_prompt,
                height=150,
                help="You can edit this prompt before sending",
                label_visibility="collapsed"
            )

            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("▶️ Run Analysis", type="primary", use_container_width=True):
                    user_query = initial_query

# Standard chat input (always available)
chat_input_query = st.chat_input("Ask about your portfolio...")
if chat_input_query:
    user_query = chat_input_query

if user_query:
    # Add user message to history (unless this is a retry)
    if not st.session_state.get('is_retry', False):
        st.session_state.chat_messages.append({
            "role": "user",
            "content": user_query
        })
    # Clear retry flag
    st.session_state.is_retry = False

    # Reuse cached context string (PERFORMANCE OPTIMIZATION)
    context_string = st.session_state.get('cached_context_string', '')

    # Get portfolio tickers for search detection
    portfolio_tickers = []
    if selected_fund:
        try:
            positions_df = get_current_positions(selected_fund)
            if not positions_df.empty and 'ticker' in positions_df.columns:
                portfolio_tickers = positions_df['ticker'].tolist()
        except Exception:
            pass

    # Perform web search - automatic detection or manual toggle
    search_results_text = ""
    search_data = None
    search_query_used = None
    search_triggered = False
    filtering_info = None  # Track filtering details for display

    # Determine if search should be triggered
    if searxng_client and searxng_available:
        # Auto-trigger based on query content, or use manual toggle
        should_search = False
        if include_search:
            # Manual toggle is on
            should_search = True
        else:
            # Auto-detect research intent
            should_search = should_trigger_search(user_query, portfolio_tickers)

        if should_search:
            search_triggered = True
            # Detect research intent for better search strategy
            research_intent = detect_research_intent(user_query)

            with st.spinner(f"🔍 Searching the web for: {user_query[:50]}..."):
                try:
                    # Determine time range based on intent subtype
                    intent_subtype = research_intent.get('intent_subtype')
                    if intent_subtype == 'earnings':
                        time_range = 'week'  # Earnings reports may be from last week/month
                    elif intent_subtype == 'analysis':
                        time_range = 'week'  # Analysis articles may be from recent days
                    elif intent_subtype == 'compare':
                        time_range = 'week'  # Comparison articles may be from recent days
                    else:
                        time_range = 'day'  # Default for research and market (latest news)
                    
                    # Build optimized search query based on intent
                    if research_intent['tickers']:
                        tickers = research_intent['tickers']

                        # Multi-ticker search: search each ticker CONCURRENTLY (PERFORMANCE OPTIMIZATION)
                        if len(tickers) > 1:
                            logger.info(f"Multi-ticker search for: {', '.join(tickers)}")
                            all_results = []
                            seen_urls = set()
                            
                            # Special handling for comparison queries
                            if intent_subtype == 'compare' and len(tickers) == 2:
                                # First, search for head-to-head comparison articles
                                try:
                                    company_name1 = get_company_name_from_db(tickers[0])
                                    company_name2 = get_company_name_from_db(tickers[1])
                                    
                                    # Build comparison query
                                    comparison_query = build_search_query(
                                        user_query,
                                        tickers=tickers,
                                        company_name=company_name1,  # Use first company name
                                        preserve_keywords=True,
                                        research_intent=research_intent
                                    )
                                    
                                    # Search for comparison articles
                                    comparison_data = searxng_client.search_news(
                                        query=comparison_query,
                                        time_range=time_range,
                                        max_results=5
                                    )
                                    
                                    if comparison_data and 'results' in comparison_data and comparison_data['results']:
                                        # Tag comparison results
                                        for result in comparison_data['results']:
                                            result['related_ticker'] = f"{tickers[0]}/{tickers[1]}"
                                            result['is_comparison'] = True
                                            url = result.get('url', '')
                                            if url and url not in seen_urls:
                                                seen_urls.add(url)
                                                all_results.append(result)
                                        logger.info(f"Found {len(comparison_data['results'])} comparison articles")
                                except Exception as e:
                                    logger.warning(f"Error searching for comparison articles: {e}")

                            # Define search function for a single ticker
                            def search_single_ticker(ticker: str) -> list[dict]:
                                """Search for a single ticker and return filtered results."""
                                try:
                                    # Lookup company name from database
                                    company_name = get_company_name_from_db(ticker)

                                    # Build query for this specific ticker
                                    ticker_search_query = build_search_query(
                                        user_query,
                                        tickers=[ticker],
                                        company_name=company_name,
                                        preserve_keywords=True,
                                        research_intent=research_intent
                                    )

                                    # Search for this ticker with appropriate time range
                                    ticker_search_data = searxng_client.search_news(
                                        query=ticker_search_query,
                                        time_range=time_range,
                                        max_results=10 if intent_subtype != 'compare' else 5
                                    )

                                    # Filter results for relevance to this specific ticker
                                    if ticker_search_data and 'results' in ticker_search_data and ticker_search_data['results']:
                                        original_count = len(ticker_search_data['results'])
                                        filter_result = filter_relevant_results(
                                            ticker_search_data['results'],
                                            ticker,
                                            company_name=company_name,
                                            min_relevance_score=min_relevance_score
                                        )
                                        logger.info(f"Ticker {ticker}: Filtered {original_count} to {filter_result['relevant_count']} relevant results")

                                        # Tag results with ticker
                                        relevant_results = filter_result['relevant']
                                        for result in relevant_results:
                                            result['related_ticker'] = ticker
                                        return relevant_results
                                    return []
                                except Exception as e:
                                    logger.error(f"Error searching ticker {ticker}: {e}")
                                    return []

                            # Execute searches in parallel (max 5 concurrent workers)
                            with ThreadPoolExecutor(max_workers=min(len(tickers), 5)) as executor:
                                future_to_ticker = {executor.submit(search_single_ticker, ticker): ticker for ticker in tickers}

                                for future in as_completed(future_to_ticker):
                                    ticker_results = future.result()
                                    # Deduplicate by URL
                                    for result in ticker_results:
                                        url = result.get('url', '')
                                        if url and url not in seen_urls:
                                            seen_urls.add(url)
                                            all_results.append(result)

                            # Combine all results
                            if all_results:
                                search_data = {'results': all_results}
                                tickers_str = ", ".join(tickers)
                                search_query_used = f"News for {tickers_str}"
                                logger.info(f"Multi-ticker search: Combined {len(all_results)} unique results from {len(tickers)} tickers")
                            else:
                                search_data = None
                                search_query_used = f"News for {', '.join(tickers)}"

                        # Single-ticker search (existing logic)
                        else:
                            ticker = tickers[0]

                            # Lookup company name from database
                            company_name = get_company_name_from_db(ticker)

                            # Build query with ticker, company name, and preserved keywords
                            search_query_used = build_search_query(
                                user_query,
                                tickers=[ticker],
                                company_name=company_name,
                                preserve_keywords=True,
                                research_intent=research_intent
                            )

                            # Fetch more results for filtering with appropriate time range
                            search_data = searxng_client.search_news(
                                query=search_query_used,
                                time_range=time_range,
                                max_results=20  # Get more results for filtering
                            )

                            # Filter results for relevance
                            if search_data and 'results' in search_data and search_data['results']:
                                original_count = len(search_data['results'])
                                filter_result = filter_relevant_results(
                                    search_data['results'],
                                    ticker,
                                    company_name=company_name,
                                    min_relevance_score=min_relevance_score
                                )

                                # Store filtering info for display
                                filtering_info = {
                                    'original_count': original_count,
                                    'relevant_count': filter_result['relevant_count'],
                                    'filtered_count': filter_result['filtered_count'],
                                    'filtered_scores': [r['relevance_score'] for r in filter_result['filtered_out']],
                                    'min_score': min_relevance_score
                                }

                                # Update search_data with filtered results
                                search_data['results'] = filter_result['relevant']
                                logger.info(f"Filtered {original_count} results to {filter_result['relevant_count']} relevant results for {ticker}")
                    elif research_intent['research_type'] == 'market':
                        # Market news search
                        search_query_used = build_search_query(
                            user_query,
                            preserve_keywords=True,
                            research_intent=research_intent
                        )
                        # Market queries use 'day' for today's news
                        market_time_range = 'day'
                        search_data = searxng_client.search_news(
                            query=search_query_used,
                            time_range=market_time_range,
                            max_results=10
                        )
                    else:
                        # General search (use web search, broader time range)
                        search_query_used = build_search_query(
                            user_query,
                            tickers=None,
                            preserve_keywords=True,
                            research_intent=research_intent
                        )
                        search_data = searxng_client.search_web(
                            query=search_query_used,
                            time_range=None,  # No time limit for general queries
                            max_results=10
                        )

                        # Apply filtering only if user enabled it
                        if filter_general_queries and search_data and 'results' in search_data and search_data['results']:
                            # Extract ticker if present for filtering
                            original_count = len(search_data['results'])
                            if research_intent['tickers']:
                                ticker = research_intent['tickers'][0]
                                company_name = get_company_name_from_db(ticker)
                                filter_result = filter_relevant_results(
                                    search_data['results'],
                                    ticker,
                                    company_name=company_name,
                                    min_relevance_score=min_relevance_score
                                )

                                # Store filtering info for display
                                filtering_info = {
                                    'original_count': original_count,
                                    'relevant_count': filter_result['relevant_count'],
                                    'filtered_count': filter_result['filtered_count'],
                                    'filtered_scores': [r['relevance_score'] for r in filter_result['filtered_out']],
                                    'min_score': min_relevance_score
                                }

                                # Update search_data with filtered results
                                search_data['results'] = filter_result['relevant']
                                logger.info(f"Filtered {original_count} general search results to {filter_result['relevant_count']} relevant results")

                    if search_data and 'results' in search_data and search_data['results']:
                        search_results_text = format_search_results(search_data, max_results=10)
                        context_string = f"{context_string}\n\n---\n\n{search_results_text}" if context_string else search_results_text
                    elif search_data and 'error' in search_data:
                        logger.warning(f"Search returned error: {search_data['error']}")

                except Exception as e:
                    st.warning(f"Web search failed: {e}")
                    logger.error(f"Search error: {e}")

    # Perform repository search (RAG)
    repository_results_text = ""
    repository_articles = []
    repository_triggered = False

    if include_repository and ollama_available:
        repository_triggered = True
        with st.spinner("🧠 Searching research repository..."):
            try:
                # Import repository
                from research_repository import ResearchRepository
                research_repo = ResearchRepository()

                # Generate embedding for the user query
                client = get_ollama_client()
                if client:
                    query_embedding = client.generate_embedding(user_query)

                    if query_embedding:
                        # Search for similar articles
                        repository_articles = research_repo.search_similar_articles(
                            query_embedding=query_embedding,
                            limit=repository_max_results,
                            min_similarity=repository_min_similarity
                        )

                        if repository_articles:
                            # Format articles for context
                            articles_text = "## Relevant Research from Repository:\n\n"
                            for i, article in enumerate(repository_articles, 1):
                                similarity = article.get('similarity', 0)
                                title = article.get('title', 'Untitled')
                                # Escape special characters to prevent Streamlit/Markdown rendering issues in context display
                                summary = escape_markdown(article.get('summary', article.get('content', '')[:300]))
                                source = article.get('source', 'Unknown')
                                published = article.get('published_at', '')

                                articles_text += f"### Article {i} (Similarity: {similarity:.2%})\n"
                                articles_text += f"**{title}**\n"
                                articles_text += f"*Source: {source}"
                                if published:
                                    articles_text += f" | Published: {published}"
                                articles_text += "*\n\n"
                                if summary:
                                    articles_text += f"{summary}\n\n"
                                articles_text += "---\n\n"

                            repository_results_text = articles_text
                            # Add to context
                            context_string = f"{context_string}\n\n{repository_results_text}" if context_string else repository_results_text
                            logger.info(f"✅ Retrieved {len(repository_articles)} articles from repository")
                    else:
                        logger.warning("Failed to generate embedding for query")
            except Exception as e:
                st.warning(f"Repository search failed: {e}")
                logger.error(f"Repository search error: {e}")

    # Generate prompt
    current_context_items = chat_context.get_items()
    if current_context_items:
        prompt = chat_context.generate_prompt(user_query)
    else:
        prompt = user_query

    # Combine context and prompt
    full_prompt = prompt
    if context_string:
        full_prompt = f"{context_string}\n\n{prompt}"

    # Display user message
    with st.chat_message("user"):
        st.markdown(user_query)

        # Show search status and results inline
        if search_triggered:
            if search_data and search_data.get('results'):
                # Build status message with filtering info
                status_msg = f"🔍 **Searched:** {search_query_used}"

                if filtering_info:
                    # Show detailed filtering information
                    original = filtering_info['original_count']
                    relevant = filtering_info['relevant_count']
                    filtered = filtering_info['filtered_count']
                    min_score = filtering_info['min_score']
                    filtered_scores = filtering_info['filtered_scores']

                    status_msg += f" | Found {relevant} results"
                    if filtered > 0:
                        # Format scores as comma-separated list, limited to first 10
                        scores_str = ", ".join([f"{s:.2f}" for s in filtered_scores[:10]])
                        if len(filtered_scores) > 10:
                            scores_str += f", ... ({len(filtered_scores) - 10} more)"
                        status_msg += f". {filtered} results did not meet {min_score} filter ({scores_str})"
                else:
                    # No filtering applied
                    status_msg += f" | Found {len(search_data['results'])} results"

                st.info(status_msg)
                # Show top results inline
                with st.expander("📰 Search Results (click to view)", expanded=True):
                    st.markdown(format_search_results(search_data, max_results=5))
            elif search_data and 'error' in search_data:
                st.warning(f"⚠️ Search completed but returned an error: {search_data['error']}")
            elif search_query_used:
                # Search was triggered but no results (not even before filtering)
                status_msg = f"🔍 **Searched:** {search_query_used}"
                if filtering_info and filtering_info['original_count'] > 0:
                    # Had results but all were filtered out
                    original = filtering_info['original_count']
                    filtered = filtering_info['filtered_count']
                    min_score = filtering_info['min_score']
                    filtered_scores = filtering_info['filtered_scores']

                    scores_str = ", ".join([f"{s:.2f}" for s in filtered_scores[:10]])
                    if len(filtered_scores) > 10:
                        scores_str += f", ... ({len(filtered_scores) - 10} more)"

                    status_msg += f" | Found 0 results. {filtered} results did not meet {min_score} filter ({scores_str})"
                else:
                    # No results at all from search
                    status_msg += " | No results found"
                st.info(status_msg)

        # Show repository results inline
        if repository_triggered:
            if repository_articles:
                st.success(f"🧠 **Repository:** Found {len(repository_articles)} relevant articles")
                with st.expander("📚 Relevant Articles (click to view)", expanded=True):
                    for i, article in enumerate(repository_articles, 1):
                        similarity = article.get('similarity', 0)
                        title = article.get('title', 'Untitled')
                        summary = article.get('summary', '')
                        st.markdown(f"**{i}. {title}** (Similarity: {similarity:.1%})")
                        if summary:
                            st.caption(summary[:200] + "...")
            else:
                st.info("🧠 **Repository:** No similar articles found")

    # Calculate context size before sending to AI
    system_prompt = get_system_prompt()
    context_info = calculate_context_size(
        system_prompt=system_prompt,
        context_string=context_string,
        conversation_history=st.session_state.chat_messages,
        current_prompt=full_prompt
    )


    # Get AI response
    with st.chat_message("assistant"):
        # Show visible status indicator during generation
        status_placeholder = st.empty()
        status_placeholder.info("🧠 **Generating response...**")

        message_placeholder = st.empty()
        full_response = ""

        try:
            # Check if using WebAI or Ollama
            if is_selected_webai:
                # Use webai service with persistent conversation
                # NOTE: WebAI via web UI has limitations:
                # - No system prompts (must include instructions in user message)
                # - Context size limited by web UI input field
                # - No tool/function calling support
                try:
                    if not HAS_WEBAI:
                        status_placeholder.empty()
                        st.error("WebAI package not available. Install with: pip install the required webapi package")
                        st.stop()
                    
                    # Get user ID for session
                    user_id = get_user_id()
                    if not user_id:
                        status_placeholder.empty()
                        model_name = get_model_display_name_short() if HAS_MODEL_KEYS else "AI Pro"
                        st.error(f"User authentication required for {model_name}")
                        st.stop()
                    
                    # Check if user changed FIRST (before checking session existence)
                    if 'webai_user_id' in st.session_state and st.session_state.webai_user_id != user_id:
                        # User changed - close old session and create new one
                        if 'webai_session' in st.session_state:
                            try:
                                st.session_state.webai_session.close_sync()
                            except:
                                pass
                            del st.session_state['webai_session']
                    
                    # Initialize session if needed
                    if 'webai_session' not in st.session_state:
                        # Get system prompt for Gems
                        system_prompt = get_system_prompt()
                        
                        # Create new session with model and system prompt
                        st.session_state.webai_session = PersistentConversationSession(
                            session_id=user_id,
                            auto_refresh=False,
                            model=selected_model,
                            system_prompt=system_prompt
                        )
                        st.session_state.webai_user_id = user_id
                    
                    # For WebAI web UI, we need to include instructions in the message itself
                    # since there's no system prompt support
                    webai_instructions = (
                        "You are an AI portfolio assistant. Analyze the provided portfolio data, "
                        "news, and research articles to provide insights. Be concise and actionable.\n\n"
                    )
                    
                    # Construct final message for WebAI (inline instructions + context + query)
                    webai_message = webai_instructions + full_prompt
                    
                    # Warn if context is very large (web UI may have limits)
                    if len(webai_message) > 30000:  # ~7500 tokens
                        st.warning(
                            "⚠️ Large context detected. The web UI may truncate very long messages. "
                            "Consider disabling some context sources or using an Ollama model for better handling."
                        )
                    
                    # Send message and get response
                    full_response = st.session_state.webai_session.send_sync(webai_message)
                    
                    # Clear status and show final response
                    status_placeholder.empty()
                    message_placeholder.markdown(full_response)
                    
                except ValueError as e:
                    # Missing cookies error
                    status_placeholder.empty()
                    model_name = get_model_display_name_short() if HAS_MODEL_KEYS else "AI Pro"
                    error_msg = f"❌ **WebAI Configuration Error**\n\n{str(e)}\n\n💡 Please configure cookies for {model_name} in AI Settings."
                    message_placeholder.markdown(error_msg)
                    full_response = error_msg
                    logger.error(f"WebAI config error: {e}")
                except Exception as e:
                    status_placeholder.empty()
                    model_name = get_model_display_name_short() if HAS_MODEL_KEYS else "AI Pro"
                    error_msg = f"❌ **Error using {model_name}**\n\n{str(e)}\n\n🔄 Try the retry button or check your connection."
                    message_placeholder.markdown(error_msg)
                    full_response = error_msg
                    logger.exception("WebAI error")
            else:
                # Use Ollama (proper API with system prompts and streaming)
                client = get_ollama_client()
                if not client:
                    status_placeholder.empty()
                    st.error("AI client not available")
                    st.stop()

                # Get system prompt for Ollama
                system_prompt = get_system_prompt()

                # Stream response (status remains visible during streaming)
                # Pass None for temperature and max_tokens to let the client handle model-specific defaults
                # Model settings come from model_config.json and database overrides
                for chunk in client.query_ollama(
                    prompt=full_prompt,
                    model=selected_model,
                    stream=True,
                    temperature=None,  # Use model default
                    max_tokens=None,   # Use model default
                    system_prompt=system_prompt
                ):
                    full_response += chunk
                    message_placeholder.markdown(full_response + "▌")

                # Clear status and show final response
                status_placeholder.empty()
                message_placeholder.markdown(full_response)

        except Exception as e:
            st.error(f"Error getting AI response: {e}")
            full_response = f"Sorry, I encountered an error: {str(e)}"

        # Add assistant message to history with model metadata
        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": full_response,
            "model": selected_model  # Store which model was actually used
        })

        # Enforce conversation history limit (trim oldest messages)
        if len(st.session_state.chat_messages) > MAX_CONVERSATION_HISTORY:
            st.session_state.chat_messages = st.session_state.chat_messages[-MAX_CONVERSATION_HISTORY:]

# Footer with context usage info
st.markdown("---")

# Calculate current context usage (always show, even when no query)
try:
    system_prompt = get_system_prompt()
    current_context_string = st.session_state.get('cached_context_string', '')
    # Use last user query if available, otherwise empty
    current_prompt = ""
    if st.session_state.chat_messages:
        # Get the last user message if available
        last_user_msg = [msg for msg in st.session_state.chat_messages if msg.get('role') == 'user']
        if last_user_msg:
            current_prompt = last_user_msg[-1].get('content', '')

    current_context_info = calculate_context_size(
        system_prompt=system_prompt,
        context_string=current_context_string,
        conversation_history=st.session_state.chat_messages,
        current_prompt=current_prompt
    )

    # Determine color/warning based on usage
    usage_percent = current_context_info['usage_percent']
    if usage_percent >= 90:
        usage_color = "🔴"
        usage_warning = "⚠️ **WARNING: Context window nearly full!** Consider clearing chat history."
    elif usage_percent >= 75:
        usage_color = "🟡"
        usage_warning = "⚠️ Context window getting full. Consider clearing chat history soon."
    else:
        usage_color = "🟢"
        usage_warning = None

    # Display context usage
    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(f"**Context Usage:** {usage_color} {current_context_info['total_tokens']:,} / {current_context_info['context_window']:,} tokens ({usage_percent:.1f}%)")
    with col2:
        st.caption(f"**History:** {len(st.session_state.chat_messages)} messages | **Context Items:** {len(chat_context.get_items())}")
    with col3:
        search_status = "✅" if searxng_available else "❌"
        # Show model from last assistant message, or "Not started" if no messages yet
        last_model = "Not started"
        if st.session_state.chat_messages:
            # Find the last assistant message with model info
            for msg in reversed(st.session_state.chat_messages):
                if msg.get('role') == 'assistant' and msg.get('model'):
                    last_model = msg['model']
                    break
        st.caption(f"**Model:** {last_model} | **Search:** {search_status}")

    if usage_warning:
        st.warning(usage_warning)

    # Show detailed breakdown in expander
    with st.expander("📊 Context Breakdown", expanded=False):
        st.markdown(f"""
        **Context Window:** {current_context_info['context_window']:,} tokens
        
        **Usage Breakdown:**
        - System Prompt: {current_context_info['system_prompt_tokens']:,} tokens
        - Portfolio Context: {current_context_info['context_tokens']:,} tokens
        - Conversation History: {current_context_info['history_tokens']:,} tokens ({len(st.session_state.chat_messages)} messages)
        - Current Prompt: {current_context_info['prompt_tokens']:,} tokens
        
        **Total:** {current_context_info['total_tokens']:,} tokens ({current_context_info['total_chars']:,} characters)
        """)

        if usage_percent >= 75:
            st.info("💡 **Tip:** Clear chat history or reduce context items to free up space.")
except Exception as e:
    # Fallback to simple footer if calculation fails
    logger.error(f"Error calculating context usage: {e}")
    search_status = "✅" if searxng_available else "❌"
    current_context_items = chat_context.get_items()
    st.caption(f"Using model: {selected_model} | Context items: {len(current_context_items)} | Search: {search_status}")

# Debug section
with st.expander("🔧 Debug Context (Raw AI Input)", expanded=False):
    current_context_items = chat_context.get_items()
    st.caption(f"**Context Items Count:** {len(current_context_items)}")

    if current_context_items:
        st.caption("**Item Types:**")
        for item in current_context_items:
            st.text(f"  • {item.item_type.value} (Fund: {item.fund})")

        st.markdown("---")
        st.caption("**Full Context String:**")
        debug_context = build_context_string_internal()
        if debug_context:
            st.code(debug_context, language="text")
        else:
            st.warning("Context string is empty (build_context_string returned nothing)")
    else:
        st.info("No context items selected.")

