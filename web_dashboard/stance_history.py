"""Append-only stance ledger helpers (Pillar 1)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from collections.abc import Mapping
from uuid import UUID

logger = logging.getLogger(__name__)

# V1 directional scoring: BUY/SELL plus meta/analysis directional labels.
# HOLD is intentionally absent: under the excess-return hit rule it can never
# be a hit or a miss, so scoring it only inflates denominators.
#
# THE canonical stance vocabulary. Every consumer that needs to know "which way
# did this call point" imports these -- track_record_service (hit rate + signed
# excess), microcap_cost_model (after-cost haircut direction), jobs_stance_outcomes
# (which rows are scoreable). Four independent copies previously agreed only by
# accident; a stance added to one and not the others silently changes a hit rate
# without changing any test.
#
# KNOWN GAP: ai_prompts emits STRONG_BULLISH / STRONG_BEARISH (see the response
# schemas around ai_prompts.py:356), but they are deliberately NOT listed here.
# is_directional_stance gates jobs_stance_outcomes' scoreable filter, so the
# model's highest-conviction calls are currently never scored at all. Adding them
# is a real change to what enters the ledger -- a product decision, not a cleanup
# -- so it is left alone here rather than smuggled in with a refactor.
BULLISH_STANCES = frozenset(
    {
        "BUY",
        "BULLISH",
        "VERY_BULLISH",
    }
)

BEARISH_STANCES = frozenset(
    {
        "SELL",
        "BEARISH",
        "VERY_BEARISH",
        "AVOID",
    }
)

DIRECTIONAL_STANCES = BULLISH_STANCES | BEARISH_STANCES

# Event sources write one row per external call (an article), not a running state.
# Consecutive rows disagreeing is two authors disagreeing, not the system changing
# its mind, so they are excluded from stance-flip detection.
EVENT_STANCE_SOURCES: tuple[str, ...] = ("alpha_idea", "precursor:ark_buy")

# Kept in ledger but excluded from directional hit-rate in V1.
NON_DIRECTIONAL_STANCES = frozenset({"RISK", "WATCH"})


def is_directional_stance(stance: str | None) -> bool:
    """Return True if stance should participate in directional outcome scoring."""
    if not stance:
        return False
    normalized = stance.strip().upper()
    if normalized in NON_DIRECTIONAL_STANCES:
        return False
    return normalized in DIRECTIONAL_STANCES


def _normalize_fund_key(fund_key: str | None) -> str:
    return (fund_key or "").strip()


def _json_metadata(metadata: Mapping[str, Any] | None) -> str | None:
    if not metadata:
        return None
    return json.dumps(dict(metadata))


def _confidence_equal(a: Any, b: Any) -> bool:
    """Compare confidences across Decimal/float/None (NUMERIC(5,4) precision)."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) < 1e-4
    except (TypeError, ValueError):
        return False


def record_stance(
    postgres: Any,
    *,
    ticker: str,
    source: str,
    stance: str | None,
    confidence: float | Decimal | None = None,
    fund_key: str = "",
    price_at_stance: float | Decimal | None = None,
    drivers: list[str] | None = None,
    risks: list[str] | None = None,
    model_used: str | None = None,
    requested_by: str | None = None,
    source_ref_id: str | UUID | None = None,
    metadata: Mapping[str, Any] | None = None,
    as_of: datetime | None = None,
    dedupe_on_source_ref: bool = False,
) -> bool:
    """Append a stance row only if it differs from the latest row for (ticker, source, fund_key).

    Two dedupe modes:

    * default — *state* sources (an analysis re-run nightly): skip when stance and
      confidence equal the latest row, so only changes enter the ledger.
    * ``dedupe_on_source_ref=True`` — *event* sources (one article = one call): skip
      only when a row for the same (ticker, source, source_ref_id) already exists.
      Two bullish articles on the same ticker are two independent calls and must both
      be scored; state dedupe would silently keep only the first one ever.

    ``as_of`` overrides the insert time (default ``now()``). Event sources set it to
    when the call became actionable so backfills and late runs score from the right
    entry date.

    Returns True if a row was inserted. Never raises — callers wrap if they need strict behavior.
    """
    ticker_u = (ticker or "").upper().strip()
    source_s = (source or "").strip()
    stance_s = (stance or "").strip()[:40] if stance else ""
    fund_s = _normalize_fund_key(fund_key)

    if not ticker_u or not source_s or not stance_s:
        return False

    if dedupe_on_source_ref and not source_ref_id:
        logger.warning("record_stance: dedupe_on_source_ref needs source_ref_id (%s)", ticker_u)
        return False

    try:
        if dedupe_on_source_ref:
            existing = postgres.execute_query(
                """
                SELECT 1 FROM stance_history
                WHERE ticker = %s AND source = %s AND source_ref_id = %s
                LIMIT 1
                """,
                (ticker_u, source_s, str(source_ref_id)),
            )
            if existing:
                return False
            return _insert_stance(
                postgres, ticker_u, fund_s, source_s, stance_s, confidence,
                price_at_stance, drivers, risks, model_used, requested_by,
                source_ref_id, metadata, as_of,
            )

        latest = postgres.execute_query(
            """
            SELECT stance, confidence FROM stance_history
            WHERE ticker = %s AND source = %s AND fund_key = %s
            ORDER BY as_of DESC
            LIMIT 1
            """,
            (ticker_u, source_s, fund_s),
        )
        # Dedupe on stance AND confidence: a confidence move on the same stance
        # (0.5 -> 0.9) is exactly the drift the calibration screens need.
        if (
            latest
            and (latest[0].get("stance") or "").strip() == stance_s
            and _confidence_equal(latest[0].get("confidence"), confidence)
        ):
            return False

        return _insert_stance(
            postgres, ticker_u, fund_s, source_s, stance_s, confidence,
            price_at_stance, drivers, risks, model_used, requested_by,
            source_ref_id, metadata, as_of,
        )
    except Exception as exc:
        logger.warning(
            "Failed to record stance for %s source=%s: %s",
            ticker_u,
            source_s,
            exc,
        )
        return False


def _insert_stance(
    postgres: Any,
    ticker_u: str,
    fund_s: str,
    source_s: str,
    stance_s: str,
    confidence: float | Decimal | None,
    price_at_stance: float | Decimal | None,
    drivers: list[str] | None,
    risks: list[str] | None,
    model_used: str | None,
    requested_by: str | None,
    source_ref_id: str | UUID | None,
    metadata: Mapping[str, Any] | None,
    as_of: datetime | None,
) -> bool:
    ref_id = str(source_ref_id) if source_ref_id else None
    postgres.execute_update(
        """
        INSERT INTO stance_history (
            ticker, fund_key, source, stance, confidence, price_at_stance,
            drivers, risks, model_used, requested_by, source_ref_id, as_of, metadata
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, now()), %s::jsonb
        )
        """,
        (
            ticker_u,
            fund_s,
            source_s,
            stance_s,
            confidence,
            price_at_stance,
            drivers,
            risks,
            model_used,
            requested_by,
            ref_id,
            as_of,
            _json_metadata(metadata),  # keep last: tests read metadata as args[-1]
        ),
    )
    logger.debug(
        "Recorded stance %s for %s source=%s fund_key=%s",
        stance_s,
        ticker_u,
        source_s,
        fund_s or "(none)",
    )
    return True


def record_stance_safe(
    postgres: Any,
    **kwargs: Any,
) -> bool:
    """Non-fatal wrapper for hook sites."""
    try:
        return record_stance(postgres, **kwargs)
    except Exception as exc:
        logger.warning("record_stance_safe failed: %s", exc)
        return False


def fetch_recent_meta_stances(
    postgres: Any,
    ticker: str,
    *,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Latest ``ticker_meta_analysis`` ledger rows for a ticker (newest first)."""
    ticker_u = (ticker or "").upper().strip()
    if not ticker_u or limit < 1:
        return []
    try:
        return postgres.execute_query(
            """
            SELECT stance, confidence, as_of, source
            FROM stance_history
            WHERE ticker = %s AND source = 'ticker_meta_analysis'
            ORDER BY as_of DESC
            LIMIT %s
            """,
            (ticker_u, limit),
        ) or []
    except Exception as exc:
        logger.warning("fetch_recent_meta_stances failed for %s: %s", ticker_u, exc)
        return []


def format_prior_stance_for_meta_bundle(
    postgres: Any,
    ticker: str,
    *,
    track_summary: Mapping[str, Any] | None = None,
) -> str | None:
    """Markdown block: prior meta stances (+ optional global source track-record).

    Returns None when there is no ledger history for the ticker.
    ``track_summary`` should be ``build_track_record_summary`` output (caller-cached).

    Only matured mechanism outcomes (from track_summary.by_mechanism) are injected —
    never in-flight validation trophies.
    """
    rows = fetch_recent_meta_stances(postgres, ticker, limit=2)
    if not rows:
        return None

    lines: list[str] = ["### Prior stance and track record"]
    latest = rows[0]
    latest_stance = (latest.get("stance") or "").strip() or "UNKNOWN"
    latest_conf = latest.get("confidence")
    latest_as_of = latest.get("as_of")
    lines.append(
        f"- Latest ticker_meta_analysis: stance={latest_stance} "
        f"confidence={latest_conf} as_of={latest_as_of}"
    )
    if len(rows) >= 2:
        prev = rows[1]
        prev_stance = (prev.get("stance") or "").strip() or "UNKNOWN"
        flipped = prev_stance.upper() != latest_stance.upper()
        flip_note = "FLIP" if flipped else "unchanged"
        lines.append(
            f"- Previous: stance={prev_stance} confidence={prev.get('confidence')} "
            f"as_of={prev.get('as_of')} ({flip_note})"
        )

    summary = track_summary
    if summary:
        # Describe the number that is actually present. The payload only reports
        # after-cost aggregates once rows carry a haircut, so asserting "after cost"
        # unconditionally would tell the model a pre-cost figure had been net of
        # trading costs -- overstating every edge it is asked to reason about.
        after_cost = summary.get("excess_metric") == "directional_after_cost"
        cost_note = "after cost" if after_cost else "before costs"
        for source in ("ticker_meta_analysis", "ticker_analysis"):
            rate = (summary.get("hit_rate_by_source") or {}).get(source)
            counts = (summary.get("counts_by_source") or {}).get(source) or {}
            scored = int(counts.get("scored") or 0)
            if scored <= 0 and rate is None:
                continue
            avg_ex = (summary.get("avg_excess_by_source") or {}).get(source)
            rate_s = f"{100.0 * rate:.1f}%" if rate is not None else "—"
            ex_s = f"{avg_ex:+.2f}" if avg_ex is not None else "—"
            horizon = summary.get("horizon_days")
            n_tested = summary.get("candidates_tested")
            lines.append(
                f"- Global {source} track record ({horizon}d): "
                f"hit_rate={rate_s} mean_directional_excess={ex_s} scored={scored} "
                f"N={n_tested} "
                f"(source calibration — not this ticker alone; excess is signed to "
                f"the call's direction {cost_note}, so positive means the call was right)"
            )

        # Matured mechanism beliefs only (AQuA §4.3 analogue).
        mechanisms = summary.get("by_mechanism") or []
        if isinstance(mechanisms, list) and mechanisms:
            lines.append("- Matured mechanisms (after cost; do not treat as live IC):")
            for mech in mechanisms[:8]:
                if not isinstance(mech, dict):
                    continue
                key = mech.get("mechanism_key") or "unspecified"
                n = int(mech.get("n") or 0)
                if n <= 0:
                    continue
                hr = mech.get("hit_rate")
                hr_s = f"{100.0 * hr:.0f}%" if hr is not None else "—"
                mean_eac = mech.get("mean_excess_after_cost")
                eac_s = f"{mean_eac:+.2f}" if mean_eac is not None else "—"
                lines.append(
                    f"  - {key}: n={n} hit_rate={hr_s} mean_excess_after_cost={eac_s}"
                )

    return "\n".join(lines)
