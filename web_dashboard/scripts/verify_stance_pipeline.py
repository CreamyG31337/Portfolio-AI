"""One-shot verification that the stance ledger pipeline is live in prod.

Read-only. Prints row counts and recency for stance_history / stance_outcomes /
idea_triage, plus scheduler job-log entries for the new jobs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient


def main() -> int:
    pg = PostgresClient()

    print("== stance_history ==")
    rows = pg.execute_query(
        """
        SELECT source, COUNT(*) AS n, MIN(as_of) AS first, MAX(as_of) AS last,
               COUNT(DISTINCT ticker) AS tickers
        FROM stance_history
        GROUP BY source
        ORDER BY n DESC
        """
    )
    if not rows:
        print("  (empty — no ledger writes yet)")
    for r in rows:
        print(f"  {r['source']:<22} rows={r['n']:<5} tickers={r['tickers']:<4} "
              f"first={r['first']} last={r['last']}")

    print("== stance_outcomes ==")
    rows = pg.execute_query(
        "SELECT horizon_days, COUNT(*) AS n FROM stance_outcomes GROUP BY horizon_days ORDER BY 1"
    )
    if not rows:
        print("  (empty — expected until ledger rows age >= 7 days)")
    for r in rows:
        print(f"  horizon={r['horizon_days']}d rows={r['n']}")

    print("== idea_triage ==")
    rows = pg.execute_query("SELECT status, COUNT(*) AS n FROM idea_triage GROUP BY status")
    if not rows:
        print("  (empty — no triage decisions yet)")
    for r in rows:
        print(f"  {r['status']}: {r['n']}")

    print("== stance_history sample (latest 5) ==")
    rows = pg.execute_query(
        """
        SELECT ticker, source, stance, confidence, model_used, as_of
        FROM stance_history ORDER BY as_of DESC LIMIT 5
        """
    )
    for r in rows:
        print(f"  {r['as_of']} {r['ticker']:<8} {r['source']:<18} "
              f"stance={r['stance']} conf={r['confidence']} model={r['model_used']}")

    print("== job_executions (Supabase) for new jobs ==")
    try:
        from supabase_client import SupabaseClient

        sb = SupabaseClient(use_service_role=True)
        res = (
            sb.supabase.table("job_executions")
            .select("job_name,status,error_message,started_at,completed_at")
            .in_("job_name", [
                "stance_outcomes", "contradiction_drilldown",
                "weekly_stance_retro", "dilution_watch",
            ])
            .order("started_at", desc=True)
            .limit(10)
            .execute()
        )
        rows = res.data or []
        if not rows:
            print("  (no executions recorded yet)")
        for r in rows:
            err = str(r.get("error_message") or "")[:90]
            print(f"  {r.get('started_at')} {r.get('job_name'):<24} "
                  f"{r.get('status')} {err}")
    except Exception as exc:
        print(f"  (lookup failed: {exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
