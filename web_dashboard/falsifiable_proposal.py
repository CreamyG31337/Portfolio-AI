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

# Controlled vocabulary for *why the market would pay*. The grouping key must be a
# closed set: slugifying the free-text mechanism sentence gave every call its own
# bucket (two phrasings of one idea hash differently), so `by_mechanism` could only
# ever report n=1 rows with a hit rate of 0.0 or 1.0 -- making "which mechanisms
# have edge after cost, with N attached" unanswerable by construction.
#
# The prose `mechanism` field is kept as the explanation; this is the axis it is
# counted on. Categories are deliberately coarse: a taxonomy fine enough to always
# fit exactly is a taxonomy that never accumulates N.
MECHANISM_CATEGORIES = frozenset(
    {
        # Information is public but not yet widely read/priced.
        "information_diffusion",
        # Thin float or forced flow moves price independently of value.
        "liquidity_premium",
        # A crowd extreme mean-reverts.
        "sentiment_reversal",
        # Post-earnings-announcement drift.
        "earnings_surprise_drift",
        # A scheduled or binary event reprices the name (trial, approval, contract).
        "catalyst_repricing",
        # A multiple gap versus peers closes.
        "valuation_mean_reversion",
        # Insider / institutional / congressional activity reveals private information.
        "informed_trading_signal",
        # Index adds, lockup expiry, buybacks, dilution.
        "supply_demand_imbalance",
        # Capital rotating into or out of the sector carries the name with it.
        "sector_rotation",
        # A story attracting incremental buyers (reflexive, not fundamental).
        "narrative_momentum",
        # Persistent neglect: no coverage, structurally under-followed.
        "structural_neglect",
        # Balance-sheet, financing or going-concern risk being re-rated.
        "risk_repricing",
        # Genuine misfits. Tracked, but a rising share of these means the taxonomy
        # needs revisiting rather than that the calls are unclassifiable.
        "other",
    }
)

MECHANISM_OTHER = "other"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def mechanism_key(category: str | None) -> str:
    """Map a supplied mechanism category onto the controlled vocabulary.

    Anything unrecognised collapses to ``other`` rather than minting a new bucket,
    so cardinality stays bounded no matter what the model emits.
    """
    text = (category or "").strip().lower()
    if not text:
        return ""
    slug = _SLUG_RE.sub("_", text).strip("_")
    return slug if slug in MECHANISM_CATEGORIES else MECHANISM_OTHER


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

    # Gated, not defaulted: a silently-defaulted category would pile unrelated
    # claims into one bucket and read as accumulated evidence for a belief nobody
    # stated. Better to reject and let the model pick.
    if not mechanism_key(node.get("mechanism_category")):
        return False, (
            "mechanism_category must be one of: "
            + ", ".join(sorted(MECHANISM_CATEGORIES))
        )

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
        "mechanism_key": mechanism_key(node.get("mechanism_category")) or MECHANISM_OTHER,
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
    """``response_ok`` hook for collect_with_summary_model_chain.

    The single implementation behind ticker analysis, meta analysis and the
    congress batch, which each previously carried a byte-identical private copy.
    """
    parsed = extract_json_fn(raw or "")
    if not isinstance(parsed, dict):
        return False
    return has_valid_falsifiable_proposal(parsed)
