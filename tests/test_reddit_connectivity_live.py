"""Live Reddit connectivity canary (RSS by default, OAuth if configured)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_dashboard"
if str(WEB_DASHBOARD_PATH) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_PATH))


@pytest.mark.live_reddit
def test_reddit_api_reachable() -> None:
    from reddit_client import check_reddit_connectivity, reset_reddit_client

    reset_reddit_client()
    status = check_reddit_connectivity()
    if status.rate_limited:
        pytest.skip(f"Reddit temporarily rate limited during live canary: {status.message}")
    assert status.ok, status.message
    assert not status.rate_limited
