"""Regression: committee jurisdictions must live in root data/ (not web_dashboard/data)."""

from data.committee_jurisdictions import COMMITTEE_CONTEXT, get_committee_context


def test_committee_context_dict_is_populated() -> None:
    assert "House Committee on Armed Services" in COMMITTEE_CONTEXT
    assert "Senate Committee on Finance" in COMMITTEE_CONTEXT


def test_get_committee_context_matches_known_committee() -> None:
    result = get_committee_context("House Committee on Armed Services (Member)")
    assert "House Committee on Armed Services" in result
    assert "Defense Contractors" in result


def test_get_committee_context_unknown_assignment() -> None:
    result = get_committee_context("Unknown")
    assert "no regulatory power" in result.lower()
