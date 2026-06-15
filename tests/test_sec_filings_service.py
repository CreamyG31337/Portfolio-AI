"""Tests for US EDGAR filing-risk detection (ROADMAP G2).

Fixture-based, no network: classification rules + dedupe on accession_no +
parallel-array extraction + CIK-map parsing + graceful degrade on a missing
filing_events table.
"""

from unittest.mock import MagicMock

from web_dashboard.sec_filings_service import (
    classify_filing,
    dedupe_events,
    extract_filing_events,
    fetch_recent_filing_alerts,
    load_ticker_cik_map,
    parse_company_tickers,
)


# --------------------------------------------------------------------------- #
# classify_filing
# --------------------------------------------------------------------------- #

def test_classify_dilution_forms():
    assert classify_filing("S-3") == ("dilution", "risk")
    assert classify_filing("S-1") == ("dilution", "risk")
    assert classify_filing("424B5") == ("dilution", "risk")
    assert classify_filing("EFFECT") == ("dilution", "risk")
    # Amendments keep the base form's classification.
    assert classify_filing("S-3/A") == ("dilution", "risk")


def test_classify_s8_is_neutral_dilution():
    # Routine employee-plan registration: dilution but low-signal (neutral).
    assert classify_filing("S-8") == ("dilution", "neutral")
    assert classify_filing("S-8/A") == ("dilution", "neutral")


def test_classify_distress_late_filings():
    assert classify_filing("NT 10-Q") == ("distress", "risk")
    assert classify_filing("NT 10-K") == ("distress", "risk")


def test_classify_8k_item_301_is_distress_no_extra_fetch():
    # Item numbers are inline in the items array — substring match, no fetch.
    assert classify_filing("8-K", "3.01,9.01") == ("distress", "risk")
    assert classify_filing("8-K", "5.02,3.01") == ("distress", "risk")


def test_classify_8k_without_301_is_ignored():
    assert classify_filing("8-K", "2.02,7.01,9.01") is None
    assert classify_filing("8-K", "") is None


def test_classify_delisting_forms():
    assert classify_filing("25") == ("delisting", "risk")
    assert classify_filing("25-NSE") == ("delisting", "risk")


def test_classify_activist_13d_both_spellings():
    # The feed mixes "SC 13D/A" and "SCHEDULE 13D/A" — match BOTH.
    assert classify_filing("SC 13D") == ("activist", "positive")
    assert classify_filing("SC 13D/A") == ("activist", "positive")
    assert classify_filing("SCHEDULE 13D/A") == ("activist", "positive")
    assert classify_filing("SC 13G") == ("activist", "positive")
    assert classify_filing("SCHEDULE 13G/A") == ("activist", "positive")


def test_classify_untracked_forms_return_none():
    assert classify_filing("10-K") is None
    assert classify_filing("10-Q") is None
    assert classify_filing("4") is None
    assert classify_filing("13F-HR") is None  # 13F must NOT match the 13D/13G rule
    assert classify_filing("") is None


# --------------------------------------------------------------------------- #
# extract_filing_events  (parallel arrays)
# --------------------------------------------------------------------------- #

def _submissions(forms, dates, accns, items=None, docs=None):
    n = len(forms)
    return {
        "filings": {
            "recent": {
                "form": forms,
                "filingDate": dates,
                "reportDate": [""] * n,
                "accessionNumber": accns,
                "items": items if items is not None else [""] * n,
                "primaryDocument": docs if docs is not None else ["x.htm"] * n,
                "primaryDocDescription": [""] * n,
            }
        }
    }


def test_extract_filters_by_since_date_and_classifies():
    subs = _submissions(
        forms=["S-3", "10-K", "8-K", "SCHEDULE 13D/A"],
        dates=["2026-06-12", "2026-06-11", "2026-06-10", "2026-05-01"],
        accns=["0001-26-000001", "0001-26-000002", "0001-26-000003", "0001-26-000004"],
        items=["", "", "3.01", ""],
    )
    events = extract_filing_events("ACME", "0000012345", subs, since_date="2026-06-01")

    # 10-K dropped (untracked); SCHEDULE 13D dropped (before since_date).
    forms = {e["form_type"] for e in events}
    assert forms == {"S-3", "8-K"}
    by_form = {e["form_type"]: e for e in events}
    assert by_form["S-3"]["category"] == "dilution"
    assert by_form["8-K"]["category"] == "distress"
    assert by_form["8-K"]["direction"] == "risk"


def test_extract_builds_archives_url_and_strips_dashes():
    subs = _submissions(
        forms=["424B5"],
        dates=["2026-06-13"],
        accns=["0001144204-26-000789"],
        docs=["form424b5.htm"],
    )
    events = extract_filing_events("ACME", "0000320193", subs, since_date="2026-06-01")
    assert len(events) == 1
    ev = events[0]
    # CIK leading zeros stripped in the path; accession dashes removed.
    assert ev["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000114420426000789/form424b5.htm"
    )
    assert ev["ticker"] == "ACME"
    assert ev["accession_no"] == "0001144204-26-000789"


def test_extract_handles_empty_recent():
    assert extract_filing_events("ACME", "0001", {}, since_date="2026-01-01") == []
    assert extract_filing_events("ACME", "0001", {"filings": {}}, since_date=None) == []


# --------------------------------------------------------------------------- #
# dedupe_events
# --------------------------------------------------------------------------- #

def test_dedupe_drops_duplicate_accession_keeps_first():
    events = [
        {"accession_no": "A-1", "form_type": "S-3"},
        {"accession_no": "A-2", "form_type": "8-K"},
        {"accession_no": "A-1", "form_type": "S-3"},  # dup
        {"accession_no": "", "form_type": "junk"},     # no accession -> dropped
    ]
    out = dedupe_events(events)
    assert [e["accession_no"] for e in out] == ["A-1", "A-2"]


# --------------------------------------------------------------------------- #
# parse_company_tickers / load_ticker_cik_map
# --------------------------------------------------------------------------- #

def test_parse_company_tickers_zero_pads_cik():
    raw = {
        "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
        "1": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
    }
    m = parse_company_tickers(raw)
    assert m["NVDA"] == "0001045810"  # zero-padded to 10 digits
    assert m["AAPL"] == "0000320193"  # lowercased ticker normalized to upper


def test_load_ticker_cik_map_uses_injected_fetcher(tmp_path):
    raw = {"0": {"cik_str": 999, "ticker": "ABC", "title": "ABC Corp"}}
    cache = tmp_path / "cik.json"
    m = load_ticker_cik_map(
        cache_path=cache, force_refresh=True, fetcher=lambda: raw
    )
    assert m == {"ABC": "0000000999"}
    assert cache.exists()  # fetched payload cached to disk


def test_load_ticker_cik_map_empty_on_fetch_failure(tmp_path):
    # Fetch returns None and no cache exists -> empty map, never raises.
    m = load_ticker_cik_map(
        cache_path=tmp_path / "missing.json", force_refresh=True, fetcher=lambda: None
    )
    assert m == {}


# --------------------------------------------------------------------------- #
# fetch_recent_filing_alerts graceful degrade
# --------------------------------------------------------------------------- #

def test_fetch_recent_filing_alerts_degrades_on_missing_table():
    pg = MagicMock()
    pg.execute_query.side_effect = Exception('relation "filing_events" does not exist')
    assert fetch_recent_filing_alerts(pg, days=14) == []


def test_fetch_recent_filing_alerts_passes_ticker_filter():
    pg = MagicMock()
    pg.execute_query.return_value = [{"ticker": "ACME"}]
    rows = fetch_recent_filing_alerts(pg, tickers=["acme"], days=10, limit=5)
    assert rows == [{"ticker": "ACME"}]
    args, _ = pg.execute_query.call_args
    sql, params = args
    assert "ticker = ANY(%s)" in sql
    assert params == (10, ["ACME"], 5)
