"""Advise v0 — ranked buy/sell suggestions from existing artifacts (no LLM).

Merges Action Queue rows, queue AI review verdicts, and Insights thesis
attention into one ranked list. Does not place trades.
"""

from __future__ import annotations

from typing import Any

# Lower = more urgent when sorting by (priority, -score)
_ADVISE_PRIORITY = {
    "SELL": 0,
    "RISK": 1,
    "BUY": 2,
    "WATCH": 3,
    "MONITOR": 4,
}

_BEARISH_META = frozenset(
    {"BEARISH", "STRONG_BEARISH", "VERY_BEARISH", "AVOID", "SELL"}
)
_BULLISH_META = frozenset(
    {"BULLISH", "STRONG_BULLISH", "VERY_BULLISH", "BUY"}
)


def disposition_to_advise(disposition: str | None, intent: str | None) -> str:
    """Map Insights axes to a coarse advise action."""
    d = (disposition or "").strip().lower()
    i = (intent or "").strip().lower()
    if i == "seek_exit" or d == "bearish":
        return "SELL"
    if i == "seek_entry" or d == "bullish":
        return "BUY"
    return "WATCH"


def _conf(val: Any) -> float:
    try:
        return max(0.0, min(1.0, float(val)))
    except (TypeError, ValueError):
        return 0.0


def _parse_thesis_suggested(row: dict[str, Any]) -> tuple[str | None, str | None]:
    meta = row.get("llm_metadata") or row.get("metadata") or {}
    if isinstance(meta, str):
        import json

        try:
            meta = json.loads(meta)
        except (TypeError, ValueError, json.JSONDecodeError):
            meta = {}
    if not isinstance(meta, dict):
        return None, None
    disp = meta.get("suggested_disposition") or meta.get("prior_disposition")
    intent = meta.get("suggested_intent") or meta.get("prior_intent")
    return (
        str(disp).strip().lower() if disp else None,
        str(intent).strip().lower() if intent else None,
    )


def _meta_conflicts_with_action(action: str, meta_conviction: str | None) -> bool:
    if not meta_conviction:
        return False
    m = meta_conviction.strip().upper()
    a = action.strip().upper()
    if a in ("BUY", "WATCH") and m in _BEARISH_META:
        return True
    if a in ("SELL", "RISK") and m in _BULLISH_META:
        return True
    return False


def build_advise_recommendations(
    *,
    action_queue: list[dict[str, Any]] | None = None,
    theses_attention: list[dict[str, Any]] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Rank tickers the system would nudge a human to BUY / SELL / RISK / WATCH.

    Pure merge of already-computed queue + Insights attention. No LLM, no DB.
    """
    by_ticker: dict[str, dict[str, Any]] = {}

    for item in action_queue or []:
        ticker = str(item.get("ticker") or "").upper().strip()
        action = str(item.get("action") or "").upper().strip()
        if not ticker or action not in _ADVISE_PRIORITY:
            continue
        conf = _conf(item.get("confidence") or item.get("confidence_score"))
        score = 40.0 + 25.0 * conf
        if action == "SELL":
            score += 15.0
        elif action == "RISK":
            score += 10.0
        elif action == "BUY":
            score += 8.0

        ai = item.get("ai_review") if isinstance(item.get("ai_review"), dict) else {}
        queue_verdict = str(ai.get("verdict") or "").upper()
        reasons = [f"queue:{action}"]
        if queue_verdict:
            reasons.append(f"queue_ai:{queue_verdict}")
            if queue_verdict == "TENSION":
                score += 18.0
            elif queue_verdict == "STALE":
                score += 10.0
            elif queue_verdict == "ALIGNED":
                score += 4.0

        rc = item.get("research_context") if isinstance(item.get("research_context"), dict) else {}
        meta_c = rc.get("meta_conviction")
        if meta_c:
            reasons.append(f"meta:{meta_c}")
            if _meta_conflicts_with_action(action, str(meta_c)):
                score += 12.0
                reasons.append("meta_conflict")

        by_ticker[ticker] = {
            "ticker": ticker,
            "advise": action,
            "score": round(score, 1),
            "reasons": reasons,
            "queue_action": action,
            "queue_verdict": queue_verdict or None,
            "thesis_verdict": None,
            "thesis_id": None,
            "dual_tension": False,
            "meta_conviction": meta_c,
            "confidence": conf or None,
        }

    for row in theses_attention or []:
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        reasons_in = {str(x).lower() for x in (row.get("attention_reasons") or [])}
        verdict = str(row.get("llm_verdict") or "").upper()
        sug_disp, sug_intent = _parse_thesis_suggested(row)
        disp = sug_disp or str(row.get("disposition") or "").lower() or None
        intent = sug_intent or str(row.get("intent") or "").lower() or None
        thesis_advise = disposition_to_advise(disp, intent)

        score_delta = 8.0
        reason_bits = [f"thesis:{thesis_advise}"]
        if verdict == "TENSION" or "tension" in reasons_in:
            score_delta += 20.0
            reason_bits.append("thesis_ai:TENSION")
        elif verdict == "STALE_THESIS" or "stale_thesis" in reasons_in:
            score_delta += 12.0
            reason_bits.append("thesis_ai:STALE_THESIS")
        if "weak" in reasons_in:
            # Weak noise should not dominate buy/sell ranking
            score_delta -= 6.0
            reason_bits.append("weak")
        if "stale" in reasons_in or "due_for_review" in reasons_in:
            score_delta += 4.0

        existing = by_ticker.get(ticker)
        if existing is None:
            by_ticker[ticker] = {
                "ticker": ticker,
                "advise": thesis_advise,
                "score": round(22.0 + score_delta, 1),
                "reasons": reason_bits,
                "queue_action": None,
                "queue_verdict": None,
                "thesis_verdict": verdict or None,
                "thesis_id": str(row.get("id") or "") or None,
                "dual_tension": False,
                "meta_conviction": None,
                "confidence": None,
            }
            continue

        existing["score"] = round(float(existing["score"]) + score_delta, 1)
        existing["reasons"] = list(existing.get("reasons") or []) + reason_bits
        existing["thesis_verdict"] = verdict or existing.get("thesis_verdict")
        existing["thesis_id"] = str(row.get("id") or "") or existing.get("thesis_id")
        qv = str(existing.get("queue_verdict") or "").upper()
        if qv == "TENSION" and (verdict == "TENSION" or "tension" in reasons_in):
            existing["dual_tension"] = True
            existing["score"] = round(float(existing["score"]) + 10.0, 1)
            existing["reasons"].append("dual_tension")

        # If queue says BUY but thesis leans SELL (or reverse), prefer the more defensive advise
        qa = str(existing.get("advise") or "").upper()
        if {qa, thesis_advise} == {"BUY", "SELL"}:
            existing["advise"] = "SELL"
            existing["reasons"].append("conflict_prefer_sell")
            existing["score"] = round(float(existing["score"]) + 8.0, 1)
        elif _ADVISE_PRIORITY.get(thesis_advise, 99) < _ADVISE_PRIORITY.get(qa, 99):
            existing["advise"] = thesis_advise

    ranked = list(by_ticker.values())
    ranked.sort(
        key=lambda r: (
            _ADVISE_PRIORITY.get(str(r.get("advise") or ""), 99),
            -float(r.get("score") or 0),
            str(r.get("ticker") or ""),
        )
    )
    return ranked[: max(1, min(limit, 50))]
