#!/usr/bin/env python3
"""
List initial BUY tickers (per fund) that still need real reasons, and how they sit vs
``research_articles`` — same matching rules as ``backfill_webull_trade_reasons.py``.

For each ticker:
  - ``no_article``: no Research Report row lists this symbol in ``tickers`` (after
    ``match_key_for_research``: strip ``.TO`` suffix for lookup).
  - ``not_in_body``: an article matches on ``tickers[]`` but the ticker does not appear
    in ``content`` (Tier 1 backfill skips these until body mentions exist or you CSV).
  - ``tier1_ok``: article + symbol hits in body (backfill Tier 1 can run if reason is replaceable).
  - ``etf_tier3``: classified as ETF (template or ``securities.asset_class``); Tier 3 uses
    metadata + optional excerpt — not blocked by missing article.

Default: only tickers whose current ``trade_log.reason`` is incomplete (placeholder, Webull,
boilerplate, empty). Pass ``--all-initial-buys`` to score every earliest qualifying BUY.

Usage (repo root):

  python web_dashboard/scripts/report_chimera_research_gaps.py
  python web_dashboard/scripts/report_chimera_research_gaps.py --fund "Project Chimera" --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DASH = _REPO_ROOT / "web_dashboard"
_SCRIPTS = _WEB_DASH / "scripts"
sys.path.insert(0, str(_WEB_DASH))
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_SCRIPTS))

from env_loader import load_project_dotenv

load_project_dotenv()

from backfill_webull_trade_reasons import (  # noqa: E402
    _load_research_reports,
    _load_research_securities_rows,
    _pick_report_for_ticker,
    _reports_by_match_key,
    _tier3_template,
    extract_ticker_excerpts_from_content,
    match_key_for_research,
)
from check_initial_buy_reasons import (  # noqa: E402
    WEBULL_PREFIX,
    _classify,
    _initial_buys_for_fund,
)
from mark_chimera_initial_buys import CHIMERA_FUND_DEFAULT, PLACEHOLDER_REASON  # noqa: E402
from postgres_client import PostgresClient  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402


def _is_etf(ticker: str, sec_row: Dict[str, Any]) -> bool:
    if _tier3_template(ticker) is not None:
        return True
    return (sec_row.get("asset_class") or "").strip().upper() == "ETF"


def _research_status(
    ticker: str,
    *,
    by_key: Dict[str, List[Dict[str, Any]]],
    is_etf: bool,
) -> tuple[str, Optional[str], Optional[Any], bool]:
    """Returns (bucket, match_key, report_id_or_none, excerpt_non_empty)."""
    key = match_key_for_research(ticker)
    rep = _pick_report_for_ticker(ticker, by_key)
    if not rep:
        if is_etf:
            return ("etf_tier3", key, None, False)
        return ("no_article", key, None, False)
    body = str(rep.get("content") or "")
    excerpt = extract_ticker_excerpts_from_content(body, ticker)
    has_excerpt = bool(excerpt.strip())
    if is_etf:
        return ("etf_tier3", key, rep.get("id"), has_excerpt)
    if not has_excerpt:
        return ("not_in_body", key, rep.get("id"), False)
    return ("tier1_ok", key, rep.get("id"), True)


def run() -> int:
    p = argparse.ArgumentParser(description="Research DB coverage vs Chimera-style initial buys.")
    p.add_argument("--fund", default=CHIMERA_FUND_DEFAULT)
    p.add_argument("--placeholder", default=PLACEHOLDER_REASON)
    p.add_argument(
        "--all-initial-buys",
        action="store_true",
        help="Include every earliest qualifying BUY, not only incomplete/boilerplate reasons.",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    fund = args.fund.strip()
    if not fund:
        print("Empty --fund", file=sys.stderr)
        return 2

    supabase = SupabaseClient(use_service_role=True).supabase
    initial = _initial_buys_for_fund(supabase, fund)
    if not initial:
        print(f"No qualifying initial BUY rows for fund {fund!r}.")
        return 0

    ph = (args.placeholder or "").strip()
    tickers: List[str] = []
    for t in sorted(initial.keys()):
        row = initial[t]
        reason = str(row.get("reason") or "")
        if args.all_initial_buys or _classify(reason, placeholder=ph) != "ok":
            tickers.append(t)

    if not tickers:
        print("No tickers in scope (try --all-initial-buys).")
        return 0

    pg = PostgresClient()
    reports = _load_research_reports(pg)
    by_key = _reports_by_match_key(reports)
    sec_rows = _load_research_securities_rows(pg, tickers)

    rows_out: List[Dict[str, Any]] = []
    for ticker in tickers:
        row = initial[ticker]
        reason = str(row.get("reason") or "")
        cat = _classify(reason, placeholder=ph)
        sr = sec_rows.get(ticker, {})
        etf = _is_etf(ticker, sr)
        bucket, mkey, rid, excerpt_ok = _research_status(ticker, by_key=by_key, is_etf=etf)
        rep = _pick_report_for_ticker(ticker, by_key)
        title = (rep.get("title") or "")[:120] if rep else ""
        rows_out.append(
            {
                "ticker": ticker,
                "reason_category": cat,
                "match_key": mkey,
                "research_bucket": bucket,
                "is_etf": etf,
                "report_id": str(rid) if rid is not None else None,
                "report_title_preview": title,
                "symbol_in_report_body": excerpt_ok,
                "current_reason_preview": reason[:160],
            }
        )

    need_article = [r for r in rows_out if r["research_bucket"] == "no_article"]
    need_body = [
        r
        for r in rows_out
        if r["research_bucket"] == "not_in_body"
    ]
    etf_rows = [r for r in rows_out if r["research_bucket"] == "etf_tier3"]
    ok_research = [r for r in rows_out if r["research_bucket"] == "tier1_ok"]

    summary = {
        "fund": fund,
        "tickers_in_scope": len(rows_out),
        "no_research_article_tickers": len(need_article),
        "article_but_not_in_body_tickers": len(need_body),
        "etf_tier3_tickers": len(etf_rows),
        "tier1_research_ready": len(ok_research),
    }

    if args.json:
        print(json.dumps({"summary": summary, "rows": rows_out}, indent=2))
        return 0

    print(f"Fund: {fund}")
    print(f"Tickers in scope: {len(rows_out)}")
    print()
    print("Summary (for fixing research coverage)")
    print(
        f"  No Research Report lists symbol (add ticker to a report's tickers[] or import report): "
        f"{len(need_article)}"
    )
    print(
        f"  Report lists symbol but ticker not found in body text (re-ingest PDF or fix content): "
        f"{len(need_body)}"
    )
    print(
        f"  ETF (Tier 3 uses securities metadata; article optional): {len(etf_rows)}"
    )
    print(f"  Stock Tier-1 ready (article + symbol in body): {len(ok_research)}")
    print()

    def _block(title: str, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        print(f"{title} ({len(items)})")
        for r in sorted(items, key=lambda x: x["ticker"]):
            tid = r["report_id"] or "-"
            print(
                f"  {r['ticker']:12} match_key={r['match_key']!r}  "
                f"reason_cat={r['reason_category']}  report_id={tid}"
            )
            if r["report_title_preview"]:
                print(f"               title: {r['report_title_preview'][:100]}")
        print()

    _block("ADD / FIND REPORTS FOR (no article lists this symbol)", need_article)
    _block("REPORT EXISTS — ADD BODY MENTIONS OR RE-IMPORT (symbol not in content)", need_body)

    if ok_research:
        names = ", ".join(r["ticker"] for r in sorted(ok_research, key=lambda x: x["ticker"]))
        print(
            "Tier-1 research already usable (article + symbol in body); "
            f"backfill can fill reasons if replaceable: {names}"
        )
        print()

    if etf_rows:
        print(f"ETF / Tier-3 ({len(etf_rows)}) — research excerpt optional; check securities metadata")
        for r in sorted(etf_rows, key=lambda x: x["ticker"]):
            ex = "yes" if r["symbol_in_report_body"] else "no"
            print(f"  {r['ticker']:12} excerpt_in_body={ex}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(run())
