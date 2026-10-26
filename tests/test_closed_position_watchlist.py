"""A SELL that closes a position removes the ticker from the watchlist."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch


class _Query:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows
        self._filters: list[tuple[str, Any]] = []

    def select(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def eq(self, col: str, val: Any) -> "_Query":
        self._filters.append((col, val))
        return self

    def execute(self) -> Any:
        data = [r for r in self._rows if all(r.get(c) == v for c, v in self._filters)]
        return type("R", (), {"data": data})()


class _Client:
    def __init__(self, trades: list[dict[str, Any]], watch: list[dict[str, Any]]):
        self.trades = trades
        self.watch = watch
        outer = self

        class _Supabase:
            def table(self, name: str) -> _Query:
                return _Query(outer.trades if name == "trade_log" else outer.watch)

        self.supabase = _Supabase()


def _run(trades: list[dict[str, Any]], watch: list[dict[str, Any]], fund: str = "Chimera") -> tuple[list[str], list[str]]:
    from routes.admin_routes import remove_closed_position_from_watchlist

    deactivated: list[str] = []

    def fake_set_active(_client: Any, *, fund: str, ticker: str, is_active: bool) -> dict[str, Any]:
        assert is_active is False
        deactivated.append(fund)
        return {"ok": True}

    with patch("watchlist_access.set_watchlist_active", side_effect=fake_set_active):
        removed = remove_closed_position_from_watchlist(_Client(trades, watch), fund, "GLO.TO")
    return removed, deactivated


def _t(fund: str, action: str, shares: float) -> dict[str, Any]:
    return {"fund": fund, "ticker": "GLO.TO", "action": action, "shares": shares, "reason": ""}


def _w(fund: str, source: str = "TRADELOG") -> dict[str, Any]:
    return {"fund": fund, "ticker": "GLO.TO", "source": source, "is_active": True}


def test_full_sell_removes_selling_fund_and_tradelog_rows_elsewhere() -> None:
    trades = [_t("Chimera", "BUY", 735.2941), _t("Chimera", "SELL", 735.2941)]
    removed, _ = _run(trades, [_w("Chimera"), _w("TFSA"), _w("RRSP")])
    assert sorted(removed) == ["Chimera", "RRSP", "TFSA"]


def test_partial_sell_keeps_watchlist() -> None:
    trades = [_t("Chimera", "BUY", 100), _t("Chimera", "SELL", 60)]
    removed, deactivated = _run(trades, [_w("Chimera")])
    assert removed == [] and deactivated == []


def test_drip_shares_count_as_held() -> None:
    # Sold the original lot but DRIP shares remain: not closed.
    trades = [_t("Chimera", "BUY", 100), _t("Chimera", "DIVIDEND", 0.25), _t("Chimera", "SELL", 100)]
    removed, _ = _run(trades, [_w("Chimera")])
    assert removed == []


def test_float_dust_counts_as_closed() -> None:
    trades = [_t("Chimera", "BUY", 10.1), _t("Chimera", "BUY", 0.2), _t("Chimera", "SELL", 10.3)]
    removed, _ = _run(trades, [_w("Chimera")])
    assert removed == ["Chimera"]


def test_other_fund_still_holding_keeps_its_row() -> None:
    trades = [_t("Chimera", "BUY", 50), _t("Chimera", "SELL", 50), _t("TFSA", "BUY", 20)]
    removed, _ = _run(trades, [_w("Chimera"), _w("TFSA")])
    assert removed == ["Chimera"]


def test_deliberate_watch_in_other_fund_is_kept() -> None:
    trades = [_t("Chimera", "BUY", 50), _t("Chimera", "SELL", 50)]
    removed, _ = _run(trades, [_w("Chimera"), _w("TFSA", source="watchlist_ui")])
    assert removed == ["Chimera"]


def test_errors_never_raise() -> None:
    from routes.admin_routes import remove_closed_position_from_watchlist

    class _Broken:
        @property
        def supabase(self) -> Any:
            raise RuntimeError("db down")

    assert remove_closed_position_from_watchlist(_Broken(), "Chimera", "GLO.TO") == []


def _trade(ticker: str, action: str, shares: float) -> dict[str, Any]:
    return {"ticker": ticker, "action": action, "shares": shares, "reason": ""}


def test_edit_and_delete_check_only_tickers_that_lost_shares() -> None:
    from routes.admin_routes import _tickers_with_fewer_shares as fewer

    buy = _trade("GLO.TO", "BUY", 100)
    assert fewer(buy) == ["GLO.TO"]                                    # delete a BUY
    assert fewer(_trade("GLO.TO", "SELL", 100)) == []                  # delete a SELL adds shares back
    assert fewer(buy, _trade("glo.to", "BUY", 40)) == ["GLO.TO"]       # BUY cut
    assert fewer(buy, _trade("GLO.TO", "BUY", 150)) == []              # BUY raised
    assert fewer(buy, _trade("GLO.TO", "SELL", 100)) == ["GLO.TO"]     # BUY flipped to SELL
    assert fewer(buy, _trade("GLO.TO", "BUY", 100)) == []              # price/date-only edit
    assert fewer(buy, _trade("KO", "BUY", 100)) == ["GLO.TO"]          # ticker typo fixed: old one lost the lot
    assert fewer(_trade("GLO.TO", "SELL", 10), _trade("KO", "SELL", 10)) == ["KO"]

def test_negative_shares_oversell_counts_as_closed() -> None:
    trades = [_t("Chimera", "BUY", 100), _t("Chimera", "SELL", 120)]
    removed, deactivated = _run(trades, [_w("Chimera"), _w("TFSA")])
    assert sorted(removed) == ["Chimera", "TFSA"]
