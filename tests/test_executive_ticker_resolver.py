"""Tests for executive branch ticker resolution and ingest."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_dashboard"
if str(WEB_DASHBOARD_PATH) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_PATH))

from executive_ticker_resolver import (  # noqa: E402
    canonicalize_oge_company_name,
    canonicalize_oge_description,
    is_bond_or_muni,
    parse_ticker_suffix,
    resolve_executive_asset,
    resolve_from_securities,
)
from scheduler.jobs_executive import (  # noqa: E402
    _normalize_trade_type,
    process_executive_transactions,
)


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "trump_transactions_sample.json"


def test_is_bond_or_muni_detects_municipal_description() -> None:
    assert is_bond_or_muni("TARRANT REGL WTR DIST TE RV BE/R/ 5 DUE 030134")
    assert not is_bond_or_muni("AAR CORP")


def test_parse_ticker_suffix_from_description() -> None:
    assert parse_ticker_suffix("BANK OF AMERICA CORPORATION - BAC") == "BAC"
    assert parse_ticker_suffix("AAR CORP") is None


def test_canonicalize_oge_strips_class_shares() -> None:
    assert canonicalize_oge_company_name("ACM RESH INC CLASS A") == "ACM RESH"
    assert canonicalize_oge_description("ACM RESH INC CLASS A") == "ACM RESH INC"


def test_resolve_executive_asset_open_cabinet_ticker() -> None:
    result = resolve_executive_asset(
        "BANK OF AMERICA CORPORATION - BAC",
        open_cabinet_ticker="BAC",
    )
    assert result.ticker == "BAC"
    assert result.source == "open_cabinet"


def test_resolve_executive_asset_suffix_fallback() -> None:
    result = resolve_executive_asset("BANK OF AMERICA CORPORATION - BAC")
    assert result.ticker == "BAC"
    assert result.source == "suffix"


def test_resolve_executive_asset_skips_bonds() -> None:
    result = resolve_executive_asset(
        "TARRANT REGL WTR DIST TE RV BE/R/ 5 DUE 030134 DTD 042826"
    )
    assert result.ticker is None
    assert result.source == "skipped_bond"


def test_resolve_executive_asset_uses_cache() -> None:
    cache = {
        "AAR": {
            "canonical_description": "AAR",
            "ticker": "AIR",
            "source": "manual",
            "confidence": 1.0,
            "asset_type": "Stock",
        }
    }
    result = resolve_executive_asset("AAR CORP", cache=cache)
    assert result.ticker == "AIR"
    assert result.source == "cache"


def test_resolve_from_securities_single_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "executive_ticker_resolver.infer_tickers_from_companies",
        lambda companies: ["AIR"] if companies else [],
    )
    assert resolve_from_securities("AAR CORP") == "AIR"


def test_resolve_from_securities_rejects_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "executive_ticker_resolver.infer_tickers_from_companies",
        lambda companies: ["AAA", "BBB"],
    )
    assert resolve_from_securities("AMBIGUOUS HOLDINGS INC") is None


def test_resolve_executive_asset_yfinance_single_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "executive_ticker_resolver.resolve_from_securities",
        lambda company_name: None,
    )

    def fake_yfinance(company_name: str):
        assert company_name == "AAR"
        return ("AIR", "Stock", 0.75)

    monkeypatch.setattr("executive_ticker_resolver.resolve_from_yfinance", fake_yfinance)

    result = resolve_executive_asset("AAR CORP", use_yfinance=True)
    assert result.ticker == "AIR"
    assert result.source == "yfinance"


def test_normalize_trade_type() -> None:
    assert _normalize_trade_type("Purchase") == "Purchase"
    assert _normalize_trade_type("Sale") == "Sale"
    assert _normalize_trade_type("buy") == "Purchase"


def test_process_executive_transactions_dry_run() -> None:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    transactions = payload["transactions"]

    mock_client = MagicMock()
    mock_client.supabase.table.return_value.select.return_value.execute.return_value.data = []

    stats = process_executive_transactions(
        mock_client,
        transactions,
        politician_id=999,
        party="Republican",
        state="US",
        dry_run=True,
    )

    assert stats["total"] == 5
    assert stats["skipped_bond"] == 1
    assert stats["inserted"] == 1
    assert stats["unresolved"] == 3


def test_fetch_executive_trades_job_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from scheduler import jobs_executive

    monkeypatch.setattr(
        jobs_executive,
        "fetch_open_cabinet_transactions",
        lambda url=None: [
            {
                "description": "BANK OF AMERICA CORPORATION - BAC",
                "ticker": "BAC",
                "type": "Purchase",
                "date": "2026-03-18",
                "amount": "$1",
            }
        ],
    )
    monkeypatch.setattr(
        jobs_executive,
        "process_executive_transactions",
        lambda *args, **kwargs: {
            "inserted": 1,
            "skipped_bond": 0,
            "unresolved": 0,
            "duplicates": 0,
            "errors": 0,
            "total": 1,
        },
    )

    class FakeSupabaseClient:
        def __init__(self, use_service_role: bool = False) -> None:
            self.supabase = MagicMock()
            (
                self.supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data
            ) = [{"id": 1, "party": "Republican", "state": "US"}]

    monkeypatch.setattr("supabase_client.SupabaseClient", FakeSupabaseClient)
    monkeypatch.setattr("utils.job_tracking.mark_job_started", lambda *args, **kwargs: None)
    monkeypatch.setattr("utils.job_tracking.mark_job_completed", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs_executive, "log_job_execution", lambda *args, **kwargs: None)

    jobs_executive.fetch_executive_trades_job()


def test_congress_trades_template_includes_executive_chamber() -> None:
    template_path = (
        Path(__file__).resolve().parents[1]
        / "web_dashboard"
        / "templates"
        / "congress_trades.html"
    )
    content = template_path.read_text(encoding="utf-8")
    assert 'value="Executive"' in content
