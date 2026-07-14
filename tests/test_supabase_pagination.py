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
