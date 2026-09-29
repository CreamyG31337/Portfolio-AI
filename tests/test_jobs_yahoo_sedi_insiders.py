"""Tests for yahoo_sedi_insiders scheduler job (ROADMAP G7)."""

from unittest.mock import MagicMock, patch

from web_dashboard.scheduler.jobs_yahoo_sedi_insiders import (
    _dedup_key,
    collect_canadian_tickers,
    yahoo_sedi_insiders_job,
)


def test_collect_canadian_tickers_filters_suffixes():
    class FakeTable:
        def __init__(self, name):
            self._name = name

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def range(self, start, end):
            self._start, self._end = start, end
            return self

        def execute(self):
            if self._name == "funds":
                return MagicMock(data=[{"name": "Project Chimera"}])
            if self._name == "latest_positions":
                return MagicMock(
                    data=[
                        {"ticker": "GLO.TO", "fund": "Project Chimera"},
                        {"ticker": "AAPL", "fund": "Project Chimera"},
                    ]
                )
            if self._name == "watched_tickers_v2":
                return MagicMock(data=[{"ticker": "GMIN.TO"}])
            return MagicMock(data=[])

    client = MagicMock()
    client.supabase.table.side_effect = lambda name: FakeTable(name)
    tickers = collect_canadian_tickers(client)
    assert tickers == ["GLO.TO", "GMIN.TO"]


def test_collect_canadian_tickers_skips_holdings_on_fund_lookup_failure():
    """Fix #5: a failed production-fund lookup must not run an unfiltered
    holdings scan that would pull TEST_* fund pollution."""

    class FakeTable:
        def __init__(self, name):
            self._name = name

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def range(self, start, end):
            return self

        def execute(self):
            if self._name == "funds":
                raise RuntimeError("supabase down")
            if self._name == "latest_positions":
                # Would leak if the scan ran unfiltered; it must be skipped.
                return MagicMock(data=[{"ticker": "TESTPOLL.TO", "fund": "TEST_X"}])
            if self._name == "watched_tickers_v2":
                return MagicMock(data=[{"ticker": "GMIN.TO"}])
            return MagicMock(data=[])

    client = MagicMock()
    client.supabase.table.side_effect = lambda name: FakeTable(name)
    tickers = collect_canadian_tickers(client)
    assert tickers == ["GMIN.TO"]


_SAMPLE_ROW = {
    "ticker": "GLO.TO",
    "insider_name": "Leung (Guy)",
    "insider_title": "",
    "transaction_date": "2026-05-15",
    "disclosure_date": "2026-05-15T00:00:00+00:00",
    "type": "Purchase",
    "shares": 1000,
    "price_per_share": 0.45,
    "value": 450.0,
    "source": "yahoo_sedi",
}


@patch("yahoo_sedi_insider_service.fetch_yahoo_insider_rows")
@patch("supabase_client.SupabaseClient")
@patch("utils.job_tracking.mark_job_started")
@patch("utils.job_tracking.mark_job_completed")
@patch("supabase_pagination.fetch_all_rows")
@patch("web_dashboard.scheduler.jobs_yahoo_sedi_insiders.collect_canadian_tickers")
@patch("web_dashboard.scheduler.jobs_yahoo_sedi_insiders.log_job_execution")
def test_yahoo_sedi_insiders_job_upserts(
    mock_log,
    mock_collect,
    mock_fetch_all_rows,
    mock_completed,
    mock_started,
    mock_sb_cls,
    mock_fetch,
):
    mock_fetch_all_rows.return_value = []
    mock_collect.return_value = ["GLO.TO"]
    mock_fetch.return_value = [dict(_SAMPLE_ROW)]
    sb = MagicMock()
    sb.supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock(
        data=[{"id": 1}]
    )
    mock_sb_cls.return_value = sb

    yahoo_sedi_insiders_job()

    upsert_call = sb.supabase.table.return_value.upsert.call_args
    assert upsert_call[0][0][0]["source"] == "yahoo_sedi"
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] is True


@patch("yahoo_sedi_insider_service.fetch_yahoo_insider_rows")
@patch("supabase_client.SupabaseClient")
@patch("utils.job_tracking.mark_job_started")
@patch("utils.job_tracking.mark_job_completed")
@patch("supabase_pagination.fetch_all_rows")
@patch("web_dashboard.scheduler.jobs_yahoo_sedi_insiders.collect_canadian_tickers")
@patch("web_dashboard.scheduler.jobs_yahoo_sedi_insiders.log_job_execution")
def test_yahoo_sedi_insiders_job_skips_existing(
    mock_log,
    mock_collect,
    mock_fetch_all_rows,
    mock_completed,
    mock_started,
    mock_sb_cls,
    mock_fetch,
):
    """An already-stored trade must not be re-inserted (dedup guard, fix #1)."""
    # Stored as the DB returns it: numeric columns come back as floats.
    mock_fetch_all_rows.return_value = [
        {
            "insider_name": "Leung (Guy)",
            "transaction_date": "2026-05-15",
            "type": "Purchase",
            "shares": 1000.0,
            "price_per_share": 0.45,
        }
    ]
    mock_collect.return_value = ["GLO.TO"]
    mock_fetch.return_value = [dict(_SAMPLE_ROW)]
    sb = MagicMock()
    mock_sb_cls.return_value = sb

    yahoo_sedi_insiders_job()

    sb.supabase.table.return_value.upsert.assert_not_called()
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] is True


def test_dedup_key_matches_numeric_forms():
    stored = {**_SAMPLE_ROW, "shares": 1000.0, "price_per_share": "0.450"}
    assert _dedup_key(stored) == _dedup_key(_SAMPLE_ROW)


def test_dedup_key_keeps_sub_cent_prices_distinct():
    other = {**_SAMPLE_ROW, "price_per_share": 0.455}
    assert _dedup_key(other) != _dedup_key(_SAMPLE_ROW)


def test_dedup_key_null_price_only_matches_null():
    priceless = {**_SAMPLE_ROW, "price_per_share": None}
    assert _dedup_key(priceless) == _dedup_key(dict(priceless))
    assert _dedup_key(priceless) != _dedup_key(_SAMPLE_ROW)
