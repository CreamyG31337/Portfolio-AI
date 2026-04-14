#!/usr/bin/env python3
"""
Fix dividend_log rows affected by the legacy eligibility bug (sells summed as buys).

Default is **dry-run** (no writes). Use ``--execute`` to apply changes.

After ``--execute``, rebuild portfolio state from trade_log for affected funds, e.g. run
``update_portfolio_prices_job`` (scheduler) so ``portfolio_positions`` / ``performance_metrics``
stay consistent with corrected DRIP trades.

Staging: use ``--fund "My Fund"`` and/or ``--limit N`` before a full run.

Environment: ``web_dashboard/.env`` with service role (same as ``SupabaseClient(use_service_role=True)``).
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

# Project root (…/web_dashboard/scripts -> …/LLM-Micro-Cap-trading-bot)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DASHBOARD = _PROJECT_ROOT / "web_dashboard"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_WEB_DASHBOARD))

from dotenv import load_dotenv

from scheduler.dividend_log_datafix import (
    parse_ex_date,
    legacy_sum_shares_before_ex,
    recalc_amounts,
    resolve_per_share,
    row_amounts_need_update,
    quantize_reinvested_shares,
)
from scheduler.jobs_dividends import (
    _is_drip_fund,
    calculate_eligible_shares,
    fetch_dividend_data,
    get_fund_dividend_mode,
    get_fund_type,
)
from web_dashboard.supabase_client import SupabaseClient

load_dotenv(_WEB_DASHBOARD / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


def _dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def fetch_all_dividend_log(
    client: SupabaseClient,
    fund_filter: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        q = client.supabase.table("dividend_log").select("*").order("pay_date", desc=True)
        if fund_filter:
            q = q.eq("fund", fund_filter)
        q = q.range(offset, offset + BATCH_SIZE - 1)
        res = q.execute()
        batch = res.data or []
        rows.extend(batch)
        if limit is not None and len(rows) >= limit:
            return rows[:limit]
        if len(batch) < BATCH_SIZE:
            break
        offset += BATCH_SIZE
        if offset > 50000:
            logger.warning("Stopped at 50k row safety cap; use --fund or rerun with offset if needed.")
            break
    return rows


def process_rows(
    client: SupabaseClient,
    rows: list[dict[str, Any]],
    execute: bool,
    csv_writer: Any | None,
) -> dict[str, int]:
    stats = defaultdict(int)
    events_cache: dict[str, list] = {}
    affected_funds: set[str] = set()

    for row in rows:
        row_id = row["id"]
        fund = row["fund"]
        ticker = row["ticker"]
        try:
            ex_date = parse_ex_date(row["ex_date"])
        except (TypeError, ValueError) as e:
            logger.error("Bad ex_date row %s: %s", row_id, e)
            stats["errors"] += 1
            continue

        eligible = calculate_eligible_shares(fund, ticker, ex_date, client)
        legacy_sum = legacy_sum_shares_before_ex(fund, ticker, ex_date, client)

        fund_type = get_fund_type(fund, client)
        dividend_mode = get_fund_dividend_mode(fund, client, fund_type)
        is_drip = _is_drip_fund(dividend_mode)
        trade_log_id = row.get("trade_log_id")

        old_gross = _dec(row.get("gross_amount"))
        old_tax = _dec(row.get("withholding_tax"))
        old_net = _dec(row.get("net_amount"))
        old_reinvested = _dec(row.get("reinvested_shares"))
        drip_price = _dec(row.get("drip_price"))

        log_line: dict[str, Any] = {
            "id": row_id,
            "fund": fund,
            "ticker": ticker,
            "ex_date": str(ex_date),
            "eligible": str(eligible),
            "legacy_sum": str(legacy_sum),
            "action": "",
            "old_net": str(old_net),
            "new_net": "",
            "per_share_source": "",
        }

        if eligible <= 0:
            log_line["action"] = "delete"
            log_line["per_share_source"] = "n/a"
            stats["to_delete"] += 1
            if csv_writer:
                csv_writer.writerow(log_line)
            if execute:
                client.supabase.table("dividend_log").delete().eq("id", row_id).execute()
                if trade_log_id:
                    client.supabase.table("trade_log").delete().eq("id", trade_log_id).execute()
                affected_funds.add(fund)
                stats["deleted"] += 1
            continue

        if ticker not in events_cache:
            events_cache[ticker] = fetch_dividend_data(ticker)
        events = events_cache[ticker]

        try:
            per_share, src = resolve_per_share(
                ticker, ex_date, old_gross, legacy_sum, events
            )
        except ValueError as e:
            logger.error("Row %s %s/%s ex=%s: %s", row_id, fund, ticker, ex_date, e)
            stats["errors"] += 1
            log_line["action"] = "error_no_per_share"
            if csv_writer:
                csv_writer.writerow(log_line)
            continue

        log_line["per_share_source"] = src
        new_gross, new_tax, new_net = recalc_amounts(
            eligible, per_share, fund_type, ticker
        )

        if is_drip and trade_log_id and drip_price > 0:
            new_reinvested = quantize_reinvested_shares(new_net, drip_price)
        else:
            new_reinvested = Decimal("0")

        needs_update = row_amounts_need_update(
            old_gross,
            old_tax,
            old_net,
            old_reinvested,
            new_gross,
            new_tax,
            new_net,
            new_reinvested,
        )

        if not needs_update:
            stats["unchanged"] += 1
            log_line["action"] = "skip"
            log_line["new_net"] = str(new_net)
            if csv_writer:
                csv_writer.writerow(log_line)
            continue

        log_line["action"] = "update_drip" if (is_drip and trade_log_id) else "update_cash"
        log_line["new_net"] = str(new_net)
        stats["to_update"] += 1
        if csv_writer:
            csv_writer.writerow(log_line)

        if not execute:
            continue

        affected_funds.add(fund)

        # DRIP with positive reinvestment: update dividend_log + trade_log
        if is_drip and trade_log_id and new_reinvested > 0:
            client.supabase.table("dividend_log").update(
                {
                    "gross_amount": float(new_gross),
                    "withholding_tax": float(new_tax),
                    "net_amount": float(new_net),
                    "reinvested_shares": float(new_reinvested),
                    "drip_price": float(drip_price.quantize(Decimal("0.01"))),
                }
            ).eq("id", row_id).execute()

            client.supabase.table("trade_log").update(
                {
                    "shares": float(new_reinvested),
                    "cost_basis": float(new_net),
                    "price": float(drip_price.quantize(Decimal("0.01"))),
                    "pnl": 0.0,
                }
            ).eq("id", trade_log_id).execute()
            stats["updated_drip"] += 1
            continue

        # Cash-style or DRIP collapsed to zero reinvestment
        patch = {
            "gross_amount": float(new_gross),
            "withholding_tax": float(new_tax),
            "net_amount": float(new_net),
            "reinvested_shares": 0.0,
        }
        if trade_log_id and new_reinvested <= 0:
            client.supabase.table("dividend_log").update(
                {**patch, "trade_log_id": None}
            ).eq("id", row_id).execute()
            client.supabase.table("trade_log").delete().eq("id", trade_log_id).execute()
            stats["updated_cash_unlinked_trade"] += 1
        else:
            client.supabase.table("dividend_log").update(patch).eq("id", row_id).execute()
            stats["updated_cash"] += 1

    if affected_funds:
        logger.info("Affected funds (rebuild portfolio from trade_log): %s", sorted(affected_funds))

    return dict(stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply deletes/updates (default is dry-run).",
    )
    parser.add_argument("--fund", type=str, default=None, help="Only process this fund name.")
    parser.add_argument("--limit", type=int, default=None, help="Max dividend_log rows to process.")
    parser.add_argument("--csv", type=str, default=None, help="Write report CSV to this path.")
    args = parser.parse_args()

    execute = bool(args.execute)
    if not execute:
        logger.info("DRY RUN (no DB writes). Pass --execute to apply.")

    client = SupabaseClient(use_service_role=True)
    rows = fetch_all_dividend_log(client, args.fund, args.limit)
    logger.info("Loaded %s dividend_log rows.", len(rows))

    csv_writer = None
    csv_file = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "id",
                "fund",
                "ticker",
                "ex_date",
                "eligible",
                "legacy_sum",
                "action",
                "old_net",
                "new_net",
                "per_share_source",
            ],
        )
        csv_writer.writeheader()

    try:
        stats = process_rows(client, rows, execute, csv_writer)
    finally:
        if csv_file:
            csv_file.close()

    for k, v in sorted(stats.items()):
        logger.info("%s: %s", k, v)


if __name__ == "__main__":
    main()
