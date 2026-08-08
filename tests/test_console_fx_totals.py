"""Regression tests for console FX-aware portfolio totals."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from show_prompt import calculate_position_metrics  # noqa: E402


def test_show_prompt_converts_usd_positions_for_totals():
    df = pd.DataFrame(
        {
            "ticker": ["AAA.TO", "BBB"],
            "shares": [10.0, 10.0],
            "buy_price": [10.0, 10.0],
            "current_price": [12.0, 12.0],
            "currency": ["CAD", "USD"],
            "daily_pnl": ["$0.00", "$0.00"],
        }
    )
    # CAD: 120 value / 20 pnl; USD: 120 value / 20 pnl -> CAD equiv at 1.25 = 150 / 25
    rates = {"USD": 1.25}

    with patch("utils.currency_converter.load_exchange_rates", return_value=rates), patch(
        "utils.currency_converter.convert_usd_to_cad",
        side_effect=lambda amount, _rates: float(amount) * 1.25,
    ):
        enhanced, total = calculate_position_metrics(df, 0.0, data_dir=Path("."))

    assert abs(total - 270.0) < 1e-6  # 120 + 150
    assert abs(float(enhanced["Total_PnL_Amount"].sum()) - 45.0) < 1e-6  # 20 + 25
