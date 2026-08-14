#!/usr/bin/env python3
"""Run ticker_analysis + ticker_meta_analysis now for one ticker (this process's code).

Use this instead of enqueueing when production workers may still be on a build
that treats Yahoo D/E percent as a ratio.

Usage (repo root):
  python web_dashboard/scripts/run_one_ticker_reanalyze.py WEB.V
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

_web_dashboard = Path(__file__).resolve().parent.parent
_repo_root = _web_dashboard.parent
for _p in (str(_repo_root), str(_web_dashboard)):
    if _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(_web_dashboard))

os.environ.setdefault("DISABLE_SCHEDULER", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_web_dashboard / ".env")
load_dotenv(_repo_root / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("run_one_ticker_reanalyze")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", help="Ticker to re-analyze (e.g. WEB.V)")
    parser.add_argument("--skip-meta", action="store_true")
    args = parser.parse_args()
    ticker = args.ticker.upper().strip()

    from ai_skip_list_manager import AISkipListManager
    from meta_analysis_service import TickerMetaAnalysisService
    from ollama_client import get_ollama_client
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient
    from ticker_analysis_service import TickerAnalysisService

    ollama = get_ollama_client()
    if not ollama:
        logger.error("No LLM client (Ollama/GLM) configured")
        return 1
    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()
    analysis = TickerAnalysisService(
        ollama, supabase, postgres, AISkipListManager(supabase)
    )
    logger.info("Running ticker_analysis for %s", ticker)
    result = analysis.analyze_ticker(ticker, requested_by="false_leverage_catchup")
    if not result:
        logger.error("ticker_analysis returned nothing for %s", ticker)
        return 1
    logger.info(
        "Saved stance=%s risks=%s",
        result.get("stance"),
        json.dumps(result.get("risks") or [], default=str)[:500],
    )

    if not args.skip_meta:
        meta = TickerMetaAnalysisService(ollama, supabase, postgres)
        logger.info("Running ticker_meta_analysis for %s", ticker)
        meta_row = meta.run_meta_analysis(
            ticker, requested_by="false_leverage_catchup", force=True
        )
        if meta_row:
            logger.info(
                "Meta conviction=%s",
                meta_row.get("unified_conviction") or meta_row.get("stance"),
            )
        else:
            logger.warning("ticker_meta_analysis returned nothing for %s", ticker)

    rows = postgres.execute_query(
        """
        SELECT stance, risks, summary, updated_at
        FROM ticker_analysis
        WHERE ticker = %s AND analysis_type = 'standard'
        ORDER BY updated_at DESC NULLS LAST
        LIMIT 1
        """,
        (ticker,),
    ) or []
    if rows:
        row = rows[0]
        print("==== stored ticker_analysis ====")
        print("updated_at:", row.get("updated_at"))
        print("stance:", row.get("stance"))
        print("risks:", row.get("risks"))
        print("summary:", (row.get("summary") or "")[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
