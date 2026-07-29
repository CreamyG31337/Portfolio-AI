#!/usr/bin/env python3
"""Daily market brief from benchmark closes + one LLM call (cached per calendar day)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from market_regime_normalization import (
    invalid_regime_enum_fields,
    merge_regime_for_storage,
    normalize_market_regime,
)
from ollama_client import OllamaClient, collect_with_summary_model_chain
from postgres_client import PostgresClient
from settings import get_summarizing_model, is_meta_analysis_trend_memory_enabled
from supabase_client import SupabaseClient
from ticker_analysis_service import extract_json

logger = logging.getLogger(__name__)

# Subset aligned with benchmark_refresh_job (indices first for macro tone)
BRIEF_BENCHMARK_TICKERS = ["^GSPC", "QQQ", "^RUT", "VTI"]
_REGIME_HISTORY_LIMIT = 10


def _ny_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _parse_regime_json(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def fetch_recent_regime_history(
    postgres: PostgresClient,
    *,
    before_date: date,
    limit: int = _REGIME_HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    """Prior market_daily_brief rows (newest first), excluding ``before_date``."""
    if limit < 1:
        return []
    try:
        rows = postgres.execute_query(
            """
            SELECT brief_date, regime_json
            FROM market_daily_brief
            WHERE brief_date < %s
            ORDER BY brief_date DESC
            LIMIT %s
            """,
            (before_date, limit),
        )
    except Exception as exc:
        logger.warning("fetch_recent_regime_history failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for row in rows or []:
        bday = row.get("brief_date")
        regime_raw = _parse_regime_json(row.get("regime_json"))
        canon = normalize_market_regime(regime_raw, brief_date=bday)
        out.append({"brief_date": bday, "regime": canon})
    return out


def format_regime_history_block(rows: list[dict[str, Any]]) -> str:
    """Markdown block: oldest → newest. Empty input → ``\"\"``."""
    if not rows:
        return ""
    # Caller may pass newest-first; render chronological for the LLM.
    chronological = list(reversed(rows))
    n = len(chronological)
    lines = [f"### Regime - last {n} sessions (oldest to newest)"]
    for item in chronological:
        bday = item.get("brief_date")
        regime = item.get("regime") if isinstance(item.get("regime"), dict) else {}
        conf = regime.get("regime_confidence")
        try:
            conf_s = f"{float(conf):.2f}" if conf is not None else "—"
        except (TypeError, ValueError):
            conf_s = "—"
        lines.append(
            f"- {bday}: {regime.get('risk_regime', 'NEUTRAL')} | "
            f"{regime.get('breadth_proxy', 'UNCLEAR')} | "
            f"{regime.get('volatility_state', 'UNKNOWN')} | "
            f"confidence={conf_s}"
        )
    return "\n".join(lines)


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

        closes = [float(r["close"]) for r in rows]
        latest = closes[0]
        prev = closes[1]
        d1 = (latest - prev) / prev * 100.0 if prev else 0.0

        d5: float | None = None
        if len(closes) >= 6:
            old = closes[5]
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

    history_text = ""
    if is_meta_analysis_trend_memory_enabled():
        history_rows = fetch_recent_regime_history(
            postgres, before_date=bdate, limit=_REGIME_HISTORY_LIMIT
        )
        history_text = format_regime_history_block(history_rows)

    prompt = MARKET_DAILY_BRIEF_PROMPT.format(
        benchmark_stats=stats_text,
        regime_history=history_text or "(none)",
    )
    model = (model_override or "").strip() or get_summarizing_model("market_brief")
    system_prompt = (
        "You are a macro commentator. Return ONLY valid JSON matching the headline, narrative, "
        "and regime object schema (risk_regime, regime_confidence, breadth_proxy, "
        "volatility_state, macro_themes array, leadership_note, caveats). "
        "No stock picks or ticker symbols."
    )
    full, model = collect_with_summary_model_chain(
        ollama,
        prompt=prompt,
        requested_model=model,
        stream=True,
        system_prompt=system_prompt,
        json_mode=True,
        temperature=0.2,
        response_ok=lambda s: extract_json(s) is not None,
        function_name="market_daily_brief",
    )
    if not full:
        logger.error("market brief LLM failed on all summarization models")
        return None

    parsed = extract_json(full)
    if not parsed:
        logger.error("market brief JSON parse failed")
        return None

    headline = (parsed.get("headline") or "")[:200]
    narrative = parsed.get("narrative") or ""
    regime_raw = parsed.get("regime")
    if not isinstance(regime_raw, dict):
        regime_raw = {}
    drift = invalid_regime_enum_fields(regime_raw)
    if drift:
        logger.warning(
            "market_daily_brief regime enum drift for %s: %s",
            bdate,
            "; ".join(drift),
        )
    regime = merge_regime_for_storage(regime_raw, brief_date=bdate)

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
