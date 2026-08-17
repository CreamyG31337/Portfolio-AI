"""Falsifiable proposal schema for LLM research outputs (AQuA transfer Phase 2).

The skill injects guidance; this module is the structural gate — invalid proposals
must not enter the Learn ledger as if they were scored claims.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

ALLOWED_HORIZONS = frozenset({7, 30, 90})
ALLOWED_DIRECTIONS = frozenset(
    {
        "higher_means_up",
        "higher_means_down",
        "bullish",
        "bearish",
        "higher_signal_predicts_higher_future_return",
        "higher_signal_predicts_lower_future_return",
    }
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def mechanism_key(mechanism: str | None) -> str:
    """Normalize mechanism text to a stable grouping key."""
    text = (mechanism or "").strip().lower()
    if not text:
        return ""
    slug = _SLUG_RE.sub("_", text).strip("_")
    return slug[:80]


def _as_horizon(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n in ALLOWED_HORIZONS else None


def _as_direction(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    return s if s in ALLOWED_DIRECTIONS else None


def validate_falsifiable_proposal(payload: Mapping[str, Any] | None) -> tuple[bool, str]:
    """Return (ok, error_message). Empty error when ok."""
    if not isinstance(payload, Mapping):
        return False, "proposal payload is not an object"

    # Nested under "falsifiable_proposal" or flat on the response root.
    node: Mapping[str, Any]
    nested = payload.get("falsifiable_proposal")
    if isinstance(nested, Mapping):
        node = nested
    else:
        node = payload

    hypothesis = str(node.get("hypothesis") or "").strip()
    if len(hypothesis) < 8:
        return False, "hypothesis missing or too short"

    mechanism = str(node.get("mechanism") or "").strip()
    if len(mechanism) < 8:
        return False, "mechanism missing or too short"

    direction = _as_direction(node.get("expected_direction"))
    if direction is None:
        return False, (
            "expected_direction must be one of: "
            + ", ".join(sorted(ALLOWED_DIRECTIONS))
        )

    horizon = _as_horizon(node.get("horizon_days"))
    if horizon is None:
        return False, "horizon_days must be 7, 30, or 90"

    falsification = node.get("falsification_criteria")
    if not isinstance(falsification, list) or not falsification:
        return False, "falsification_criteria must be a non-empty list"
    cleaned_f = [str(x).strip() for x in falsification if str(x).strip()]
    if not cleaned_f:
        return False, "falsification_criteria entries are empty"

    failure_modes = node.get("expected_failure_modes")
    if not isinstance(failure_modes, list) or not failure_modes:
        return False, "expected_failure_modes must be a non-empty list"
    cleaned_m = [str(x).strip() for x in failure_modes if str(x).strip()]
    if not cleaned_m:
        return False, "expected_failure_modes entries are empty"

    return True, ""


def has_valid_falsifiable_proposal(payload: Mapping[str, Any] | None) -> bool:
    ok, _ = validate_falsifiable_proposal(payload)
    return ok


def extract_proposal_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize proposal fields from a validated (or best-effort) response."""
    nested = payload.get("falsifiable_proposal")
    node: Mapping[str, Any] = nested if isinstance(nested, Mapping) else payload

    mechanism = str(node.get("mechanism") or "").strip()
    falsification = node.get("falsification_criteria") or []
    failure_modes = node.get("expected_failure_modes") or []
    if not isinstance(falsification, list):
        falsification = [str(falsification)]
    if not isinstance(failure_modes, list):
        failure_modes = [str(failure_modes)]

    return {
        "hypothesis": str(node.get("hypothesis") or "").strip(),
        "mechanism": mechanism,
        "mechanism_key": mechanism_key(mechanism),
        "expected_direction": (_as_direction(node.get("expected_direction")) or ""),
        "horizon_days": _as_horizon(node.get("horizon_days")),
        "falsification_criteria": [str(x).strip() for x in falsification if str(x).strip()],
        "expected_failure_modes": [str(x).strip() for x in failure_modes if str(x).strip()],
    }


def proposal_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Subset suitable for stance_history.metadata."""
    fields = extract_proposal_fields(payload)
    return {"falsifiable_proposal": fields}


def response_has_proposal(raw: str, extract_json_fn: Any) -> bool:
    """Adapter for collect_with_summary_model_chain response_ok hooks."""
    parsed = extract_json_fn(raw or "")
    if not isinstance(parsed, dict):
        return False
    return has_valid_falsifiable_proposal(parsed)
