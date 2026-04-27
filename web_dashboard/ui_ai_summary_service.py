#!/usr/bin/env python3
"""Tier-1 / tier-2 UI AI summary persistence and refresh helpers."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from dashboard_portfolio_digest import build_dashboard_portfolio_digest, digest_fingerprint
from ollama_client import OllamaClient
from postgres_client import PostgresClient
from settings import get_summarizing_model
from supabase_client import SupabaseClient
from ticker_analysis_service import extract_json
from ui_ai_summary_scopes import make_portfolio_scope_key, scope_dashboard_portfolio

logger = logging.getLogger(__name__)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_ui_summary_row(
    postgres: PostgresClient,
    scope: str,
    scope_key: str,
) -> dict[str, Any] | None:
    rows = postgres.execute_query(
        """
        SELECT id, scope, scope_key, content_class, summary_json, inputs_digest,
               model_used, created_at, updated_at
        FROM ui_ai_summary
        WHERE scope = %s AND scope_key = %s
        LIMIT 1
        """,
        (scope, scope_key),
    )
    return dict(rows[0]) if rows else None


def upsert_ui_summary(
    postgres: PostgresClient,
    *,
    scope: str,
    scope_key: str,
    content_class: str,
    summary_json: dict[str, Any],
    inputs_digest: str,
    model_used: str,
) -> None:
    postgres.execute_update(
        """
        INSERT INTO ui_ai_summary (
            scope, scope_key, content_class, summary_json, inputs_digest, model_used
        ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (scope, scope_key) DO UPDATE SET
            content_class = EXCLUDED.content_class,
            summary_json = EXCLUDED.summary_json,
            inputs_digest = EXCLUDED.inputs_digest,
            model_used = EXCLUDED.model_used,
            updated_at = NOW()
        """,
        (
            scope,
            scope_key,
            content_class,
            json.dumps(summary_json, default=str),
            inputs_digest,
            model_used,
        ),
    )


def refresh_dashboard_portfolio_overview(
    ollama: OllamaClient,
    postgres: PostgresClient,
    *,
    fund: str,
    display_currency: str,
    time_range: str = "ALL",
    force_llm: bool = False,
    model_override: str | None = None,
) -> dict[str, Any] | None:
    """
    Build digest, skip LLM if inputs_digest unchanged unless force_llm.
    Returns latest row dict (summary fields) or None on failure.
    """
    from ai_prompts import DASHBOARD_PORTFOLIO_OVERVIEW_PROMPT

    scope = scope_dashboard_portfolio()
    sk = make_portfolio_scope_key(fund, display_currency, time_range)
    digest = build_dashboard_portfolio_digest(fund, display_currency, time_range)
    fp = digest_fingerprint(digest)
    d_hash = sha256_hex(fp)

    existing = fetch_ui_summary_row(postgres, scope, sk)
    if existing and existing.get("inputs_digest") == d_hash and not force_llm:
        logger.info("ui_ai_summary skip LLM (unchanged digest) scope=%s key=%s", scope, sk)
        return existing

    model = (model_override or "").strip() or get_summarizing_model()
    prompt = DASHBOARD_PORTFOLIO_OVERVIEW_PROMPT.format(digest_json=json.dumps(digest, indent=2, default=str))
    full = ""
    for chunk in ollama.query_ollama(
        prompt=prompt,
        model=model,
        stream=True,
        system_prompt="Return ONLY valid JSON with headline, narrative, bullets.",
        json_mode=True,
        temperature=0.2,
    ):
        full += chunk
    parsed = extract_json(full)
    if not parsed:
        logger.error("dashboard portfolio overview JSON parse failed")
        return existing

    summary_json = {
        "headline": (parsed.get("headline") or "")[:200],
        "narrative": parsed.get("narrative") or "",
        "bullets": parsed.get("bullets") if isinstance(parsed.get("bullets"), list) else [],
        "digest": digest,
    }
    upsert_ui_summary(
        postgres,
        scope=scope,
        scope_key=sk,
        content_class="price_linked",
        summary_json=summary_json,
        inputs_digest=d_hash,
        model_used=model,
    )
    return fetch_ui_summary_row(postgres, scope, sk)


def fetch_rollup_row(postgres: PostgresClient, fund: str) -> dict[str, Any] | None:
    rows = postgres.execute_query(
        """
        SELECT fund, headline, narrative, sources_used, inputs_digest, model_used, updated_at
        FROM ui_ai_rollup_fund
        WHERE fund = %s
        LIMIT 1
        """,
        (fund,),
    )
    return dict(rows[0]) if rows else None


def upsert_fund_rollup(
    postgres: PostgresClient,
    *,
    fund: str,
    headline: str,
    narrative: str,
    sources_used: dict[str, Any],
    inputs_digest: str,
    model_used: str,
) -> None:
    postgres.execute_update(
        """
        INSERT INTO ui_ai_rollup_fund (
            fund, headline, narrative, sources_used, inputs_digest, model_used
        ) VALUES (%s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (fund) DO UPDATE SET
            headline = EXCLUDED.headline,
            narrative = EXCLUDED.narrative,
            sources_used = EXCLUDED.sources_used,
            inputs_digest = EXCLUDED.inputs_digest,
            model_used = EXCLUDED.model_used,
            updated_at = NOW()
        """,
        (
            fund,
            headline[:300],
            narrative,
            json.dumps(sources_used),
            inputs_digest,
            model_used,
        ),
    )


def _market_backdrop_text(postgres: PostgresClient) -> str:
    try:
        from market_brief_service import fetch_latest_brief

        row = fetch_latest_brief(postgres)
        if not row:
            return "(none)"
        h = row.get("headline") or ""
        n = (row.get("narrative") or "")[:1200]
        return f"Headline: {h}\nNarrative: {n}"
    except Exception as exc:
        logger.warning("market brief fetch for rollup: %s", exc)
        return "(none)"


def _portfolio_summary_text(postgres: PostgresClient, fund: str, currency: str) -> str:
    row = fetch_ui_summary_row(
        postgres,
        scope_dashboard_portfolio(),
        make_portfolio_scope_key(fund, currency, "ALL"),
    )
    if not row:
        return "(none)"
    sj = row.get("summary_json")
    if isinstance(sj, str):
        try:
            sj = json.loads(sj)
        except json.JSONDecodeError:
            sj = {}
    if not isinstance(sj, dict):
        sj = {}
    h = sj.get("headline") or ""
    n = (sj.get("narrative") or "")[:1500]
    bullets = sj.get("bullets") or []
    btxt = "\n".join(f"- {b}" for b in bullets[:8]) if isinstance(bullets, list) else ""
    return f"Headline: {h}\nNarrative: {n}\n{btxt}"


def refresh_fund_cross_screen_rollup(
    ollama: OllamaClient,
    postgres: PostgresClient,
    *,
    fund: str,
    display_currency: str = "CAD",
    force_llm: bool = False,
    model_override: str | None = None,
    skip_if_unchanged: bool = True,
) -> dict[str, Any] | None:
    """Tier-2 digest for one fund. Computes inputs_digest from backdrop + tier-1 portfolio text."""
    from ai_prompts import FUND_CROSS_SCREEN_ROLLUP_PROMPT

    backdrop = _market_backdrop_text(postgres)
    port = _portfolio_summary_text(postgres, fund, display_currency)
    blob = json.dumps(
        {"fund": fund, "currency": display_currency, "market": backdrop, "portfolio": port},
        sort_keys=True,
    )
    d_hash = sha256_hex(blob)

    existing = fetch_rollup_row(postgres, fund)
    if existing and existing.get("inputs_digest") == d_hash and skip_if_unchanged and not force_llm:
        logger.info("ui_ai_rollup_fund skip LLM (unchanged) fund=%s", fund)
        return existing

    model = (model_override or "").strip() or get_summarizing_model()
    prompt = FUND_CROSS_SCREEN_ROLLUP_PROMPT.format(
        fund=fund,
        market_backdrop=backdrop,
        portfolio_summary=port,
    )
    full = ""
    for chunk in ollama.query_ollama(
        prompt=prompt,
        model=model,
        stream=True,
        system_prompt="Return ONLY valid JSON with headline, narrative, sources_note.",
        json_mode=True,
        temperature=0.2,
    ):
        full += chunk
    parsed = extract_json(full)
    if not parsed:
        logger.error("fund rollup JSON parse failed for %s", fund)
        return existing

    sources_used = {
        "scopes": ["dashboard.portfolio_overview", "market_daily_brief"],
        "sources_note": parsed.get("sources_note") or "",
    }
    upsert_fund_rollup(
        postgres,
        fund=fund,
        headline=(parsed.get("headline") or "")[:300],
        narrative=parsed.get("narrative") or "",
        sources_used=sources_used,
        inputs_digest=d_hash,
        model_used=model,
    )
    return fetch_rollup_row(postgres, fund)


def list_production_fund_names(supabase: SupabaseClient) -> list[str]:
    try:
        funds_res = supabase.supabase.table("funds").select("name").eq("is_production", True).execute()
        names = [r["name"] for r in (funds_res.data or []) if r.get("name")]
        if names:
            return names
        funds_res = supabase.supabase.table("funds").select("name").limit(10).execute()
        return [r["name"] for r in (funds_res.data or []) if r.get("name")]
    except Exception as exc:
        logger.warning("list_production_fund_names: %s", exc)
        return []
