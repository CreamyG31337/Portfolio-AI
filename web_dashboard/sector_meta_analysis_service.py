#!/usr/bin/env python3
"""Sector-level meta synthesis over ETF Analysis articles (Phase 3b, research DB)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from ollama_client import OllamaClient, collect_with_summary_model_chain
from postgres_client import PostgresClient
from sector_meta_normalization import normalize_sector_meta_payload
from settings import get_summarizing_model, is_meta_analysis_phase3_sector_enabled
from supabase_client import SupabaseClient
from ticker_analysis_service import extract_json

logger = logging.getLogger(__name__)

_MAX_ARTICLE_EXCERPT = 900
_LOOKBACK_DAYS = 730
_MAX_SECTORS_PER_RUN = 18
_MAX_ARTICLES_PER_SECTOR = 14


def _clip(text: str | None, max_len: int = _MAX_ARTICLE_EXCERPT) -> str:
    if not text:
        return ""
    t = " ".join(str(text).split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 3].rsplit(" ", 1)[0] + "..."


def _parse_as_of_to_utc(s: str, fallback: datetime) -> datetime:
    ss = (s or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ss.replace(" ", "T", 1))
    except ValueError:
        return fallback if fallback.tzinfo else fallback.replace(tzinfo=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class SectorMetaAnalysisService:
    """Build per-sector artifact bundles from ETF Analysis articles and run meta synthesis."""

    def __init__(
        self,
        ollama: OllamaClient | None,
        supabase: SupabaseClient,
        postgres: PostgresClient,
    ) -> None:
        self.ollama = ollama
        self.supabase = supabase
        self.postgres = postgres

    def _resolve_model(self, model_override: str | None) -> str:
        if model_override:
            c = str(model_override).strip()
            if c:
                return c
        return get_summarizing_model("sector_meta")

    def list_sector_keys(self) -> list[str]:
        """Distinct sector buckets (blank sector → __UNTAGGED__), newest activity first."""
        rows = self.postgres.execute_query(
            """
            SELECT COALESCE(NULLIF(TRIM(sector), ''), '__UNTAGGED__') AS sk
            FROM research_articles
            WHERE article_type = 'ETF Analysis'
              AND fetched_at >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY MAX(fetched_at) DESC
            LIMIT %s
            """,
            (_LOOKBACK_DAYS, _MAX_SECTORS_PER_RUN),
        )
        return [str(r["sk"]) for r in (rows or []) if r.get("sk")]

    def fetch_etf_articles_for_sector(self, sector_key: str) -> list[dict[str, Any]]:
        if sector_key == "__UNTAGGED__":
            where = """
                article_type = 'ETF Analysis'
                AND fetched_at >= NOW() - (%s * INTERVAL '1 day')
                AND (sector IS NULL OR TRIM(sector) = '')
            """
            params: tuple[Any, ...] = (_LOOKBACK_DAYS,)
        else:
            where = """
                article_type = 'ETF Analysis'
                AND fetched_at >= NOW() - (%s * INTERVAL '1 day')
                AND TRIM(COALESCE(sector, '')) = %s
            """
            params = (_LOOKBACK_DAYS, sector_key)
        q = f"""
            SELECT id, tickers, sector, title, summary, content, conclusion,
                   sentiment, sentiment_score, source, published_at, fetched_at
            FROM research_articles
            WHERE {where}
            ORDER BY fetched_at DESC
            LIMIT %s
        """
        params = params + (_MAX_ARTICLES_PER_SECTOR,)
        return list(self.postgres.execute_query(q, params) or [])

    def build_artifact_bundle(self, sector_key: str, articles: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        parts.append(f"### Target sector label: {sector_key}")
        parts.append("")
        if not articles:
            parts.append("### ETF Analysis articles in lookback window")
            parts.append("- (none)")
            return "\n".join(parts).strip()

        parts.append("### ETF Analysis articles (newest first; titles + excerpts only)")
        for a in articles:
            tickers = a.get("tickers")
            if isinstance(tickers, list):
                tprev = ", ".join(str(t) for t in tickers[:16] if t)
            else:
                tprev = str(tickers or "")
            parts.append(f"- title: {_clip(a.get('title'), 200)}")
            parts.append(f"  fetched_at: {a.get('fetched_at')} | sentiment: {a.get('sentiment')} score={a.get('sentiment_score')}")
            if tprev:
                parts.append(f"  tickers: {_clip(tprev, 200)}")
            body = a.get("summary") or a.get("content") or ""
            parts.append(f"  summary_excerpt: {_clip(body, _MAX_ARTICLE_EXCERPT)}")
            if a.get("conclusion"):
                parts.append(f"  conclusion_excerpt: {_clip(a.get('conclusion'), 500)}")
            parts.append("")
        return "\n".join(parts).strip()

    def run_sector_meta(
        self,
        sector_key: str,
        model_override: str | None = None,
    ) -> dict[str, Any] | None:
        """Synthesize one sector row for today's ``run_date`` (UTC)."""
        if not is_meta_analysis_phase3_sector_enabled():
            logger.info("Sector meta skipped (META_ANALYSIS_PHASE3_SECTOR off)")
            return None

        articles = self.fetch_etf_articles_for_sector(sector_key)
        bundle = self.build_artifact_bundle(sector_key, articles)
        now = datetime.now(UTC)
        run_date = now.date()

        if not articles:
            normalized = normalize_sector_meta_payload(
                {
                    "sector": sector_key,
                    "sector_stance": "INSUFFICIENT_DATA",
                    "momentum_state": "UNKNOWN",
                    "news_pressure": "UNKNOWN",
                    "rotation_rank": 0,
                    "confidence": 0.0,
                    "key_drivers": [],
                    "risk_flags": ["no_etf_analysis_articles_in_lookback"],
                    "as_of": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                },
                sector_label=sector_key,
                as_of_fallback=now,
            )
            self._save_row(sector_key, run_date, normalized, model_used="insufficient_input_no_llm")
            return normalized

        if not self.ollama:
            logger.error("Sector meta requires an LLM client for %s", sector_key)
            return None

        from ai_prompts import SECTOR_META_ANALYSIS_PROMPT

        prompt = SECTOR_META_ANALYSIS_PROMPT.format(sector=sector_key, artifact_bundle=bundle)
        try:
            from skill_loader import build_enhanced_prompt

            prompt = build_enhanced_prompt(prompt, bundle, "sector_meta_analysis")
        except Exception as exc:
            logger.warning("Skill injection failed for sector meta: %s", exc)

        model = self._resolve_model(model_override)
        system_prompt = (
            "You are a skeptical macro editor. Return ONLY valid JSON with the exact fields specified. "
            "Do not add keys."
        )
        full_response, model_used = collect_with_summary_model_chain(
            self.ollama,
            prompt=prompt,
            requested_model=model,
            stream=True,
            system_prompt=system_prompt,
            json_mode=True,
            temperature=0.15,
            response_ok=lambda s: extract_json(s) is not None,
        )
        if not full_response:
            logger.error("Sector meta LLM failed on all summarization models for %s", sector_key)
            return None

        parsed = extract_json(full_response)
        if not parsed:
            logger.error("Sector meta JSON parse failed for %s", sector_key)
            return None

        normalized = normalize_sector_meta_payload(parsed, sector_label=sector_key, as_of_fallback=now)

        logger.info(
            "Sector meta synthesis for %s: stance=%s momentum=%s news=%s rank=%s",
            sector_key,
            normalized.get("sector_stance"),
            normalized.get("momentum_state"),
            normalized.get("news_pressure"),
            normalized.get("rotation_rank"),
        )

        self._save_row(sector_key, run_date, normalized, model_used=model_used)
        return normalized

    def _save_row(
        self,
        sector_key: str,
        run_date: Any,
        normalized: dict[str, Any],
        model_used: str,
    ) -> None:
        as_of_dt = _parse_as_of_to_utc(str(normalized.get("as_of") or ""), datetime.now(UTC))
        drivers = normalized.get("key_drivers") or []
        risks = normalized.get("risk_flags") or []
        if not isinstance(drivers, list):
            drivers = [str(drivers)]
        if not isinstance(risks, list):
            risks = [str(risks)]
        full_json = json.dumps(normalized)

        q = """
            INSERT INTO sector_meta_analysis (
                sector, run_date, sector_stance, momentum_state, news_pressure,
                rotation_rank, confidence, key_drivers, risk_flags, as_of, full_result, model_used
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s
            )
            ON CONFLICT (sector, run_date) DO UPDATE SET
                sector_stance = EXCLUDED.sector_stance,
                momentum_state = EXCLUDED.momentum_state,
                news_pressure = EXCLUDED.news_pressure,
                rotation_rank = EXCLUDED.rotation_rank,
                confidence = EXCLUDED.confidence,
                key_drivers = EXCLUDED.key_drivers,
                risk_flags = EXCLUDED.risk_flags,
                as_of = EXCLUDED.as_of,
                full_result = EXCLUDED.full_result,
                model_used = EXCLUDED.model_used,
                updated_at = NOW()
        """
        self.postgres.execute_update(
            q,
            (
                sector_key[:120],
                run_date,
                normalized.get("sector_stance"),
                normalized.get("momentum_state"),
                normalized.get("news_pressure"),
                int(normalized.get("rotation_rank") or 0),
                float(normalized.get("confidence") or 0.0),
                json.dumps(drivers),
                json.dumps(risks),
                as_of_dt,
                full_json,
                (model_used or "")[:100] or None,
            ),
        )
        logger.info("Saved sector meta analysis for %s run_date=%s", sector_key, run_date)
