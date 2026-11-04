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


NEXT = "<script>self.__next_f.push([1,'x'])</script>"
SHELL_429 = "<html><body>Too Many Requests</body></html>"


def _run(seed, monkeypatch, pages, *, months_back=11, start_page=1):
    """Drive the real page loop over fake pages: (html, [tx dates]) per fetch."""
    from unittest.mock import MagicMock

    fetched: list[int] = []
    queue = list(pages)

    def fake_fetch(url: str):
        fetched.append(int(url.rsplit("page=", 1)[1]))
        html, _ = queue[0] if len(queue) == 1 else queue.pop(0)
        fake_fetch.current = queue[0] if len(queue) == 1 else None
        fake_fetch.last = (html, _)
        return html

    def fake_extract(html: str):
        dates = fake_fetch.last[1]
        return [{"tx": d} for d in dates]

    monkeypatch.setattr(seed, "get_web_fetch_client", lambda: MagicMock(check_health=lambda: False))
    monkeypatch.setattr(seed, "fetch_page_direct", fake_fetch)
    monkeypatch.setattr(seed, "extract_trade_data_from_html", fake_extract)
    monkeypatch.setattr(seed, "map_trade_to_schema", lambda tr: {"transaction_date": tr["tx"]})
    monkeypatch.setattr(seed.time, "sleep", lambda _s: None)
    import supabase_client

    monkeypatch.setattr(supabase_client, "SupabaseClient", lambda **_k: MagicMock())
    ok = seed.seed_congress_trades(months_back=months_back, start_page=start_page)
    return ok, fetched


def test_429_shell_is_retried_not_treated_as_end_of_data(seed, monkeypatch) -> None:
    recent = ["2026-10-01"]
    pages = [(NEXT, recent), (SHELL_429, []), (SHELL_429, []), (NEXT, recent), (NEXT, [])]
    ok, fetched = _run(seed, monkeypatch, pages)
    assert ok is True
    assert fetched == [1, 2, 2, 2, 3]  # page 2 retried until it came back


def test_persistent_block_fails_the_run(seed, monkeypatch) -> None:
    ok, fetched = _run(seed, monkeypatch, [(NEXT, ["2026-10-01"]), (SHELL_429, [])])
    assert ok is False
    assert fetched == [1, 2, 2, 2, 2]  # 1 try + 3 backoff retries, then give up


def test_one_old_page_does_not_stop_but_three_do(seed, monkeypatch) -> None:
    new, old = ["2026-10-01"], ["2024-10-29"]
    pages = [(NEXT, new), (NEXT, old), (NEXT, new), (NEXT, old), (NEXT, old), (NEXT, old), (NEXT, new)]
    ok, fetched = _run(seed, monkeypatch, pages)
    assert ok is True
    assert fetched == [1, 2, 3, 4, 5, 6]


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
