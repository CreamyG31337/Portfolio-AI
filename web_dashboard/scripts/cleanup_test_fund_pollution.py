"""Clean test-suite pollution out of the prod intelligence pipeline.

Background (2026-06-10/11): test runs leave TEST_* funds with fixture
positions (STOCK1, FIFO, COMPLEX, ...) in prod Supabase. The nightly
ticker_analysis job had no production-fund filter, so it analyzed those
fixtures with real LLMs, cascading rows into ticker_analysis,
ticker_meta_analysis, and the new stance_history ledger. The selection
filter is fixed in ticker_analysis_service.get_tickers_to_analyze(); this
script repairs the data side.

Dry-run by default. Flags:
  --apply      delete fixture-ticker rows from the Research DB tables
  --fix-tfsa   set funds.is_production = true for TFSA (it is a real fund;
               without the flag the holdings filter and the action-queue
               review job both skip it)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from postgres_client import PostgresClient
from supabase_client import SupabaseClient

FIXTURE_TICKERS = ["COMPLEX", "DUAL", "DUAL_REAL", "FIFO", "STOCK1", "STOCK2",
                   "STOCK3", "DAILY", "TEST"]
TABLES = ("stance_history", "ticker_analysis", "ticker_meta_analysis")


def main() -> int:
    apply = "--apply" in sys.argv
    fix_tfsa = "--fix-tfsa" in sys.argv

    sb = SupabaseClient(use_service_role=True)
    res = sb.supabase.table("funds").select("name,is_production").execute()
    rows = res.data or []
    prod = sorted(r["name"] for r in rows if r.get("is_production"))
    print(f"funds: total={len(rows)} production={prod}")

    if fix_tfsa:
        sb.supabase.table("funds").update({"is_production": True}) \
            .eq("name", "TFSA").execute()
        chk = sb.supabase.table("funds").select("name,is_production") \
            .eq("name", "TFSA").execute()
        print(f"TFSA flag now: {chk.data}")
    elif "TFSA" not in prod:
        print("WARNING: TFSA lacks is_production=true (rerun with --fix-tfsa)")

    pg = PostgresClient()
    for table in TABLES:
        cnt = pg.execute_query(
            f"SELECT COUNT(*) AS n FROM {table} WHERE ticker = ANY(%s)",
            (FIXTURE_TICKERS,),
        )
        n = cnt[0]["n"] if cnt else 0
        print(f"{table}: fixture rows = {n}")
        if apply and n:
            pg.execute_update(
                f"DELETE FROM {table} WHERE ticker = ANY(%s)", (FIXTURE_TICKERS,)
            )
            left = pg.execute_query(
                f"SELECT COUNT(*) AS n FROM {table} WHERE ticker = ANY(%s)",
                (FIXTURE_TICKERS,),
            )
            print(f"  deleted; remaining = {left[0]['n']}")

    if not apply:
        print("(dry run — pass --apply to delete fixture rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
