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

from market_regime_normalization import normalize_market_regime
from ollama_client import OllamaClient, collect_with_summary_model_chain
from postgres_client import PostgresClient
from settings import (
    get_summarizing_model,
    is_meta_analysis_phase1_signal_fusion_enabled,
    is_meta_analysis_phase3_sector_enabled,
)
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
        return get_summarizing_model("meta_analysis")

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

    def _fetch_signal_snapshot(self, ticker: str) -> dict[str, Any] | None:
        """Fetch the latest technical signal snapshot for ticker (if any)."""
        try:
            res = (
                self.supabase.supabase.table("signal_analysis")
                .select(
                    "analysis_date, overall_signal, confidence_score, "
                    "structure_signal, timing_signal, fear_risk_signal, momentum_signal, fundamental_signal"
                )
                .eq("ticker", ticker)
                .order("analysis_date", desc=True)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as exc:
            logger.debug("Signal snapshot fetch failed for %s: %s", ticker, exc)
            return None

    def _fetch_market_brief_snippet(self) -> dict[str, Any] | None:
        """Fetch the latest market regime brief for global context."""
        rows = self.postgres.execute_query(
            """
            SELECT brief_date, headline, narrative, regime_json, updated_at
            FROM market_daily_brief
            ORDER BY brief_date DESC
            LIMIT 1
            """
        )
        return rows[0] if rows else None

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

    def _fetch_ticker_sector(self, ticker: str) -> str | None:
        """GICS-style sector from Supabase ``securities`` (same source as ticker UI)."""
        try:
            result = (
                self.supabase.supabase.table("securities")
                .select("sector")
                .eq("ticker", ticker.upper())
                .limit(1)
                .execute()
            )
            if result.data:
                raw = result.data[0].get("sector")
                label = str(raw).strip() if raw is not None else ""
                return label or None
        except Exception as exc:
            logger.debug("Sector lookup failed for %s: %s", ticker, exc)
        return None

    def _fetch_sector_meta_prior(self, sector_label: str) -> dict[str, Any] | None:
        """Latest ``sector_meta_analysis`` row for a sector label (Phase 3b)."""
        try:
            rows = self.postgres.execute_query(
                """
                SELECT sector, run_date, sector_stance, momentum_state, news_pressure,
                       rotation_rank, confidence, key_drivers, risk_flags, as_of, updated_at
                FROM sector_meta_analysis
                WHERE TRIM(sector) = %s
                ORDER BY run_date DESC NULLS LAST, updated_at DESC NULLS LAST
                LIMIT 1
                """,
                (sector_label.strip(),),
            )
            return rows[0] if rows else None
        except Exception as exc:
            logger.debug("sector_meta fetch failed for %s: %s", sector_label, exc)
            return None

    def _append_sector_prior_block(self, parts: list[str], ticker: str) -> None:
        """Add ETF-flow sector synthesis prior when Phase 3c is enabled."""
        parts.append("### Sector rotation prior (ETF flow synthesis)")
        sector_label = self._fetch_ticker_sector(ticker)
        if not sector_label:
            parts.append("- mapped_sector: MISSING (no sector on securities row)")
            parts.append("- sector_meta: unavailable")
            parts.append("")
            return

        parts.append(f"- mapped_sector: {sector_label}")
        row = self._fetch_sector_meta_prior(sector_label)
        if not row:
            parts.append("- sector_meta: MISSING (no sector_meta_analysis row for mapped_sector)")
            parts.append("")
            return

        drivers = row.get("key_drivers") or []
        if isinstance(drivers, str):
            try:
                drivers = json.loads(drivers)
            except (json.JSONDecodeError, TypeError):
                drivers = [drivers]
        risks = row.get("risk_flags") or []
        if isinstance(risks, str):
            try:
                risks = json.loads(risks)
            except (json.JSONDecodeError, TypeError):
                risks = [risks]
        driver_txt = ", ".join(_clip(str(d), 120) for d in drivers[:5] if str(d).strip())
        risk_txt = ", ".join(_clip(str(r), 120) for r in risks[:4] if str(r).strip())
        conf = row.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else 0.0
        except (TypeError, ValueError):
            conf_f = 0.0
        parts.append(
            f"- run_date: {row.get('run_date')} | row_updated_at: {row.get('updated_at')} | "
            f"as_of: {row.get('as_of')}"
        )
        parts.append(
            f"- sector_stance: {row.get('sector_stance')} | momentum_state: {row.get('momentum_state')} | "
            f"news_pressure: {row.get('news_pressure')}"
        )
        parts.append(f"- rotation_rank: {row.get('rotation_rank')} | confidence: {conf_f:.2f}")
        if driver_txt:
            parts.append(f"- key_drivers: {_clip(driver_txt, 320)}")
        if risk_txt:
            parts.append(f"- risk_flags: {_clip(risk_txt, 240)}")
        parts.append(
            "- usage: calibrate ticker stance vs institutional sector rotation; "
            "do not treat as ticker-specific catalyst"
        )
        parts.append("")

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

        if is_meta_analysis_phase1_signal_fusion_enabled():
            signal = self._fetch_signal_snapshot(ticker)
            if signal:
                structure = signal.get("structure_signal") or {}
                timing = signal.get("timing_signal") or {}
                fear = signal.get("fear_risk_signal") or {}
                momentum = signal.get("momentum_signal") or {}
                fundamental = signal.get("fundamental_signal") or {}
                parts.append("### Technical signal snapshot (latest)")
                parts.append(f"- analysis_date: {signal.get('analysis_date')}")
                parts.append(
                    f"- overall_signal: {signal.get('overall_signal')} "
                    f"(confidence={signal.get('confidence_score')})"
                )
                parts.append(
                    f"- trend: {structure.get('trend')} | timing: {timing.get('timing')} "
                    f"| fear_level: {fear.get('fear_level')}"
                )
                parts.append(
                    f"- momentum_bias: {momentum.get('bias')} | momentum_score: {momentum.get('composite_score')}"
                )
                parts.append(
                    f"- fundamental_bias: {fundamental.get('bias')} | "
                    f"fundamental_score: {fundamental.get('composite_score')}"
                )
                parts.append("")
            else:
                parts.append("### Technical signal snapshot (latest)")
                parts.append("- signal_data: MISSING")
                parts.append("")

            market_brief = self._fetch_market_brief_snippet()
            if market_brief:
                regime_raw = market_brief.get("regime_json") or {}
                if isinstance(regime_raw, str):
                    try:
                        regime_raw = json.loads(regime_raw)
                    except (json.JSONDecodeError, TypeError):
                        regime_raw = {}
                elif not isinstance(regime_raw, dict):
                    regime_raw = {}
                canon = normalize_market_regime(
                    regime_raw,
                    brief_date=market_brief.get("brief_date"),
                    updated_at=market_brief.get("updated_at"),
                )
                caveats_lines = canon.get("caveats") or []
                caveat_txt = ", ".join(
                    _clip(str(c), 140) for c in caveats_lines[:4] if str(c).strip()
                )
                themes_txt = ", ".join(
                    _clip(str(t), 140)
                    for t in (canon.get("macro_themes") or [])[:8]
                    if str(t).strip()
                )
                rc = canon.get("regime_confidence")
                try:
                    conf_f = float(rc) if rc is not None else 0.0
                except (TypeError, ValueError):
                    conf_f = 0.0
                conf_txt = f"{conf_f:.2f}"
                parts.append("### Latest market regime context")
                parts.append(
                    f"- brief_date: {market_brief.get('brief_date')} | row_updated_at: "
                    f"{market_brief.get('updated_at')} | regime_as_of: {canon.get('as_of')}"
                )
                parts.append(f"- headline: {_clip(market_brief.get('headline'), 180)}")
                parts.append(
                    f"- risk_regime: {canon.get('risk_regime')} "
                    f"(regime_confidence={conf_txt})"
                )
                parts.append(
                    f"- breadth_proxy: {canon.get('breadth_proxy')} | "
                    f"volatility_state: {canon.get('volatility_state')}"
                )
                if themes_txt:
                    parts.append(f"- macro_themes: {_clip(themes_txt, 280)}")
                ln = canon.get("leadership_note") or ""
                parts.append(f"- leadership_note: {_clip(ln, 180)}")
                if caveat_txt:
                    parts.append(f"- caveats: {_clip(caveat_txt, 240)}")
                parts.append(f"- narrative: {_clip(market_brief.get('narrative'), 600)}")
                parts.append("")

        if is_meta_analysis_phase3_sector_enabled():
            self._append_sector_prior_block(parts, ticker)

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

        from ai_prompts import TICKER_META_ANALYSIS_PROMPT, TICKER_META_ANALYSIS_PROMPT_LEGACY

        tmpl = (
            TICKER_META_ANALYSIS_PROMPT
            if is_meta_analysis_phase1_signal_fusion_enabled()
            else TICKER_META_ANALYSIS_PROMPT_LEGACY
        )
        prompt = tmpl.format(ticker=ticker_u, artifact_bundle=bundle)
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
        full_response, model = collect_with_summary_model_chain(
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
            logger.error("Meta analysis LLM failed on all summarization models for %s", ticker_u)
            return None

        response = extract_json(full_response)
        if not response:
            logger.error("Meta analysis JSON parse failed for %s", ticker_u)
            return None

        contradictions = response.get("contradictions") or []
        if not isinstance(contradictions, list):
            contradictions = [str(contradictions)]
        risk_flags = response.get("risk_flags") or []
        if not isinstance(risk_flags, list):
            risk_flags = [str(risk_flags)]
        logger.info(
            "Meta synthesis for %s: stance=%s confidence=%s contradictions=%s risk_flags=%s",
            ticker_u,
            response.get("stance") or response.get("unified_conviction"),
            response.get("confidence") if response.get("confidence") is not None else response.get("confidence_adjusted"),
            len(contradictions),
            len(risk_flags),
        )

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
                (
                    response.get("unified_conviction")
                    or response.get("stance")
                    or "INSUFFICIENT_DATA"
                )[:40] or None,
                (
                    response.get("confidence_adjusted")
                    if response.get("confidence_adjusted") is not None
                    else response.get("confidence")
                ),
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
