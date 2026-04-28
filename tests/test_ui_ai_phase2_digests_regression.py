from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from ui_ai_phase2_digests import build_dashboard_commodities_digest, build_dashboard_currency_digest  # noqa: E402


def test_build_dashboard_commodities_digest_handles_close_dataframe(monkeypatch):
    cols = pd.MultiIndex.from_tuples([("Close", "GC=F"), ("Open", "GC=F")])
    hist = pd.DataFrame([[100.0, 99.0], [105.0, 104.0]], columns=cols)

    monkeypatch.setattr("ui_ai_phase2_digests.yf.download", lambda *args, **kwargs: hist)

    digest = build_dashboard_commodities_digest(days=30)

    assert "gold" in digest["series"]
    assert digest["series"]["gold"]["start"] == 100.0
    assert digest["series"]["gold"]["end"] == 105.0
    assert digest["series"]["gold"]["points"] == 2


def test_build_dashboard_currency_digest_uses_supabase_client_paths(monkeypatch):
    class _Client:
        def __init__(self, use_service_role=True):
            self._use_service_role = use_service_role

        def get_current_positions(self, fund):
            return [
                {"currency": "USD", "market_value": 100.0},
                {"currency": "CAD", "market_value": 300.0},
            ]

        def get_cash_balances(self, fund):
            return {"USD": 50.0, "CAD": 25.0}

    class _Fx:
        @staticmethod
        def get_exchange_rates(_start, _end, _from, _to):
            return [{"rate": 1.30}, {"rate": 1.35}]

    monkeypatch.setattr("ui_ai_phase2_digests.SupabaseClient", _Client)
    monkeypatch.setattr("ui_ai_phase2_digests.get_fx_supabase_client", lambda use_service_role=True: _Fx())

    digest = build_dashboard_currency_digest(fund="TEST")

    assert digest["fund"] == "TEST"
    assert digest["currency_exposure"]["USD"] == 150.0
    assert digest["currency_exposure"]["CAD"] == 325.0
    assert digest["usd_cad_30d_change_pct"] == 3.846
