"""Congress backfill: the scraper must not stop at the first late filing, and the
post-scrape session backfill must be importable."""

from __future__ import annotations

import importlib
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "web_dashboard" / "scripts"


@pytest.fixture()
def seed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONGRESS_TRADES_BASE_URL", "https://example.com/trades")
    monkeypatch.syspath_prepend(str(_SCRIPTS))
    sys.modules.pop("seed_congress_trades", None)
    return importlib.import_module("seed_congress_trades")


def test_late_filing_on_a_page_does_not_end_the_backfill(seed) -> None:
    cutoff = datetime(2025, 12, 8)
    # A recent page whose oldest trade is a 2024 late filing: keep going.
    assert seed.reached_cutoff(date(2026, 10, 30), cutoff) is False
    # Only a page that is entirely before the cutoff stops it.
    assert seed.reached_cutoff(date(2025, 11, 30), cutoff) is True
    assert seed.reached_cutoff(None, cutoff) is False
    assert seed.reached_cutoff(date(2001, 1, 1), None) is False


def test_session_backfill_imports_grouping_from_web_dashboard() -> None:
    src = (_SCRIPTS / "backfill_congress_sessions.py").read_text()
    assert "\nfrom utils.grouping import" not in src  # root `utils` shadows web_dashboard/utils
    from web_dashboard.utils.grouping import get_politician_sessions

    assert callable(get_politician_sessions)
