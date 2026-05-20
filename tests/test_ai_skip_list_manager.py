"""Unit tests for the AI skip-list policy.

Background: In May 2026 a single ``NoneType.__format__`` crash silently banned
84 production tickers forever because the original ``record_failure`` insert
left ``skip_until`` NULL and ``should_skip`` treated NULL as "skip forever".
These tests pin down the corrected behavior so we don't regress.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DASHBOARD = PROJECT_ROOT / "web_dashboard"
if str(WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD))

from ai_skip_list_manager import AISkipListManager, _classify_failure  # noqa: E402


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self._action = None
        self._payload = None
        self._filters = []

    def select(self, *_a, **_k):
        self._action = "select"
        return self

    def insert(self, payload):
        self._action = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._action = "update"
        self._payload = payload
        return self

    def delete(self):
        self._action = "delete"
        return self

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self._filters.append(("in", column, list(values)))
        return self

    def ilike(self, column, pattern):
        self._filters.append(("ilike", column, pattern))
        return self

    def execute(self):
        action = self._action
        if action == "select":
            rows = [
                row for row in self.table.rows
                if all(self._row_matches(row, f) for f in self._filters)
            ]
            return types.SimpleNamespace(data=rows)
        if action == "insert":
            new_row = dict(self._payload)
            new_row.setdefault("skip_until", None)
            self.table.rows.append(new_row)
            return types.SimpleNamespace(data=[new_row])
        if action == "update":
            for row in self.table.rows:
                if all(self._row_matches(row, f) for f in self._filters):
                    row.update(self._payload)
            return types.SimpleNamespace(data=[])
        if action == "delete":
            removed = [r for r in self.table.rows if all(self._row_matches(r, f) for f in self._filters)]
            self.table.rows = [r for r in self.table.rows if r not in removed]
            return types.SimpleNamespace(data=removed)
        return types.SimpleNamespace(data=[])

    @staticmethod
    def _row_matches(row, filt):
        op, col, val = filt
        if op == "eq":
            return row.get(col) == val
        if op == "in":
            return row.get(col) in val
        if op == "ilike":
            return (val or "").strip("%").lower() in (str(row.get(col) or "")).lower()
        return False


class FakeTable:
    def __init__(self, name):
        self.name = name
        self.rows: list[dict] = []

    def __call__(self):
        return FakeQuery(self)


class FakeSupabaseRaw:
    def __init__(self):
        self._tables: dict[str, FakeTable] = {}

    def table(self, name):
        if name not in self._tables:
            self._tables[name] = FakeTable(name)
        return FakeQuery(self._tables[name])


class FakeSupabase:
    def __init__(self):
        self.supabase = FakeSupabaseRaw()


def _rows(client: FakeSupabase) -> list[dict]:
    return client.supabase._tables["ai_analysis_skip_list"].rows  # noqa: SLF001


def test_first_failure_does_not_permanently_ban():
    client = FakeSupabase()
    mgr = AISkipListManager(client)

    mgr.record_failure("TSLA", "boom: unexpected error")

    rows = _rows(client)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "TSLA"
    assert row["failure_count"] == 1
    skip_until = row["skip_until"]
    assert skip_until is not None, "first failure must NOT set skip_until=NULL"
    parsed = datetime.fromisoformat(skip_until.replace("Z", "+00:00"))
    delta = parsed - datetime.now(timezone.utc)
    assert delta.total_seconds() > 0, "skip_until must be in the future"
    assert delta.total_seconds() < 3 * 3600, "first-failure cooldown should be ~1h"


def test_third_transient_failure_uses_finite_skip_until():
    client = FakeSupabase()
    mgr = AISkipListManager(client)

    mgr.record_failure("MSFT", "transient: format crash")
    mgr.record_failure("MSFT", "transient: format crash")
    mgr._cache.pop("MSFT", None)
    mgr.record_failure("MSFT", "transient: format crash")

    row = _rows(client)[0]
    assert row["failure_count"] == 3
    assert row["skip_until"] is not None, "transient failures must NOT permanently ban"
    parsed = datetime.fromisoformat(row["skip_until"].replace("Z", "+00:00"))
    delta = parsed - datetime.now(timezone.utc)
    hours = delta.total_seconds() / 3600
    assert 20 <= hours <= 26, f"expected ~24h transient skip, got {hours:.1f}h"


def test_permanent_marker_sets_skip_forever():
    client = FakeSupabase()
    mgr = AISkipListManager(client)

    mgr.record_failure("ZZZZ", "delisted: ticker no longer trades")
    mgr.record_failure("ZZZZ", "delisted: ticker no longer trades")
    mgr._cache.pop("ZZZZ", None)
    mgr.record_failure("ZZZZ", "delisted: ticker no longer trades")

    row = _rows(client)[0]
    assert row["failure_count"] == 3
    assert row["skip_until"] is None, "permanent markers should still skip_until=NULL"


def test_should_skip_returns_false_when_skip_until_expired():
    client = FakeSupabase()
    client.supabase._tables.setdefault(
        "ai_analysis_skip_list", FakeTable("ai_analysis_skip_list")
    )
    client.supabase._tables["ai_analysis_skip_list"].rows.append({
        "ticker": "AAPL",
        "skip_until": "2020-01-01T00:00:00+00:00",
        "reason": "old",
        "failure_count": 5,
    })
    mgr = AISkipListManager(client)

    assert mgr.should_skip("AAPL") is False, "expired skip_until should not skip"


def test_clear_entries_matching_purges_format_bug_rows():
    client = FakeSupabase()
    client.supabase._tables.setdefault(
        "ai_analysis_skip_list", FakeTable("ai_analysis_skip_list")
    )
    rows = client.supabase._tables["ai_analysis_skip_list"].rows
    rows.append({"ticker": "FOO", "reason": "unsupported format string passed to NoneType.__format__", "failure_count": 1, "skip_until": None})
    rows.append({"ticker": "BAR", "reason": "delisted: never coming back", "failure_count": 3, "skip_until": None})
    rows.append({"ticker": "BAZ", "reason": "unsupported format string passed to NoneType.__format__", "failure_count": 1, "skip_until": None})
    mgr = AISkipListManager(client)

    deleted = mgr.clear_entries_matching("NoneType.__format__")

    assert deleted == 2
    remaining = [r["ticker"] for r in _rows(client)]
    assert remaining == ["BAR"], "only permanent (delisted) row should remain"


def test_classify_failure_recognizes_transient_and_permanent():
    assert _classify_failure("delisted by SEC") == (True, "delisted_or_unknown")
    assert _classify_failure("no such ticker") == (True, "delisted_or_unknown")
    assert _classify_failure("Symbol not found in yfinance") == (True, "delisted_or_unknown")
    assert _classify_failure("unsupported format string passed to NoneType.__format__") == (
        False,
        "transient",
    )
    assert _classify_failure(None) == (False, "transient")
