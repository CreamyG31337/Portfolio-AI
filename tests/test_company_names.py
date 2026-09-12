"""Ticker -> company name: readable output, and never a blank where a ticker was."""

from __future__ import annotations

from unittest.mock import MagicMock

import company_names
from company_names import attach_company_names, get_company_names, tidy_company_name


def _supabase(rows: list[dict], *, capture: list | None = None) -> MagicMock:
    """Minimal stand-in for the chained supabase query builder."""
    sb = MagicMock()
    table = sb.supabase.table.return_value
    select = table.select.return_value

    def _in(field, values):
        if capture is not None:
            capture.append((field, list(values)))
        result = MagicMock()
        result.execute.return_value = MagicMock(
            data=[r for r in rows if r.get("ticker") in set(values)]
        )
        return result

    select.in_.side_effect = _in
    select.range.return_value.execute.return_value = MagicMock(data=rows)
    select.execute.return_value = MagicMock(data=rows)
    return sb


def setup_function() -> None:
    company_names._cache.clear()
    company_names._cache_loaded_at = 0.0


def test_tidy_strips_legal_noise_and_fixes_shouting() -> None:
    assert tidy_company_name("CUMMINS INC") == "Cummins Inc"
    assert tidy_company_name("META PLATFORMS INC CLASS A") == "Meta Platforms Inc"
    assert tidy_company_name("  ") == ""
    assert tidy_company_name(None) == ""


def test_tidy_keeps_initialisms_uppercase() -> None:
    """title() would render these as 'Etf' and 'Ge', which looks broken."""
    assert tidy_company_name("SPROTT URANIUM MINERS ETF") == "Sprott Uranium Miners ETF"
    assert tidy_company_name("GE VERNOVA INC") == "GE Vernova Inc"


def test_tidy_leaves_mixed_case_names_alone() -> None:
    assert tidy_company_name("iShares Core Equity ETF Portfolio") == "iShares Core Equity ETF Portfolio"
    assert tidy_company_name("lululemon athletica") == "lululemon athletica"


def test_requested_tickers_are_queried_not_scanned() -> None:
    """A bare select is capped at 1000 rows by PostgREST and silently drops the rest."""
    captured: list = []
    sb = _supabase(
        [
            {"ticker": "CMI", "company_name": "CUMMINS INC"},
            {"ticker": "META", "company_name": "META PLATFORMS INC CLASS A"},
        ],
        capture=captured,
    )
    names = get_company_names(sb, ["cmi", "META"])
    assert names == {"CMI": "Cummins Inc", "META": "Meta Platforms Inc"}
    assert captured and captured[0][0] == "ticker"
    assert set(captured[0][1]) == {"CMI", "META"}


def test_unknown_ticker_is_absent_so_callers_fall_back() -> None:
    sb = _supabase([{"ticker": "CMI", "company_name": "CUMMINS INC"}])
    assert get_company_names(sb, ["NOSUCH"]) == {}


def test_name_identical_to_ticker_is_dropped() -> None:
    """Showing 'URNM · URNM' is noise, not information."""
    sb = _supabase([{"ticker": "URNM", "company_name": "URNM"}])
    assert get_company_names(sb, ["URNM"]) == {}


def test_lookup_failure_is_not_fatal() -> None:
    sb = MagicMock()
    sb.supabase.table.side_effect = Exception("supabase down")
    assert get_company_names(sb, ["CMI"]) == {}


def test_attach_adds_names_in_place_and_skips_unknowns() -> None:
    sb = _supabase([{"ticker": "CMI", "company_name": "CUMMINS INC"}])
    items = [{"ticker": "CMI"}, {"ticker": "NOSUCH"}, {"no_ticker": 1}]
    attach_company_names(sb, items)
    assert items[0]["company_name"] == "Cummins Inc"
    assert "company_name" not in items[1]
    assert "company_name" not in items[2]
    attach_company_names(sb, [])  # must not raise
