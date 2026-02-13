#!/usr/bin/env python3
"""
Backfill Performance Metrics Script (Fast Version)
====================================================

Populates the performance_metrics table with historical data from portfolio_positions.
Uses bulk queries to minimize API calls — runs in ~1 minute instead of hours.

Usage:
    python web_dashboard/backfill_performance_metrics.py

Options:
    --fund FUND_NAME    Only backfill for a specific fund
    --from-date DATE    Start date (YYYY-MM-DD)
    --to-date DATE      End date (YYYY-MM-DD)
    --force             Overwrite existing metrics (default: skip existing)
"""

import sys
import os
from datetime import datetime, date, timedelta, time as dt_time
from decimal import Decimal
from collections import defaultdict
import argparse
import logging

# Add parent directory to path for console utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from display.console_output import _safe_emoji

# Add web_dashboard to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from supabase_client import SupabaseClient

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def _fetch_all_paginated(client, table: str, select: str,
                         filters: list[tuple[str, str, str]] | None = None,
                         order: str | None = None,
                         page_size: int = 1000) -> list[dict]:
    """Fetch all rows from a Supabase table, handling pagination.
    
    Creates a fresh query per page to avoid stacking .range() calls.
    """
    all_rows: list[dict] = []
    offset = 0
    while True:
        query = client.supabase.table(table).select(select)
        if filters:
            for col, op, val in filters:
                if op == 'eq':
                    query = query.eq(col, val)
                elif op == 'gte':
                    query = query.gte(col, val)
                elif op == 'lte':
                    query = query.lte(col, val)
                elif op == 'lt':
                    query = query.lt(col, val)
        if order:
            query = query.order(order)
        result = query.range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < page_size:
            break  # Last page
        offset += page_size
    return all_rows


def backfill_performance_metrics(
    fund_filter: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    force: bool = False
) -> None:
    """Fast bulk backfill of performance_metrics table.

    Strategy:
    1. Bulk-fetch ALL portfolio_positions (paginated)
    2. Bulk-fetch ALL exchange rates for USD→CAD
    3. Bulk-fetch ALL existing performance_metrics dates (for skip_existing)
    4. Aggregate in-memory (grouped by fund+date)
    5. Batch-upsert results
    """

    print(f"{_safe_emoji('🔄')} Starting FAST performance metrics backfill...")

    client = SupabaseClient(use_service_role=True)

    # ── Step 1: Bulk-fetch all portfolio positions ──────────────────────
    print(f"{_safe_emoji('📊')} Step 1/5: Fetching all portfolio positions...")
    pos_filters: list[tuple[str, str, str]] = []
    if fund_filter:
        pos_filters.append(("fund", "eq", fund_filter))
    if from_date:
        pos_filters.append(("date", "gte", f"{from_date}T00:00:00"))
    if to_date:
        pos_filters.append(("date", "lte", f"{to_date}T23:59:59.999999"))

    all_positions = _fetch_all_paginated(
        client, "portfolio_positions",
        "fund, total_value, cost_basis, pnl, currency, date",
        filters=pos_filters, order="date"
    )

    if not all_positions:
        print(f"{_safe_emoji('⚠️')} No position data found matching criteria")
        return

    print(f"   Fetched {len(all_positions)} position rows")

    # ── Step 2: Group positions by (fund, date) ────────────────────────
    print(f"{_safe_emoji('🔢')} Step 2/5: Grouping by fund+date...")

    # Exclude today — the daily job handles it after market close.
    # Use ET timezone to match market hours.
    import pytz
    et = pytz.timezone('America/New_York')
    today_et = datetime.now(et).date()

    # Track which (fund, date) combos we need and whether any are USD
    grouped: dict[tuple[str, date], list[dict]] = defaultdict(list)
    needs_usd_rate: set[date] = set()
    skipped_today = 0

    for pos in all_positions:
        dt = datetime.fromisoformat(pos['date'].replace('Z', '+00:00')).date()
        if dt >= today_et:
            skipped_today += 1
            continue  # Skip today and any future dates
        fund = pos['fund']
        grouped[(fund, dt)].append(pos)

        currency = (pos.get('currency') or 'CAD').strip().upper()
        if currency in ('NAN', 'NONE', 'NULL', ''):
            currency = 'CAD'
        if currency == 'USD':
            needs_usd_rate.add(dt)

    if not grouped:
        print(f"{_safe_emoji('⚠️')} No historical position data to backfill (all positions are from today)")
        return

    unique_dates = sorted({dt for _, dt in grouped.keys()})
    print(f"   Found {len(grouped)} fund-date combinations across {len(unique_dates)} dates")
    print(f"   Date range: {unique_dates[0]} to {unique_dates[-1]}")
    if skipped_today:
        print(f"   Skipped {skipped_today} positions from today ({today_et}) — daily job handles those")
    print(f"   Dates needing USD->CAD conversion: {len(needs_usd_rate)}")

    # ── Step 3: Bulk-fetch exchange rates ──────────────────────────────
    print(f"{_safe_emoji('💱')} Step 3/5: Fetching exchange rates...")

    # Fetch all USD→CAD rates in one query (we'll pick closest by date)
    rate_cache: dict[date, Decimal] = {}
    if needs_usd_rate:
        min_rate_date = min(needs_usd_rate)
        max_rate_date = max(needs_usd_rate)

        rate_filters = [
            ("from_currency", "eq", "USD"),
            ("to_currency", "eq", "CAD"),
            ("timestamp", "gte", f"{min_rate_date - timedelta(days=7)}T00:00:00+00:00"),
            ("timestamp", "lte", f"{max_rate_date + timedelta(days=1)}T00:00:00+00:00"),
        ]
        all_rates = _fetch_all_paginated(
            client, "exchange_rates", "rate, timestamp",
            filters=rate_filters, order="timestamp"
        )
        print(f"   Fetched {len(all_rates)} exchange rate records")

        # Build date→rate lookup (use the latest rate on or before each date)
        rate_by_timestamp: list[tuple[date, Decimal]] = []
        for r in all_rates:
            ts = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00')).date()
            rate_by_timestamp.append((ts, Decimal(str(r['rate']))))

        rate_by_timestamp.sort(key=lambda x: x[0])

        # For each date that needs a rate, find the closest one on or before
        for target in sorted(needs_usd_rate):
            best_rate = Decimal('1.35')  # default fallback
            for ts_date, rate in rate_by_timestamp:
                if ts_date <= target:
                    best_rate = rate
                else:
                    break
            rate_cache[target] = best_rate
    else:
        print("   No USD positions — skipping exchange rate fetch")

    # ── Step 4: Check existing metrics (for skip_existing) ─────────────
    existing_keys: set[tuple[str, str]] = set()
    if not force:
        print(f"{_safe_emoji('🔍')} Step 4/5: Checking existing metrics...")
        exist_filters: list[tuple[str, str, str]] = []
        if fund_filter:
            exist_filters.append(("fund", "eq", fund_filter))
        if from_date:
            exist_filters.append(("date", "gte", str(from_date)))
        if to_date:
            exist_filters.append(("date", "lte", str(to_date)))

        existing_rows = _fetch_all_paginated(
            client, "performance_metrics", "fund, date",
            filters=exist_filters
        )
        for row in existing_rows:
            existing_keys.add((row['fund'], row['date']))
        print(f"   Found {len(existing_keys)} existing metric entries")
    else:
        print(f"{_safe_emoji('🔍')} Step 4/5: Force mode — will overwrite existing metrics")

    # ── Step 5: Aggregate and upsert ───────────────────────────────────
    print(f"{_safe_emoji('📤')} Step 5/5: Aggregating and upserting...")

    rows_to_upsert: list[dict] = []
    skipped = 0

    for (fund, dt), positions in grouped.items():
        date_str = str(dt)

        # Skip if already exists and not forcing
        if not force and (fund, date_str) in existing_keys:
            skipped += 1
            continue

        total_value = Decimal('0')
        cost_basis = Decimal('0')
        unrealized_pnl = Decimal('0')
        total_trades = 0

        for pos in positions:
            currency = (pos.get('currency') or 'CAD').strip().upper()
            if currency in ('NAN', 'NONE', 'NULL', ''):
                currency = 'CAD'

            tv = Decimal(str(pos.get('total_value', 0) or 0))
            cb = Decimal(str(pos.get('cost_basis', 0) or 0))
            pnl = Decimal(str(pos.get('pnl', 0) or 0))

            if currency == 'USD':
                rate = rate_cache.get(dt, Decimal('1.35'))
                tv *= rate
                cb *= rate
                pnl *= rate

            total_value += tv
            cost_basis += cb
            unrealized_pnl += pnl
            total_trades += 1

        performance_pct = (
            (float(unrealized_pnl) / float(cost_basis) * 100)
            if cost_basis > 0 else 0.0
        )

        rows_to_upsert.append({
            'fund': fund,
            'date': date_str,
            'total_value': float(total_value),
            'cost_basis': float(cost_basis),
            'unrealized_pnl': float(unrealized_pnl),
            'performance_pct': round(performance_pct, 2),
            'total_trades': total_trades,
            'winning_trades': 0,
            'losing_trades': 0,
        })

    print(f"   {len(rows_to_upsert)} rows to upsert, {skipped} skipped (already exist)")

    if not rows_to_upsert:
        print(f"\n{_safe_emoji('✅')} Nothing to backfill — all metrics already exist!")
        return

    # Batch upsert in chunks of 100 (Supabase limit)
    batch_size = 100
    upserted = 0
    for i in range(0, len(rows_to_upsert), batch_size):
        batch = rows_to_upsert[i:i + batch_size]
        try:
            client.supabase.table("performance_metrics")\
                .upsert(batch, on_conflict='fund,date')\
                .execute()
            upserted += len(batch)
            print(f"   Upserted {upserted}/{len(rows_to_upsert)}...", end='\r')
        except Exception as e:
            print(f"\n   {_safe_emoji('❌')} Batch upsert failed at offset {i}: {e}")
            # Try individual inserts for this batch
            for row in batch:
                try:
                    client.supabase.table("performance_metrics")\
                        .upsert(row, on_conflict='fund,date')\
                        .execute()
                    upserted += 1
                except Exception as row_err:
                    print(f"   {_safe_emoji('❌')} Failed: {row['fund']} {row['date']}: {row_err}")

    print(f"\n\n{_safe_emoji('✅')} Backfill complete!")
    print(f"   Rows upserted: {upserted}")
    print(f"   Rows skipped:  {skipped}")
    print(f"   Total fund-date combos: {len(grouped)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fast backfill of performance_metrics table')
    parser.add_argument('--fund', help='Only backfill for specific fund')
    parser.add_argument('--from-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--force', action='store_true', help='Overwrite existing metrics')

    args = parser.parse_args()

    fd = datetime.strptime(args.from_date, '%Y-%m-%d').date() if args.from_date else None
    td = datetime.strptime(args.to_date, '%Y-%m-%d').date() if args.to_date else None

    backfill_performance_metrics(
        fund_filter=args.fund,
        from_date=fd,
        to_date=td,
        force=args.force
    )
