import types

import pytest

import web_dashboard.ticker_analysis_service as ticker_analysis_service
from web_dashboard.ticker_analysis_service import (
    TickerAnalysisService,
    _normalize_score,
    _normalize_stance,
    _truncate_text,
)


class DummySkipList:
    def __init__(self, banned: set[str] | None = None) -> None:
        self.banned = set(banned or ())

    def should_skip(self, ticker: str) -> bool:
        return ticker.upper() in self.banned

    def record_failure(self, _ticker: str, _error: str) -> None:
        return None

    def remove_from_skip_list(self, _ticker: str) -> None:
        return None


class DummySupabaseTable:
    def __init__(self, parent, name: str) -> None:
        self.parent = parent
        self.name = name
        self._update_payload = None

    def select(self, *_args, **_kwargs):
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self._update_payload is not None:
            self.parent.updated = self._update_payload
            return types.SimpleNamespace(data=[{"ticker": "TSLA"}])
        return types.SimpleNamespace(data=self.parent.data)


class DummySupabaseClient:
    def __init__(self, data):
        self.data = data
        self.updated = None

    def table(self, name: str):
        return DummySupabaseTable(self, name)


class DummySupabaseWrapper:
    def __init__(self, data):
        self.supabase = DummySupabaseClient(data)


def test_format_signals_uses_schema_fields():
    service = TickerAnalysisService(
        ollama=None,
        supabase=DummySupabaseWrapper([]),
        postgres=None,
        skip_list=DummySkipList()
    )
    signals = {
        "overall_signal": "WATCH",
        "confidence_score": 0.0,
        "structure_signal": {
            "trend": "UPTREND",
            "pullback": False,
            "breakout": False
        },
        "timing_signal": {
            "volume_ok": True,
            "rsi": 37.8,
            "cci": 0.0
        },
        "fear_risk_signal": {
            "fear_level": "LOW",
            "risk_score": 0.0,
            "recommendation": "SAFE"
        }
    }

    text = service._format_signals(signals)

    assert "Overall Signal: WATCH (Confidence: 0%)" in text
    assert "Structure - Trend: UPTREND, Pullback: False, Breakout: False" in text
    assert "Timing - Volume: OK, RSI: 37.8, CCI: 0.0" in text
    assert "Fear & Risk - Level: LOW, Score: 0.0/100, Rec: SAFE" in text


def test_get_fundamentals_refreshes_missing_fields(monkeypatch):
    data = [{
        "ticker": "TSLA",
        "trailing_pe": None,
        "dividend_yield": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None
    }]
    supabase = DummySupabaseWrapper(data)

    class FakeTicker:
        def __init__(self, info):
            self.info = info

    class FakeYF:
        def Ticker(self, _ticker: str):
            return FakeTicker({
                "trailingPE": 303.8,
                "dividendYield": 0.0,
                "fiftyTwoWeekHigh": 498.83,
                "fiftyTwoWeekLow": 214.25
            })

    monkeypatch.setattr(ticker_analysis_service, "HAS_YFINANCE", True)
    monkeypatch.setattr(ticker_analysis_service, "yf", FakeYF())

    service = TickerAnalysisService(
        ollama=None,
        supabase=supabase,
        postgres=None,
        skip_list=DummySkipList()
    )

    fundamentals = service._get_fundamentals("TSLA")

    assert fundamentals is not None
    assert fundamentals["trailing_pe"] == 303.8
    assert fundamentals["fifty_two_week_high"] == 498.83
    assert supabase.supabase.updated is not None
    assert supabase.supabase.updated["trailing_pe"] == 303.8


class _RangeQuery:
    """Minimal Supabase-style query that supports .select().range().execute()."""

    def __init__(self, rows):
        self._rows = rows
        self._start = 0
        self._end = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def in_(self, column, values):
        self._rows = [r for r in self._rows if r.get(column) in values]
        return self

    def range(self, start, end):
        self._start = start
        self._end = end
        return self

    def execute(self):
        if self._end is None:
            return types.SimpleNamespace(data=self._rows)
        return types.SimpleNamespace(data=self._rows[self._start:self._end + 1])


class _RangeSupabaseRaw:
    def __init__(self, holdings_rows, manual_rows=None, funds_rows=None):
        self._holdings = holdings_rows
        self._manual = manual_rows or []
        self._funds = funds_rows or []

    def table(self, name):
        if name == "portfolio_positions":
            return _RangeQuery(list(self._holdings))
        if name == "ai_analysis_queue":
            return _RangeQuery(list(self._manual))
        if name == "funds":
            return _RangeQuery(list(self._funds))
        return _RangeQuery([])


class _RangeSupabaseWrapper:
    def __init__(self, holdings_rows, manual_rows=None, funds_rows=None):
        self.supabase = _RangeSupabaseRaw(holdings_rows, manual_rows, funds_rows)


class _StubPostgres:
    def execute_query(self, *_a, **_k):
        return []


def _make_service(holdings_rows, skip_list, monkeypatch, funds_rows=None):
    monkeypatch.setattr(
        ticker_analysis_service,
        "get_active_watchlist_tickers",
        lambda *_a, **_k: [],
    )
    return TickerAnalysisService(
        ollama=None,
        supabase=_RangeSupabaseWrapper(holdings_rows, funds_rows=funds_rows),
        postgres=_StubPostgres(),
        skip_list=skip_list,
    )


def test_get_tickers_to_analyze_paginates_beyond_1000(monkeypatch):
    holdings = [{"ticker": f"T{i:05d}"} for i in range(2500)]
    service = _make_service(holdings, DummySkipList(), monkeypatch)

    tickers = service.get_tickers_to_analyze()

    assert len(tickers) == 2500, "must paginate past Supabase's 1000-row default"
    assert service.last_selection_stats["holdings_candidates"] == 2500
    assert service.last_selection_stats["selected"] == 2500


def test_get_tickers_to_analyze_filters_holdings_to_production_funds(monkeypatch):
    """Fixture positions from TEST_* funds must not reach the nightly LLM run.

    Observed 2026-06-10: test-suite leftovers (STOCK1, FIFO, ...) in prod
    portfolio_positions were analyzed with real models and polluted the
    brand-new stance_history ledger.
    """
    holdings = [
        {"ticker": "REAL1", "fund": "Project Chimera"},
        {"ticker": "STOCK1", "fund": "TEST_fund_abc123"},
        {"ticker": "FIFO", "fund": "TEST_fund_def456"},
    ]
    funds = [{"name": "Project Chimera"}]
    service = _make_service(holdings, DummySkipList(), monkeypatch, funds_rows=funds)

    tickers = service.get_tickers_to_analyze()

    assert [t for t, _ in tickers] == ["REAL1"]
    assert service.last_selection_stats["holdings_candidates"] == 1


def test_get_tickers_to_analyze_unfiltered_when_funds_lookup_empty(monkeypatch):
    """If the funds table is unreadable/empty, fall back to all holdings."""
    holdings = [
        {"ticker": "AAA", "fund": "Project Chimera"},
        {"ticker": "BBB", "fund": "TEST_fund_abc123"},
    ]
    service = _make_service(holdings, DummySkipList(), monkeypatch, funds_rows=[])

    tickers = service.get_tickers_to_analyze()

    assert [t for t, _ in tickers] == ["AAA", "BBB"]


def test_get_tickers_to_analyze_reports_skip_list_filtering(monkeypatch):
    holdings = [{"ticker": "AAA"}, {"ticker": "BBB"}, {"ticker": "CCC"}]
    service = _make_service(holdings, DummySkipList(banned={"AAA", "BBB"}), monkeypatch)

    tickers = service.get_tickers_to_analyze()

    assert [t for t, _ in tickers] == ["CCC"]
    stats = service.last_selection_stats
    assert stats["holdings_candidates"] == 3
    assert stats["filtered_by_skip_list"] == 2
    assert stats["selected"] == 1


def test_extract_ticker_analysis_audit_fields_pulls_sentiment_from_json():
    """The audit-field extractor passed to the chain must surface sentiment.

    Replaces the old ``_log_ticker_analysis_audit`` test; that helper was
    removed once ``collect_with_summary_model_chain`` started writing the
    audit row centrally (so GLM fallback attempts get audited too).
    """
    from ticker_analysis_service import _extract_ticker_analysis_audit_fields

    fields = _extract_ticker_analysis_audit_fields(
        '{"sentiment": "BULLISH", "summary": "Constructive setup"}'
    )
    assert fields == {"sentiment": "BULLISH"}


def test_extract_ticker_analysis_audit_fields_handles_garbage_input():
    """Non-JSON / empty responses must return an empty enrichment dict, not raise."""
    from ticker_analysis_service import _extract_ticker_analysis_audit_fields

    assert _extract_ticker_analysis_audit_fields("not json at all") == {}
    assert _extract_ticker_analysis_audit_fields("") == {}
    assert _extract_ticker_analysis_audit_fields('{"unrelated": "field"}') == {}


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("not a number", None),
        (0.42, 0.42),
        (-0.7, -0.7),
        (1.0, 1.0),
        (-1.0, -1.0),
        (50, 0.5),
        (-30, -0.3),
        (250, 1.0),
        (-250, -1.0),
        ("0.85", 0.85),
        (1.5, 1.0),
    ],
)
def test_normalize_score_handles_llm_output_shapes(raw, expected):
    result = _normalize_score(raw)
    if expected is None:
        assert result is None
    else:
        assert pytest.approx(expected, rel=1e-6) == result


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("BUY", "BUY"),
        ("sell", "SELL"),
        ("Hold", "HOLD"),
        ("AVOID", "AVOID"),
        ("strong BUY recommendation", "BUY"),
        ("watch", None),
        ("BUY THE DIP NOW", "BUY"),
    ],
)
def test_normalize_stance(raw, expected):
    assert _normalize_stance(raw) == expected


def test_truncate_text_clips_long_values():
    assert _truncate_text(None, 10) is None
    assert _truncate_text("", 10) is None
    assert _truncate_text("  hi  ", 10) == "hi"
    assert _truncate_text("short", 10) == "short"
    long_str = "a" * 200
    assert _truncate_text(long_str, 60) == "a" * 60
    assert _truncate_text(
        "1-2 weeks short-term swing trade horizon waiting for breakout", 20
    ) == "1-2 weeks short-term"
