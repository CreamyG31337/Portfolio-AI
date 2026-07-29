#!/usr/bin/env python3
"""Monitor executive LLM ticker-resolution quality and queue progress.

Re-reads ``og_asset_ticker_map`` (source=llm) and re-validates each mapping
against yfinance. Flags weak or suspicious hits so you can delete bad rows and
re-enqueue before backfilling trades.

Usage (from web_dashboard/):
    python scripts/monitor_executive_ticker_resolution.py
    python scripts/monitor_executive_ticker_resolution.py --sample 30
    python scripts/monitor_executive_ticker_resolution.py --revalidate

If you need to fix bad rows and restart:
    1. Stop the local worker process (Ctrl+C on the worker terminal).
    2. Delete bad cache rows:
         DELETE FROM og_asset_ticker_map WHERE source = 'llm' AND canonical_description IN (...);
       Or wipe all LLM rows: DELETE FROM og_asset_ticker_map WHERE source = 'llm';
    3. Cancel pending tasks (optional, if you want a clean re-run):
         UPDATE ai_task_queue SET status = 'cancelled'
         WHERE analysis_type = 'executive_ticker_resolve' AND status IN ('pending','leased');
    4. Re-enqueue: python scripts/enqueue_executive_ticker_resolution.py
    5. Restart workers (see enqueue script doc / prior session command).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WEB_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(WEB_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_DIR))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("monitor_executive_ticker_resolution")

ANALYSIS_TYPE = "executive_ticker_resolve"


@dataclass(frozen=True)
class CacheRow:
    canonical_description: str
    ticker: str
    confidence: float
    asset_type: str


@dataclass(frozen=True)
class QualityFinding:
    canonical_description: str
    ticker: str
    confidence: float
    yfinance_name: str
    issue: str


def _lead_token(name: str) -> str:
    from executive_ticker_resolver import canonicalize_oge_company_name

    tokens = canonicalize_oge_company_name(name).split()
    for tok in tokens:
        if len(tok) >= 3:
            return tok
    return tokens[0] if tokens else ""


def _fetch_queue_stats(client: Any) -> dict[str, int]:
    rows = (
        client.supabase.table("ai_task_queue")
        .select("status")
        .eq("analysis_type", ANALYSIS_TYPE)
        .execute()
        .data
        or []
    )
    return dict(Counter(str(r.get("status") or "unknown") for r in rows))


def _fetch_llm_cache(client: Any) -> list[CacheRow]:
    rows = (
        client.supabase.table("og_asset_ticker_map")
        .select("canonical_description,ticker,confidence,asset_type,resolved_at")
        .eq("source", "llm")
        .order("resolved_at", desc=True)
        .execute()
        .data
        or []
    )
    out: list[CacheRow] = []
    for row in rows:
        key = str(row.get("canonical_description") or "").strip()
        ticker = str(row.get("ticker") or "").upper().strip()
        if not key or not ticker:
            continue
        try:
            confidence = float(row.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        out.append(
            CacheRow(
                canonical_description=key,
                ticker=ticker,
                confidence=confidence,
                asset_type=str(row.get("asset_type") or "Stock"),
            )
        )
    return out


def _yfinance_name(ticker: str) -> str:
    try:
        import yfinance as yf
    except ImportError:
        return ""
    try:
        search = yf.Search(ticker, max_results=5, news_count=0, enable_fuzzy_query=False)
        for quote in search.quotes if hasattr(search, "quotes") else []:
            if str(quote.get("symbol") or "").upper() == ticker.upper():
                return str(quote.get("longname") or quote.get("shortname") or "")
    except Exception:  # noqa: BLE001
        return ""
    return ""


def assess_quality(
    rows: list[CacheRow], *, revalidate: bool
) -> list[QualityFinding]:
    from executive_ticker_resolver import (
        canonicalize_oge_company_name,
        confirm_ticker_symbol,
        _names_overlap,
    )

    findings: list[QualityFinding] = []
    for row in rows:
        yf_name = _yfinance_name(row.ticker)
        lead = _lead_token(row.canonical_description)
        issues: list[str] = []

        if row.confidence < 0.65:
            issues.append(f"low_confidence={row.confidence:.2f}")

        if yf_name and lead and lead not in canonicalize_oge_company_name(yf_name):
            issues.append(f"lead_token_{lead!r}_missing_in_{yf_name!r}")

        if yf_name and not _names_overlap(
            canonicalize_oge_company_name(row.canonical_description), yf_name
        ):
            issues.append("name_overlap_weak")

        if revalidate:
            ok = confirm_ticker_symbol(row.ticker, row.canonical_description)
            if not ok:
                issues.append("revalidate_failed")

        if issues:
            findings.append(
                QualityFinding(
                    canonical_description=row.canonical_description,
                    ticker=row.ticker,
                    confidence=row.confidence,
                    yfinance_name=yf_name,
                    issue="; ".join(issues),
                )
            )
    return findings


def _print_report(
    queue: dict[str, int],
    cache_rows: list[CacheRow],
    findings: list[QualityFinding],
    *,
    sample: int,
) -> None:
    total_tasks = sum(queue.values())
    done = queue.get("done", 0)
    pending = queue.get("pending", 0)
    leased = queue.get("leased", 0)
    failed = queue.get("failed", 0)

    print("=== Executive ticker resolution monitor ===")
    print(f"Queue ({ANALYSIS_TYPE}): total={total_tasks}")
    for status in ("done", "pending", "leased", "failed", "cancelled"):
        if status in queue:
            print(f"  {status}: {queue[status]}")

    if total_tasks:
        pct = 100.0 * done / total_tasks
        print(f"  progress: {done}/{total_tasks} ({pct:.1f}%)")

    print(f"LLM cache rows: {len(cache_rows)}")
    if done:
        hit_rate = 100.0 * len(cache_rows) / done
        print(f"  cache hit rate (llm rows / done tasks): {hit_rate:.1f}%")

    print()
    print(f"Recent resolutions (up to {sample}):")
    print(f"{'CANONICAL':<28} {'TICKER':<8} {'CONF':>5}  YFINANCE NAME")
    print("-" * 72)
    for row in cache_rows[:sample]:
        yf_name = _yfinance_name(row.ticker)[:32]
        print(
            f"{row.canonical_description[:28]:<28} {row.ticker:<8} {row.confidence:5.2f}  {yf_name}"
        )

    if findings:
        print()
        print(f"FLAGGED ({len(findings)} suspicious):")
        for f in findings[:sample]:
            print(
                f"  {f.canonical_description!r} -> {f.ticker} "
                f"(conf={f.confidence:.2f}, yf={f.yfinance_name!r})"
            )
            print(f"    {f.issue}")
    else:
        print()
        print("FLAGGED: none in sampled cache rows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=20,
        help="How many recent cache rows to display (default 20).",
    )
    parser.add_argument(
        "--revalidate",
        action="store_true",
        help="Re-run confirm_ticker_symbol on each LLM row (slower, uses yfinance).",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(WEB_DASHBOARD_DIR / ".env")
    load_dotenv(WEB_DASHBOARD_DIR.parent / ".env")

    from supabase_client import SupabaseClient

    client = SupabaseClient(use_service_role=True)
    queue = _fetch_queue_stats(client)
    cache_rows = _fetch_llm_cache(client)
    findings = assess_quality(cache_rows, revalidate=args.revalidate)
    _print_report(queue, cache_rows, findings, sample=max(1, args.sample))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
