"""
Backfill insider_trades from SEC Form 4 for 2025.

Downloads 2025 form.gz index(es), fetches Form 4 filings, parses and upserts to Supabase.
Uses yfinance to fill missing price_per_share for transaction_date when SEC filing has no price.

To reset 2025 and re-run: DELETE FROM insider_trades WHERE transaction_date >= '2025-01-01' AND transaction_date < '2026-01-01'; then run this script. Other sources (e.g. OpenInsider) are unaffected.

Env: FLARESOLVERR_URL, SEC_EDGAR_USER_AGENT (see sec_form4_poc). SEC_INSIDER_BACKFILL_LIMIT=0 (no limit) or N to cap filings per quarter. SEC_INSIDER_BACKFILL_QUARTERS=1,2,3,4 (default all). SEC_INSIDER_BACKFILL_WORKERS=9 (parallel fetch+parse workers). SEC_INSIDER_SKIP_NO_PRICE=1 (skip trades when price lookup fails; default off).
SEC_INSIDER_BACKFILL_DATE_FROM and SEC_INSIDER_BACKFILL_DATE_TO (YYYY-MM-DD): when both set, only upsert trades whose transaction_date is in [FROM, TO] inclusive. Use to fill a gap from SEC without duplicating another source (e.g. FROM=2025-01-01 TO=2025-01-18).
Full 2025 (all quarters, ~356k Form 4 filings): run with no limit; expect several hours (SEC rate limit ~9 req/s).
  python web_dashboard/scripts/backfill_insider_trades_sec_2025.py
Fill Jan 1-18 only (no Jan 19+ from SEC to avoid duplicates):
  $env:SEC_INSIDER_BACKFILL_DATE_FROM = "2025-01-01"; $env:SEC_INSIDER_BACKFILL_DATE_TO = "2025-01-18"
  python web_dashboard/scripts/backfill_insider_trades_sec_2025.py
Test run (e.g. 500 filings total):
  $env:SEC_INSIDER_BACKFILL_LIMIT = "500"
  python web_dashboard/scripts/backfill_insider_trades_sec_2025.py
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Path setup
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
_web_dashboard = _script_dir.parent
import sys
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_web_dashboard) not in sys.path:
    sys.path.insert(0, str(_web_dashboard))

try:
    from dotenv import load_dotenv
    load_dotenv(_project_root / ".env")
    load_dotenv(_project_root / "web_dashboard" / ".env")
except ImportError:
    pass

# SEC Form 4 parsing (same module as POC)
from scheduler.sec_form4_poc import (
    download_index,
    parse_form_idx,
    filter_form4,
    fetch_filing,
    extract_xml_from_submission,
    parse_form4_xml,
    parse_form4_sgml,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)
# Reduce Supabase/httpx request log noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Optional limit: cap number of Form 4 filings per quarter (0 = no limit)
BACKFILL_LIMIT = int(os.getenv("SEC_INSIDER_BACKFILL_LIMIT", "0"))
# Quarters to process: "1" or "1,2,3,4" (default all)
_backfill_quarters_env = os.getenv("SEC_INSIDER_BACKFILL_QUARTERS", "1,2,3,4")
BACKFILL_QUARTERS = [int(q.strip()) for q in _backfill_quarters_env.split(",") if q.strip().isdigit()]
if not BACKFILL_QUARTERS:
    BACKFILL_QUARTERS = [1, 2, 3, 4]
# Parallel fetch+parse workers (~9 to match SEC 9 req/s rate limit)
BACKFILL_WORKERS = int(os.getenv("SEC_INSIDER_BACKFILL_WORKERS", "9"))
# When true, skip inserting trades when price_per_share could not be looked up (yfinance failed). Default off.
SKIP_NO_PRICE = os.getenv("SEC_INSIDER_SKIP_NO_PRICE", "").lower() in ("1", "true", "yes")
# Optional date filter: only upsert trades with transaction_date in [DATE_FROM, DATE_TO] inclusive (YYYY-MM-DD).
# Use to fill a gap from SEC without inserting Jan 19+ (other source). When either unset, no date filter.
BACKFILL_DATE_FROM = (os.getenv("SEC_INSIDER_BACKFILL_DATE_FROM") or "").strip()[:10]
BACKFILL_DATE_TO = (os.getenv("SEC_INSIDER_BACKFILL_DATE_TO") or "").strip()[:10]
YFINANCE_CACHE: Dict[tuple, Optional[float]] = {}
YFINANCE_DELAY = 0.2  # be polite

# Dir for saving raw filing text when we hit junk tickers (e.g. KEY) for later inspection
JUNK_INSPECT_DIR = _project_root / "debug" / "insider_junk"
_saved_raw_count = 0  # ensure we save at least one sample


def _save_raw_for_inspection(ticker: str, filename: str, company: str, raw: str) -> None:
    """Write raw filing text to debug/insider_junk/{ticker}_{basename}.txt for later inspection."""
    try:
        JUNK_INSPECT_DIR.mkdir(parents=True, exist_ok=True)
        basename = filename.split("/")[-1] if "/" in filename else filename
        out_path = JUNK_INSPECT_DIR / f"{ticker}_{basename}"
        out_path.write_text(raw, encoding="utf-8", errors="replace")
        logger.info("Saved raw filing for %r to %s", ticker, out_path)
    except Exception as e:
        logger.warning("Could not save raw for %r: %s", ticker, e)


def fetch_and_parse_one(
    row: Tuple[str, str, str, str, str],
) -> Tuple[str, Optional[str], List[Dict[str, Any]]]:
    """Fetch one Form 4 filing and parse to transaction list. Returns (date_filed, raw, trans_list)."""
    cik, company, form_type, date_filed, filename = row
    raw = fetch_filing(filename)
    if not raw:
        return (date_filed, None, [])
    xml_str = extract_xml_from_submission(raw)
    if not xml_str and ("<ownershipDocument" in raw or "<nonDerivativeTable" in raw):
        xml_str = raw
    if xml_str:
        trans_list = parse_form4_xml(xml_str)
    else:
        trans_list = []
    if not trans_list or all(not t.get("transaction_date") for t in trans_list):
        trans_list = parse_form4_sgml(raw)
    return (date_filed, raw, trans_list or [])


def get_close_price_for_date(ticker: str, trans_date: str) -> Optional[float]:
    """Return closing price for ticker on trans_date (YYYY-MM-DD). Cached per (ticker, date)."""
    if not ticker or not trans_date or len(trans_date) < 10:
        return None
    key = (ticker.upper(), trans_date[:10])
    if key in YFINANCE_CACHE:
        return YFINANCE_CACHE[key]
    time.sleep(YFINANCE_DELAY)
    try:
        import yfinance as yf
        d = datetime.strptime(trans_date[:10], "%Y-%m-%d").date()
        end = d + timedelta(days=1)
        t = yf.Ticker(ticker.upper())
        hist = t.history(start=d, end=end, auto_adjust=False)
        if hist is None or hist.empty:
            YFINANCE_CACHE[key] = None
            return None
        close = float(hist["Close"].iloc[0])
        YFINANCE_CACHE[key] = round(close, 2)
        return YFINANCE_CACHE[key]
    except Exception as e:
        logger.debug("yfinance %s %s: %s", ticker, trans_date, e)
        YFINANCE_CACHE[key] = None
        return None


def run_backfill_2025() -> None:
    year = 2025
    if BACKFILL_DATE_FROM and BACKFILL_DATE_TO:
        logger.info("Date filter active: only upserting trades with transaction_date in [%s, %s]", BACKFILL_DATE_FROM, BACKFILL_DATE_TO)
    try:
        from supabase_client import SupabaseClient
    except ImportError as e:
        logger.error("Missing supabase_client: %s", e)
        return
    client = SupabaseClient(use_service_role=True)
    total_upserted = 0
    total_errors = 0
    total_skipped = 0
    for quarter in BACKFILL_QUARTERS:
        logger.info("=== 2025 QTR%s ===", quarter)
        index_text = download_index(year, quarter, use_gzip=True)
        if not index_text:
            logger.warning("No index for 2025 QTR%s, skipping.", quarter)
            continue
        rows = parse_form_idx(index_text)
        form4_rows = filter_form4(rows)
        logger.info("Form 4 rows in index: %s", len(form4_rows))
        # Index has one row per reporting owner; same filing (filename) can appear multiple times.
        unique_filings = len({r[4] for r in form4_rows})
        if unique_filings < len(form4_rows):
            logger.info("Unique filings (by path): %s (rows are higher due to multiple reporting owners per form)", unique_filings)
        if BACKFILL_LIMIT > 0:
            form4_rows = form4_rows[:BACKFILL_LIMIT]
            logger.info("Limited to first %s filings.", BACKFILL_LIMIT)
        logger.info("Using %s parallel workers for fetch+parse.", BACKFILL_WORKERS)
        processed = 0
        with ThreadPoolExecutor(max_workers=BACKFILL_WORKERS) as executor:
            futures = {executor.submit(fetch_and_parse_one, row): row for row in form4_rows}
            for future in as_completed(futures):
                row = futures[future]
                cik, company, form_type, date_filed, filename = row
                try:
                    date_filed, raw, trans_list = future.result()
                except Exception as e:
                    logger.warning("Worker failed: %s", e)
                    total_errors += 1
                    processed += 1
                    continue
                if not raw:
                    total_errors += 1
                    processed += 1
                    continue
                if not trans_list:
                    total_skipped += 1
                    processed += 1
                    continue
                # Save raw for first filing so we always have at least one .txt to inspect
                global _saved_raw_count
                if _saved_raw_count < 1 and raw and filename:
                    _save_raw_for_inspection("sample_first", filename, company or "?", raw)
                    _saved_raw_count += 1
                for t in trans_list:
                    t["_date_filed"] = t.get("_date_filed") or date_filed
                for t in trans_list:
                    ticker = (t.get("ticker") or "").strip().upper()
                    if not ticker or ticker in ("FILED", "NONE", "-", "DATE", "OWNER", "INDEX", "FILM"):
                        if ticker:
                            logger.info(
                                "Skipped junk ticker %r from %s (%s) — inspect at https://www.sec.gov/Archives/%s",
                                ticker, filename.split("/")[-1] if filename else "?", company or "?", filename or "",
                            )
                        if raw and filename:
                            _save_raw_for_inspection(ticker or "no_ticker", filename, company or "?", raw)
                        continue
                    insider_name = (t.get("insider_name") or "Unknown").strip()
                    insider_title = (t.get("insider_title") or "").strip()
                    trans_date_str = (t.get("transaction_date") or "").strip()[:10]
                    if not trans_date_str:
                        continue
                    # Only upsert trades in [BACKFILL_DATE_FROM, BACKFILL_DATE_TO] when both are set (e.g. Jan 1-18 only).
                    if BACKFILL_DATE_FROM and BACKFILL_DATE_TO:
                        if trans_date_str < BACKFILL_DATE_FROM or trans_date_str > BACKFILL_DATE_TO:
                            continue
                    trade_type = (t.get("type") or "Unknown").strip()
                    shares = t.get("shares")
                    price = t.get("price_per_share")
                    value = t.get("value")
                    disclosure_str = (t.get("_date_filed") or trans_date_str).strip()[:10]
                    if not disclosure_str:
                        disclosure_str = trans_date_str
                    if price is None:
                        price = get_close_price_for_date(ticker, trans_date_str)
                        if price is not None and value is None and shares is not None:
                            value = round(shares * price, 2)
                    if value is None and shares is not None and price is not None:
                        value = round(shares * price, 2)
                    if price is not None:
                        price = round(float(price), 2)
                    if value is not None:
                        value = round(float(value), 2)
                    if SKIP_NO_PRICE and price is None:
                        continue  # skip trades we couldn't get a price for
                    try:
                        transaction_date = trans_date_str
                        disclosure_date = disclosure_str + "T00:00:00" if len(disclosure_str) == 10 else disclosure_str
                        if "T" not in disclosure_date:
                            disclosure_date = disclosure_date + "T00:00:00"
                        record = {
                            "ticker": ticker,
                            "insider_name": insider_name,
                            "insider_title": insider_title or None,
                            "transaction_date": transaction_date,
                            "disclosure_date": disclosure_date,
                            "type": trade_type,
                            "shares": shares,
                            "price_per_share": price,
                            "value": value,
                        }
                        client.supabase.table("insider_trades").upsert(
                            record,
                            on_conflict="ticker,insider_name,transaction_date,type,shares,price_per_share",
                        ).execute()
                        total_upserted += 1
                    except Exception as e:
                        logger.warning("Upsert failed %s %s %s: %s", ticker, insider_name, trans_date_str, e)
                        total_errors += 1
                processed += 1
                if processed % 100 == 0 and processed > 0:
                    logger.info("Processed %s index rows, upserted %s trades so far.", processed, total_upserted)
        logger.info("QTR%s done: processed %s index rows.", quarter, processed)
    logger.info("Backfill complete: upserted=%s errors=%s skipped=%s", total_upserted, total_errors, total_skipped)


if __name__ == "__main__":
    run_backfill_2025()
