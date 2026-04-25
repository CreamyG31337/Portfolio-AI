#!/usr/bin/env python3
"""
System Settings Module
======================

Helper functions for reading and writing global system settings.
Settings are stored in the `system_settings` table as key-value pairs.
"""

from typing import Optional, Any
from copy import deepcopy
import logging
import os

logger = logging.getLogger(__name__)


DEFAULT_FUND_PROFILE_SETTINGS: dict[str, dict[str, Any]] = {
    "DEFAULT": {
        "signal_alert_min_confidence": 0.72,
        "signal_alert_fear_levels": ["HIGH", "EXTREME"],
        "signal_alert_cooldown_minutes": 240,
        "opportunity_min_evidence_count": 2,
        "opportunity_max_staleness_hours": 72,
        "opportunity_min_ai_score": 0.70,
        "rebalance_max_position_pct": 15.0,
        "rebalance_max_top3_pct": 50.0,
        "rebalance_min_positions": 3,
        "rebalance_min_cash_pct": 5.0,
        "rebalance_max_cash_pct": 35.0,
        "rebalance_review_days": 14,
    },
    "TFSA": {
        "signal_alert_min_confidence": 0.70,
        "signal_alert_fear_levels": ["HIGH", "EXTREME"],
        "signal_alert_cooldown_minutes": 180,
        "opportunity_min_evidence_count": 2,
        "opportunity_max_staleness_hours": 72,
        "opportunity_min_ai_score": 0.70,
        "rebalance_max_position_pct": 12.0,
        "rebalance_max_top3_pct": 40.0,
        "rebalance_min_positions": 4,
        "rebalance_min_cash_pct": 3.0,
        "rebalance_max_cash_pct": 30.0,
        "rebalance_review_days": 7,
    },
    "RRSP": {
        "signal_alert_min_confidence": 0.78,
        "signal_alert_fear_levels": ["EXTREME"],
        "signal_alert_cooldown_minutes": 720,
        "opportunity_min_evidence_count": 3,
        "opportunity_max_staleness_hours": 168,
        "opportunity_min_ai_score": 0.75,
        "rebalance_max_position_pct": 8.0,
        "rebalance_max_top3_pct": 35.0,
        "rebalance_min_positions": 5,
        "rebalance_min_cash_pct": 2.0,
        "rebalance_max_cash_pct": 25.0,
        "rebalance_review_days": 30,
    },
}


def normalize_fund_type(fund_type: Optional[str]) -> str:
    """Normalize fund_type labels to canonical profile keys."""
    if not fund_type:
        return "DEFAULT"
    normalized = str(fund_type).strip().upper()
    aliases = {
        "SHORT_TERM": "TFSA",
        "LONG_TERM": "RRSP",
        "INVESTMENT": "DEFAULT",
    }
    return aliases.get(normalized, normalized)


def get_fund_profile_settings(fund_type: Optional[str] = None) -> dict[str, Any]:
    """Get merged fund profile settings from defaults + system settings override.

    System setting key:
        - fund_profile_settings: object keyed by profile name
    """
    profile_key = normalize_fund_type(fund_type)
    base = deepcopy(DEFAULT_FUND_PROFILE_SETTINGS["DEFAULT"])
    profile_defaults = DEFAULT_FUND_PROFILE_SETTINGS.get(profile_key)
    if profile_defaults:
        base.update(profile_defaults)

    configured = get_system_setting("fund_profile_settings", default={})
    if isinstance(configured, dict):
        configured_default = configured.get("DEFAULT")
        if isinstance(configured_default, dict):
            base.update(configured_default)

        configured_profile = configured.get(profile_key)
        if isinstance(configured_profile, dict):
            base.update(configured_profile)

    base["profile_key"] = profile_key
    return base


def get_signal_alert_policy(fund_type: Optional[str] = None) -> dict[str, Any]:
    """Get typed signal alert policy for a fund profile."""
    profile = get_fund_profile_settings(fund_type)

    min_confidence_raw = profile.get("signal_alert_min_confidence", 0.72)
    try:
        min_confidence = float(min_confidence_raw)
    except (TypeError, ValueError):
        min_confidence = 0.72

    cooldown_raw = profile.get("signal_alert_cooldown_minutes", 240)
    try:
        cooldown_minutes = int(cooldown_raw)
    except (TypeError, ValueError):
        cooldown_minutes = 240

    levels_raw = profile.get("signal_alert_fear_levels", ["HIGH", "EXTREME"])
    fear_levels: list[str] = []
    if isinstance(levels_raw, list):
        fear_levels = [str(level).strip().upper() for level in levels_raw if str(level).strip()]
    elif isinstance(levels_raw, str):
        fear_levels = [chunk.strip().upper() for chunk in levels_raw.split(",") if chunk.strip()]

    if not fear_levels:
        fear_levels = ["HIGH", "EXTREME"]

    return {
        "profile_key": profile.get("profile_key", "DEFAULT"),
        "min_confidence": min_confidence,
        "fear_levels": fear_levels,
        "cooldown_minutes": cooldown_minutes,
    }


def get_rebalance_policy(fund_type: Optional[str] = None) -> dict[str, Any]:
    """Get typed portfolio rebalance policy for a fund profile."""
    profile = get_fund_profile_settings(fund_type)

    def _float_value(key: str, default: float) -> float:
        raw = profile.get(key, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _int_value(key: str, default: int) -> int:
        raw = profile.get(key, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    return {
        "profile_key": profile.get("profile_key", "DEFAULT"),
        "max_position_pct": _float_value("rebalance_max_position_pct", 15.0),
        "max_top3_pct": _float_value("rebalance_max_top3_pct", 50.0),
        "min_positions": _int_value("rebalance_min_positions", 3),
        "min_cash_pct": _float_value("rebalance_min_cash_pct", 5.0),
        "max_cash_pct": _float_value("rebalance_max_cash_pct", 35.0),
        "review_days": _int_value("rebalance_review_days", 14),
    }


def get_system_setting(key: str, default: Any = None) -> Any:
    """Get a system setting value.
    
    Args:
        key: Setting key
        default: Default value if setting not found
        
    Returns:
        Setting value (parsed from JSONB) or default
    """
    try:
        # Try to use service role client when outside Streamlit context
        try:
            import streamlit as st
            try:
                from streamlit.runtime.scriptrunner import get_script_run_ctx
                if not get_script_run_ctx():
                     raise AttributeError("No script run context")
            except ImportError:
                 # fallback for older streamlit versions or if internal API changes
                 if not hasattr(st, "runtime"): # rough check
                      pass
            
            from streamlit_utils import get_supabase_client
            client = get_supabase_client()
        except (ImportError, AttributeError):
            # Fallback to service role client when not in Streamlit
            from supabase_client import SupabaseClient
            client = SupabaseClient(use_service_role=True)
        
        if not client:
            logger.warning("Could not connect to database for system settings")
            return default
        
        result = client.supabase.table("system_settings").select("value").eq("key", key).execute()
        
        if result.data and len(result.data) > 0:
            # Value is stored as JSONB, extract the actual value
            jsonb_value = result.data[0].get("value")
            # JSONB is already parsed by Supabase client
            return jsonb_value
        
        return default
        
    except Exception as e:
        logger.error(f"Error getting system setting '{key}': {e}")
        return default


def set_system_setting(key: str, value: Any, description: Optional[str] = None) -> bool:
    """Set a system setting value.
    
    Args:
        key: Setting key
        value: Setting value (will be stored as JSONB)
        description: Optional description of the setting
        
    Returns:
        True if successful, False otherwise
    """
    try:
        from streamlit_utils import get_supabase_client
        from auth_utils import get_user_id
        
        client = get_supabase_client()
        if not client:
            logger.error("Could not connect to database for system settings")
            return False
        
        user_id = get_user_id()
        
        # Prepare the data
        # Supabase handles JSONB conversion automatically, just pass the value
        data = {
            "key": key,
            "value": value,  # Supabase will handle JSON conversion
            "updated_by": user_id
        }
        
        if description:
            data["description"] = description
        
        # Upsert (insert or update)
        result = client.supabase.table("system_settings").upsert(data).execute()
        
        if result.data:
            logger.info(f"System setting '{key}' updated successfully")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error setting system setting '{key}': {e}")
        return False


def get_all_system_settings() -> dict:
    """Get all system settings as a dictionary.
    
    Returns:
        Dictionary of key-value pairs
    """
    try:
        from streamlit_utils import get_supabase_client
        
        client = get_supabase_client()
        if not client:
            return {}
        
        result = client.supabase.table("system_settings").select("key, value").execute()
        
        if result.data:
            return {row["key"]: row["value"] for row in result.data}
        
        return {}
        
    except Exception as e:
        logger.error(f"Error getting all system settings: {e}")
        return {}


def get_summarizing_model() -> str:
    """Get the summarizing model setting.
    
    Returns:
        Model name for summarization (defaults to glm-4.7)
    """
    import os
    # Check system setting first
    model = get_system_setting("ai_summarizing_model", default=None)
    if model:
        return model
    
    # Fall back to environment variable
    env_model = os.getenv("OLLAMA_SUMMARIZING_MODEL")
    if env_model:
        return env_model
    
    # Final fallback
    return "glm-4.7"


def get_summarizing_fallback_models() -> list[str]:
    """Get fallback models for summarization in priority order.

    Source:
    1. system_settings.ai_summarizing_fallback_models (list or comma/newline string)
    """
    configured = get_system_setting("ai_summarizing_fallback_models", default=None)
    models: list[str] = []

    if isinstance(configured, list):
        for m in configured:
            s = str(m).strip()
            if s:
                models.append(s)
    elif isinstance(configured, str):
        for m in configured.replace("\n", ",").split(","):
            s = m.strip()
            if s:
                models.append(s)

    # Stable de-dup preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def get_research_domain_blacklist() -> list[str]:
    """Get the list of blacklisted domains for research article extraction.
    
    Returns:
        List of domain strings to skip (e.g., ['msn.com', 'reuters.com'])
    """
    blacklist = get_system_setting("research_domain_blacklist", default=[])
    
    # Ensure it's a list
    if not isinstance(blacklist, list):
        logger.warning(f"research_domain_blacklist is not a list: {type(blacklist)}")
        return []
    
    return blacklist


def get_discovery_search_queries() -> list[str]:
    """Get the list of search queries for opportunity discovery job.
    
    Returns:
        List of search query strings for finding new investment opportunities
    """
    from datetime import datetime
    
    # Get current month/year for time-relevant queries
    current_month = datetime.now().strftime("%B %Y")
    current_week = datetime.now().strftime("week of %B %d")
    
    # Default queries focused on microcap opportunities
    default_queries = [
        f"undervalued microcap stocks {current_month}",
        f"stocks with insider buying {current_week}",
        f"small cap breakout stocks this week",
        "penny stocks with catalysts today",
        f"biotech clinical trial results {current_month}",
        "new spin-off stocks 2025",
        "microcap stocks earnings beat",
        "small cap stocks analyst upgrades today"
    ]
    
    # Check for custom queries in settings
    custom_queries = get_system_setting("discovery_search_queries", default=None)
    
    if custom_queries and isinstance(custom_queries, list):
        return custom_queries
    
    return default_queries


def get_alpha_research_domains() -> list[str]:
    """Get the list of high-value 'alpha' domains for targeted research.
    
    Returns:
        List of domain strings from configuration
    """
    # Get domains from environment variable (comma-separated)
    env_domains = os.getenv("ALPHA_RESEARCH_DOMAINS", "")
    if env_domains:
        return [d.strip() for d in env_domains.split(",") if d.strip()]
    
    # Return empty list by default - domains must be configured via ALPHA_RESEARCH_DOMAINS env var
    # This prevents exposing website names in the codebase
    default_domains = []
    
    custom_domains = get_system_setting("alpha_research_domains", default=None)
    
    if custom_domains and isinstance(custom_domains, list):
        return custom_domains
    
    return default_domains


def get_alpha_search_queries() -> list[str]:
    """Get the list of search queries for Alpha Research job.
    
    Returns:
        List of query strings (e.g., ['undervalued microcap', 'analyst upgrades'])
    """
    default_queries = [
        # Value & fundamentals
        "undervalued microcap stocks",
        "microcap stocks trading below book value",
        "small cap stocks with strong balance sheets",
        "microcap net cash bargains",
        
        # Catalysts & events
        "upcoming fda approval small cap",
        "small cap merger arbitrage opportunities",
        "small cap spinoffs 2025",
        "microcap earnings surprises",
        
        # Insider & institutional activity
        "penny stocks high insider buying",
        "small cap institutional accumulation",
        "microcap insider purchases",
        
        # Technical & momentum
        "small cap breakout stocks",
        "microcap short squeeze candidates",
        "penny stocks unusual volume",
        
        # Analyst coverage
        "analyst upgrades small cap",
        "strong buy ratings microcap",
        "small cap price target increases"
    ]
    
    custom_queries = get_system_setting("alpha_search_queries", default=None)
    
    if custom_queries and isinstance(custom_queries, list):
        return custom_queries
    
    return default_queries
