import pytest
from flask import Flask
from web_dashboard.routes.admin_routes import remove_closed_position_from_watchlist

# Mock client and classes
class _Result:
    def __init__(self, data):
        self.data = data

class _Query:
    def __init__(self, data):
        self.data = data
    def select(self, *a, **k):
        return self
    def eq(self, *a, **k):
        return self
    def execute(self):
        return _Result(self.data)

class _Supabase:
    def __init__(self, trades, watch):
        self.trades = trades
        self.watch = watch
    def table(self, name):
        if name == "trade_log":
            return _Query(self.trades)
        return _Query(self.watch)

class _MockClient:
    def __init__(self, trades, watch):
        self.supabase = _Supabase(trades, watch)

def test_edit_to_zero_removes_from_watchlist(monkeypatch):
    trades = [
        {"fund": "F1", "action": "BUY", "shares": 10},
        {"fund": "F1", "action": "SELL", "shares": 10}  # Net is 0
    ]
    watch = [
        {"fund": "F1", "source": "TRADELOG", "is_active": True}
    ]

    removed_calls = []
    def mock_set_active(client, fund, ticker, is_active):
        removed_calls.append(fund)
        return {"ok": True}

    monkeypatch.setattr("web_dashboard.routes.admin_routes.set_watchlist_active", mock_set_active, raising=False)
    monkeypatch.setattr("web_dashboard.routes.admin_routes.WATCHLIST_V2_TABLE", "watchlist_v2", raising=False)
    monkeypatch.setattr("watchlist_access.set_watchlist_active", mock_set_active, raising=False)
    monkeypatch.setattr("watchlist_access.WATCHLIST_V2_TABLE", "watchlist_v2", raising=False)

    client = _MockClient(trades, watch)
    result = remove_closed_position_from_watchlist(client, "F1", "AAPL")

    assert result == ["F1"]
    assert removed_calls == ["F1"]

def test_delete_buy_leaving_net_negative_or_zero_removes_from_watchlist(monkeypatch):
    trades = [
        {"fund": "F1", "action": "SELL", "shares": 10}  # Net is -10 (or 0 if we consider it closed)
    ]
    watch = [
        {"fund": "F1", "source": "TRADELOG", "is_active": True}
    ]

    removed_calls = []
    def mock_set_active(client, fund, ticker, is_active):
        removed_calls.append(fund)
        return {"ok": True}

    monkeypatch.setattr("web_dashboard.routes.admin_routes.set_watchlist_active", mock_set_active, raising=False)
    monkeypatch.setattr("web_dashboard.routes.admin_routes.WATCHLIST_V2_TABLE", "watchlist_v2", raising=False)
    monkeypatch.setattr("watchlist_access.set_watchlist_active", mock_set_active, raising=False)
    monkeypatch.setattr("watchlist_access.WATCHLIST_V2_TABLE", "watchlist_v2", raising=False)

    client = _MockClient(trades, watch)
    result = remove_closed_position_from_watchlist(client, "F1", "AAPL")

    assert result == ["F1"]
    assert removed_calls == ["F1"]
