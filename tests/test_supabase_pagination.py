"""Guards against PostgREST silent 1000-row truncation bugs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB_DASHBOARD = Path(__file__).resolve().parents[1] / "web_dashboard"


def test_clamp_page_size_and_page_ranges() -> None:
    import sys

    sys.path.insert(0, str(WEB_DASHBOARD))
    from supabase_pagination import SUPABASE_MAX_ROWS, clamp_page_size, page_ranges

    assert SUPABASE_MAX_ROWS == 1000
    assert clamp_page_size(5000) == 1000
    assert clamp_page_size(0) == 1
    assert clamp_page_size(250) == 250

    ranges = page_ranges(3084, 1000)
    assert ranges == [(0, 999), (1000, 1999), (2000, 2999), (3000, 3083)]
    # No gaps between consecutive ranges
    for (a, b), (c, d) in zip(ranges, ranges[1:]):
        assert c == b + 1


def test_fetch_all_rows_pages_and_clamps_oversized_page_size() -> None:
    """Oversized page_size must still step by SUPABASE_MAX_ROWS (no silent gaps)."""
    import sys
    from unittest.mock import MagicMock

    sys.path.insert(0, str(WEB_DASHBOARD))
    from supabase_pagination import SUPABASE_MAX_ROWS, fetch_all_rows

    page1 = [{"id": i} for i in range(SUPABASE_MAX_ROWS)]
    page2 = [{"id": SUPABASE_MAX_ROWS + i} for i in range(50)]
    execute = MagicMock(
        side_effect=[
            MagicMock(data=page1),
            MagicMock(data=page2),
        ]
    )
    recorder: list[tuple[int, int]] = []

    def _table(_name: str) -> MagicMock:
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain

        def _range(start: int, end: int) -> MagicMock:
            recorder.append((start, end))
            return chain

        chain.range.side_effect = _range
        chain.execute = execute
        return chain

    client = MagicMock()
    client.supabase.table.side_effect = _table

    rows = fetch_all_rows(
        client,
        "trade_log",
        filters=[("fund", "eq", "TEST")],
        order="date",
        order_desc=True,
        page_size=5000,  # would silently truncate without clamping
    )

    assert len(rows) == SUPABASE_MAX_ROWS + 50
    assert execute.call_count == 2
    assert recorder == [(0, 999), (1000, 1999)]


def test_fetch_all_rows_applies_secondary_order() -> None:
    """Secondary order must be chained for stable paging on non-unique keys."""
    import sys
    from unittest.mock import MagicMock, call

    sys.path.insert(0, str(WEB_DASHBOARD))
    from supabase_pagination import fetch_all_rows

    chain = MagicMock()
    chain.select.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.execute.return_value = MagicMock(data=[{"id": 1}])

    client = MagicMock()
    client.supabase.table.return_value = chain

    rows = fetch_all_rows(
        client,
        "congress_trades_enriched",
        order="transaction_date",
        order_desc=True,
        order_secondary="id",
        order_secondary_desc=True,
    )

    assert rows == [{"id": 1}]
    assert chain.order.call_args_list == [
        call("transaction_date", desc=True),
        call("id", desc=True),
    ]


def test_no_oversized_supabase_chunks_in_web_dashboard() -> None:
    """Fail if production code asks PostgREST for more than 1000 rows per page.

    Patterns like ``chunk_size = 5000`` or ``.limit(5000)`` look fine but are
    silently truncated by PostgREST, causing missing rows / wrong totals.
    """
    # Scripts/debug/tests often intentionally experiment — focus on runtime paths.
    skip_dirs = {
        "scripts",
        "debug",
        "test_files",
        "static",
        "node_modules",
        "__pycache__",
        "venv",
    }
    dangerous = re.compile(
        r"""(?x)
        chunk_size\s*=\s*(?:[2-9]\d{3,}|[1-9]\d{4,})
        | batch_size\s*=\s*(?:[2-9]\d{3,}|[1-9]\d{4,})
        | page_size\s*=\s*(?:[2-9]\d{3,}|[1-9]\d{4,})
        | \.limit\(\s*(?:[2-9]\d{3,}|[1-9]\d{4,})\s*\)
        """
    )
    # Allow documented constants that are then clamped, or non-Supabase uses.
    allow_files = {
        # Safety caps on total rows across many pages, not per-request size.
        "backfill_performance_metrics.py",
    }
    offenders: list[str] = []
    for path in WEB_DASHBOARD.rglob("*.py"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.name in allow_files:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            if "max_rows" in line or "max_row" in line or "safety" in line.lower():
                continue
            if "offset >" in line or "offset >=" in line:
                continue
            if dangerous.search(line):
                offenders.append(f"{path.relative_to(WEB_DASHBOARD.parent)}:{i}: {line.strip()}")

    assert not offenders, (
        "PostgREST max is 1000 rows/request. Use supabase_pagination.clamp_page_size "
        "or page at 1000. Offenders:\n" + "\n".join(offenders)
    )
