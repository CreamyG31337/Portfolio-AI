#!/usr/bin/env python3
"""
Audit Supabase etf_holdings_log / etf_holdings_changes usage in repo + prod DB.

Read-only. Run before dropping legacy Supabase holdings objects.

Usage:
    cd web_dashboard
    python scripts/audit_supabase_etf_holdings_deps.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from dotenv import load_dotenv

load_dotenv(project_root / "web_dashboard" / ".env")

ROOT = project_root
PATTERNS = [
    re.compile(r"\.table\(['\"]etf_holdings_log['\"]"),
    re.compile(r"\.from_\(['\"]etf_holdings_changes['\"]"),
    re.compile(r"sb\.table\(['\"]etf_holdings_log['\"]"),
]

PRODUCTION_PATHS = {
    "web_dashboard/ticker_state.py",
    "web_dashboard/ticker_analysis_service.py",
    "web_dashboard/pages/etf_holdings.py",
    "web_dashboard/etf_group_analysis.py",  # fixed locally; may still be old on server
    "web_dashboard/scheduler/jobs_etf_analysis.py",
}

SKIP_DIRS = {
    ".git",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "static/js",
}


@dataclass
class Hit:
    path: str
    line_no: int
    line: str
    category: str


def categorize(rel: str) -> str:
    if rel.replace("\\", "/") in PRODUCTION_PATHS:
        return "PRODUCTION"
    if "/pages/" in rel.replace("\\", "/") and "etf_holdings" in rel:
        return "STREAMLIT_PROTOTYPE"
    if "/debug/" in rel.replace("\\", "/") or rel.startswith("debug"):
        return "DEBUG"
    if "/scripts/" in rel.replace("\\", "/"):
        if "migrate_etf" in rel or "investigate" in rel or "audit_" in rel:
            return "MIGRATION_OR_AUDIT"
        return "SCRIPT"
    if "database/schema/supabase" in rel.replace("\\", "/"):
        return "SCHEMA"
    if "database/schema/research" in rel.replace("\\", "/"):
        return "RESEARCH_SCHEMA"
    if "/tests/" in rel.replace("\\", "/"):
        return "TEST"
    return "OTHER"


def scan_repo() -> list[Hit]:
    hits: list[Hit] = []
    for path in ROOT.rglob("*.py"):
        parts = set(path.parts)
        if parts & SKIP_DIRS:
            continue
        rel = str(path.relative_to(ROOT))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "etf_holdings_log" not in text and "etf_holdings_changes" not in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if not any(
                p.search(line)
                for p in PATTERNS
            ) and "etf_holdings_log" not in line and "etf_holdings_changes" not in line:
                continue
            if "etf_holdings_log" in line or "etf_holdings_changes" in line:
                if ".supabase" in line or "sb.table" in line or "from_(" in line:
                    hits.append(Hit(rel, i, line.strip()[:120], categorize(rel)))
    return hits


def scan_prod_db() -> None:
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient

    print("\n=== Prod DB objects (Supabase) ===\n")
    sb = SupabaseClient(use_service_role=True)
    # Row count
    r = sb.supabase.table("etf_holdings_log").select("*", count="exact").limit(0).execute()
    print(f"etf_holdings_log rows: {r.count or 0}")

    # We cannot run arbitrary SQL via supabase-py easily; use Research for comparison
    pc = PostgresClient()
    pg = pc.execute_query(
        "SELECT COUNT(*) c, MAX(date) mx FROM etf_holdings_log"
    )[0]
    print(f"Research etf_holdings_log rows: {pg['c']:,}  max_date={pg['mx']}")


def main() -> None:
    print("=" * 70)
    print("Supabase ETF holdings dependency audit (repository)")
    print("=" * 70)

    hits = scan_repo()
    supabase_hits = [h for h in hits if "supabase" in h.line.lower() or "sb.table" in h.line or "from_(" in h.line]

    by_cat: dict[str, list[Hit]] = {}
    for h in supabase_hits:
        by_cat.setdefault(h.category, []).append(h)

    order = ["PRODUCTION", "STREAMLIT_PROTOTYPE", "SCRIPT", "DEBUG", "MIGRATION_OR_AUDIT", "OTHER"]
    for cat in order:
        group = by_cat.get(cat, [])
        if not group:
            continue
        print(f"\n--- {cat} ({len(group)} supabase client call sites) ---")
        for h in sorted(group, key=lambda x: (x.path, x.line_no)):
            print(f"  {h.path}:{h.line_no}")
            print(f"    {h.line}")

    prod = by_cat.get("PRODUCTION", [])
    print("\n" + "=" * 70)
    if prod:
        print("BLOCKERS: fix PRODUCTION paths before DROP (or they will error / return empty).")
        for h in prod:
            print(f"  - {h.path}")
    else:
        print("No production Python files call Supabase etf_holdings_* via client.")

    print("\nSafe on Research already (PostgresClient SQL, not Supabase table API):")
    research_ok = [
        "web_dashboard/routes/etf_routes.py",
        "web_dashboard/scheduler/jobs_etf_watchtower.py",
        "web_dashboard/app.py (get_etf_holding_trades)",
        "web_dashboard/routes/ai_routes.py (get_etf_holding_trades_batch)",
        "web_dashboard/routes/admin_routes.py",
    ]
    for p in research_ok:
        print(f"  - {p}")

    scan_prod_db()

    print("\n=== Drop order (Supabase only, after blockers fixed) ===")
    print("  1. DROP VIEW IF EXISTS etf_holdings_changes CASCADE;")
    print("  2. DROP FUNCTION IF EXISTS get_etf_holding_trades_batch(...);")
    print("  3. DROP FUNCTION IF EXISTS get_etf_holding_trades(...);")
    print("  4. DROP TABLE IF EXISTS etf_holdings_log CASCADE;")
    print("\nResearch DB keeps table + view + functions (source of truth).")


if __name__ == "__main__":
    main()
