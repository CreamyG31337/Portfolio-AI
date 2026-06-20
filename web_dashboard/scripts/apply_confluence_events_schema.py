"""Apply confluence_events DDL to the Research DB (one-time / idempotent)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient

SQL_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "database"
    / "schema"
    / "research"
    / "tables"
    / "confluence_events.sql"
)


def _statements_from_file(path: Path) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.strip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
    return statements


def main() -> int:
    pg = PostgresClient()
    for i, stmt in enumerate(_statements_from_file(SQL_PATH), 1):
        print(f"Running statement {i}...")
        pg.execute_update(stmt)
        print("  OK")

    cols = pg.execute_query(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'confluence_events'
        ORDER BY ordinal_position
        """
    )
    print("== confluence_events columns ==")
    for row in cols:
        print(f"  {row['column_name']}: {row['data_type']}")
    n = pg.execute_query("SELECT COUNT(*) AS n FROM confluence_events")[0]["n"]
    print(f"row_count={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
