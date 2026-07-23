"""Shared access helpers for fund-scoped watchlists with legacy fallback.

Strict mode
-----------
Set the environment variable ``WATCHLIST_STRICT=1`` to disable legacy
fallback entirely.  When strict mode is active, only ``watched_tickers_v2``
is queried and any fallback attempt is skipped.

Switch criteria (all must be true before enabling strict mode):
- v2 is populated for all required funds.
- All key endpoints tested with v2-only data.
- No fallback hits observed for a defined monitoring period.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _iso_ts(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)

WATCHLIST_V2_TABLE = "watched_tickers_v2"
WATCHLIST_LEGACY_TABLE = "watched_tickers"
VALID_PRIORITY_TIERS = frozenset({"A", "B", "C"})
MAX_BULK_TICKERS = 40

_STRICT_MODE: bool | None = None


def normalize_ticker(ticker: str) -> str:
    return (ticker or "").upper().strip()


def normalize_priority_tier(tier: str | None, *, default: str = "B") -> str:
    t = (tier or default).strip().upper()
    return t if t in VALID_PRIORITY_TIERS else default


def parse_ticker_list(raw: str | list[str] | None) -> list[str]:
    """Split pasted text or list into unique uppercase tickers (order preserved)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        import re

        parts = re.split(r"[\s,;]+", str(raw))
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        t = normalize_ticker(p)
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _is_strict_mode() -> bool:
    """Return True when legacy fallback is disabled."""
    global _STRICT_MODE
    if _STRICT_MODE is None:
        _STRICT_MODE = os.environ.get("WATCHLIST_STRICT", "").strip() in ("1", "true", "yes")
    return _STRICT_MODE


def _normalize_watchlist_rows(rows: list[dict[str, Any]], default_fund: str | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in rows:
        ticker = str(item.get("ticker") or "").upper().strip()
        if not ticker:
            continue

        fund = item.get("fund")
        if fund is None and default_fund is not None:
            fund = default_fund

        row = {
            "fund": fund,
            "ticker": ticker,
            "priority_tier": item.get("priority_tier") or "C",
            "is_active": bool(item.get("is_active", True)),
            "source": item.get("source"),
            "created_at": item.get("created_at"),
        }
        dedupe_key = (str(row.get("fund") or ""), ticker)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(row)
    return normalized


def get_active_watchlist_rows(
    supabase_client: Any,
    fund: str | None = None,
    fallback_if_empty: bool = True,
) -> list[dict[str, Any]]:
    """Return active watchlist rows using v2 table first, then legacy fallback.

    When ``WATCHLIST_STRICT=1`` is set (or *fallback_if_empty* is ``False``),
    the legacy table is never consulted.
    """
    strict = _is_strict_mode()
    effective_fallback = fallback_if_empty and not strict

    v2_rows: list[dict[str, Any]] = []
    try:
        query = supabase_client.supabase.table(WATCHLIST_V2_TABLE).select(
            "fund, ticker, priority_tier, is_active, source, created_at"
        ).eq("is_active", True)
        if fund:
            query = query.eq("fund", fund)
        v2_result = query.execute()
        v2_rows = _normalize_watchlist_rows(v2_result.data or [], default_fund=fund)
        if v2_rows or not effective_fallback:
            return v2_rows
    except Exception as e:
        logger.debug("watchlist v2 query failed (%s): %s", WATCHLIST_V2_TABLE, e)
        if strict:
            logger.warning("strict mode active — skipping legacy fallback after v2 failure")
            return []

    logger.info("watchlist fallback: v2 returned 0 rows for fund=%s, consulting legacy table", fund)

    try:
        legacy_result = supabase_client.supabase.table(WATCHLIST_LEGACY_TABLE).select(
            "ticker, priority_tier, is_active, source, created_at"
        ).eq("is_active", True).execute()
        return _normalize_watchlist_rows(legacy_result.data or [], default_fund=fund)
    except Exception as e:
        logger.warning("watchlist query failed (legacy=%s): %s", WATCHLIST_LEGACY_TABLE, e)
        return []


def get_active_watchlist_tickers(
    supabase_client: Any,
    fund: str | None = None,
    fallback_if_empty: bool = True,
) -> list[str]:
    """Return unique active tickers from watchlist rows."""
    rows = get_active_watchlist_rows(
        supabase_client=supabase_client,
        fund=fund,
        fallback_if_empty=fallback_if_empty,
    )
    return sorted({row["ticker"] for row in rows if row.get("ticker")})


def list_watchlist_for_fund(
    supabase_client: Any,
    fund: str,
    *,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    """List v2 watchlist rows for one fund (optionally including inactive)."""
    fund_s = (fund or "").strip()
    if not fund_s:
        return []
    try:
        query = supabase_client.supabase.table(WATCHLIST_V2_TABLE).select(
            "fund, ticker, priority_tier, is_active, source, created_at"
        ).eq("fund", fund_s)
        if not include_inactive:
            query = query.eq("is_active", True)
        result = query.execute()
        rows = _normalize_watchlist_rows(result.data or [], default_fund=fund_s)
        rows.sort(key=lambda r: (0 if r.get("is_active") else 1, str(r.get("ticker") or "")))
        return rows
    except Exception as exc:
        logger.warning("list_watchlist_for_fund failed fund=%s: %s", fund_s, exc)
        return []


def _batch_latest_ticker_analysis(
    postgres_client: Any, tickers: list[str]
) -> dict[str, dict[str, Any]]:
    """Latest ticker_analysis row per ticker (Research DB)."""
    if not postgres_client or not tickers:
        return {}
    try:
        rows = postgres_client.execute_query(
            """
            SELECT DISTINCT ON (ticker)
                ticker,
                analysis_date,
                updated_at,
                sentiment,
                stance,
                confidence_score,
                summary
            FROM ticker_analysis
            WHERE ticker = ANY(%s)
            ORDER BY ticker, analysis_date DESC, updated_at DESC NULLS LAST
            """,
            (tickers,),
        )
    except Exception as exc:
        logger.warning("batch ticker_analysis lookup failed: %s", exc)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        t = normalize_ticker(str(row.get("ticker") or ""))
        if not t:
            continue
        conf = row.get("confidence_score")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        summary = row.get("summary")
        summary_s = str(summary).strip() if summary else None
        if summary_s and len(summary_s) > 160:
            summary_s = summary_s[:157] + "…"
        out[t] = {
            "analyzed": True,
            "analysis_date": _iso_ts(row.get("analysis_date")),
            "analysis_updated_at": _iso_ts(row.get("updated_at")),
            "sentiment": row.get("sentiment"),
            "stance": row.get("stance"),
            "confidence_score": conf_f,
            "summary_snippet": summary_s,
        }
    return out


def _batch_ticker_meta(
    postgres_client: Any, tickers: list[str]
) -> dict[str, dict[str, Any]]:
    if not postgres_client or not tickers:
        return {}
    try:
        rows = postgres_client.execute_query(
            """
            SELECT ticker, unified_conviction, confidence_adjusted, updated_at
            FROM ticker_meta_analysis
            WHERE ticker = ANY(%s)
            """,
            (tickers,),
        )
    except Exception as exc:
        logger.warning("batch ticker_meta_analysis lookup failed: %s", exc)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        t = normalize_ticker(str(row.get("ticker") or ""))
        if not t:
            continue
        conf = row.get("confidence_adjusted")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        out[t] = {
            "has_meta": True,
            "meta_conviction": row.get("unified_conviction"),
            "meta_confidence": conf_f,
            "meta_updated_at": _iso_ts(row.get("updated_at")),
        }
    return out


def _batch_queue_status(
    supabase_client: Any, tickers: list[str]
) -> dict[str, str]:
    """Map ticker → pending|leased from ai_task_queue / legacy queue."""
    status: dict[str, str] = {}
    if not supabase_client or not tickers:
        return status
    try:
        result = (
            supabase_client.supabase.table("ai_task_queue")
            .select("target_key, status, analysis_type")
            .in_("target_key", tickers)
            .in_("analysis_type", ["ticker_analysis", "ticker_meta_analysis"])
            .in_("status", ["pending", "leased"])
            .execute()
        )
        for row in result.data or []:
            t = normalize_ticker(str(row.get("target_key") or ""))
            if not t:
                continue
            st = str(row.get("status") or "")
            # leased wins over pending
            if st == "leased" or status.get(t) != "leased":
                status[t] = st
    except Exception as exc:
        logger.warning("ai_task_queue status lookup failed: %s", exc)
    try:
        legacy = (
            supabase_client.supabase.table("ai_analysis_queue")
            .select("target_key, status")
            .eq("analysis_type", "ticker")
            .in_("target_key", tickers)
            .eq("status", "pending")
            .execute()
        )
        for row in legacy.data or []:
            t = normalize_ticker(str(row.get("target_key") or ""))
            if t and t not in status:
                status[t] = "pending"
    except Exception as exc:
        logger.warning("legacy ai_analysis_queue status lookup failed: %s", exc)
    return status


def enrich_watchlist_rows(
    rows: list[dict[str, Any]],
    *,
    supabase_client: Any = None,
    postgres_client: Any = None,
) -> list[dict[str, Any]]:
    """Attach analysis / meta / queue fields for the watchlist UI."""
    tickers = [normalize_ticker(str(r.get("ticker") or "")) for r in rows]
    tickers = [t for t in tickers if t]
    analyses = _batch_latest_ticker_analysis(postgres_client, tickers)
    metas = _batch_ticker_meta(postgres_client, tickers)
    queue = _batch_queue_status(supabase_client, tickers)
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        t = normalize_ticker(str(item.get("ticker") or ""))
        a = analyses.get(t) or {
            "analyzed": False,
            "analysis_date": None,
            "analysis_updated_at": None,
            "sentiment": None,
            "stance": None,
            "confidence_score": None,
            "summary_snippet": None,
        }
        m = metas.get(t) or {
            "has_meta": False,
            "meta_conviction": None,
            "meta_confidence": None,
            "meta_updated_at": None,
        }
        item.update(a)
        item.update(m)
        item["queue_status"] = queue.get(t)
        item["dossier_url"] = f"/ticker?ticker={t}" if t else None
        enriched.append(item)
    return enriched


def request_manual_ticker_analysis(
    supabase_client: Any,
    tickers: list[str],
    *,
    enqueued_by: str = "watchlist_ui",
    include_meta: bool = True,
) -> dict[str, Any]:
    """Enqueue ASAP ticker (+ optional meta) analysis for the given symbols.

    Writes legacy ``ai_analysis_queue`` rows (priority 1000) and modern
    ``ai_task_queue`` tasks so either worker path picks them up.
    """
    unique = parse_ticker_list(tickers)
    if not unique:
        return {"ok": False, "error": "tickers required", "enqueued": 0}
    if len(unique) > MAX_BULK_TICKERS:
        return {
            "ok": False,
            "error": f"max {MAX_BULK_TICKERS} tickers per request",
            "enqueued": 0,
        }

    legacy_added: list[str] = []
    for t in unique:
        try:
            existing = (
                supabase_client.supabase.table("ai_analysis_queue")
                .select("id")
                .eq("analysis_type", "ticker")
                .eq("target_key", t)
                .eq("status", "pending")
                .limit(1)
                .execute()
            )
            if existing.data:
                continue
            supabase_client.supabase.table("ai_analysis_queue").insert(
                {
                    "analysis_type": "ticker",
                    "target_key": t,
                    "priority": 1000,
                    "status": "pending",
                }
            ).execute()
            legacy_added.append(t)
        except Exception as exc:
            logger.warning("legacy queue insert failed for %s: %s", t, exc)

    from scheduler.ai_task_workers import (
        enqueue_ticker_analysis_tasks,
        enqueue_ticker_meta_analysis_tasks,
    )

    pairs = [(t, 1000) for t in unique]
    analysis_stats = enqueue_ticker_analysis_tasks(
        supabase_client, pairs, enqueued_by=enqueued_by
    )
    meta_stats: dict[str, int] = {"attempted": 0, "enqueued": 0, "failed": 0}
    if include_meta:
        meta_stats = enqueue_ticker_meta_analysis_tasks(
            supabase_client, pairs, enqueued_by=enqueued_by
        )
    return {
        "ok": True,
        "tickers": unique,
        "legacy_queued": legacy_added,
        "ticker_analysis": analysis_stats,
        "ticker_meta": meta_stats,
        "enqueued": int(analysis_stats.get("enqueued") or 0),
    }


def get_watchlist_status_for_fund(
    supabase_client: Any,
    *,
    fund: str | None,
    ticker: str,
) -> dict[str, Any]:
    """Fund-scoped status for ticker details (always returns a dict)."""
    ticker_u = normalize_ticker(ticker)
    fund_s = (fund or "").strip() or None
    base: dict[str, Any] = {
        "fund": fund_s,
        "ticker": ticker_u,
        "priority_tier": "B",
        "is_active": False,
        "source": None,
        "created_at": None,
        "in_watchlist": False,
    }
    if not ticker_u or not fund_s or not supabase_client:
        return base
    try:
        result = (
            supabase_client.supabase.table(WATCHLIST_V2_TABLE)
            .select("fund, ticker, priority_tier, is_active, source, created_at")
            .eq("fund", fund_s)
            .eq("ticker", ticker_u)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return base
        row = _normalize_watchlist_rows(rows, default_fund=fund_s)[0]
        active = bool(row.get("is_active"))
        return {
            "fund": fund_s,
            "ticker": ticker_u,
            "priority_tier": row.get("priority_tier") or "B",
            "is_active": active,
            "source": row.get("source"),
            "created_at": row.get("created_at"),
            "in_watchlist": active,
        }
    except Exception as exc:
        logger.warning(
            "get_watchlist_status_for_fund failed %s/%s: %s", fund_s, ticker_u, exc
        )
        return base


def upsert_watchlist_ticker(
    supabase_client: Any,
    *,
    fund: str,
    ticker: str,
    priority_tier: str = "B",
    source: str = "manual",
    is_active: bool = True,
) -> dict[str, Any]:
    """Ensure securities row exists, then upsert watched_tickers_v2.

    Caller should pass a service-role Supabase client (RLS has no user writes).

    WARNING: This upsert always writes ``source`` on conflict. That overwrites
    provenance such as ``ideas_inbox`` (Ideas Accept — used later to expire or
    audit discovery adds). Prefer ``update_watchlist_item`` for tier/active
    patches so ``source``/``created_at`` stay intact. Do not casually re-upsert
    an existing Ideas row with ``manual`` / ``watchlist_ui`` / ``bulk_paste``.
    """
    fund_s = (fund or "").strip()
    ticker_u = normalize_ticker(ticker)
    if not fund_s or not ticker_u:
        return {"ok": False, "ticker": ticker_u or ticker, "error": "fund and ticker required"}
    tier = normalize_priority_tier(priority_tier)
    try:
        try:
            from utils.ticker_utils import get_ticker_currency

            currency = get_ticker_currency(ticker_u)
        except Exception:
            currency = "USD"
        ensure = getattr(supabase_client, "ensure_ticker_in_securities", None)
        if callable(ensure):
            ok_sec = ensure(ticker_u, currency)
            if ok_sec is False:
                return {
                    "ok": False,
                    "ticker": ticker_u,
                    "error": "failed to register ticker in securities",
                }
        # WARNING: on_conflict replaces source — see docstring above.
        supabase_client.supabase.table(WATCHLIST_V2_TABLE).upsert(
            {
                "fund": fund_s,
                "ticker": ticker_u,
                "priority_tier": tier,
                "is_active": bool(is_active),
                "source": (source or "manual")[:50],
            },
            on_conflict="fund,ticker",
        ).execute()
        return {"ok": True, "ticker": ticker_u, "priority_tier": tier, "source": source}
    except Exception as exc:
        logger.warning("upsert_watchlist_ticker failed %s/%s: %s", fund_s, ticker_u, exc)
        return {"ok": False, "ticker": ticker_u, "error": str(exc)}


def update_watchlist_item(
    supabase_client: Any,
    *,
    fund: str,
    ticker: str,
    is_active: bool | None = None,
    priority_tier: str | None = None,
) -> dict[str, Any]:
    """Patch is_active and/or priority_tier for an existing (fund, ticker) row.

    Does not touch ``source`` or ``created_at`` (keeps ``ideas_inbox`` provenance).
    Only the missing-row activate fallback below upserts and may set source.
    """
    fund_s = (fund or "").strip()
    ticker_u = normalize_ticker(ticker)
    if not fund_s or not ticker_u:
        return {"ok": False, "ticker": ticker_u or ticker, "error": "fund and ticker required"}
    if is_active is None and priority_tier is None:
        return {"ok": False, "ticker": ticker_u, "error": "nothing to update"}
    patch: dict[str, Any] = {}
    if is_active is not None:
        patch["is_active"] = bool(is_active)
    if priority_tier is not None:
        patch["priority_tier"] = normalize_priority_tier(priority_tier)
    try:
        result = (
            supabase_client.supabase.table(WATCHLIST_V2_TABLE)
            .update(patch)
            .eq("fund", fund_s)
            .eq("ticker", ticker_u)
            .execute()
        )
        if not (result.data or []):
            # Row missing — upsert soft state if activating.
            # WARNING: only safe because no prior row (hence no ideas_inbox to keep).
            if is_active is True:
                return upsert_watchlist_ticker(
                    supabase_client,
                    fund=fund_s,
                    ticker=ticker_u,
                    priority_tier=patch.get("priority_tier", "B"),
                    source="watchlist_ui",
                    is_active=True,
                )
            return {"ok": False, "ticker": ticker_u, "error": "watchlist row not found"}
        return {"ok": True, "ticker": ticker_u, **patch}
    except Exception as exc:
        logger.warning("update_watchlist_item failed %s/%s: %s", fund_s, ticker_u, exc)
        return {"ok": False, "ticker": ticker_u, "error": str(exc)}


def set_watchlist_active(
    supabase_client: Any,
    *,
    fund: str,
    ticker: str,
    is_active: bool,
) -> dict[str, Any]:
    return update_watchlist_item(
        supabase_client, fund=fund, ticker=ticker, is_active=is_active
    )


def upsert_watchlist_tickers_bulk(
    supabase_client: Any,
    *,
    fund: str,
    tickers: list[str],
    priority_tier: str = "B",
    source: str = "bulk_paste",
) -> dict[str, Any]:
    """Upsert many tickers; returns results map and failed list.

    WARNING: each ticker goes through ``upsert_watchlist_ticker``, which overwrites
    ``source`` on conflict (including ``ideas_inbox``). Do not bulk-paste over
    Ideas-accepted names if you still need that provenance for expiry.
    """
    parsed = parse_ticker_list(tickers)[:MAX_BULK_TICKERS]
    results: dict[str, str] = {}
    for t in parsed:
        outcome = upsert_watchlist_ticker(
            supabase_client,
            fund=fund,
            ticker=t,
            priority_tier=priority_tier,
            source=source,
            is_active=True,
        )
        results[t] = "added" if outcome.get("ok") else "failed"
    failed = sorted(t for t, r in results.items() if r != "added")
    return {
        "ok": not failed,
        "results": results,
        "failed_tickers": failed,
        "added_count": sum(1 for r in results.values() if r == "added"),
    }
