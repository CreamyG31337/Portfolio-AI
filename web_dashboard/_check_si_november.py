"""One-off: print SI=F November rows from benchmark_data (delete after use)."""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_wd = Path(__file__).resolve().parent
sys.path.insert(0, str(_wd))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv

load_dotenv(_wd / ".env")
load_dotenv(_root / ".env")

from supabase_client import SupabaseClient


def show_november(year: int) -> None:
    start = f"{year}-11-01"
    end = f"{year}-11-30"
    c = SupabaseClient(use_service_role=True)
    r = (
        c.supabase.table("benchmark_data")
        .select("date, open, high, low, close, volume")
        .eq("ticker", "SI=F")
        .gte("date", start)
        .lte("date", end)
        .order("date")
        .execute()
    )
    rows = r.data or []
    print(f"\n=== SI=F November {year} ({len(rows)} rows) ===")
    for row in rows:
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        cl = float(row["close"])
        v = int(row["volume"] or 0)
        rng = (h - l) / cl * 100 if cl else 0.0
        flat = abs(h - l) < 1e-6 * max(cl, 1.0)
        flag = " FLAT_OHLC" if flat else ""
        print(f"{row['date']}  O={o:.4f} H={h:.4f} L={l:.4f} C={cl:.4f}  range%={rng:.5f}  vol={v}{flag}")


if __name__ == "__main__":
    show_november(2024)
    show_november(2025)
