#!/usr/bin/env python3
"""Phase K8 — sweep production holdings for videos about them, then optionally ingest.

Search is listing-only and costs **no caption quota** (§14), so the sweep runs wide by
default and reports what it found. Captions are fetched only for confirmed, ranked hits
and only when ``--ingest`` is passed, bounded by ``--max-fetches``.

Usage (from repo root, venv active)::

    python scripts/yt_holdings_sweep.py                        # dry run, all holdings
    python scripts/yt_holdings_sweep.py --ticker CCO.TO OKLO   # just these
    python scripts/yt_holdings_sweep.py --json > sweep.json
    python scripts/yt_holdings_sweep.py --ingest --max-fetches 20

Exit codes:
  0 completed
  1 no holdings resolved / fatal error
  2 bad CLI usage
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web_dashboard"
for path in (_REPO_ROOT, _WEB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

logger = logging.getLogger("yt_holdings_sweep")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass


def _holdings_rows(tickers: list[str] | None) -> list[dict[str, Any]]:
    """Production holdings joined to ``securities`` for company_name + sector."""
    from supabase_client import SupabaseClient

    client = SupabaseClient(use_service_role=True)
    if tickers:
        held = sorted({t.strip().upper() for t in tickers if t.strip()})
    else:
        funds = (
            client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
            .data
            or []
        )
        names = [f["name"] for f in funds]
        if not names:
            return []
        pos = (
            client.supabase.table("latest_positions")
            .select("ticker")
            .in_("fund", names)
            .execute()
            .data
            or []
        )
        held = sorted({str(p["ticker"]) for p in pos if p.get("ticker")})
    if not held:
        return []
    rows = (
        client.supabase.table("securities")
        .select("ticker,company_name,sector")
        .in_("ticker", held)
        .execute()
        .data
        or []
    )
    return [dict(r) for r in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search YouTube for held securities")
    parser.add_argument("--ticker", nargs="*", help="Limit to these tickers")
    parser.add_argument("--limit", type=int, default=12, help="Search hits per holding")
    parser.add_argument("--top", type=int, default=3, help="Confirmed hits to show/ingest")
    parser.add_argument(
        "--ingest", action="store_true", help="Fetch captions and land articles"
    )
    parser.add_argument(
        "--max-fetches",
        type=int,
        default=20,
        help="Hard ceiling on caption fetches this run (quota guard)",
    )
    parser.add_argument(
        "--sleep", type=float, default=1.0, help="Seconds between search calls"
    )
    parser.add_argument("--include-funds", action="store_true", help="Do not skip ETFs")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")

    from yt_holdings_search import search_holding, targets_from_holdings

    try:
        rows = _holdings_rows(args.ticker)
    except Exception as exc:
        logger.error("Could not load holdings: %s", exc)
        return 1

    targets = targets_from_holdings(rows, include_funds=args.include_funds)
    if not targets:
        print("No searchable holdings resolved.", file=sys.stderr)
        return 1

    report: list[dict[str, Any]] = []
    covered = 0
    for i, target in enumerate(targets):
        hits = search_holding(target, limit=args.limit)[: args.top]
        if hits:
            covered += 1
        report.append(
            {
                "ticker": target.ticker,
                "company": target.core_name,
                "query": target.query(),
                "confirmed": len(hits),
                "hits": [
                    {
                        "video_id": h.video_id,
                        "title": h.title,
                        "url": h.url,
                        "score": h.score,
                        "views": h.view_count,
                        "matched": list(h.matched),
                    }
                    for h in hits
                ],
            }
        )
        if not args.json:
            mark = "OK " if hits else "-- "
            print(f"{mark}{target.ticker:9} {target.core_name[:30]:32} {len(hits)} confirmed")
            for h in hits:
                views = f"{h.view_count:,}" if h.view_count else "?"
                print(f"      [{h.score:>2}] {views:>10}  {h.title[:64]}")
        if args.sleep and i < len(targets) - 1:
            time.sleep(args.sleep)

    pct = covered / len(targets) if targets else 0.0
    summary = {
        "holdings_searched": len(targets),
        "with_confirmed_hits": covered,
        "coverage": round(pct, 3),
        "results": report,
    }

    if args.ingest:
        summary["ingested"] = _ingest(report, args.max_fetches)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"\n{covered}/{len(targets)} holdings have a confirmed video ({pct:.0%})")
        if args.ingest:
            print(f"ingested: {summary['ingested']}")
    return 0


def _ingest(report: list[dict[str, Any]], max_fetches: int) -> dict[str, int]:
    """Land captions for confirmed hits, best-scored first, under a hard fetch cap."""
    from research_repository import ResearchRepository
    from yt_article_ingest import _production_holdings
    from yt_articles import ingest_video

    queue = sorted(
        (
            (hit, entry["ticker"])
            for entry in report
            for hit in entry["hits"]
        ),
        key=lambda pair: -pair[0]["score"],
    )[:max_fetches]

    repo = ResearchRepository()
    owned = _production_holdings()
    counts: dict[str, int] = {}
    for hit, ticker in queue:
        try:
            outcome = ingest_video(
                hit["video_id"],
                research_repo=repo,
                # Search hits have no youtube_sources row. expected_tickers stays
                # empty on purpose: this is not an issuer channel, so tickers must
                # come from the transcript (§26 / is_issuer_channel).
                source_row={"label": f"search:{ticker}", "expected_tickers": []},
                owned_tickers=owned,
            )
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            print(f"  {outcome.status:16} {ticker:9} {hit['title'][:52]}")
        except Exception as exc:
            counts["error"] = counts.get("error", 0) + 1
            logger.error("Ingest failed for %s: %s", hit["video_id"], exc)
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
