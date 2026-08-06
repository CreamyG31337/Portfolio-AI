"""Supabase / PostgREST pagination helpers.

PostgREST (Supabase REST) hard-caps each response at 1000 rows no matter what
``.limit()`` / ``.range()`` you pass. Asking for a 5000-row "chunk" silently
returns only the first 1000 — leaving gaps if you then jump to offset 5000.

Use ``SUPABASE_MAX_ROWS`` / ``clamp_page_size`` / ``fetch_all_rows`` for any
full-table or large filtered read.

TODO(quota): Do not blindly replace every ``.limit()`` / chunked loop with
``fetch_all_rows``. Intentional LLM context caps (e.g. ``.limit(50)`` in AI
routes) and parallel 1000-row aggregations (e.g. congress stats in ``app.py``)
are not truncation bugs — see ``.jules/quota.md``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

# PostgREST default max-rows. Raising it requires a server config change.
SUPABASE_MAX_ROWS = 1000


def clamp_page_size(requested: int, *, maximum: int = SUPABASE_MAX_ROWS) -> int:
    """Clamp a page/chunk size to the PostgREST hard limit (at least 1)."""
    try:
        size = int(requested)
    except (TypeError, ValueError):
        size = maximum
    return max(1, min(size, maximum))


def fetch_all_rows(
    client: Any,
    table: str,
    select: str = "*",
    *,
    filters: Optional[Sequence[tuple[str, str, Any]]] = None,
    order: Optional[str] = None,
    order_desc: bool = False,
    page_size: int = SUPABASE_MAX_ROWS,
    max_rows: int = 200_000,
    apply_query: Optional[Callable[[Any], Any]] = None,
) -> list[dict]:
    """Fetch all matching rows, paging at ``SUPABASE_MAX_ROWS``.

    ``filters`` entries are ``(column, op, value)`` where ``op`` is one of
    ``eq``, ``gte``, ``lte``, ``lt``, ``gt``, ``neq``.
    ``apply_query`` may add arbitrary PostgREST query transforms.
    """
    size = clamp_page_size(page_size)
    all_rows: list[dict] = []
    offset = 0

    while offset < max_rows:
        query = client.supabase.table(table).select(select)
        if filters:
            for col, op, val in filters:
                method = getattr(query, op, None)
                if method is None:
                    raise ValueError(f"Unsupported filter op: {op}")
                query = method(col, val)
        if apply_query is not None:
            query = apply_query(query)
        if order:
            query = query.order(order, desc=order_desc)

        result = query.range(offset, offset + size - 1).execute()
        batch = result.data or []
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < size:
            break
        offset += size

    if offset >= max_rows:
        logger.warning(
            "fetch_all_rows hit max_rows=%d for %s (got %d rows)",
            max_rows,
            table,
            len(all_rows),
        )
    return all_rows


def page_ranges(total: int, page_size: int = SUPABASE_MAX_ROWS) -> list[tuple[int, int]]:
    """Inclusive ``(start, end)`` ranges covering ``total`` rows without gaps."""
    size = clamp_page_size(page_size)
    if total <= 0:
        return []
    ranges: list[tuple[int, int]] = []
    for start in range(0, total, size):
        end = min(start + size - 1, total - 1)
        ranges.append((start, end))
    return ranges
