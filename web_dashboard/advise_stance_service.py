"""Nightly Today advise_pack → stance_history ledger (ROADMAP §2.8 Z3).

WHY THIS EXISTS
---------------
Every surface that makes a directional claim must be scored automatically.
Today's ranked buy/sell candidate pack (advise_pack, built by advise_service.rank_candidate_pack
inside today_briefing_service.build_today_briefing) is displayed to users daily, but was never
written to stance_history, so nobody knew if it helped.

This nightly job captures the advise_pack recommendations without requiring a user to open
the Today screen. Outcome scoring (jobs_stance_outcomes.py) grades it forward at 3d, 7d, 14d,
30d horizons.

DESIGN DECISIONS
----------------
* State dedupe, NOT event dedupe. A ticker that remains BUY for five consecutive days is one call;
  a flip (e.g. BUY -> SELL or score drift) is recorded as a new row.
* Action to stance mapping:
  - BUY / ADD / ACCUMULATE -> BULLISH
  - SELL / TRIM / EXIT / REDUCE -> BEARISH
  - RISK / WATCH / HOLD / other -> recorded as-is (non-directional; ledger keeps it, scoring ignores it)
* confidence is left NULL on the row: the rank score drifts nightly and state dedupe compares
  confidence, so storing it would re-record an unchanged BUY every night (heavily overlapping
  "calls"). The normalised score lives in metadata.score instead.
* Metadata preserves: advise_source ("advise" | "signal_fallback"), rank (1-indexed), raw action,
  score and up to 3 reason tags.
* Funds: only fund=None ("all funds", Today's default). Per-fund packs overlap it heavily and
  would double-count calls; per-fund SELLs on held names are already scored via
  action_queue_ai_review. get_supported_funds() is kept for callers that want per-fund runs.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from stance_history import record_stance_safe
from today_briefing_service import build_advise_pack

logger = logging.getLogger(__name__)

SOURCE = "advise_pack"
DEFAULT_LIMIT = 12

DIRECTIONAL_ACTION_MAP: dict[str, str] = {
    "BUY": "BULLISH",
    "ADD": "BULLISH",
    "ACCUMULATE": "BULLISH",
    "SELL": "BEARISH",
    "TRIM": "BEARISH",
    "EXIT": "BEARISH",
    "REDUCE": "BEARISH",
}


def map_action_to_stance(action: str) -> str:
    """Map a raw recommendation/queue action to a stance string.

    BUY/ADD/ACCUMULATE -> BULLISH
    SELL/TRIM/EXIT/REDUCE -> BEARISH
    RISK/WATCH/HOLD/other -> record as-is (non-directional)
    """
    act = (action or "").strip().upper()
    if not act:
        return ""
    return DIRECTIONAL_ACTION_MAP.get(act, act)


def normalize_score_to_confidence(val: Any) -> float | None:
    """Normalise a row's numeric score or confidence to a 0.0..1.0 float."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f < 0.0:
        return 0.0
    if f <= 1.0:
        return round(f, 4)
    if f <= 10.0:
        return round(f / 10.0, 4)
    if f <= 100.0:
        return round(f / 100.0, 4)
    return 1.0


def _extract_row_action(row: dict[str, Any]) -> str:
    raw = row.get("action") or row.get("advise") or row.get("queue_action") or ""
    return str(raw).strip().upper()


def _extract_row_confidence(row: dict[str, Any]) -> float | None:
    # Prefer explicit confidence; fall back to score
    val = row.get("confidence")
    if val is None:
        val = row.get("score")
    return normalize_score_to_confidence(val)


def _extract_row_reasons(row: dict[str, Any]) -> list[str]:
    reasons_val = row.get("reasons")
    if isinstance(reasons_val, list):
        return [str(r).strip() for r in reasons_val if str(r).strip()][:3]
    if isinstance(reasons_val, str) and reasons_val.strip():
        return [reasons_val.strip()][:3]
    reason_single = row.get("reason")
    if reason_single and str(reason_single).strip():
        return [str(reason_single).strip()][:3]
    return []


def get_supported_funds(supabase_client: Any) -> list[str | None]:
    """Enumerate production funds supported by Today, plus None ('all' funds).

    Today defaults to fund=None ('all funds') when no specific fund is selected in the UI.
    Production funds are retrieved from the funds table where is_production=True, falling back
    to get_available_funds().
    """
    funds: list[str | None] = [None]
    try:
        res = (
            supabase_client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
        )
        names = [r["name"] for r in (res.data or []) if r.get("name")]
        if not names and hasattr(supabase_client, "get_available_funds"):
            names = supabase_client.get_available_funds() or []
        for n in names:
            if n not in funds:
                funds.append(n)
    except Exception as exc:
        logger.warning(
            "get_supported_funds: error retrieving production funds (%s); defaulting to [None, 'Project Chimera']",
            exc,
        )
        if "Project Chimera" not in funds:
            funds.append("Project Chimera")
    return funds


def record_advise_pack_stances(
    postgres: Any,
    supabase_client: Any,
    *,
    funds: Sequence[str | None] | None = None,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
    skip_nondirectional: bool = False,
) -> dict[str, int]:
    """Capture Today's advise_pack recommendations into stance_history.

    Returns stats dict:
        {"funds": ..., "rows_seen": ..., "written": ..., "skipped_nondirectional": ..., "errors": ...}
    """
    stats: dict[str, int] = {
        "funds": 0,
        "rows_seen": 0,
        "written": 0,
        "skipped_nondirectional": 0,
        "errors": 0,
    }

    fund_list = list(funds) if funds is not None else [None]

    for fund in fund_list:
        try:
            pack, advise_source = build_advise_pack(
                postgres,
                supabase_client,
                fund=fund,
                limit=limit,
            )
        except Exception as exc:
            logger.warning(
                "record_advise_pack_stances: build_advise_pack failed for fund=%s: %s",
                fund,
                exc,
                exc_info=True,
            )
            stats["errors"] += 1
            continue

        stats["funds"] += 1
        for i, row in enumerate(pack or [], start=1):
            stats["rows_seen"] += 1
            ticker = str(row.get("ticker") or "").upper().strip()
            if not ticker:
                continue

            raw_action = _extract_row_action(row)
            if not raw_action:
                continue

            stance = map_action_to_stance(raw_action)
            is_directional = stance in {"BULLISH", "BEARISH"}
            if not is_directional and skip_nondirectional:
                stats["skipped_nondirectional"] += 1
                continue

            confidence = _extract_row_confidence(row)
            reasons = _extract_row_reasons(row)

            if dry_run:
                continue

            inserted = record_stance_safe(
                postgres,
                ticker=ticker,
                source=SOURCE,
                stance=stance,
                confidence=None,
                fund_key=fund or "",
                metadata={
                    "advise_source": advise_source,
                    "rank": i,
                    "action": raw_action,
                    "score": confidence,
                    "reasons": reasons,
                },
                dedupe_on_source_ref=False,
            )
            if inserted:
                stats["written"] += 1

    return stats
