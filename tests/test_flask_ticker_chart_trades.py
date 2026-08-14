"""Ticker chart user-trade markers must follow trade_log.action, not a 'SELL' substring."""
from __future__ import annotations

import pandas as pd

from chart_utils import create_ticker_price_chart


def _price_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-10", "2026-08-11", "2026-08-12"]),
            "price": [10.0, 11.0, 12.0],
            "normalized": [100.0, 110.0, 120.0],
        }
    )


def _trace_names(fig) -> list[str]:
    return [str(trace.name) for trace in fig.data]


def test_ticker_chart_buy_not_labeled_sell_when_reason_mentions_selloff() -> None:
    trades = [
        {
            "date": "2026-08-11",
            "shares": 100,
            "price": 11.0,
            "action": "BUY",
            "reason": "After the sell-off, adding WEB.V",
            "fund": "TEST",
        }
    ]
    fig = create_ticker_price_chart(
        _price_df(),
        "WEB.V",
        show_benchmarks=None,
        show_weekend_shading=False,
        user_trades=trades,
    )
    names = _trace_names(fig)
    assert "My Buy" in names
    assert "My Sell" not in names


def test_ticker_chart_sell_when_action_is_sell() -> None:
    trades = [
        {
            "date": "2026-08-12",
            "shares": 50,
            "price": 12.0,
            "action": "SELL",
            "reason": "Taking profits",
            "fund": "TEST",
        }
    ]
    fig = create_ticker_price_chart(
        _price_df(),
        "WEB.V",
        show_benchmarks=None,
        show_weekend_shading=False,
        user_trades=trades,
    )
    names = _trace_names(fig)
    assert "My Sell" in names
    assert "My Buy" not in names


def test_ticker_chart_plots_buy_before_later_sell() -> None:
    trades = [
        {
            "date": "2026-08-12",
            "shares": 50,
            "price": 12.0,
            "action": "SELL",
            "reason": "Trim",
            "fund": "TEST",
        },
        {
            "date": "2026-08-10",
            "shares": 100,
            "price": 10.0,
            "action": "BUY",
            "reason": "Initial buy",
            "fund": "TEST",
        },
    ]
    fig = create_ticker_price_chart(
        _price_df(),
        "WEB.V",
        show_benchmarks=None,
        show_weekend_shading=False,
        user_trades=trades,
    )
    marker_names = [n for n in _trace_names(fig) if n in ("My Buy", "My Sell")]
    assert marker_names == ["My Buy", "My Sell"]
