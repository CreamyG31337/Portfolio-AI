"""Tests for executive branch ticker resolution and ingest."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_dashboard"
if str(WEB_DASHBOARD_PATH) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_PATH))

import executive_ticker_resolver  # noqa: E402
from executive_ticker_resolver import (  # noqa: E402
    LLMResolutionError,
    _is_us_primary_symbol,
    _parse_llm_ticker_json,
    _select_best_equity,
    canonicalize_oge_company_name,
    canonicalize_oge_description,
    classify_oge_asset_type,
    confirm_ticker_symbol,
    is_bond_or_muni,
    parse_ticker_suffix,
    resolve_executive_asset,
    resolve_from_llm,
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
    assert not is_bond_or_muni("PNC FINL PERP 6 2500")


def test_classify_oge_asset_type_examples() -> None:
    assert classify_oge_asset_type("BANK OF AMERICA CORPORATION - BAC") == "Stock"
    assert classify_oge_asset_type("PNC FINL PERP 6 2500") == "Preferred"
    assert classify_oge_asset_type("KEY DP SH PFD H GTO 08 24 22") == "Preferred"
    assert (
        classify_oge_asset_type("GENL MOTORS FINL 6 100 010734 DT0120723")
        == "Corporate Bond"
    )
    assert (
        classify_oge_asset_type("STE STRT COMTN SR SLCT SCTR SPDR ETF") == "ETF"
    )
    assert (
        classify_oge_asset_type("TARRANT REGL WTR DIST TE RV BE/R/ 5 DUE 030134")
        == "Municipal Bond"
    )


def test_resolve_executive_asset_sets_preferred_type_from_cache() -> None:
    description = "PNC FINL PERP 6 2500"
    key = canonicalize_oge_company_name(description)
    cache = {
        key: {
            "canonical_description": key,
            "ticker": "PNC",
            "source": "llm",
            "confidence": 0.85,
            "asset_type": "Stock",
        }
    }
    result = resolve_executive_asset(description, cache=cache)
    assert result.ticker == "PNC"
    assert result.asset_type == "Preferred"


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


def test_is_us_primary_symbol() -> None:
    assert _is_us_primary_symbol("ABM")
    assert _is_us_primary_symbol("EAT")
    assert not _is_us_primary_symbol("AB4.F")
    assert not _is_us_primary_symbol("US2927651040.SG")
    assert not _is_us_primary_symbol("CM.TO")


def test_select_best_equity_prefers_us_primary_over_foreign() -> None:
    quotes = [
        {"symbol": "ABM", "quote_type": "EQUITY", "name": "ABM Industries Incorporated"},
        {"symbol": "AB4.F", "quote_type": "EQUITY", "name": "ABM Industries Incorporated"},
    ]
    match = _select_best_equity("ABM INDS", quotes)
    assert match is not None and match["symbol"] == "ABM"


def test_select_best_equity_rejects_distinct_companies() -> None:
    quotes = [
        {"symbol": "APOG", "quote_type": "EQUITY", "name": "Apogee Enterprises, Inc."},
        {"symbol": "APGE", "quote_type": "EQUITY", "name": "Apogee Therapeutics, Inc."},
    ]
    assert _select_best_equity("APOGEE", quotes) is None


def test_select_best_equity_same_company_picks_shortest_symbol() -> None:
    quotes = [
        {"symbol": "BTSG", "quote_type": "EQUITY", "name": "BrightSpring Health Services, Inc."},
        {"symbol": "BTSGU", "quote_type": "EQUITY", "name": "BrightSpring Health Services, Inc."},
    ]
    match = _select_best_equity("BRIGHTSPRING HEALTH", quotes)
    assert match is not None and match["symbol"] == "BTSG"


def test_select_best_equity_rejects_no_overlap() -> None:
    quotes = [
        {"symbol": "BAC", "quote_type": "EQUITY", "name": "Bank of America Corporation"},
        {"symbol": "USB", "quote_type": "EQUITY", "name": "U.S. Bancorp"},
    ]
    assert _select_best_equity("BANC CALIF", quotes) is None


def test_select_best_equity_rejects_single_common_token_match() -> None:
    # 'JBG SMITH PPTYS' should NOT match 'A. O. Smith' on the shared token SMITH.
    quotes = [
        {"symbol": "AOS", "quote_type": "EQUITY", "name": "A. O. Smith Corporation"},
    ]
    assert _select_best_equity("JBG SMITH PPTYS", quotes) is None


def test_select_best_equity_rejects_foreign_only_listing() -> None:
    # Only a foreign secondary listing available -> skip (US bot).
    quotes = [
        {"symbol": "CSG.AS", "quote_type": "EQUITY", "name": "CSG Systems International"},
    ]
    assert _select_best_equity("CSG", quotes) is None


def test_select_best_equity_accepts_abbreviated_second_token() -> None:
    # 'COMSTOCK RES' -> 'Comstock Resources' via lead token COMSTOCK.
    quotes = [
        {"symbol": "CRK", "quote_type": "EQUITY", "name": "Comstock Resources, Inc."},
        {"symbol": "CX91.MU", "quote_type": "EQUITY", "name": "Comstock Resources Inc"},
    ]
    match = _select_best_equity("COMSTOCK RES", quotes)
    assert match is not None and match["symbol"] == "CRK"


def test_normalize_trade_type() -> None:
    assert _normalize_trade_type("Purchase") == "Purchase"
    assert _normalize_trade_type("Sale") == "Sale"
    assert _normalize_trade_type("buy") == "Purchase"


def test_process_executive_transactions_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep hermetic: no live securities/yfinance lookups. Only the Open Cabinet
    # ticker (BAC) should resolve; the rest stay unresolved.
    monkeypatch.setattr(
        "executive_ticker_resolver.resolve_from_securities",
        lambda company_name: None,
    )

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


class _FakeOllama:
    """Minimal stand-in for OllamaClient.generate_completion."""

    def __init__(self, response: object) -> None:
        self._response = response
        self.prompts: list[str] = []

    def generate_completion(
        self,
        prompt: str,
        model: object = None,
        json_mode: bool = False,
        temperature: object = None,
    ) -> object:
        self.prompts.append(prompt)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _install_fake_yfinance(
    monkeypatch: pytest.MonkeyPatch, quotes: list[dict]
) -> None:
    """Inject a fake ``yfinance`` module whose Search returns ``quotes``."""

    module = types.ModuleType("yfinance")

    class _Search:  # noqa: D401 - test double
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.quotes = quotes

    module.Search = _Search  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", module)
    monkeypatch.setattr(executive_ticker_resolver, "_throttle_yfinance", lambda: None)


def test_parse_llm_ticker_json_handles_code_fences() -> None:
    assert _parse_llm_ticker_json(
        '```json\n{"ticker": "AIR", "company_name": "AAR", "confidence": 0.9}\n```'
    ) == {"ticker": "AIR", "company_name": "AAR", "confidence": 0.9}
    assert _parse_llm_ticker_json('here you go: {"ticker": null}') == {"ticker": None}
    assert _parse_llm_ticker_json("not json at all") is None
    assert _parse_llm_ticker_json("") is None


def test_confirm_ticker_symbol_accepts_matching_us_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_yfinance(
        monkeypatch,
        [{"symbol": "AIR", "quoteType": "EQUITY", "longname": "AAR Corp"}],
    )
    assert confirm_ticker_symbol("AIR", "AAR CORP") == ("AIR", "Stock")


def test_confirm_ticker_symbol_rejects_hallucinated_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Model proposed ZZZZ but the search returns a different, unrelated symbol.
    _install_fake_yfinance(
        monkeypatch,
        [{"symbol": "AIR", "quoteType": "EQUITY", "longname": "AAR Corp"}],
    )
    assert confirm_ticker_symbol("ZZZZ", "AAR CORP") is None


def test_confirm_ticker_symbol_rejects_name_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_yfinance(
        monkeypatch,
        [{"symbol": "AIR", "quoteType": "EQUITY", "longname": "AAR Corp"}],
    )
    # Symbol exists but the issuer name does not overlap the OGE description.
    assert confirm_ticker_symbol("AIR", "MICROSOFT CORP") is None


def test_confirm_ticker_symbol_rejects_foreign_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_yfinance(
        monkeypatch,
        [{"symbol": "AIR.PA", "quoteType": "EQUITY", "longname": "Airbus SE"}],
    )
    assert confirm_ticker_symbol("AIR.PA", "AIRBUS SE") is None


def test_resolve_from_llm_returns_validated_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        executive_ticker_resolver,
        "confirm_ticker_symbol",
        lambda symbol, description, llm_name=None: ("AIR", "Stock"),
    )
    ollama = _FakeOllama('{"ticker": "AIR", "company_name": "AAR", "confidence": 0.9}')
    result = resolve_from_llm("AAR CORP", ollama_client=ollama)
    assert result is not None
    ticker, asset_type, confidence = result
    assert ticker == "AIR"
    assert asset_type == "Stock"
    assert 0.6 <= confidence <= 0.85


def test_resolve_from_llm_none_when_model_declines() -> None:
    ollama = _FakeOllama('{"ticker": null, "company_name": null, "confidence": 0.0}')
    assert resolve_from_llm("SOME PRIVATE FUND", ollama_client=ollama) is None


def test_resolve_from_llm_none_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        executive_ticker_resolver,
        "confirm_ticker_symbol",
        lambda symbol, description, llm_name=None: None,
    )
    ollama = _FakeOllama('{"ticker": "FAKE", "confidence": 0.99}')
    assert resolve_from_llm("AAR CORP", ollama_client=ollama) is None


def test_resolve_from_llm_raises_on_empty_response() -> None:
    # generate_completion swallows infra errors and returns None -> transient.
    ollama = _FakeOllama(None)
    with pytest.raises(LLMResolutionError):
        resolve_from_llm("AAR CORP", ollama_client=ollama)


def test_resolve_from_llm_raises_on_client_exception() -> None:
    ollama = _FakeOllama(RuntimeError("connection refused"))
    with pytest.raises(LLMResolutionError):
        resolve_from_llm("AAR CORP", ollama_client=ollama)


class _RpcResult:
    def __init__(self, calls: list[tuple[str, dict]], name: str, params: dict) -> None:
        calls.append((name, params))

    def execute(self) -> object:
        class _R:
            data = [{"id": "task-1"}]

        return _R()


class _FakeInner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, params: dict) -> _RpcResult:
        return _RpcResult(self.calls, name, params)


class _FakeSupabaseForEnqueue:
    def __init__(self) -> None:
        self.supabase = _FakeInner()


def test_enqueue_executive_ticker_tasks_builds_tasks() -> None:
    from scheduler.ai_task_workers import (
        QUEUE_JOB_EXECUTIVE_TICKER_RESOLVE,
        enqueue_executive_ticker_tasks,
    )

    client = _FakeSupabaseForEnqueue()
    stats = enqueue_executive_ticker_tasks(
        client,
        [("AAR", "AAR CORP", 0), ("", "skip me", 0)],
    )
    assert stats == {"attempted": 2, "enqueued": 1, "failed": 1}
    assert len(client.supabase.calls) == 1
    name, params = client.supabase.calls[0]
    assert name == "enqueue_ai_task"
    assert params["p_analysis_type"] == QUEUE_JOB_EXECUTIVE_TICKER_RESOLVE
    assert params["p_target_key"] == "AAR"
    assert params["p_payload"]["description"] == "AAR CORP"


def _load_enqueue_script() -> types.ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "web_dashboard"
        / "scripts"
        / "enqueue_executive_ticker_resolution.py"
    )
    spec = importlib.util.spec_from_file_location("_enqueue_exec_ticker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collect_unresolved_names_dedupes_and_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_enqueue_script()
    transactions = [
        {"description": "BANK OF AMERICA CORPORATION - BAC", "ticker": "BAC"},
        {"description": "TARRANT REGL WTR DIST TE RV BE/R/ 5 DUE 030134"},
        {"description": "ACME WIDGETS INC"},
        {"description": "ACME WIDGETS INC CLASS A"},
        {"description": ""},
    ]
    names = module.collect_unresolved_names(
        transactions, cache={}, use_yfinance=False
    )
    # BAC resolves (open_cabinet), bond skipped, the two ACME rows collapse to one.
    assert len(names) == 1
    canonical, description, priority = names[0]
    assert "ACME" in canonical
    assert priority == 0


def test_process_executive_transactions_batches_upserts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "executive_ticker_resolver.resolve_from_securities",
        lambda company_name: None,
    )

    upsert_calls: list[tuple[str, list]] = []

    class _Table:
        def __init__(self, name: str) -> None:
            self.name = name

        def select(self, *_args: object, **_kwargs: object) -> "_Table":
            return self

        def upsert(self, rows: list, on_conflict: str = "") -> "_Table":
            upsert_calls.append((self.name, list(rows)))
            return self

        def execute(self) -> MagicMock:
            result = MagicMock()
            result.data = []
            return result

    class _Client:
        def __init__(self) -> None:
            self.supabase = MagicMock()
            self.supabase.table.side_effect = lambda name: _Table(name)

    client = _Client()
    transactions = [
        {
            "description": "BANK OF AMERICA CORPORATION - BAC",
            "ticker": "BAC",
            "type": "Purchase",
            "date": "2026-03-18",
            "amount": "$1,001 - $15,000",
        },
        {
            "description": "AAR CORP",
            "ticker": None,
            "type": "Purchase",
            "date": "2026-03-18",
            "amount": "$1,001 - $15,000",
        },
        {
            # Same conflict key as first — counts as in-batch duplicate.
            "description": "BANK OF AMERICA CORPORATION - BAC",
            "ticker": "BAC",
            "type": "Purchase",
            "date": "2026-03-18",
            "amount": "$1,001 - $15,000",
        },
    ]

    # Pretend AAR resolves via open_cabinet once we force a ticker.
    transactions[1]["ticker"] = "AIR"

    stats = process_executive_transactions(
        client,
        transactions,
        politician_id=999,
        party="Republican",
        state="US",
        dry_run=False,
    )

    assert stats["inserted"] == 2  # unique conflict keys
    assert stats["duplicates"] == 1
    tables = [name for name, _ in upsert_calls]
    assert "congress_trades" in tables
    congress_batches = [rows for name, rows in upsert_calls if name == "congress_trades"]
    assert len(congress_batches) == 1
    assert len(congress_batches[0]) == 2


def test_congress_trades_template_includes_executive_chamber() -> None:
    template_path = (
        Path(__file__).resolve().parents[1]
        / "web_dashboard"
        / "templates"
        / "congress_trades.html"
    )
    content = template_path.read_text(encoding="utf-8")
    assert 'value="Executive"' in content
