#!/usr/bin/env python3
"""Daily market brief from benchmark closes + one LLM call (cached per calendar day)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ollama_client import OllamaClient
from postgres_client import PostgresClient
from settings import get_summarizing_model
from supabase_client import SupabaseClient
from ticker_analysis_service import extract_json

logger = logging.getLogger(__name__)

# Subset aligned with benchmark_refresh_job (indices first for macro tone)
BRIEF_BENCHMARK_TICKERS = ["^GSPC", "QQQ", "^RUT", "VTI"]


def _ny_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def fetch_benchmark_snapshot(supabase: SupabaseClient) -> tuple[str, dict[str, Any]]:
    """Return human-readable stats block + structured digest for LLM input."""
    lines: list[str] = []
    digest: dict[str, Any] = {"tickers": {}, "as_of_ny": str(_ny_today())}

    for sym in BRIEF_BENCHMARK_TICKERS:
        try:
            res = (
                supabase.supabase.table("benchmark_data")
                .select("date, close")
                .eq("ticker", sym)
                .order("date", desc=True)
                .limit(12)
                .execute()
            )
            rows = list(res.data or [])
        except Exception as exc:
            logger.warning("benchmark fetch failed for %s: %s", sym, exc)
            continue

        if len(rows) < 2:
            lines.append(f"{sym}: insufficient history")
            digest["tickers"][sym] = {"error": "insufficient_history"}
            continue

        def _close(i: int) -> float:
            return float(rows[i]["close"])

        latest = _close(0)
        prev = _close(1)
        d1 = (latest - prev) / prev * 100.0 if prev else 0.0

        d5: float | None = None
        if len(rows) >= 6:
            old = _close(5)
            if old:
                d5 = (latest - old) / old * 100.0

        last_date = rows[0].get("date")
        lines.append(
            f"{sym} as_of={last_date} close={latest:.2f} "
            f"1d_pct={d1:+.2f}%"
            + (f" 5d_pct={d5:+.2f}%" if d5 is not None else "")
        )
        digest["tickers"][sym] = {
            "last_date": str(last_date),
            "close": latest,
            "pct_change_1d": round(d1, 4),
            "pct_change_5d": None if d5 is None else round(d5, 4),
        }

    return "\n".join(lines), digest


def run_market_daily_brief(
    ollama: OllamaClient,
    postgres: PostgresClient,
    supabase: SupabaseClient,
    *,
    brief_date: date | None = None,
    model_override: str | None = None,
) -> dict[str, Any] | None:
    """Build and upsert one row for brief_date (default: today US/Eastern)."""
    bdate = brief_date or _ny_today()
    stats_text, digest = fetch_benchmark_snapshot(supabase)
    if not stats_text.strip():
        logger.warning("No benchmark stats for market brief")
        return None

    from ai_prompts import MARKET_DAILY_BRIEF_PROMPT

    prompt = MARKET_DAILY_BRIEF_PROMPT.format(benchmark_stats=stats_text)
    model = (model_override or "").strip() or get_summarizing_model()
    system_prompt = (
        "You are a macro commentator. Return ONLY valid JSON with the exact keys requested. "
        "No stock picks or ticker symbols."
    )
    full = ""
    for chunk in ollama.query_ollama(
        prompt=prompt,
        model=model,
        stream=True,
        system_prompt=system_prompt,
        json_mode=True,
        temperature=0.2,
    ):
        full += chunk

    parsed = extract_json(full)
    if not parsed:
        logger.error("market brief JSON parse failed")
        return None

    headline = (parsed.get("headline") or "")[:200]
    narrative = parsed.get("narrative") or ""
    regime = parsed.get("regime") or {}

    q = """
        INSERT INTO market_daily_brief (
            brief_date, headline, narrative, regime_json, inputs_digest, model_used
        ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
        ON CONFLICT (brief_date) DO UPDATE SET
            headline = EXCLUDED.headline,
            narrative = EXCLUDED.narrative,
            regime_json = EXCLUDED.regime_json,
            inputs_digest = EXCLUDED.inputs_digest,
            model_used = EXCLUDED.model_used,
            updated_at = NOW()
    """
    postgres.execute_update(
        q,
        (
            bdate,
            headline or None,
            narrative or None,
            json.dumps(regime),
            json.dumps(digest),
            model,
        ),
    )

    row = postgres.execute_query(
        """
        SELECT brief_date, headline, narrative, regime_json, inputs_digest, model_used, updated_at
        FROM market_daily_brief WHERE brief_date = %s
        """,
        (bdate,),
    )
    return row[0] if row else None


def fetch_latest_brief(postgres: PostgresClient) -> dict[str, Any] | None:
    rows = postgres.execute_query(
        """
        SELECT brief_date, headline, narrative, regime_json, inputs_digest, model_used, updated_at
        FROM market_daily_brief
        ORDER BY brief_date DESC
        LIMIT 1
        """
    )
    return rows[0] if rows else None
