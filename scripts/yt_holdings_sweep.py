#!/usr/bin/env python3
"""Phase K8 — sweep production holdings for videos about them, then optionally ingest.

This is the CLI over ``scheduler.jobs_yt_sweep.sweep_holdings``, which is also what
the nightly ``youtube_holdings_sweep`` job runs. The logic lives there so the
hand-run and scheduled paths cannot drift — in particular the pre-filter against
``research_articles`` (``ingest_video`` fetches captions *before* its own
existence check, so re-offering a known video spends quota for nothing) and the
round-robin fetch budget.

Search is listing-only and costs **no caption quota** (§13), so the sweep runs wide by
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
from pathlib import Path

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
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")

    from research_repository import ResearchRepository
    from scheduler.jobs_yt_sweep import sweep_holdings

    ollama_client = None
    if args.ingest:
        try:
            from ollama_client import get_ollama_client

            ollama_client = get_ollama_client()
        except Exception as exc:
            logger.warning("Ollama client unavailable (no embeddings): %s", exc)

    try:
        summary = sweep_holdings(
            research_repo=ResearchRepository(),
            tickers=args.ticker,
            ollama_client=ollama_client,
            budget=args.max_fetches,
            search_limit=args.limit,
            top_per_holding=args.top,
            include_funds=args.include_funds,
            ingest=args.ingest,
            sleep_fn=(lambda _s: None) if not args.sleep else None,
        )
    except Exception as exc:
        logger.error("Sweep failed: %s", exc, exc_info=args.verbose)
        return 1

    if not summary.holdings_searched:
        print("No searchable holdings resolved.", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "holdings_searched": summary.holdings_searched,
                    "with_confirmed_hits": summary.with_confirmed_hits,
                    "coverage": round(summary.coverage, 3),
                    "planned": summary.planned,
                    "landed": summary.landed,
                    "skipped_known": summary.skipped_known,
                    "soft_failed": summary.soft_failed,
                    "errors": summary.errors,
                    "statuses": summary.statuses,
                    "results": summary.results,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    for entry in summary.results:
        hits = entry["hits"]
        mark = "OK " if hits else "-- "
        print(f"{mark}{entry['ticker']:9} {entry['company'][:30]:32} {len(hits)} confirmed")
        for h in hits:
            views = f"{h['views']:,}" if h.get("views") else "?"
            print(f"      [{h['score']:>2}] {views:>10}  {h['title'][:64]}")

    print(f"\n{summary.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
