"""Advise — ranked buy/sell suggestions from existing artifacts (no LLM).

v0: merge Action Queue + Insights attention.
v1: reweight by track-record hit rates + recent confluence (Learn → Decide).
Does not place trades.
"""

from __future__ import annotations

from typing import Any, Callable

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

# Min scored outcomes before we trust a hit-rate adjustment.
_MIN_SCORED_FOR_LEARN = 12
_HIT_BOOST_THRESHOLD = 0.55
_HIT_PENALTY_THRESHOLD = 0.45


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


def learn_weight_multiplier(
    *,
    source_hit_rate: float | None,
    source_scored: int,
    verdict_hit_rate: float | None = None,
    verdict_scored: int = 0,
) -> tuple[float, list[str]]:
    """Return (multiplier, reason chips) from track-record rates.

    Neutral (1.0) when samples are thin. Boost reliable sources/verdicts;
    soft-penalize coin-flip-or-worse so Advise leans on what historically works.
    """
    reasons: list[str] = []
    mult = 1.0

    if source_hit_rate is not None and source_scored >= _MIN_SCORED_FOR_LEARN:
        if source_hit_rate >= _HIT_BOOST_THRESHOLD:
            bump = min(0.35, (source_hit_rate - _HIT_BOOST_THRESHOLD) * 1.5)
            mult += bump
            reasons.append(f"learn_src+{source_hit_rate:.0%}")
        elif source_hit_rate <= _HIT_PENALTY_THRESHOLD:
            cut = min(0.30, (_HIT_PENALTY_THRESHOLD - source_hit_rate) * 1.2)
            mult -= cut
            reasons.append(f"learn_src-{source_hit_rate:.0%}")

    if verdict_hit_rate is not None and verdict_scored >= max(5, _MIN_SCORED_FOR_LEARN // 2):
        if verdict_hit_rate >= _HIT_BOOST_THRESHOLD:
            bump = min(0.25, (verdict_hit_rate - _HIT_BOOST_THRESHOLD) * 1.2)
            mult += bump
            reasons.append(f"learn_verdict+{verdict_hit_rate:.0%}")
        elif verdict_hit_rate <= _HIT_PENALTY_THRESHOLD:
            cut = min(0.20, (_HIT_PENALTY_THRESHOLD - verdict_hit_rate) * 1.0)
            mult -= cut
            reasons.append(f"learn_verdict-{verdict_hit_rate:.0%}")

    return max(0.55, min(1.6, mult)), reasons


def _index_track_record(summary: dict[str, Any] | None) -> tuple[
    dict[str, tuple[float | None, int]],
    dict[str, tuple[float | None, int]],
]:
    """Map source/verdict → (hit_rate, scored_n)."""
    if not summary:
        return {}, {}
    rates_s = summary.get("hit_rate_by_source") or {}
    counts_s = summary.get("counts_by_source") or {}
    rates_v = summary.get("hit_rate_by_verdict") or {}
    counts_v = summary.get("counts_by_verdict") or {}
    by_src: dict[str, tuple[float | None, int]] = {}
    for src, rate in rates_s.items():
        scored = int((counts_s.get(src) or {}).get("scored") or 0)
        by_src[str(src)] = (rate, scored)
    by_ver: dict[str, tuple[float | None, int]] = {}
    for ver, rate in rates_v.items():
        scored = int((counts_v.get(ver) or {}).get("scored") or 0)
        by_ver[str(ver).upper()] = (rate, scored)
    return by_src, by_ver


def _confluence_index(
    events: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Best recent confluence event per ticker."""
    out: dict[str, dict[str, Any]] = {}
    for ev in events or []:
        t = str(ev.get("ticker") or "").upper().strip()
        if not t:
            continue
        prev = out.get(t)
        score = float(ev.get("score") or 0)
        if prev is None or score >= float(prev.get("score") or 0):
            out[t] = ev
    return out


def build_advise_recommendations(
    *,
    action_queue: list[dict[str, Any]] | None = None,
    theses_attention: list[dict[str, Any]] | None = None,
    track_record: dict[str, Any] | None = None,
    confluence_events: list[dict[str, Any]] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Rank tickers the system would nudge a human to BUY / SELL / RISK / WATCH.

    Pure merge + Learn reweight. No LLM. Optional ``track_record`` /
    ``confluence_events`` keep the core testable without DB.
    """
    by_src, by_ver = _index_track_record(track_record)
    conf_by_ticker = _confluence_index(confluence_events)
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

        # Learn: weight queue mechanical action by historical queue-review source
        # performance, and ALIGNED/TENSION by verdict calibration when available.
        src_rate, src_n = by_src.get("action_queue_ai_review", (None, 0))
        ver_rate, ver_n = by_ver.get(queue_verdict, (None, 0)) if queue_verdict else (None, 0)
        # Meta conviction available → also blend meta learn weight lightly
        meta_rate, meta_n = by_src.get("ticker_meta_analysis", (None, 0))
        mult_q, learn_bits = learn_weight_multiplier(
            source_hit_rate=src_rate,
            source_scored=src_n,
            verdict_hit_rate=ver_rate,
            verdict_scored=ver_n,
        )
        if meta_c and meta_n >= _MIN_SCORED_FOR_LEARN and meta_rate is not None:
            mult_m, bits_m = learn_weight_multiplier(
                source_hit_rate=meta_rate,
                source_scored=meta_n,
            )
            # Average toward meta when research_context is present
            mult_q = (mult_q + mult_m) / 2.0
            learn_bits = learn_bits + [b.replace("learn_src", "learn_meta") for b in bits_m]
        if abs(mult_q - 1.0) > 0.01:
            score *= mult_q
            reasons.extend(learn_bits)

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
            "confluence_direction": None,
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
            score_delta -= 6.0
            reason_bits.append("weak")
        if "stale" in reasons_in or "due_for_review" in reasons_in:
            score_delta += 4.0

        thesis_rate, thesis_n = by_src.get("thesis_ai_review", (None, 0))
        mult_t, learn_t = learn_weight_multiplier(
            source_hit_rate=thesis_rate,
            source_scored=thesis_n,
        )
        if abs(mult_t - 1.0) > 0.01:
            score_delta *= mult_t
            reason_bits.extend(learn_t)

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
                "confluence_direction": None,
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

        qa = str(existing.get("advise") or "").upper()
        if {qa, thesis_advise} == {"BUY", "SELL"}:
            existing["advise"] = "SELL"
            existing["reasons"].append("conflict_prefer_sell")
            existing["score"] = round(float(existing["score"]) + 8.0, 1)
        elif _ADVISE_PRIORITY.get(thesis_advise, 99) < _ADVISE_PRIORITY.get(qa, 99):
            existing["advise"] = thesis_advise

    # Confluence: reinforce directionally aligned advises; flag risk
    for ticker, row in by_ticker.items():
        ev = conf_by_ticker.get(ticker)
        if not ev:
            continue
        direction = str(ev.get("direction") or "").lower()
        cscore = float(ev.get("score") or 0)
        row["confluence_direction"] = direction or None
        advise = str(row.get("advise") or "").upper()
        if direction == "bullish" and advise in ("BUY", "WATCH"):
            row["score"] = round(float(row["score"]) + 6.0 + min(4.0, cscore), 1)
            row["reasons"] = list(row.get("reasons") or []) + ["confluence:bullish"]
        elif direction == "bullish" and advise in ("SELL", "RISK"):
            row["score"] = round(float(row["score"]) + 5.0, 1)
            row["reasons"] = list(row.get("reasons") or []) + ["confluence_vs_sell"]
        elif direction == "risk":
            if advise in ("SELL", "RISK"):
                row["score"] = round(float(row["score"]) + 8.0, 1)
            else:
                # Risk confluence on a BUY → prefer RISK attention
                if advise == "BUY":
                    row["advise"] = "RISK"
                    row["reasons"] = list(row.get("reasons") or []) + ["confluence:risk→RISK"]
                row["score"] = round(float(row["score"]) + 6.0, 1)
            row["reasons"] = list(row.get("reasons") or []) + ["confluence:risk"]

    ranked = list(by_ticker.values())
    ranked.sort(
        key=lambda r: (
            _ADVISE_PRIORITY.get(str(r.get("advise") or ""), 99),
            -float(r.get("score") or 0),
            str(r.get("ticker") or ""),
        )
    )
    return ranked[: max(1, min(limit, 50))]


def _attach_analysis_stance(
    rows: list[dict[str, Any]],
    action_queue: list[dict[str, Any]] | None,
) -> None:
    """Copy standard ``analysis_stance`` from action-queue research_context onto
    advise rows in place.

    Advise rows only carry ``meta_conviction``; A2 tension detection also reads
    the standard ticker_analysis stance. Without this, Today advise_pack would
    see a narrower tension signal than the chat pulse's leaned candidates.
    """
    if not rows or not action_queue:
        return
    stance_by_t: dict[str, Any] = {}
    for a in action_queue:
        t = str(a.get("ticker") or "").upper().strip()
        rc = a.get("research_context") if isinstance(a.get("research_context"), dict) else {}
        stance = rc.get("analysis_stance")
        if t and stance and t not in stance_by_t:
            stance_by_t[t] = stance
    for row in rows:
        t = str(row.get("ticker") or "").upper().strip()
        if not row.get("stance") and t in stance_by_t:
            row["stance"] = stance_by_t[t]


def rank_candidate_pack(
    *,
    action_queue: list[dict[str, Any]] | None,
    theses_attention: list[dict[str, Any]] | None = None,
    track_record: dict[str, Any] | None = None,
    confluence_events: list[dict[str, Any]] | None = None,
    signal_fallback: Callable[[], list[dict[str, Any]]] | list[dict[str, Any]] | None = None,
    limit: int = 12,
) -> tuple[list[dict[str, Any]], str]:
    """Single ranking source for Today advise_pack and the chat pulse/candidates.

    A3: both surfaces call this so they cannot structurally drift. Builds ranked
    advise recommendations; when those are empty (common: no BUYs, SELL/RISK need
    held) it uses the shared watchlist ``signal_fallback``. A2 tension annotation
    + demotion is applied to whichever set is returned.

    ``signal_fallback`` may be a precomputed list or a zero-arg callable (invoked
    only when advise is empty, so callers avoid the DB read on the hot path).

    Returns ``(rows, source)`` where source is ``advise`` | ``signal_fallback`` |
    ``none``. Advise rows keep their full shape (score/reasons/…); callers that
    need lean chat rows format them afterwards.
    """
    from ai_assistant_candidates import annotate_and_demote_tension

    pack = build_advise_recommendations(
        action_queue=action_queue or [],
        theses_attention=theses_attention,
        track_record=track_record,
        confluence_events=confluence_events,
        limit=limit,
    )
    if pack:
        _attach_analysis_stance(pack, action_queue)
        return annotate_and_demote_tension(pack), "advise"

    fallback = signal_fallback() if callable(signal_fallback) else (signal_fallback or [])
    fallback = [r for r in (fallback or []) if r.get("ticker")]
    if fallback:
        return annotate_and_demote_tension(fallback), "signal_fallback"
    return [], "none"
