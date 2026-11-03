"""batch_upsert: one repeated or bad row must never drop a whole scraped batch."""

from __future__ import annotations

from typing import Any

from batch_upsert import dedupe_by_keys, upsert_in_chunks


class _Supa:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []
        outer = self

        class _T:
            def __init__(self, name: str) -> None:
                self.name, self.rows, self.oc = name, [], ""

            def upsert(self, rows: list[dict[str, Any]], on_conflict: str) -> "_T":
                self.rows, self.oc = rows, on_conflict
                return self

            def execute(self) -> Any:
                outer.calls.append((self.name, len(self.rows), self.oc))
                keys = [(r["politician_id"], r["ticker"]) for r in self.rows]
                if len(keys) != len(set(keys)) or any(r["ticker"] == "BAD" for r in self.rows):
                    raise RuntimeError("cannot affect row a second time")
                return type("R", (), {"data": list(self.rows)})()

        class _S:
            def table(self, name: str) -> _T:
                return _T(name)

        self.supabase = _S()


def _r(t: str, pid: int = 1) -> dict[str, Any]:
    return {"politician_id": pid, "ticker": t, "amount": "$1K"}


def test_dedupe_by_keys() -> None:
    assert dedupe_by_keys([_r("A"), _r("A"), _r("A", 2)], ["politician_id", "ticker"]) == [_r("A"), _r("A", 2)]


def test_congress_style_conflict_string_and_repeat() -> None:
    db = _Supa()
    saved, failed = upsert_in_chunks(db, "congress_trades", [_r("A"), _r("B"), _r("A")], "politician_id,ticker")
    assert (saved, failed) == (2, 0)
    assert db.calls == [("congress_trades", 2, "politician_id,ticker")]


def test_bad_row_isolated() -> None:
    db = _Supa()
    saved, failed = upsert_in_chunks(db, "t", [_r("A"), _r("BAD"), _r("C")], ["politician_id", "ticker"], chunk_size=10)
    assert (saved, failed) == (2, 1)


def test_congress_fetch_polls_hourly_through_the_us_day() -> None:
    """FMP returns only the latest 10 per chamber; nightly polling missed most filings."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_rss_feed_ingest_registration import _RecordingScheduler

    from scheduler.jobs import register_default_jobs

    sched = _RecordingScheduler()
    register_default_jobs(sched)
    trig = sched.jobs["congress_trades_fetch"]["trigger"]
    hours = str(next(f for f in trig.fields if f.name == "hour"))
    assert hours == "7-23"
    assert str(trig.timezone) == "America/New_York"
