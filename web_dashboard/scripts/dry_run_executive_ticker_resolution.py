#!/usr/bin/env python3
"""
Dry-run executive ticker resolution against Open Cabinet JSON.

Reports resolution rates before writing to the database.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_DASHBOARD_PATH.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(WEB_DASHBOARD_PATH))

from executive_ticker_resolver import (  # noqa: E402
    ExecutiveTickerResolution,
    load_og_asset_ticker_cache,
    resolve_executive_asset,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_TRUMP_URL = (
    "https://raw.githubusercontent.com/tbrown034/open-cabinet/main/data/officials/"
    "trump-donald-j.json"
)


def _load_transactions(source: str) -> list[dict[str, Any]]:
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=60) as response:
            payload = json.load(response)
    else:
        with open(source, encoding="utf-8") as handle:
            payload = json.load(handle)

    if isinstance(payload, dict):
        transactions = payload.get("transactions") or []
    elif isinstance(payload, list):
        transactions = payload
    else:
        raise ValueError(f"Unsupported JSON shape in {source}")

    if not isinstance(transactions, list):
        raise ValueError(f"Expected transactions list in {source}")
    return transactions


def _load_cache_rows() -> list[dict[str, Any]]:
    try:
        from supabase_client import SupabaseClient

        client = SupabaseClient(use_service_role=True)
        result = (
            client.supabase.table("og_asset_ticker_map")
            .select("canonical_description, ticker, source, confidence, asset_type")
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("Could not load og_asset_ticker_map cache: %s", exc)
        return []


def run_dry_run(
    source: str,
    *,
    use_yfinance: bool,
    use_cache: bool,
    sample_unresolved: int,
) -> dict[str, Any]:
    transactions = _load_transactions(source)
    cache = load_og_asset_ticker_cache(_load_cache_rows()) if use_cache else {}

    results: list[ExecutiveTickerResolution] = []
    for txn in transactions:
        description = str(txn.get("description") or "")
        results.append(
            resolve_executive_asset(
                description,
                open_cabinet_ticker=txn.get("ticker"),
                cache=cache,
                use_yfinance=use_yfinance,
            )
        )

    counts = Counter()
    for result in results:
        if result.source == "skipped_bond":
            counts["skipped_bond"] += 1
        elif result.ticker:
            counts[f"resolved_{result.source}"] += 1
        else:
            counts["unresolved"] += 1

    non_bond_total = sum(1 for r in results if r.source != "skipped_bond")
    resolved_total = sum(1 for r in results if r.ticker)
    non_bond_resolved = sum(
        1 for r in results if r.ticker and r.source != "skipped_bond"
    )
    non_bond_rate = (non_bond_resolved / non_bond_total * 100) if non_bond_total else 0.0

    unresolved_samples = [
        r.canonical_description
        for r in results
        if r.ticker is None and r.source != "skipped_bond"
    ][:sample_unresolved]

    summary = {
        "total": len(transactions),
        "resolved_total": resolved_total,
        "non_bond_total": non_bond_total,
        "non_bond_resolved": non_bond_resolved,
        "non_bond_resolution_pct": round(non_bond_rate, 2),
        "counts": dict(counts),
        "unresolved_samples": unresolved_samples,
    }

    logger.info("Executive ticker resolution dry-run")
    logger.info("Source: %s", source)
    logger.info("Total transactions: %s", summary["total"])
    logger.info("Resolved (all): %s", summary["resolved_total"])
    logger.info("Skipped bonds/munis: %s", counts.get("skipped_bond", 0))
    logger.info("Non-bond resolved: %s / %s (%.2f%%)", non_bond_resolved, non_bond_total, non_bond_rate)
    for key in sorted(counts):
        if key.startswith("resolved_"):
            logger.info("  %s: %s", key, counts[key])
    logger.info("Unresolved: %s", counts.get("unresolved", 0))
    if unresolved_samples:
        logger.info("Unresolved samples:")
        for sample in unresolved_samples:
            logger.info("  - %s", sample)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_TRUMP_URL, help="URL or local JSON path")
    parser.add_argument(
        "--use-yfinance",
        action="store_true",
        help="Enable yfinance fallback (slow; hits external API)",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Load og_asset_ticker_map from Supabase when available",
    )
    parser.add_argument(
        "--sample-unresolved",
        type=int,
        default=15,
        help="Number of unresolved descriptions to print",
    )
    args = parser.parse_args()

    summary = run_dry_run(
        args.source,
        use_yfinance=args.use_yfinance,
        use_cache=args.use_cache,
        sample_unresolved=args.sample_unresolved,
    )
    if summary["non_bond_resolution_pct"] < 90.0 and args.use_yfinance:
        logger.warning(
            "Non-bond resolution %.2f%% is below 90%% target",
            summary["non_bond_resolution_pct"],
        )


if __name__ == "__main__":
    main()
