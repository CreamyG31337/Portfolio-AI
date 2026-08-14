"""Ticker-chart benchmark cache must cover the requested start, not only a fresh end."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

from chart_utils import _benchmark_cache_covers_window, _fetch_benchmark_data
from scheduler.jobs_metrics import BENCHMARK_REFRESH_LOOKBACK_DAYS


def test_benchmark_refresh_lookback_covers_five_years() -> None:
    assert BENCHMARK_REFRESH_LOOKBACK_DAYS == 1825


def test_cache_covers_window_requires_start() -> None:
    end = datetime(2026, 8, 13)
    start = end - timedelta(days=1825)
    short = pd.DataFrame(
        {
            "Date": pd.date_range(end=end, periods=400, freq="D"),
            "Close": 1.0,
        }
    )
    assert not _benchmark_cache_covers_window(short, start, end)

    full = pd.DataFrame(
        {
            "Date": pd.date_range(end=end, periods=1825, freq="D"),
            "Close": 1.0,
        }
    )
    assert _benchmark_cache_covers_window(full, start, end)


def test_cache_covers_window_rejects_stale_end() -> None:
    end = datetime(2026, 8, 13)
    start = end - timedelta(days=90)
    data = pd.DataFrame(
        {
            "Date": pd.date_range(end=end - timedelta(days=10), periods=90, freq="D"),
            "Close": 1.0,
        }
    )
    assert not _benchmark_cache_covers_window(data, start, end)


def _cached_rows(start: datetime, end: datetime) -> list[dict]:
    rows: list[dict] = []
    for day in pd.date_range(start=start, end=end, freq="D"):
        rows.append(
            {
                "date": day.isoformat(),
                "close": 100.0,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "volume": 1,
            }
        )
    return rows


def test_fetch_benchmark_data_yahoo_fills_missing_start() -> None:
    end = datetime(2026, 8, 13)
    start = end - timedelta(days=1825)
    client = MagicMock()
    client.get_benchmark_data.return_value = _cached_rows(end - timedelta(days=399), end)

    yahoo_idx = pd.date_range(
        start=start - timedelta(days=5),
        end=end + timedelta(days=1),
        freq="B",
    )
    yahoo_df = pd.DataFrame(
        {
            "Close": [200.0 + i for i in range(len(yahoo_idx))],
            "Open": 200.0,
            "High": 201.0,
            "Low": 199.0,
            "Volume": 1,
        },
        index=yahoo_idx,
    )
    yahoo_df.index.name = "Date"

    with patch("chart_utils.yf.download", return_value=yahoo_df) as download:
        result = _fetch_benchmark_data("^GSPC", start, end, client=client)

    download.assert_called_once()
    assert result is not None
    assert not result.empty
    assert result["Date"].min() < pd.Timestamp(end) - pd.Timedelta(days=500)
    client.cache_benchmark_data.assert_called()


def test_fetch_benchmark_data_uses_cache_when_window_covered() -> None:
    end = datetime(2026, 8, 13)
    start = end - timedelta(days=90)
    client = MagicMock()
    client.get_benchmark_data.return_value = _cached_rows(start, end)

    with patch("chart_utils.yf.download") as download:
        result = _fetch_benchmark_data("^GSPC", start, end, client=client)

    download.assert_not_called()
    assert result is not None
    assert not result.empty
    assert result["normalized"].iloc[0] == 100.0
