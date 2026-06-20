#!/usr/bin/env python3
"""Apply G7 migration: insider_trades.source column (Supabase prod)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
web_dashboard = project_root / "web_dashboard"
sys.path.insert(0, str(web_dashboard))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")
load_dotenv(web_dashboard / ".env")


def main() -> int:
    db_url = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if not db_url:
        print("[ERROR] SUPABASE_DATABASE_URL not set")
        return 1

    sql_path = project_root / "database/schema/supabase/migrations/add_insider_trades_source.sql"
    sql = sql_path.read_text(encoding="utf-8")

    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 not installed")
        return 1

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    print(f"Applying {sql_path.name} ...")
    cur.execute(sql)

    cur.execute(
        """
        SELECT column_name, data_type, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'insider_trades'
          AND column_name = 'source'
        """
    )
    col = cur.fetchone()
    cur.execute(
        "SELECT source, COUNT(*) AS n FROM insider_trades GROUP BY source ORDER BY n DESC"
    )
    counts = cur.fetchall()
    cur.close()
    conn.close()

    print("[OK] Migration applied")
    print("Column:", col)
    print("Counts by source:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
