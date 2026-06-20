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

    print("== evidence provenance (last 24h, G1) ==")
    rows = pg.execute_query(
        """
        SELECT source,
               COUNT(*) AS n,
               COUNT(*) FILTER (WHERE metadata ? 'evidence') AS with_evidence,
               COUNT(*) FILTER (
                   WHERE jsonb_array_length(
                       COALESCE(metadata->'evidence'->'article_ids', '[]'::jsonb)
                   ) > 0
               ) AS with_article_ids
        FROM stance_history
        WHERE as_of > NOW() - INTERVAL '24 hours'
        GROUP BY source
        ORDER BY n DESC
        """
    )
    if not rows:
        print("  (no stances in the last 24h)")
    for r in rows:
        n = r["n"] or 0
        cov = (100.0 * (r["with_evidence"] or 0) / n) if n else 0.0
        note = ""
        if r["source"] == "action_queue_ai_review" and cov == 0.0:
            note = " (verdict in metadata — expected)"
        print(f"  {r['source']:<22} rows={n:<5} "
              f"evidence={r['with_evidence']:<5} ({cov:5.1f}%) "
              f"article_ids={r['with_article_ids']}{note}")

    print("== stance_outcomes ==")
    rows = pg.execute_query(
        """
        SELECT horizon_days, COUNT(*) AS n,
               COUNT(*) FILTER (WHERE excess_return > 0) AS hits,
               COUNT(*) FILTER (WHERE excess_return <= 0) AS misses,
               COUNT(*) FILTER (WHERE excess_return != excess_return) AS nan_rows
        FROM stance_outcomes
        GROUP BY horizon_days
        ORDER BY 1
        """
    )
    if not rows:
        print("  (empty — expected until ledger rows age >= 7 days)")
    for r in rows:
        nan_note = f" nan={r['nan_rows']}" if r.get("nan_rows") else ""
        print(
            f"  horizon={r['horizon_days']}d rows={r['n']} "
            f"hits={r.get('hits', 0)} misses={r.get('misses', 0)}{nan_note}"
        )

    print("== track record (7d preview) ==")
    try:
        from track_record_service import build_track_record_summary

        s7 = build_track_record_summary(pg, horizon_days=7)
        print(f"  total_scored={s7.get('total_scored', 0)}")
        for src, rate in (s7.get("hit_rate_by_source") or {}).items():
            counts = (s7.get("counts_by_source") or {}).get(src) or {}
            rate_s = f"{100 * rate:.1f}%" if rate is not None else "—"
            print(
                f"  {src}: hit_rate={rate_s} "
                f"({counts.get('hits', 0)}/{counts.get('scored', 0)} scored)"
            )
    except Exception as exc:
        print(f"  (failed: {exc})")

    print("== filing_events (G2) ==")
    try:
        rows = pg.execute_query(
            """
            SELECT category, COUNT(*) AS n, MAX(filed_at) AS last_filed
            FROM filing_events
            GROUP BY category
            ORDER BY n DESC
            """
        )
        if not rows:
            print("  (empty — sec_filings not run or no events yet)")
        for r in rows:
            print(f"  {r['category']}: {r['n']} last={r['last_filed']}")
    except Exception as exc:
        print(f"  (lookup failed: {exc})")

    print("== retro digest config (G5) ==")
    try:
        from retro_digest_service import get_retro_digest_recipients, retro_digest_enabled

        recipients = get_retro_digest_recipients()
        print(f"  enabled={retro_digest_enabled()} recipients={len(recipients)}")
        if recipients:
            print(f"  first={recipients[0]}")
        else:
            print("  (set RETRO_DIGEST_RECIPIENTS + Mailgun to enable weekly email)")
    except Exception as exc:
        print(f"  (lookup failed: {exc})")

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

    print("== confluence_events (G4) ==")
    try:
        rows = pg.execute_query(
            """
            SELECT direction, COUNT(*) AS n, MAX(as_of) AS last_as_of,
                   COUNT(DISTINCT ticker) AS tickers
            FROM confluence_events
            GROUP BY direction
            ORDER BY n DESC
            """
        )
        if not rows:
            print("  (empty — job not run yet or table not applied)")
        for r in rows:
            print(f"  {r['direction']:<8} rows={r['n']:<5} tickers={r['tickers']:<4} last={r['last_as_of']}")
    except Exception as exc:
        print(f"  (lookup failed: {exc})")

    print("== job_executions (Supabase) for new jobs ==")
    try:
        from supabase_client import SupabaseClient

        sb = SupabaseClient(use_service_role=True)
        res = (
            sb.supabase.table("job_executions")
            .select("job_name,status,error_message,started_at,completed_at")
            .in_("job_name", [
                "stance_outcomes", "contradiction_drilldown",
                "weekly_stance_retro", "dilution_watch", "sec_filings", "confluence",
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
