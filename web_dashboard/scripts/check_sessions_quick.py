"""Quick check of congress_trade_sessions counts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from postgres_client import PostgresClient
pg = PostgresClient()
r = pg.execute_query("SELECT COUNT(*) as total FROM congress_trade_sessions")
print("Total sessions:", r[0]["total"] if r else 0)
r2 = pg.execute_query("SELECT COUNT(*) as n FROM congress_trade_sessions WHERE needs_reanalysis = TRUE")
print("needs_reanalysis=TRUE:", r2[0]["n"] if r2 else 0)
r3 = pg.execute_query("SELECT MIN(end_date) as min_d, MAX(end_date) as max_d FROM congress_trade_sessions")
if r3:
    print("end_date range:", r3[0]["min_d"], "to", r3[0]["max_d"])
for year in (2026, 2025):
    r4 = pg.execute_query(
        "SELECT COUNT(*) as n FROM congress_trade_sessions WHERE end_date >= %s AND end_date < %s",
        (f"{year}-01-01", f"{year}-02-01")
    )
    print(f"Sessions end_date in Jan {year}:", r4[0]["n"] if r4 else 0)
