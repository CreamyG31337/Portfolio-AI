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


def is_meta_analysis_phase1_signal_fusion_enabled() -> bool:
    """Gate Phase 1 ticker-meta inputs (signal snapshot + market brief) and matching prompt.

    Set ``META_ANALYSIS_PHASE1_SIGNAL_FUSION`` to ``false``, ``0``, ``no``, or ``off`` to revert
    to the pre-fusion bundle and prompt without redeploying code.

    Default: enabled (true).
    """
    raw = os.getenv("META_ANALYSIS_PHASE1_SIGNAL_FUSION", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_meta_analysis_phase3_sector_enabled() -> bool:
    """Phase 3b sector synthesis — always on. Env var ``META_ANALYSIS_PHASE3_SECTOR=false`` to
    disable in an emergency without redeploying code (set to ``false``/``0``/``no``/``off``)."""
    raw = os.getenv("META_ANALYSIS_PHASE3_SECTOR", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_meta_analysis_human_thesis_enabled() -> bool:
    """Inject Insights (``ticker_theses``) into ticker-meta artifact bundles (ROADMAP §2.6 R1).

    Default on. Set ``META_ANALYSIS_HUMAN_THESIS=false`` to disable without redeploying.
    Scope via ``META_ANALYSIS_HUMAN_THESIS_SCOPE`` (see ``get_meta_analysis_human_thesis_scope``).
    """
    raw = os.getenv("META_ANALYSIS_HUMAN_THESIS", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_meta_analysis_phase_h2_enabled() -> bool:
    """Inject Phase H2 families into ticker-meta bundles (clusters, dilution, filings,
    confluence, prior stance + track record).

    Default on. Set ``META_ANALYSIS_PHASE_H2=false`` to disable without redeploying.
    """
    raw = os.getenv("META_ANALYSIS_PHASE_H2", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_meta_analysis_trend_memory_enabled() -> bool:
    """Inject prior regime / rotation-rank history into market brief and sector meta (Phase H4).

    Default on. Set ``META_ANALYSIS_TREND_MEMORY=false`` to disable without redeploying.
    """
    raw = os.getenv("META_ANALYSIS_TREND_MEMORY", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def is_story_dedup_enabled() -> bool:
    """Phase I1 near-duplicate headline matching before extract/summarize.

    Default on. Set ``STORY_DEDUP_ENABLED=false`` to disable without redeploying.
    """
    raw = os.getenv("STORY_DEDUP_ENABLED", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def get_meta_analysis_human_thesis_scope() -> str:
    """Who gets theses injected into meta: ``holdings`` (default), ``holdings_or_recent``, or ``all``.

    ``holdings`` — production fund positions only (limits first-night meta refresh backlog).
    ``holdings_or_recent`` — holdings plus tickers with an active thesis updated in the last 14d.
    ``all`` — any ticker with an active Insights thesis.
    """
    raw = os.getenv("META_ANALYSIS_HUMAN_THESIS_SCOPE", "holdings").strip().lower()
    if raw in ("all", "holdings_or_recent", "holdings"):
        return raw
    return "holdings"


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
    """Get a system setting value."""
    try:
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
        from supabase_client import SupabaseClient
        from flask_auth_utils import get_user_id_flask

        client = SupabaseClient(use_service_role=True)
        if not client:
            logger.error("Could not connect to database for system settings")
            return False

        user_id = None
        try:
            from flask import has_request_context

            if has_request_context():
                user_id = get_user_id_flask()
        except (ImportError, RuntimeError):
            pass
        
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
        from supabase_client import SupabaseClient

        client = SupabaseClient(use_service_role=True)
        if not client:
            return {}
        
        result = client.supabase.table("system_settings").select("key, value").execute()
        
        if result.data:
            return {row["key"]: row["value"] for row in result.data}
        
        return {}
        
    except Exception as e:
        logger.error(f"Error getting all system settings: {e}")
        return {}


def get_summarizing_model(scope: Optional[str] = None) -> str:
    """Get the summarizing model setting.

    When ``scope`` is set (e.g. ``meta_analysis``, ``market_brief``), reads
    ``system_settings`` key ``ai_summarizing_model_<scope>`` first (suffix is
    lowercased non-alphanumeric runs replaced with ``_``). If unset, falls back to
    the global ``ai_summarizing_model`` chain.

    Args:
        scope: Optional logical workload name for per-job model overrides.

    Returns:
        Model name for summarization (defaults to ``OLLAMA_SUMMARIZING_DEFAULT`` when unset)
    """
    import os
    import re

    from model_registry import OLLAMA_SUMMARIZING_DEFAULT, remap_deprecated_model

    if scope and str(scope).strip():
        suffix = re.sub(r"[^a-zA-Z0-9]+", "_", str(scope).strip()).strip("_").lower()
        if suffix:
            scoped = get_system_setting(f"ai_summarizing_model_{suffix}", default=None)
            if scoped:
                return remap_deprecated_model(str(scoped).strip())

    model = get_system_setting("ai_summarizing_model", default=None)
    if model:
        return remap_deprecated_model(str(model).strip())

    env_model = os.getenv("OLLAMA_SUMMARIZING_MODEL")
    if env_model:
        return remap_deprecated_model(env_model.strip())

    return OLLAMA_SUMMARIZING_DEFAULT


def get_summarizing_fallback_models() -> list[str]:
    """Get fallback models for summarization in priority order.

    Source:
    1. system_settings.ai_summarizing_fallback_models (list or comma/newline string)
    2. ``OLLAMA_SUMMARIZING_FALLBACK_MODELS`` (comma-separated) when (1) is empty
    3. Built-in queue Ollama pair then primary GLM (``get_builtin_summarizing_fallback_models()``) when still empty
    """
    from model_registry import get_builtin_summarizing_fallback_models, remap_deprecated_model

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

    env_fb = os.getenv("OLLAMA_SUMMARIZING_FALLBACK_MODELS", "").strip()
    if not models and env_fb:
        for m in env_fb.replace("\n", ",").split(","):
            s = m.strip()
            if s:
                models.append(s)

    if not models:
        models = get_builtin_summarizing_fallback_models()

    # Stable de-dup preserving order; remap deleted Qwen3.6 tags etc.
    seen: set[str] = set()
    unique: list[str] = []
    for m in models:
        remapped = remap_deprecated_model(m)
        if remapped and remapped not in seen:
            seen.add(remapped)
            unique.append(remapped)
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


def _normalize_alpha_domain_entries(raw: Any) -> list[dict[str, Any]]:
    """Normalize a raw ``alpha_research_domains`` value into structured entries.

    Accepts two on-disk shapes for backwards compatibility:

    1. Legacy flat list of strings::

        ["fool.com", "benzinga.com"]

       Every string is treated as an enabled domain.

    2. Preferred structured list of objects::

        [
            {"domain": "fool.com", "enabled": true, "note": "reliable"},
            {"domain": "seekingalpha.com", "enabled": false, "note": "paywalled"}
        ]

       ``enabled`` defaults to ``True`` when omitted so an operator can add a
       bare ``{"domain": "..."}`` and have it active. ``note`` is free-form and
       only used for human/operator context (and a future admin UI).

    Mixed lists (some strings, some dicts) are tolerated. Invalid/blank
    entries are dropped. Returns a list of dicts with at least ``domain`` and
    ``enabled`` keys; ``note`` is preserved when present.
    """
    if not isinstance(raw, list):
        return []

    normalized: list[dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, str):
            domain = entry.strip()
            if domain:
                normalized.append({"domain": domain, "enabled": True})
        elif isinstance(entry, dict):
            domain = str(entry.get("domain", "")).strip()
            if not domain:
                continue
            # Default to enabled when the flag is missing; coerce truthy/falsey.
            enabled = entry.get("enabled", True)
            item: dict[str, Any] = {"domain": domain, "enabled": bool(enabled)}
            note = entry.get("note")
            if note:
                item["note"] = str(note)
            normalized.append(item)
        # Anything else (None, numbers, nested lists) is silently skipped.

    return normalized


def get_alpha_research_domain_config() -> list[dict[str, Any]]:
    """Get the FULL structured alpha-domain config (including disabled entries).

    This is the source-of-truth view for operators / a future admin UI: it
    returns every configured domain with its ``enabled`` flag and optional
    ``note``, so disabled domains remain visible and easy to re-enable.

    Resolution order mirrors :func:`get_alpha_research_domains`:

    1. ``ALPHA_RESEARCH_DOMAINS`` env var (comma-separated) -- every listed
       domain is returned as enabled. Intended for local/dev overrides.
    2. ``system_settings`` key ``alpha_research_domains`` (flat list or
       structured list -- see :func:`_normalize_alpha_domain_entries`).
    3. Empty list when nothing is configured.
    """
    env_domains = os.getenv("ALPHA_RESEARCH_DOMAINS", "")
    if env_domains:
        return [
            {"domain": d.strip(), "enabled": True}
            for d in env_domains.split(",")
            if d.strip()
        ]

    custom_domains = get_system_setting("alpha_research_domains", default=None)
    return _normalize_alpha_domain_entries(custom_domains)


def get_alpha_research_domains() -> list[str]:
    """Get the list of ENABLED 'alpha' domains for targeted research.

    Returns only the host names whose config entry is enabled, so the Alpha
    Research job builds ``site:`` dorks exclusively from active domains. An
    operator can temporarily disable a noisy or blocked domain by flipping its
    ``enabled`` flag to ``false`` in the ``alpha_research_domains``
    ``system_settings`` row -- without losing the entry or its note. See
    :func:`get_alpha_research_domain_config` for the full structured view.

    Domains are intentionally kept out of source control (see git history);
    configure them via ``system_settings`` or the ``ALPHA_RESEARCH_DOMAINS``
    env var.

    Returns:
        List of enabled domain strings (possibly empty).
    """
    return [
        entry["domain"]
        for entry in get_alpha_research_domain_config()
        if entry.get("enabled", True)
    ]


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


# Valid SearXNG time-range filters; anything else means "all time" (None).
_VALID_SEARCH_TIME_RANGES = ("day", "week", "month", "year")


def get_alpha_search_time_range() -> Optional[str]:
    """Time-range filter for the Alpha Hunter's web search.

    The Alpha Hunter runs ``site:``-restricted queries against a small set of
    high-value domains. Those analysis/opinion pieces are frequently a few
    days-to-weeks old, so the previous ``news`` + ``time_range='day'`` strategy
    returned almost nothing. This setting controls the window for the general
    web search instead.

    Resolution order:
    1. ``system_settings`` key ``alpha_search_time_range`` (tune without a
       redeploy).
    2. ``ALPHA_SEARCH_TIME_RANGE`` env var.
    3. Default ``"week"``.

    Accepted values: ``day`` / ``week`` / ``month`` / ``year``, or one of
    ``none`` / ``all`` / ``any`` / empty to search all time (returns ``None``).
    Invalid values fall back to ``"week"``.
    """
    value = get_system_setting("alpha_search_time_range", default=None)
    if value is None:
        value = os.getenv("ALPHA_SEARCH_TIME_RANGE") or "week"

    normalized = str(value).strip().lower()
    if normalized in ("", "none", "all", "any"):
        return None
    if normalized not in _VALID_SEARCH_TIME_RANGES:
        logger.warning(
            "Invalid alpha_search_time_range %r; falling back to 'week'", value
        )
        return "week"
    return normalized


def get_alpha_queries_per_run(query_count: Optional[int] = None) -> int:
    """How many search queries the Alpha Hunter runs per scheduled invocation.

    The job rotates through the full query list over successive days so all
    configured queries get coverage (see ``select_alpha_queries`` in
    ``jobs_common``).

    Resolution order:
    1. ``system_settings`` key ``alpha_queries_per_run``.
    2. ``ALPHA_QUERIES_PER_RUN`` env var.
    3. Default ``4``.

    The value is clamped to ``[1, query_count]`` when ``query_count`` is known;
    otherwise clamped to ``[1, 32]``.
    """
    value = get_system_setting("alpha_queries_per_run", default=None)
    if value is None:
        value = os.getenv("ALPHA_QUERIES_PER_RUN") or "4"

    try:
        n = int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid alpha_queries_per_run %r; falling back to 4", value)
        n = 4

    if query_count is not None and query_count > 0:
        return max(1, min(n, query_count))
    return max(1, min(n, 32))
