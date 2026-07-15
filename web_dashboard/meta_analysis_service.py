#!/usr/bin/env python3
"""
Per-ticker meta analysis: second LLM pass over stored analysis artifacts only.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import datetime, UTC
from typing import Any

from market_regime_normalization import normalize_market_regime
from ollama_client import OllamaClient, collect_with_summary_model_chain
from postgres_client import PostgresClient
from settings import (
    get_meta_analysis_human_thesis_scope,
    get_summarizing_model,
    is_meta_analysis_human_thesis_enabled,
    is_meta_analysis_phase1_signal_fusion_enabled,
    is_meta_analysis_phase3_sector_enabled,
    is_meta_analysis_phase_h2_enabled,
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


def _extract_ticker_meta_audit_fields(raw_response: str) -> dict:
    """Extract stance + horizon for the AI Audit row.

    Used as ``extract_audit_fields`` for ``collect_with_summary_model_chain``
    so successful ticker_meta_analysis attempts surface their stance in
    ``/admin/ai-audit`` (closest analogue to the ``sentiment`` column).
    """
    fields: dict = {}
    try:
        parsed = extract_json(raw_response or "")
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        stance = parsed.get("stance")
        if stance:
            fields["sentiment"] = str(stance)
    return fields


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
        self._held_tickers_cache: set[str] | None = None
        self._insider_clusters_cache: list[dict[str, Any]] | None = None
        self._track_record_cache: dict[str, Any] | None = None
        self._track_record_cache_tried = False

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

    def fetch_standard_ticker_candidates(self, limit: int = 250) -> list[str]:
        """Latest standard-analysis tickers that can feed meta synthesis.

        This intentionally does not reuse ``TickerAnalysisService.get_tickers_to_analyze``:
        that selector filters out tickers analyzed within 24 hours, which is exactly
        the fresh standard analysis output this meta pass should consume.
        """
        rows = self.postgres.execute_query(
            """
            SELECT ticker
            FROM (
                SELECT DISTINCT ON (ticker)
                       ticker, updated_at, analysis_date
                FROM ticker_analysis
                WHERE analysis_type = 'standard'
                  AND ticker IS NOT NULL
                ORDER BY ticker, updated_at DESC NULLS LAST, analysis_date DESC NULLS LAST
            ) latest
            ORDER BY updated_at DESC NULLS LAST, analysis_date DESC NULLS LAST, ticker
            LIMIT %s
            """,
            (limit,),
        )
        tickers: list[str] = []
        seen: set[str] = set()
        for row in rows or []:
            ticker = str(row.get("ticker") or "").upper().strip()
            if ticker and ticker not in seen:
                tickers.append(ticker)
                seen.add(ticker)
        return tickers

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
            SELECT id, title, conclusion, sentiment, sentiment_score, published_at, fetched_at
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
        """Return (formatted bundle text, primary standard analysis row).

        Back-compat 2-tuple wrapper. Use build_artifact_bundle_with_evidence when
        you need the evidence manifest (G1 stance provenance).
        """
        bundle, primary, _evidence = self.build_artifact_bundle_with_evidence(ticker)
        return bundle, primary

    def build_artifact_bundle_with_evidence(
        self, ticker: str
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
        """Return (bundle text, primary standard analysis row, evidence manifest).

        The manifest records which artifact families fed the bundle and the
        research article IDs included, so stances written from this bundle are
        attributable (G1 provenance). Families with no data are omitted.
        """
        evidence: dict[str, Any] = {"article_ids": [], "artifact_types": []}
        std_rows = self.fetch_latest_standard_analyses(ticker)
        if not std_rows:
            return "", None, evidence

        families: list[str] = ["standard_analysis"]
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
                families.append("signals")
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
                families.append("market_regime")
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
            _before_sector = len(parts)
            self._append_sector_prior_block(parts, ticker)
            if len(parts) > _before_sector:
                families.append("sector_prior")

        social = self._fetch_social_snippets(ticker)
        if social:
            families.append("social")
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
            families.append("articles")
            parts.append("### Research articles (titles + conclusions + sentiment only)")
            for a in articles:
                aid = a.get("id")
                if aid is not None:
                    evidence["article_ids"].append(str(aid))
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
        if sessions or trade_ai:
            families.append("congress")
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

        if is_meta_analysis_phase_h2_enabled():
            for family, block in (
                ("insider_cluster", self._fetch_insider_cluster_block(ticker)),
                ("dilution", self._fetch_dilution_block(ticker)),
                ("filing", self._fetch_filing_block(ticker)),
                ("confluence", self._fetch_confluence_block(ticker)),
                ("prior_stance", self._fetch_prior_stance_block(ticker)),
            ):
                if block:
                    families.append(family)
                    parts.append("")
                    parts.append(block)

        if self._should_include_human_thesis(ticker):
            thesis_block = self._fetch_human_thesis_block(ticker)
            if thesis_block:
                families.append("human_thesis")
                parts.append("")
                parts.append(thesis_block)

        evidence["artifact_types"] = families
        return "\n".join(parts).strip(), std_rows[0], evidence

    def _production_held_tickers(self) -> set[str]:
        """Cached set of tickers held across production funds (best-effort)."""
        if self._held_tickers_cache is not None:
            return self._held_tickers_cache
        held: set[str] = set()
        try:
            funds_res = (
                self.supabase.supabase.table("funds")
                .select("name")
                .eq("is_production", True)
                .execute()
            )
            fund_names = [r["name"] for r in (funds_res.data or []) if r.get("name")]
            if not fund_names:
                funds_res = (
                    self.supabase.supabase.table("funds").select("name").limit(5).execute()
                )
                fund_names = [r["name"] for r in (funds_res.data or []) if r.get("name")]
            for fund in fund_names:
                try:
                    for pos in self.supabase.get_current_positions(fund) or []:
                        t = str(pos.get("ticker") or pos.get("symbol") or "").upper().strip()
                        if t:
                            held.add(t)
                except Exception as pos_exc:
                    logger.debug("human_thesis holdings skip fund %s: %s", fund, pos_exc)
        except Exception as exc:
            logger.warning("human_thesis holdings lookup failed: %s", exc)
        self._held_tickers_cache = held
        return held

    def _should_include_human_thesis(self, ticker: str) -> bool:
        if not is_meta_analysis_human_thesis_enabled():
            return False
        scope = get_meta_analysis_human_thesis_scope()
        if scope == "all":
            return True
        ticker_u = ticker.upper().strip()
        held = self._production_held_tickers()
        if ticker_u in held:
            return True
        if scope == "holdings_or_recent":
            try:
                from user_insights_service import ticker_has_recent_active_thesis

                return ticker_has_recent_active_thesis(self.postgres, ticker_u)
            except Exception as exc:
                logger.debug("human_thesis recent check failed for %s: %s", ticker_u, exc)
                return False
        # default: holdings only
        return False

    def _fetch_human_thesis_block(self, ticker: str) -> str | None:
        try:
            from user_insights_service import format_human_theses_for_meta_bundle

            return format_human_theses_for_meta_bundle(self.postgres, ticker)
        except Exception as exc:
            logger.warning("human_thesis bundle fetch failed for %s: %s", ticker, exc)
            return None

    def _cached_insider_clusters(self) -> list[dict[str, Any]]:
        if self._insider_clusters_cache is not None:
            return self._insider_clusters_cache
        try:
            from insider_clusters_service import build_insider_cluster_buys

            self._insider_clusters_cache = build_insider_cluster_buys(
                self.supabase, days=30, min_insiders=3, limit=50
            )
        except Exception as exc:
            logger.warning("insider cluster cache build failed: %s", exc)
            self._insider_clusters_cache = []
        return self._insider_clusters_cache

    def _cached_track_record_summary(self) -> dict[str, Any] | None:
        if self._track_record_cache_tried:
            return self._track_record_cache
        self._track_record_cache_tried = True
        try:
            from track_record_service import build_track_record_summary

            summary = build_track_record_summary(self.postgres, horizon_days=30)
            total = int(summary.get("total_scored") or 0)
            if total <= 0:
                summary = build_track_record_summary(self.postgres, horizon_days=7)
            self._track_record_cache = summary
        except Exception as exc:
            logger.warning("track record cache for meta H2 failed: %s", exc)
            self._track_record_cache = None
        return self._track_record_cache

    def _fetch_insider_cluster_block(self, ticker: str) -> str | None:
        ticker_u = ticker.upper().strip()
        try:
            matches = [
                c
                for c in self._cached_insider_clusters()
                if str(c.get("ticker") or "").upper() == ticker_u
            ][:3]
            if not matches:
                return None
            lines = ["### Insider cluster buys"]
            for c in matches:
                names = [
                    str(i.get("name") or "").strip()
                    for i in (c.get("insiders") or [])[:5]
                    if i.get("name")
                ]
                name_s = ", ".join(names) if names else "n/a"
                lines.append(
                    f"- {c.get('insider_count')} distinct insiders / "
                    f"{c.get('buy_count')} buys; latest={c.get('latest_buy')}; "
                    f"held={c.get('held')} watched={c.get('watched')}"
                )
                lines.append(f"  insiders: {name_s}")
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("insider_cluster bundle fetch failed for %s: %s", ticker_u, exc)
            return None

    def _fetch_dilution_block(self, ticker: str) -> str | None:
        ticker_u = ticker.upper().strip()
        try:
            from dilution_service import fetch_recent_dilution_flags

            rows = fetch_recent_dilution_flags(
                self.postgres, tickers=[ticker_u], days=45, limit=5
            )
            if not rows:
                return None
            lines = ["### Dilution / shares-outstanding flags"]
            for r in rows[:5]:
                lines.append(
                    f"- window={r.get('window_days')}d pct_change={r.get('pct_change')}% "
                    f"shares {r.get('shares_start')} → {r.get('shares_end')} "
                    f"as_of={r.get('as_of')}"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("dilution bundle fetch failed for %s: %s", ticker_u, exc)
            return None

    def _fetch_filing_block(self, ticker: str) -> str | None:
        ticker_u = ticker.upper().strip()
        try:
            from sec_filings_service import fetch_recent_filing_alerts

            rows = fetch_recent_filing_alerts(
                self.postgres, tickers=[ticker_u], days=14, limit=6
            )
            if not rows:
                return None
            lines = ["### SEC filing-risk alerts"]
            for r in rows[:6]:
                lines.append(
                    f"- {r.get('form_type')} category={r.get('category')} "
                    f"direction={r.get('direction')} filed_at={r.get('filed_at')}"
                )
                title = r.get("title")
                if title:
                    lines.append(f"  {_clip(str(title), 200)}")
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("filing bundle fetch failed for %s: %s", ticker_u, exc)
            return None

    def _fetch_confluence_block(self, ticker: str) -> str | None:
        ticker_u = ticker.upper().strip()
        try:
            from confluence_service import fetch_recent_confluence_events

            rows = fetch_recent_confluence_events(
                self.postgres, tickers=[ticker_u], days=7, limit=5
            )
            if not rows:
                return None
            lines = ["### Confluence events"]
            for r in rows[:5]:
                families = r.get("families") or []
                if isinstance(families, list):
                    fam_s = ", ".join(str(f) for f in families[:8])
                else:
                    fam_s = str(families)
                lines.append(
                    f"- score={r.get('score')} direction={r.get('direction')} "
                    f"as_of={r.get('as_of')} families=[{fam_s}]"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("confluence bundle fetch failed for %s: %s", ticker_u, exc)
            return None

    def _fetch_prior_stance_block(self, ticker: str) -> str | None:
        ticker_u = ticker.upper().strip()
        try:
            from stance_history import format_prior_stance_for_meta_bundle

            return format_prior_stance_for_meta_bundle(
                self.postgres,
                ticker_u,
                track_summary=self._cached_track_record_summary(),
            )
        except Exception as exc:
            logger.warning("prior_stance bundle fetch failed for %s: %s", ticker_u, exc)
            return None

    def run_meta_analysis(
        self,
        ticker: str,
        requested_by: str | None = None,
        model_override: str | None = None,
        force: bool = False,
        model_chain_override: Sequence[str] | None = None,
    ) -> dict[str, Any] | None:
        ticker_u = ticker.upper().strip()
        bundle, primary, evidence = self.build_artifact_bundle_with_evidence(ticker_u)
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
            function_name="ticker_meta_analysis",
            audit_extra={"tickers_extracted": [ticker_u]},
            extract_audit_fields=_extract_ticker_meta_audit_fields,
            model_chain_override=model_chain_override,
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
            evidence=evidence,
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
        evidence: dict[str, Any] | None = None,
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

        stance_value = (
            response.get("unified_conviction")
            or response.get("stance")
            or "INSUFFICIENT_DATA"
        )[:40] or None
        confidence_value = (
            response.get("confidence_adjusted")
            if response.get("confidence_adjusted") is not None
            else response.get("confidence")
        )

        self.postgres.execute_update(
            query,
            (
                ticker,
                str(src_id) if src_id else None,
                snap,
                stance_value,
                confidence_value,
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

        try:
            from stance_history import record_stance_safe

            stance_metadata: dict[str, Any] = {
                "contradictions_count": len(contradictions),
                "artifact_bundle_digest": bundle_digest,
            }
            if evidence:
                stance_metadata["evidence"] = evidence

            record_stance_safe(
                self.postgres,
                ticker=ticker,
                source="ticker_meta_analysis",
                stance=stance_value,
                confidence=confidence_value,
                drivers=action_items if action_items else None,
                model_used=model_used,
                requested_by=requested_by,
                source_ref_id=str(src_id) if src_id else None,
                metadata=stance_metadata,
            )
        except Exception as ledger_exc:
            logger.warning("stance_history hook failed for %s: %s", ticker, ledger_exc)
