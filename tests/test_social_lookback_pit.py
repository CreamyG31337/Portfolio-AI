"""Social lookback honesty (AQuA transfer Phase 1)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from ticker_analysis_service import TickerAnalysisService


def test_get_social_sentiment_honors_start_date_lookback() -> None:
    svc = object.__new__(TickerAnalysisService)
    svc.postgres = MagicMock()
    svc.postgres.execute_query.side_effect = [[], []]

    start = datetime(2025, 6, 1, tzinfo=timezone.utc)
    with patch("pit_time.social_as_of_expr", return_value="COALESCE(available_at, created_at)"):
        svc._get_social_sentiment("ABCD", start)

    assert svc.postgres.execute_query.call_count == 2
    latest_sql, latest_params = svc.postgres.execute_query.call_args_list[0][0]
    assert "COALESCE(available_at, created_at) >= %s" in latest_sql.replace("\n", " ")
    assert latest_params[1] == start.isoformat()
