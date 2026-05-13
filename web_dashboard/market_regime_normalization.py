"""Normalize `market_daily_brief.regime_json` to a stable Phase-2-ish contract.

`as_of` convention: ISO-8601 timestamp in UTC. Prefer PostgreSQL ``updated_at`` when
provided (converted to UTC if aware). Otherwise use **market close placeholder** on
``brief_date``: 16:00 America/New_York expressed in UTC — this matches “backdrop as of that
NYSE session”, not midnight local.

Legacy LLM payloads used ``risk_tone`` with the same allowed labels as ``risk_regime``;
both are honored (``risk_regime`` wins when both present).

See ``docs/meta_analysis_roadmap.md`` Phase 2 for the semantic contract reference.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")

_ALLOWED_RISK = frozenset({"RISK_ON", "RISK_OFF", "NEUTRAL", "MIXED"})
_ALLOWED_BREADTH = frozenset({"LEADERSHIP_BROAD", "LEADERSHIP_NARROW", "UNCLEAR"})
_ALLOWED_VOL = frozenset({"CALM", "ELEVATED", "STRESSED", "UNKNOWN"})

_MAX_THEMES_STORE = 8


def invalid_regime_enum_fields(raw: dict[str, Any] | None) -> list[str]:
    """Return ``key=value`` strings for non-empty enum fields not in the allowed set (LLM drift).

    Used for warning logs before merge; normalization still clamps to defaults on write.
    """
    if not isinstance(raw, dict) or not raw:
        return []
    checks: tuple[tuple[str, frozenset[str]], ...] = (
        ("risk_regime", _ALLOWED_RISK),
        ("risk_tone", _ALLOWED_RISK),
        ("breadth_proxy", _ALLOWED_BREADTH),
        ("volatility_state", _ALLOWED_VOL),
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


def _coerce_date(brief_date: date | datetime | str | None) -> date | None:
    if brief_date is None:
        return None
    if isinstance(brief_date, datetime):
        bt = brief_date
        if bt.tzinfo is None:
            return bt.date()
        return bt.astimezone(UTC).date()
    if isinstance(brief_date, date):
        return brief_date
    if isinstance(brief_date, str):
        s = brief_date.strip()
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _as_of_fallback(brief_day: date) -> str:
    """16:00 US/Eastern on ``brief_day`` as UTC ISO."""
    local = datetime.combine(brief_day, time(16, 0), tzinfo=_NY)
    return local.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_of_from_updated(updated_at: datetime | str | None) -> str | None:
    if updated_at is None:
        return None
    dt: datetime
    if isinstance(updated_at, str):
        ss = updated_at.strip()
        if not ss:
            return None
        if ss.endswith("Z"):
            ss = ss[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(ss.replace(" ", "T", 1))
        except ValueError:
            return None
    else:
        dt = updated_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _macro_themes(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw[:_MAX_THEMES_STORE]:
        s = _clean_str(item)
        if s:
            out.append(s[:200])
        if len(out) >= _MAX_THEMES_STORE:
            break
    return out


def _caveats(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for c in raw:
        s = _clean_str(c)
        if s:
            out.append(s[:300])
    return out


def normalize_market_regime(
    regime: dict[str, Any] | None,
    *,
    brief_date: date | datetime | str | None,
    updated_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Return canonical regime fields (never drops unknown extra keys callers merge separately).

    Output always contains keys matching the roadmap example; invalid/missing enums use
    safe defaults (**NEUTRAL** risk when neither ``risk_regime`` nor ``risk_tone`` parses,
    **UNCLEAR** breadth, **UNKNOWN** volatility).
    """
    r = regime if isinstance(regime, dict) else {}
    bday = _coerce_date(brief_date) or date.today()

    rr = (
        _member_or(r.get("risk_regime"), _ALLOWED_RISK, "")
        or _member_or(r.get("risk_tone"), _ALLOWED_RISK, "")
        or "NEUTRAL"
    )
    breadth = _member_or(r.get("breadth_proxy"), _ALLOWED_BREADTH, "UNCLEAR")
    vol = _member_or(r.get("volatility_state"), _ALLOWED_VOL, "UNKNOWN")
    conf = _confidence(r.get("regime_confidence"))
    themes = _macro_themes(r.get("macro_themes"))

    ln = _clean_str(r.get("leadership_note")) or ""
    caveats = _caveats(r.get("caveats"))

    ao = _as_of_from_updated(updated_at) or _as_of_fallback(bday)

    return {
        "risk_regime": rr,
        "regime_confidence": conf if conf is not None else 0.0,
        "breadth_proxy": breadth,
        "volatility_state": vol,
        "macro_themes": themes,
        "leadership_note": ln,
        "caveats": caveats,
        "as_of": ao,
    }


def merge_regime_for_storage(
    raw_regime: dict[str, Any] | None,
    *,
    brief_date: date,
) -> dict[str, Any]:
    """Merge LLM regime JSON with canonical fields for UPSERT (no ``updated_at`` yet)."""
    raw = dict(raw_regime) if isinstance(raw_regime, dict) else {}
    canon = normalize_market_regime(raw, brief_date=brief_date, updated_at=None)
    merged: dict[str, Any] = {**raw, **canon}
    return merged
