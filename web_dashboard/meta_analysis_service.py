#!/usr/bin/env python3
"""
Per-ticker meta analysis: second LLM pass over stored analysis artifacts only.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, UTC
from typing import Any

from ollama_client import OllamaClient
from postgres_client import PostgresClient
from settings import get_summarizing_model
from supabase_client import SupabaseClient
from ticker_analysis_service import extract_json

logger = logging.getLogger(__name__)


def artifact_bundle_digest(bundle: str) -> str:
    """SHA-256 hex of UTF-8 bundle text (same bytes the meta LLM sees)."""
    return hashlib.sha256(bundle.encode("utf-8")).hexdigest()

_MAX_TEXT = 1200
_MAX_REASON = 500


def _clip(text: str | None, max_len: int = _MAX_TEXT) -> str:
    if not text:
        return ""
    t = " ".join(str(text).split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 3].rsplit(" ", 1)[0] + "..."


class TickerMetaAnalysisService:
    """Build artifact bundles and run meta synthesis for one ticker."""

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
        return get_summarizing_model()

    def fetch_latest_standard_analyses(self, ticker: str) -> list[dict[str, Any]]:
        rows = self.postgres.execute_query(
            """
            SELECT id, updated_at, analysis_date, summary, analysis_text, stance, sentiment,
                   sentiment_score, confidence_score, reasoning
            FROM ticker_analysis
            WHERE ticker = %s AND analysis_type = 'standard'
            ORDER BY updated_at DESC NULLS LAST, analysis_date DESC
            LIMIT 2
            """,
            (ticker,),
        )
        return list(rows or [])

    def fetch_meta_row(self, ticker: str) -> dict[str, Any] | None:
        rows = self.postgres.execute_query(
            """
            SELECT id, ticker, source_analysis_id, source_analysis_snapshot_at,
                   unified_conviction, confidence_adjusted, contradictions,
                   what_changed_vs_last_run, action_items, narrative, full_result,
                   model_used, requested_by, artifact_bundle_digest, created_at, updated_at
            FROM ticker_meta_analysis
            WHERE ticker = %s
            LIMIT 1
            """,
            (ticker,),
        )
        return rows[0] if rows else None

    def needs_refresh(self, ticker: str) -> tuple[bool, dict[str, Any] | None]:
        """Return (needs_run, primary_standard_row_or_none).

        Refresh when there is no meta row, when the stored artifact digest differs from
        the current bundle (social/articles/congress/standard snapshots), or when the
        row predates digest tracking (NULL digest).
        """
        bundle, primary = self.build_artifact_bundle(ticker)
        if not primary:
            return False, None
        digest = artifact_bundle_digest(bundle)
        meta = self.fetch_meta_row(ticker)
        if not meta:
            return True, primary
        stored = meta.get("artifact_bundle_digest")
        if stored != digest:
            return True, primary
        return False, primary

    def _fetch_social_snippets(self, ticker: str) -> list[dict[str, Any]]:
        return self.postgres.execute_query(
            """
            SELECT summary, reasoning, key_themes, sentiment_label, sentiment_score,
                   confidence_score, platform, analyzed_at
            FROM social_sentiment_analysis
            WHERE ticker = %s
            ORDER BY analyzed_at DESC NULLS LAST
            LIMIT 4
            """,
            (ticker,),
        ) or []

    def _fetch_article_snippets(self, ticker: str) -> list[dict[str, Any]]:
        return self.postgres.execute_query(
            """
            SELECT title, conclusion, sentiment, sentiment_score, published_at, fetched_at
            FROM research_articles
            WHERE (
                ticker = %s
                OR (tickers IS NOT NULL AND %s = ANY(tickers))
            )
            AND fetched_at > NOW() - INTERVAL '90 days'
            ORDER BY fetched_at DESC
            LIMIT 6
            """,
            (ticker, ticker),
        ) or []

    def _fetch_congress_snippets(self, ticker: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        trade_rows: list[dict[str, Any]] = []
        session_summaries: list[dict[str, Any]] = []
        try:
            res = (
                self.supabase.supabase.table("congress_trades")
                .select("id")
                .eq("ticker", ticker)
                .order("transaction_date", desc=True)
                .limit(25)
                .execute()
            )
            ids = [r["id"] for r in (res.data or []) if r.get("id") is not None]
        except Exception as exc:
            logger.debug("Congress trade id fetch failed for %s: %s", ticker, exc)
            return trade_rows, session_summaries

        if not ids:
            return trade_rows, session_summaries

        try:
            trade_rows = (
                self.postgres.execute_query(
                    """
                    SELECT trade_id, conflict_score, risk_pattern, reasoning, session_id, analyzed_at
                    FROM congress_trades_analysis
                    WHERE trade_id = ANY(%s::int[])
                    ORDER BY analyzed_at DESC NULLS LAST
                    LIMIT 8
                    """,
                    (ids,),
                )
                or []
            )
        except Exception as exc:
            logger.debug("Congress analysis fetch failed for %s: %s", ticker, exc)

        session_ids = sorted(
            {r["session_id"] for r in trade_rows if r.get("session_id") is not None}
        )[:4]
        if session_ids:
            try:
                session_summaries = (
                    self.postgres.execute_query(
                        """
                        SELECT id, politician_name, ai_summary, conflict_score, risk_pattern, last_analyzed_at
                        FROM congress_trade_sessions
                        WHERE id = ANY(%s::int[])
                        """,
                        (session_ids,),
                    )
                    or []
                )
            except Exception as exc:
                logger.debug("Congress session fetch failed for %s: %s", ticker, exc)

        return trade_rows, session_summaries

    def build_artifact_bundle(self, ticker: str) -> tuple[str, dict[str, Any] | None]:
        """Return (formatted bundle text, primary standard analysis row)."""
        std_rows = self.fetch_latest_standard_analyses(ticker)
        if not std_rows:
            return "", None

        parts: list[str] = []

        for i, row in enumerate(std_rows):
            label = "Latest standard ticker_analysis" if i == 0 else "Prior standard ticker_analysis snapshot"
            parts.append(f"### {label} (updated {row.get('updated_at')})")
            parts.append(f"- stance: {row.get('stance')}")
            parts.append(f"- sentiment: {row.get('sentiment')} (score {row.get('sentiment_score')})")
            parts.append(f"- confidence: {row.get('confidence_score')}")
            parts.append(f"- summary: {_clip(row.get('summary'), 800)}")
            parts.append(f"- analysis_excerpt: {_clip(row.get('analysis_text'), _MAX_TEXT)}")
            parts.append(f"- reasoning_excerpt: {_clip(row.get('reasoning'), _MAX_REASON)}")
            parts.append("")

        social = self._fetch_social_snippets(ticker)
        if social:
            parts.append("### Social sentiment AI (session-level)")
            for s in social:
                themes = s.get("key_themes") or []
                th = ", ".join(themes[:8]) if isinstance(themes, list) else str(themes)
                parts.append(
                    f"- [{s.get('platform')}] {s.get('sentiment_label')} "
                    f"score={s.get('sentiment_score')} @ {s.get('analyzed_at')}"
                )
                parts.append(f"  summary: {_clip(s.get('summary'), 400)}")
                parts.append(f"  reasoning: {_clip(s.get('reasoning'), _MAX_REASON)}")
                if th:
                    parts.append(f"  themes: {th}")
            parts.append("")

        articles = self._fetch_article_snippets(ticker)
        if articles:
            parts.append("### Research articles (titles + conclusions + sentiment only)")
            for a in articles:
                parts.append(f"- {_clip(a.get('title'), 200)}")
                parts.append(
                    f"  sentiment={a.get('sentiment')} score={a.get('sentiment_score')} "
                    f"published={a.get('published_at')}"
                )
                concl = a.get("conclusion")
                if concl:
                    parts.append(f"  conclusion: {_clip(concl, 500)}")
            parts.append("")

        trade_ai, sessions = self._fetch_congress_snippets(ticker)
        if sessions:
            parts.append("### Congress session AI summaries")
            for ses in sessions:
                parts.append(
                    f"- {ses.get('politician_name')} session {ses.get('id')}: "
                    f"conflict={ses.get('conflict_score')} pattern={ses.get('risk_pattern')}"
                )
                parts.append(f"  {_clip(ses.get('ai_summary'), _MAX_TEXT)}")
            parts.append("")
        if trade_ai:
            parts.append("### Congress trade-level AI (excerpts)")
            for t in trade_ai[:6]:
                parts.append(
                    f"- trade {t.get('trade_id')}: conflict={t.get('conflict_score')} "
                    f"pattern={t.get('risk_pattern')}"
                )
                parts.append(f"  {_clip(t.get('reasoning'), _MAX_REASON)}")

        return "\n".join(parts).strip(), std_rows[0]

    def run_meta_analysis(
        self,
        ticker: str,
        requested_by: str | None = None,
        model_override: str | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        ticker_u = ticker.upper().strip()
        bundle, primary = self.build_artifact_bundle(ticker_u)
        if not primary:
            logger.warning("Meta analysis skipped for %s: no standard ticker_analysis", ticker_u)
            return None

        if not force:
            need, _ = self.needs_refresh(ticker_u)
            if not need:
                existing = self.fetch_meta_row(ticker_u)
                if existing:
                    return existing

        if not bundle:
            return None

        if not self.ollama:
            logger.error("Meta analysis requires an LLM client for %s", ticker_u)
            return None

        from ai_prompts import TICKER_META_ANALYSIS_PROMPT

        prompt = TICKER_META_ANALYSIS_PROMPT.format(ticker=ticker_u, artifact_bundle=bundle)
        try:
            from skill_loader import build_enhanced_prompt

            prompt = build_enhanced_prompt(prompt, bundle, "ticker_meta_analysis")
        except Exception as exc:
            logger.warning("Skill injection failed for meta analysis: %s", exc)

        model = self._resolve_model(model_override)
        system_prompt = (
            "You are a skeptical editor. Return ONLY valid JSON with the exact fields specified. "
            "Do not add keys."
        )
        full_response = ""
        for chunk in self.ollama.query_ollama(
            prompt=prompt,
            model=model,
            stream=True,
            system_prompt=system_prompt,
            json_mode=True,
            temperature=0.15,
        ):
            full_response += chunk

        response = extract_json(full_response)
        if not response:
            logger.error("Meta analysis JSON parse failed for %s", ticker_u)
            return None

        bundle_digest = artifact_bundle_digest(bundle)
        self._save_meta(
            ticker_u,
            primary,
            response,
            model,
            requested_by,
            bundle_digest,
        )
        return self.fetch_meta_row(ticker_u)

    def _save_meta(
        self,
        ticker: str,
        primary: dict[str, Any],
        response: dict[str, Any],
        model_used: str,
        requested_by: str | None,
        bundle_digest: str,
    ) -> None:
        src_id = primary.get("id")
        snap = primary.get("updated_at")
        if isinstance(snap, datetime) and snap.tzinfo is None:
            snap = snap.replace(tzinfo=UTC)

        contradictions = response.get("contradictions") or []
        if not isinstance(contradictions, list):
            contradictions = [str(contradictions)]

        action_items = response.get("action_items") or []
        if not isinstance(action_items, list):
            action_items = [str(action_items)]

        full_json = json.dumps(response)

        query = """
            INSERT INTO ticker_meta_analysis (
                ticker, source_analysis_id, source_analysis_snapshot_at,
                unified_conviction, confidence_adjusted, contradictions,
                what_changed_vs_last_run, action_items, narrative, full_result,
                model_used, requested_by, artifact_bundle_digest
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s::jsonb,
                %s, %s, %s, %s::jsonb,
                %s, %s, %s
            )
            ON CONFLICT (ticker) DO UPDATE SET
                source_analysis_id = EXCLUDED.source_analysis_id,
                source_analysis_snapshot_at = EXCLUDED.source_analysis_snapshot_at,
                unified_conviction = EXCLUDED.unified_conviction,
                confidence_adjusted = EXCLUDED.confidence_adjusted,
                contradictions = EXCLUDED.contradictions,
                what_changed_vs_last_run = EXCLUDED.what_changed_vs_last_run,
                action_items = EXCLUDED.action_items,
                narrative = EXCLUDED.narrative,
                full_result = EXCLUDED.full_result,
                model_used = EXCLUDED.model_used,
                requested_by = EXCLUDED.requested_by,
                artifact_bundle_digest = EXCLUDED.artifact_bundle_digest,
                updated_at = NOW()
        """

        self.postgres.execute_update(
            query,
            (
                ticker,
                str(src_id) if src_id else None,
                snap,
                (response.get("unified_conviction") or "")[:40] or None,
                response.get("confidence_adjusted"),
                json.dumps(contradictions),
                response.get("what_changed_vs_last_run"),
                action_items,
                response.get("narrative"),
                full_json,
                model_used,
                requested_by,
                bundle_digest,
            ),
        )
        logger.info("Saved ticker meta analysis for %s", ticker)
