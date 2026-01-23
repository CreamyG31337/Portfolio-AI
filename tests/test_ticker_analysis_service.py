import types

import web_dashboard.ticker_analysis_service as ticker_analysis_service
from web_dashboard.ticker_analysis_service import TickerAnalysisService


class DummySkipList:
    def should_skip(self, _ticker: str) -> bool:
        return False

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
