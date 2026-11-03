"""Batched Supabase upserts that can't silently lose a whole batch.

Postgres rejects an ``INSERT ... ON CONFLICT DO UPDATE`` that touches the same conflict
key twice ("cannot affect row a second time"), and PostgREST sends a batch as one
statement. So one repeated row in a scraped page failed the whole batch and every row in
it was dropped (insider trades 2026-08..11). This helper dedupes by the conflict key,
upserts in chunks, and retries a failed chunk row by row so one bad row costs one row.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)


def dedupe_by_keys(records: Sequence[Mapping[str, Any]], key_columns: Sequence[str]) -> list[Mapping[str, Any]]:
    """Keep the first record per conflict key."""
    seen: set = set()
    out: list[Mapping[str, Any]] = []
    for rec in records:
        key = tuple(rec.get(c) for c in key_columns)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def upsert_in_chunks(
    supabase_client: Any,
    table: str,
    records: Sequence[Mapping[str, Any]],
    conflict_columns: Sequence[str] | str,
    *,
    chunk_size: int = 200,
    label: str = "",
) -> tuple[int, int]:
    """Upsert ``records`` into ``table``; returns (rows saved, rows failed). Never raises."""
    cols = [c.strip() for c in conflict_columns.split(",")] if isinstance(conflict_columns, str) else list(conflict_columns)
    on_conflict = ",".join(cols)
    tbl = supabase_client.supabase.table
    rows = dedupe_by_keys(records, cols)
    what = label or table
    saved = failed = 0
    for start in range(0, len(rows), chunk_size):
        chunk = list(rows[start : start + chunk_size])
        try:
            result = tbl(table).upsert(chunk, on_conflict=on_conflict).execute()
            saved += len(result.data or [])
            continue
        except Exception as chunk_error:
            logger.warning("%s upsert chunk of %d failed (%s); retrying row by row", what, len(chunk), chunk_error)
        for rec in chunk:
            try:
                result = tbl(table).upsert([rec], on_conflict=on_conflict).execute()
                saved += len(result.data or [])
            except Exception as row_error:
                failed += 1
                logger.warning(
                    "%s row not saved (%s): %s", what, {c: rec.get(c) for c in cols}, row_error
                )
    return saved, failed
