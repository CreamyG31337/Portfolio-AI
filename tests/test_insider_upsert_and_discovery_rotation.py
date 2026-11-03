"""Regression tests for two jobs that reported success while saving ~nothing.

- insider_trades: one batched upsert of the whole page failed whenever the page repeated
  a conflict key, dropping every trade (2026-08..11).
- opportunity_discovery: hour-based query rotation on a once-a-day job ran the same
  query forever (2026-07..11).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from scheduler.jobs_insiders import _dedupe_insider_records, _upsert_insider_trades


def _rec(ticker: str, name: str = "Doe Jane", shares: int = 100, price: float = 2.5) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "insider_name": name,
        "transaction_date": "2026-11-02",
        "type": "Purchase",
        "shares": shares,
        "price_per_share": price,
    }


class _Table:
    def __init__(self, db: "_FakeSupabase") -> None:
        self.db = db
        self.rows: list[dict[str, Any]] = []

    def upsert(self, rows: list[dict[str, Any]], on_conflict: str) -> "_Table":
        self.rows = rows
        return self

    def execute(self) -> Any:
        self.db.calls.append(len(self.rows))
        keys = [tuple(sorted(r.items())) for r in self.rows]
        if len(keys) != len(set(keys)):
            raise RuntimeError("ON CONFLICT DO UPDATE command cannot affect row a second time")
        if any(r["ticker"] == "BAD" for r in self.rows):
            raise RuntimeError("bad row")
        return type("R", (), {"data": list(self.rows)})()


class _FakeSupabase:
    def __init__(self) -> None:
        self.calls: list[int] = []
        outer = self

        class _S:
            def table(self, _name: str) -> _Table:
                return _Table(outer)

        self.supabase = _S()


def test_dedupe_keeps_first_per_conflict_key() -> None:
    rows = [_rec("JCTC"), _rec("JCTC"), _rec("JCTC", shares=200), _rec("TSI")]
    assert _dedupe_insider_records(rows) == [_rec("JCTC"), _rec("JCTC", shares=200), _rec("TSI")]


def test_repeated_rows_on_the_page_no_longer_drop_the_batch() -> None:
    db = _FakeSupabase()
    rows = [_rec(f"T{i}") for i in range(10)] + [_rec("T3")]  # one repeat, as on the live page
    saved, failed = _upsert_insider_trades(db, rows)
    assert (saved, failed) == (10, 0)
    assert db.calls == [10]  # one batched call, no fallback needed


def test_one_bad_row_costs_one_row_not_the_chunk() -> None:
    db = _FakeSupabase()
    rows = [_rec("A"), _rec("BAD"), _rec("C")]
    saved, failed = _upsert_insider_trades(db, rows)
    assert (saved, failed) == (2, 1)
    assert db.calls == [3, 1, 1, 1]  # chunk fails, then row by row


def test_large_pages_are_chunked() -> None:
    db = _FakeSupabase()
    saved, failed = _upsert_insider_trades(db, [_rec(f"T{i}") for i in range(450)])
    assert (saved, failed) == (450, 0)
    assert db.calls == [200, 200, 50]


def test_discovery_rotation_changes_daily_at_a_fixed_hour() -> None:
    """Same clock time on consecutive days must pick different queries."""
    import scheduler.jobs_opportunity as job

    src = open(job.__file__).read()
    assert "datetime.now().hour % len(queries)" not in src
    assert "datetime.now().toordinal() % len(queries)" in src
    picks = {datetime(2026, 11, d, 4, 15).toordinal() % 8 for d in range(1, 9)}
    assert len(picks) == 8


def test_discovery_queries_have_no_hardcoded_past_year() -> None:
    from settings import get_discovery_search_queries

    with patch("settings.get_system_setting", return_value=None):
        queries = get_discovery_search_queries()
    year = str(datetime.now().year)
    assert any(year in q for q in queries if "spin-off" in q)
    assert not any("2025" in q for q in queries)
