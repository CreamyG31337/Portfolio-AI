#!/usr/bin/env python3
"""
Apply trade reasons from a CSV (columns: ticker, date, reason) to trade_log.

**Default funds:** Project Chimera + RRSP Lance Webull (same run updates each fund that has
a matching row). Override with ``--funds``.

**Matching:**
- **Month mode (default):** ``--year-month YYYY-MM`` — CSV rows must fall in that month (NY);
  DB row must be the earliest qualifying BUY in that month for the ticker.
- **Any month:** ``--no-month-filter`` — first CSV row per ticker (date column optional);
  DB row is the **earliest qualifying BUY** for that ticker in the fund (any date).

Default: dry-run. Production writes require ``--apply`` and ``--confirm-production`` on
non-test Supabase.

Usage (repo root):

  venv\\Scripts\\python.exe web_dashboard/scripts/apply_csv_reasons_august_webull.py \\
      --csv path/to/reasons.csv --no-month-filter --quiet
  venv\\Scripts\\python.exe web_dashboard/scripts/apply_csv_reasons_august_webull.py \\
      --csv path/to/reasons.csv --year-month 2025-08 \\
      --apply --confirm-production --audit-file reasons_apply.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DASH = _REPO_ROOT / "web_dashboard"
sys.path.insert(0, str(_WEB_DASH))
sys.path.insert(0, str(_REPO_ROOT))

from env_loader import load_project_dotenv

load_project_dotenv()

from supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
MAX_REASON_CHARS = 500
SCRIPT_NAME = "apply_csv_reasons_august_webull"
DEFAULT_FUNDS = ("Project Chimera", "RRSP Lance Webull")
CSV_DATE_FMT = "%m/%d/%Y %I:%M %p"


def _fingerprint_supabase() -> str:
    url = os.getenv("SUPABASE_URL") or ""
    try:
        return urlparse(url).hostname or url[:60]
    except Exception:
        return url[:60] or "(no SUPABASE_URL)"


def _is_likely_test_supabase() -> bool:
    url = (os.getenv("SUPABASE_URL") or "").lower()
    return "localhost" in url or "127.0.0.1" in url or ":5433" in url or "test" in url


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s.replace(" ", "T", 1))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def _row_in_target_month(row: dict[str, Any], year: int, month: int) -> bool:
    ts = _parse_ts(row["date"]).astimezone(NY)
    return ts.year == year and ts.month == month


def _is_qualifying_buy_row(row: dict[str, Any], year: int | None, month: int | None) -> bool:
    act = str(row.get("action") or "").strip().upper()
    try:
        shares = float(row.get("shares") or 0)
    except (TypeError, ValueError):
        return False
    if shares <= 0:
        return False
    if act != "BUY":
        return False
    if year is not None and month is not None:
        if not _row_in_target_month(row, year, month):
            return False
    return True


def _parse_year_month(s: str) -> tuple[int, int]:
    parts = s.strip().split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid --year-month {s!r}; use YYYY-MM")
    y, m = int(parts[0]), int(parts[1])
    if not (1 <= m <= 12):
        raise ValueError(f"Invalid month in {s!r}")
    return y, m


def _load_csv_month_rows(
    path: Path, year: int, month: int
) -> list[dict[str, str]]:
    """Rows from CSV whose date cell falls in `year`-`month` (NY). First row wins per ticker."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip()
            date_cell = (row.get("date") or "").strip()
            reason = (row.get("reason") or "").strip()
            if not ticker or not date_cell:
                continue
            try:
                naive = datetime.strptime(date_cell, CSV_DATE_FMT)
            except ValueError:
                logger.warning("Skip CSV row: bad date %r for ticker %s", date_cell, ticker)
                continue
            dt_ny = naive.replace(tzinfo=NY)
            if dt_ny.year != year or dt_ny.month != month:
                continue
            if ticker in seen:
                logger.warning("Duplicate CSV ticker in month %s-%02d: %s (using first)", year, month, ticker)
                continue
            seen.add(ticker)
            out.append({"ticker": ticker, "date": date_cell, "reason": reason})
    return sorted(out, key=lambda r: r["ticker"])


def _load_csv_all_tickers(path: Path) -> list[dict[str, str]]:
    """First row per ticker; date optional (for audit display only)."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip()
            reason = (row.get("reason") or "").strip()
            if not ticker:
                continue
            if ticker in seen:
                logger.warning("Duplicate CSV ticker (using first): %s", ticker)
                continue
            seen.add(ticker)
            date_cell = (row.get("date") or "").strip()
            out.append({"ticker": ticker, "date": date_cell or "(no date)", "reason": reason})
    return sorted(out, key=lambda r: r["ticker"])


def _fetch_trades_for_tickers(supabase: Any, fund: str, tickers: list[str]) -> list[dict[str, Any]]:
    if not tickers:
        return []
    res = (
        supabase.table("trade_log")
        .select("id,fund,ticker,date,reason,shares,action")
        .eq("fund", fund)
        .in_("ticker", tickers)
        .execute()
    )
    return res.data or []


def _pick_earliest_buy(
    rows: list[dict[str, Any]], year: int | None, month: int | None
) -> tuple[list[dict[str, Any]] | None, str]:
    """
    Returns (candidates_with_min_date, error_code).
    error_code: '' ok, 'no_row', 'ambiguous'
    """
    candidates = [r for r in rows if _is_qualifying_buy_row(r, year, month)]
    if not candidates:
        return None, "no_row"
    candidates.sort(key=lambda r: _parse_ts(r["date"]))
    min_dt = _parse_ts(candidates[0]["date"])
    tied = [r for r in candidates if _parse_ts(r["date"]) == min_dt]
    if len(tied) > 1:
        return tied, "ambiguous"
    return [candidates[0]], ""


def run() -> int:
    p = argparse.ArgumentParser(description="Apply CSV reasons to trade_log (earliest BUY per ticker per fund).")
    p.add_argument("--csv", type=Path, required=True, help="Path to ticker,date,reason CSV")
    p.add_argument(
        "--funds",
        default=",".join(DEFAULT_FUNDS),
        help=f"Comma-separated trade_log.fund values (default: {' + '.join(DEFAULT_FUNDS)})",
    )
    p.add_argument(
        "--no-month-filter",
        action="store_true",
        help="Match earliest BUY in DB for any date; CSV date optional (first row per ticker).",
    )
    p.add_argument(
        "--year-month",
        default="2025-08",
        help="YYYY-MM (America/New_York). Ignored if --no-month-filter (default 2025-08 for month mode).",
    )
    p.add_argument("--quiet", action="store_true", help="Summary stats only (no per-ticker table)")
    p.add_argument("--apply", action="store_true", help="Write to Supabase (default dry-run)")
    p.add_argument(
        "--confirm-production",
        action="store_true",
        help="Required with --apply on non-test Supabase URL",
    )
    p.add_argument("--audit-file", default="", help="Append JSONL audit lines on apply")
    p.add_argument(
        "--allow-ambiguous",
        action="store_true",
        help="If multiple rows share the earliest August timestamp, update all of them",
    )
    args = p.parse_args()

    funds = tuple(f.strip() for f in args.funds.split(",") if f.strip())
    if not funds:
        logger.error("Empty --funds")
        return 2

    if args.no_month_filter:
        y, m = None, None
    else:
        try:
            y, m = _parse_year_month(args.year_month)
        except ValueError as e:
            logger.error("%s", e)
            return 2

    logger.info("Supabase host fingerprint: %s", _fingerprint_supabase())
    likely_test = _is_likely_test_supabase()
    if likely_test:
        logger.info("Heuristic: SUPABASE_URL looks like test/local.")
    else:
        logger.warning("Heuristic: non-test Supabase — treat as production.")

    if args.apply and not likely_test and not args.confirm_production:
        logger.error("Refusing --apply without --confirm-production on non-test Supabase URL.")
        return 3

    csv_path = args.csv.resolve()
    if not csv_path.is_file():
        logger.error("CSV not found: %s", csv_path)
        return 4

    if args.no_month_filter:
        csv_rows = _load_csv_all_tickers(csv_path)
        if not csv_rows:
            logger.info("No CSV rows in %s. Nothing to do.", csv_path)
            return 0
    else:
        assert y is not None and m is not None
        csv_rows = _load_csv_month_rows(csv_path, y, m)
        if not csv_rows:
            logger.info("No CSV rows in %s for %s-%02d (NY). Nothing to do.", csv_path, y, m)
            return 0

    tickers = [r["ticker"] for r in csv_rows]
    reason_by_ticker = {r["ticker"]: r["reason"] for r in csv_rows}
    date_by_ticker = {r["ticker"]: r["date"] for r in csv_rows}

    if not os.getenv("SUPABASE_URL"):
        logger.error("SUPABASE_URL not set.")
        return 5

    supabase = SupabaseClient(use_service_role=True).supabase

    stats = {
        "match": 0,
        "will_update": 0,
        "skip_no_row": 0,
        "skip_ambiguous": 0,
        "skip_invalid_reason": 0,
        "applied": 0,
    }

    planned: list[dict[str, Any]] = []

    ym_label = "any month (earliest BUY)" if args.no_month_filter else f"{y}-{m:02d} (NY)"

    tickers_to_process: list[str] = []
    for t in sorted(reason_by_ticker.keys()):
        new_reason = reason_by_ticker[t]
        csv_date = date_by_ticker[t]
        if len(new_reason) > MAX_REASON_CHARS:
            stats["skip_invalid_reason"] += 1
            if not args.quiet:
                print(
                    f"{t:<12} {'SKIP_LEN':<14} {'':<38} {csv_date:<22} reason > {MAX_REASON_CHARS} chars"
                )
            continue
        tickers_to_process.append(t)

    for fund in funds:
        db_rows = _fetch_trades_for_tickers(supabase, fund, tickers)
        by_ticker: dict[str, list[dict[str, Any]]] = {}
        for r in db_rows:
            by_ticker.setdefault(str(r.get("ticker") or ""), []).append(r)

        if not args.quiet:
            print(f"Fund: {fund}")
            print(f"CSV: {csv_path}")
            print(f"Match mode: {ym_label}")
            print(f"CSV tickers: {len(csv_rows)}")
            print("-" * 100)
            print(f"{'ticker':<12} {'status':<14} {'db_id':<38} {'csv_date':<22} note")
            print("-" * 100)

        for t in tickers_to_process:
            new_reason = reason_by_ticker[t]
            csv_date = date_by_ticker[t]

            lst = by_ticker.get(t, [])
            picked, err = _pick_earliest_buy(lst, y, m)
            if err == "no_row":
                if not args.quiet:
                    print(
                        f"{t:<12} {'SKIP_no_row':<14} {'':<38} {csv_date:<22} no qualifying BUY in DB"
                    )
                stats["skip_no_row"] += 1
                continue
            assert picked is not None
            if err == "ambiguous" and not args.allow_ambiguous:
                if not args.quiet:
                    ids = ", ".join(str(x["id"]) for x in picked)
                    print(
                        f"{t:<12} {'SKIP_ambiguous':<14} {'':<38} {csv_date:<22} tied earliest ts: {ids}"
                    )
                stats["skip_ambiguous"] += 1
                continue

            targets = picked
            if err == "ambiguous" and args.allow_ambiguous:
                logger.warning("Ticker %s: updating %s rows tied at earliest timestamp", t, len(targets))

            for row in targets:
                rid = str(row["id"])
                old = str(row.get("reason") or "")
                if old == new_reason:
                    if not args.quiet:
                        print(f"{t:<12} {'MATCH':<14} {rid:<38} {csv_date:<22}")
                    stats["match"] += 1
                else:
                    if not args.quiet:
                        print(f"{t:<12} {'WILL_UPDATE':<14} {rid:<38} {csv_date:<22}")
                    stats["will_update"] += 1
                    planned.append(
                        {
                            "id": rid,
                            "fund": fund,
                            "ticker": t,
                            "csv_date": csv_date,
                            "old_reason": old,
                            "new_reason": new_reason,
                        }
                    )

        if not args.quiet:
            print("-" * 100)

    print("Summary:", stats)

    if not args.apply:
        logger.info("Dry-run complete (--apply not set). No database writes.")
        return 0

    audit_fp = open(args.audit_file, "a", encoding="utf-8") if args.audit_file else None
    try:
        for item in planned:
            supabase.table("trade_log").update({"reason": item["new_reason"], "action": "BUY"}).eq("id", item["id"]).eq(
                "reason", item["old_reason"]
            ).execute()
            stats["applied"] += 1
            if audit_fp:
                audit_fp.write(
                    json.dumps(
                        {
                            "id": item["id"],
                            "fund": item["fund"],
                            "ticker": item["ticker"],
                            "old_reason": item["old_reason"],
                            "new_reason": item["new_reason"],
                            "csv_date": item["csv_date"],
                            "script": SCRIPT_NAME,
                            "utc_timestamp": datetime.now(dt_timezone.utc).isoformat(),
                        }
                    )
                    + "\n"
                )
    finally:
        if audit_fp:
            audit_fp.close()

    logger.info("Apply complete. Rows updated: %s", stats["applied"])
    return 0


if __name__ == "__main__":
    sys.exit(run())
