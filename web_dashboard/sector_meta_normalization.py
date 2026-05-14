"""Validate and clamp sector_meta_analysis LLM output to the Phase 3b contract.

See ``docs/meta_analysis_roadmap.md`` (Sector output contract). Drift is logged and clamped;
callers should not fail the job on enum mismatch alone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_ALLOWED_STANCE = frozenset({"BULLISH", "NEUTRAL", "BEARISH", "MIXED", "INSUFFICIENT_DATA"})
_ALLOWED_MOMENTUM = frozenset({"ACCELERATING", "STABLE", "DECELERATING", "UNKNOWN"})
_ALLOWED_NEWS = frozenset({"POSITIVE", "NEUTRAL", "NEGATIVE", "MIXED", "UNKNOWN"})


def invalid_sector_meta_enum_fields(raw: dict[str, Any] | None) -> list[str]:
    """Return ``key=value`` strings for enum fields not in the allowed set."""
    if not isinstance(raw, dict) or not raw:
        return []
    checks: tuple[tuple[str, frozenset[str]], ...] = (
        ("sector_stance", _ALLOWED_STANCE),
        ("momentum_state", _ALLOWED_MOMENTUM),
        ("news_pressure", _ALLOWED_NEWS),
    )
    out: list[str] = []
    for key, allowed in checks:
        v = raw.get(key)
        s = _clean_str(v)
        if s is None:
            continue
        up = s.upper().replace("-", "_")
        if up not in allowed:
            out.append(f"{key}={v!r}")
    return out


def _clean_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _member_or(value: Any, allowed: frozenset[str], default: str) -> str:
    s = _clean_str(value)
    if s is None:
        return default
    up = s.upper().replace("-", "_")
    if up in allowed:
        return up
    return default


def _coerce_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _coerce_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _string_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = _clean_str(v)
    return [s] if s else []


def _as_of_iso(raw: dict[str, Any], fallback: datetime) -> str:
    v = raw.get("as_of")
    s = _clean_str(v)
    if s:
        return s
    dt = fallback if fallback.tzinfo else fallback.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_sector_meta_payload(
    raw: dict[str, Any] | None,
    *,
    sector_label: str,
    as_of_fallback: datetime,
) -> dict[str, Any]:
    """Return a dict matching the locked Phase 3b JSON contract (exact keys)."""
    src = raw if isinstance(raw, dict) else {}
    drift = invalid_sector_meta_enum_fields(src)
    if drift:
        logger.warning("sector_meta enum drift (will clamp): %s", ", ".join(drift))

    stance = _member_or(src.get("sector_stance"), _ALLOWED_STANCE, "INSUFFICIENT_DATA")
    momentum = _member_or(src.get("momentum_state"), _ALLOWED_MOMENTUM, "UNKNOWN")
    news_p = _member_or(src.get("news_pressure"), _ALLOWED_NEWS, "UNKNOWN")

    rank = _coerce_int(src.get("rotation_rank"), 0)
    conf = _coerce_float(src.get("confidence"), 0.0)
    drivers = _string_list(src.get("key_drivers"))
    risks = _string_list(src.get("risk_flags"))

    sector_out = _clean_str(src.get("sector")) or sector_label

    return {
        "sector": sector_out,
        "sector_stance": stance,
        "momentum_state": momentum,
        "news_pressure": news_p,
        "rotation_rank": rank,
        "confidence": conf,
        "key_drivers": drivers,
        "risk_flags": risks,
        "as_of": _as_of_iso(src, as_of_fallback),
    }
