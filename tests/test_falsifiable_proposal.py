"""Tests for falsifiable_proposal validation gate."""

from __future__ import annotations

from falsifiable_proposal import (
    MECHANISM_CATEGORIES,
    has_valid_falsifiable_proposal,
    mechanism_key,
    proposal_metadata,
    validate_falsifiable_proposal,
)


def _valid(**overrides: object) -> dict:
    base = {
        "hypothesis": "Post-catalyst silence predicts underperformance vs peers",
        "mechanism": "Market priced the event; lack of follow-through implies weak demand",
        "mechanism_category": "catalyst_repricing",
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


def test_rejects_missing_mechanism_category() -> None:
    payload = _valid()
    del payload["mechanism_category"]
    ok, err = validate_falsifiable_proposal(payload)
    assert not ok
    assert "mechanism_category" in err


def test_mechanism_key_accepts_the_controlled_vocabulary() -> None:
    assert mechanism_key("Catalyst Repricing") == "catalyst_repricing"
    assert mechanism_key("earnings_surprise_drift") == "earnings_surprise_drift"


def test_mechanism_key_collapses_unknown_categories_instead_of_minting_buckets() -> None:
    """The whole point of a closed vocabulary: cardinality cannot grow with phrasing.

    Free-text slugging gave every call its own bucket, so `by_mechanism` could only
    ever hold n=1 rows and "which mechanisms have edge, with N attached" was
    unanswerable by construction.
    """
    a = mechanism_key("Market priced the event; lack of follow-through implies weak demand")
    b = mechanism_key("The event was already priced so no follow-through means weak demand")
    assert a == b == "other"
    assert a in MECHANISM_CATEGORIES


def test_same_idea_phrased_twice_lands_in_one_bucket() -> None:
    first = proposal_metadata(_valid(mechanism="Priced already; no follow-through"))
    second = proposal_metadata(_valid(mechanism="Already in the price, follow-through absent"))
    assert (
        first["falsifiable_proposal"]["mechanism_key"]
        == second["falsifiable_proposal"]["mechanism_key"]
        == "catalyst_repricing"
    )


def test_proposal_metadata_shape() -> None:
    meta = proposal_metadata(_valid())
    assert meta["falsifiable_proposal"]["mechanism_key"]
    assert meta["falsifiable_proposal"]["horizon_days"] == 30
