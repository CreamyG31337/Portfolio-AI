"""Tests for falsifiable_proposal validation gate."""

from __future__ import annotations

from falsifiable_proposal import (
    has_valid_falsifiable_proposal,
    mechanism_key,
    proposal_metadata,
    validate_falsifiable_proposal,
)


def _valid(**overrides: object) -> dict:
    base = {
        "hypothesis": "Post-catalyst silence predicts underperformance vs peers",
        "mechanism": "Market priced the event; lack of follow-through implies weak demand",
        "expected_direction": "bearish",
        "horizon_days": 30,
        "falsification_criteria": ["excess vs ^RUT > 0 at 30d"],
        "expected_failure_modes": ["broad risk-on lifts all micro-caps"],
    }
    base.update(overrides)
    return base


def test_valid_flat_proposal() -> None:
    ok, err = validate_falsifiable_proposal(_valid())
    assert ok and err == ""


def test_valid_nested_proposal() -> None:
    payload = {"stance": "BUY", "falsifiable_proposal": _valid()}
    assert has_valid_falsifiable_proposal(payload)


def test_rejects_bad_horizon() -> None:
    ok, err = validate_falsifiable_proposal(_valid(horizon_days=14))
    assert not ok
    assert "horizon_days" in err


def test_rejects_missing_falsification() -> None:
    ok, err = validate_falsifiable_proposal(_valid(falsification_criteria=[]))
    assert not ok


def test_mechanism_key_slug() -> None:
    assert mechanism_key("Catalyst Gap / Weak Follow-Through!") == "catalyst_gap_weak_follow_through"


def test_proposal_metadata_shape() -> None:
    meta = proposal_metadata(_valid())
    assert meta["falsifiable_proposal"]["mechanism_key"]
    assert meta["falsifiable_proposal"]["horizon_days"] == 30
