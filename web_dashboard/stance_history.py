"""Append-only stance ledger helpers (Pillar 1)."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from collections.abc import Mapping
from uuid import UUID

logger = logging.getLogger(__name__)

# V1 directional scoring: BUY/SELL plus meta/analysis directional labels.
# HOLD is intentionally absent: under the excess-return hit rule it can never
# be a hit or a miss, so scoring it only inflates denominators.
DIRECTIONAL_STANCES = frozenset(
    {
        "BUY",
        "SELL",
        "BULLISH",
        "BEARISH",
        "VERY_BULLISH",
        "VERY_BEARISH",
        "AVOID",
    }
)

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
) -> bool:
    """Append a stance row only if it differs from the latest row for (ticker, source, fund_key).

    Returns True if a row was inserted. Never raises — callers wrap if they need strict behavior.
    """
    ticker_u = (ticker or "").upper().strip()
    source_s = (source or "").strip()
    stance_s = (stance or "").strip()[:40] if stance else ""
    fund_s = _normalize_fund_key(fund_key)

    if not ticker_u or not source_s or not stance_s:
        return False

    try:
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

        ref_id = str(source_ref_id) if source_ref_id else None
        postgres.execute_update(
            """
            INSERT INTO stance_history (
                ticker, fund_key, source, stance, confidence, price_at_stance,
                drivers, risks, model_used, requested_by, source_ref_id, metadata
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s::jsonb
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
                _json_metadata(metadata),
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
    except Exception as exc:
        logger.warning(
            "Failed to record stance for %s source=%s: %s",
            ticker_u,
            source_s,
            exc,
        )
        return False


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
