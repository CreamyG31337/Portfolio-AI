#!/usr/bin/env python3
"""
Backfill trade_log.reason for **earliest qualifying BUY** rows using the research DB
(``research_articles`` + ``securities``) + optional GLM.

For each (fund, ticker) in ``--funds``, picks the earliest BUY (``trade_log.action`` when set,
else inferred from reason), groups by ticker, generates one sentence per ticker, updates **only**
rows that are safe to overwrite (see below).

**Replaceable reasons (default):** exact match to ``--placeholder-reason`` (same default as
``mark_chimera_initial_buys.py``) **or** reason starting with ``Imported from Webull``. Any other
text on an initial-buy row is **skipped** (no GLM spend) unless you pass
``--force-overwrite-custom-reasons`` (production apply also requires ``--confirm-force-overwrite``).

Non-ETF tickers with **no** matching research article (``tickers`` array / ``.TO`` key) are **not**
updated. ETF tickers use templates or ``asset_class=ETF``.

Default ``--funds``: Project Chimera + RRSP Lance Webull (one command covers both; add others via ``--funds`` if needed).

Default: dry-run. Production writes require ``--apply`` and ``--confirm-production``.

Usage (repo root):
  python web_dashboard/scripts/backfill_webull_trade_reasons.py --quiet
  python web_dashboard/scripts/backfill_webull_trade_reasons.py --funds "Project Chimera" --max-tickers 3 --quiet
  python web_dashboard/scripts/backfill_webull_trade_reasons.py --apply --confirm-production --audit-file audit.jsonl

Python path: run from repo root; script adds ``web_dashboard/`` to ``sys.path``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

# Repo root on path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DASH = _REPO_ROOT / "web_dashboard"
sys.path.insert(0, str(_WEB_DASH))
sys.path.insert(0, str(_REPO_ROOT))

from env_loader import load_project_dotenv

load_project_dotenv()

import requests

from glm_config import get_zhipu_api_key
from postgres_client import PostgresClient
from supabase_client import SupabaseClient
from utils.trade_reason import infer_trade_action

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

WEBULL_REASON_PREFIX = "Imported from Webull"
# Keep in sync with mark_chimera_initial_buys.PLACEHOLDER_REASON
DEFAULT_PLACEHOLDER_REASON = "Initial buy (rationale pending)"
DEFAULT_FUNDS: Tuple[str, ...] = ("Project Chimera", "RRSP Lance Webull")

ZHIPU_API_URL = "https://api.z.ai/api/coding/paas/v4"
GLM_MODEL = "glm-5.1"
MAX_REASON_CHARS = 500
# Tier 1: conclusion + mechanical excerpts only (never full multi-ticker report body).
MAX_CONCLUSION_FOR_GLM = 1800
TICKER_CONTEXT_BEFORE = 450
TICKER_CONTEXT_AFTER = 650
MECHANICAL_EXCERPT_MAX = 2800
MAX_ETF_DESCRIPTION_FOR_GLM = 3500
GLM_SLEEP_SUCCESS_SEC = 3.0
GLM_MAX_RETRIES = 5
GLM_BASE_DELAY_SEC = 15

# Tier 3: ticker (exact as traded) -> rationale
ETF_TEMPLATES: Dict[str, str] = {}
for _t in ("VOO", "VTI", "VFV.TO", "XEQT.TO", "XIC.TO"):
    ETF_TEMPLATES[_t] = "Broad market index exposure for passive diversification."
for _t in ("XGD.TO", "CGL.TO", "GLCC.TO", "AEM.TO"):
    ETF_TEMPLATES[_t] = "Gold and precious metals exposure as inflation hedge and diversifier."
for _t in ("BUG", "CIBR", "XHAK.TO"):
    ETF_TEMPLATES[_t] = "Thematic cybersecurity ETF for sector exposure."
for _t in ("ITA", "LHX"):
    ETF_TEMPLATES[_t] = "Defense and aerospace sector exposure."
for _t in ("ROBO", "NXTG.TO"):
    ETF_TEMPLATES[_t] = "Thematic robotics and next-generation technology ETF."
for _t in ("ZEA.TO", "XHC.TO", "FXD", "FXG", "FXL", "FTXL"):
    ETF_TEMPLATES[_t] = "Sector ETF for diversified thematic exposure."

ETF_GENERIC = "ETF held for thematic or sector diversification."


def match_key_for_research(ticker: str) -> str:
    t = ticker.strip().upper()
    if t.endswith(".TO"):
        t = t[:-3]
    return t


def _ticker_search_needles(ticker: str) -> List[str]:
    """Symbols to locate in report body (longest first to prefer e.g. BRK.B over B)."""
    t = ticker.strip()
    if not t:
        return []
    seen: Set[str] = set()
    out: List[str] = []
    for n in (t, t.upper(), t.lower()):
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    u = t.upper()
    if u.endswith(".TO") and len(u) > 4:
        base = u[:-3]
        for n in (base, f"{base}.TO", f"{base}.To", f"{base}.to"):
            if n not in seen:
                seen.add(n)
                out.append(n)
    return sorted(out, key=len, reverse=True)


def _find_all_ci(haystack: str, needle: str) -> List[int]:
    if not needle or not haystack:
        return []
    hl = haystack.lower()
    nl = needle.lower()
    starts: List[int] = []
    start = 0
    while True:
        i = hl.find(nl, start)
        if i < 0:
            break
        starts.append(i)
        start = i + max(1, len(needle))
    return starts


def _merge_intervals(intervals: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ps, pe = merged[-1]
        if s <= pe + 1:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


def extract_ticker_excerpts_from_content(
    content: str,
    ticker: str,
    *,
    max_total: int = MECHANICAL_EXCERPT_MAX,
    before: int = TICKER_CONTEXT_BEFORE,
    after: int = TICKER_CONTEXT_AFTER,
) -> str:
    """Merged context windows around case-insensitive ticker mentions."""
    if not content or not ticker.strip():
        return ""
    n = len(content)
    intervals: List[Tuple[int, int]] = []
    for needle in _ticker_search_needles(ticker):
        for pos in _find_all_ci(content, needle):
            s = max(0, pos - before)
            e = min(n, pos + len(needle) + after)
            intervals.append((s, e))
    merged = _merge_intervals(intervals)
    if not merged:
        return ""
    gap = "\n\n[...]\n\n"
    parts: List[str] = []
    for i, (s, e) in enumerate(merged):
        chunk = content[s:e].strip()
        if not chunk:
            continue
        piece = (gap + chunk) if parts else chunk
        parts.append(piece)
    out = "".join(parts).strip()
    if len(out) > max_total:
        out = out[: max_total - 3].rsplit(" ", 1)[0] + "..."
    return out


def _fingerprint_supabase() -> str:
    url = os.getenv("SUPABASE_URL") or ""
    try:
        host = urlparse(url).hostname or url[:60]
    except Exception:
        host = url[:60]
    return host or "(no SUPABASE_URL)"


def _is_likely_test_supabase() -> bool:
    url = (os.getenv("SUPABASE_URL") or "").lower()
    return "localhost" in url or "127.0.0.1" in url or ":5433" in url or "test" in url


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s.replace(" ", "T", 1))


def _is_initial_buy_row(row: Dict[str, Any]) -> bool:
    act = str(row.get("action") or "").strip().upper()
    if act == "DIVIDEND":
        return False
    shares = float(row.get("shares") or 0)
    if shares <= 0:
        return False
    if act == "SELL":
        return False
    if act == "BUY":
        return True
    return infer_trade_action(row.get("reason"), default="BUY") == "BUY"


def _reason_is_replaceable(
    reason: Optional[str],
    *,
    placeholder: str,
    webull_prefix: str,
    force_any: bool,
) -> bool:
    if force_any:
        return True
    s = (reason or "").strip()
    if s == (placeholder or "").strip():
        return True
    return s.startswith(webull_prefix)


def _fetch_trade_log_in_funds(supabase: Any, funds: Sequence[str]) -> List[Dict[str, Any]]:
    """All trade_log rows in allowlist (ordered by date for stable earliest-buy picks)."""
    page_size = 1000
    offset = 0
    out: List[Dict[str, Any]] = []
    while True:
        q = (
            supabase.table("trade_log")
            .select("id,fund,ticker,date,reason,shares,action")
            .in_("fund", list(funds))
            .order("date")
            .range(offset, offset + page_size - 1)
        )
        res = q.execute()
        batch = res.data or []
        out.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return out


def _group_initial_buy_rows_by_ticker(
    rows: List[Dict[str, Any]], funds: Sequence[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """Earliest qualifying BUY per (fund, ticker), grouped by ticker."""
    fund_set = set(funds)
    by_pair: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        f = str(r.get("fund") or "")
        t = str(r.get("ticker") or "")
        if f not in fund_set or not t:
            continue
        by_pair[(f, t)].append(r)
    initial: List[Dict[str, Any]] = []
    for (f, t), lst in by_pair.items():
        buys = [x for x in lst if _is_initial_buy_row(x)]
        if not buys:
            continue
        buys.sort(key=lambda x: _parse_ts(x["date"]))
        initial.append(buys[0])
    by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in initial:
        by_ticker[str(r["ticker"])].append(r)
    return dict(by_ticker)


def _glm_chat(system: str, user: str, skip: bool) -> Optional[str]:
    if skip:
        return None
    api_key = get_zhipu_api_key()
    if not api_key:
        logger.error("GLM API key not configured (glm_config / env).")
        return None
    url = f"{ZHIPU_API_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: Dict[str, Any] = {
        "model": GLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.25,
        # GLM on Z.AI may use `reasoning_content`; long inputs + reasoning can exhaust budget before `content`.
        "max_tokens": 8192,
    }
    for attempt in range(GLM_MAX_RETRIES):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=240)
            if r.status_code == 429:
                if attempt < GLM_MAX_RETRIES - 1:
                    delay = GLM_BASE_DELAY_SEC * (2**attempt)
                    logger.warning("GLM 429; sleeping %.0fs...", delay)
                    time.sleep(delay)
                    continue
                logger.error("GLM rate limited after retries.")
                return None
            r.raise_for_status()
            data = r.json()
            if data.get("error"):
                logger.error("GLM API error object in body: %s", data.get("error"))
                return None
            choices = data.get("choices") or []
            if not choices:
                logger.warning("GLM returned no choices; body keys=%s", list(data.keys()))
                return None
            msg = choices[0].get("message") or {}
            finish = choices[0].get("finish_reason")
            text = msg.get("content") or ""
            if not str(text).strip():
                logger.warning(
                    "GLM empty message.content (finish_reason=%s, message keys=%s, raw content repr=%r)",
                    finish,
                    list(msg.keys()),
                    text[:200] if isinstance(text, str) else text,
                )
            text = str(text).strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
                text = re.sub(r"\s*```$", "", text).strip()
            text = text.strip('"').strip("'")
            text = re.sub(r"\s+", " ", text.strip())
            if len(text) > MAX_REASON_CHARS:
                text = text[: MAX_REASON_CHARS - 1].rsplit(" ", 1)[0] + "."
            if text:
                time.sleep(GLM_SLEEP_SUCCESS_SEC)
            return text or None
        except requests.RequestException as e:
            if attempt < GLM_MAX_RETRIES - 1:
                delay = GLM_BASE_DELAY_SEC * (2**attempt)
                logger.warning("GLM request error %s; retry in %.0fs", e, delay)
                time.sleep(delay)
            else:
                logger.error("GLM failed: %s", e)
                return None
    return None


def _load_research_reports(pg: PostgresClient) -> List[Dict[str, Any]]:
    sql = """
        SELECT id, title, tickers, fund, conclusion, content
        FROM research_articles
        WHERE article_type = 'Research Report'
    """
    return pg.execute_query(sql, None)


def _reports_by_match_key(
    reports: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in reports:
        tickers = r.get("tickers")
        if not tickers:
            continue
        if isinstance(tickers, str):
            tickers = [tickers]
        for raw in tickers:
            if not raw:
                continue
            key = match_key_for_research(str(raw))
            by_key[key].append(r)
    return by_key


def _pick_report_for_ticker(
    ticker: str, by_key: Dict[str, List[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    key = match_key_for_research(ticker)
    candidates = by_key.get(key) or []
    if not candidates:
        return None
    return candidates[0]


def _load_research_securities_rows(
    pg: PostgresClient, tickers: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    """Research DB securities row per ticker (for ETF Tier 3 GLM context)."""
    if not tickers:
        return {}
    sql = """
        SELECT ticker, asset_class, name, description, sector
        FROM securities
        WHERE ticker = ANY(%s)
    """
    rows = pg.execute_query(sql, (list(tickers),))
    return {str(r["ticker"]): dict(r) for r in rows}


def _tier3_template(ticker: str) -> Optional[str]:
    if ticker in ETF_TEMPLATES:
        return ETF_TEMPLATES[ticker]
    return None


def _validate_reason(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if len(t) > MAX_REASON_CHARS:
        return False
    return True


def run() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill trade_log.reason from research DB (+ optional GLM), earliest BUY per (fund,ticker)."
    )
    parser.add_argument(
        "--funds",
        type=str,
        default=",".join(DEFAULT_FUNDS),
        help="Comma-separated funds (default: Project Chimera + RRSP Lance Webull)",
    )
    parser.add_argument(
        "--placeholder-reason",
        type=str,
        default=DEFAULT_PLACEHOLDER_REASON,
        help="Reason text treated as safe to overwrite (must match mark_chimera_initial_buys if you use that script).",
    )
    parser.add_argument(
        "--force-overwrite-custom-reasons",
        action="store_true",
        help="Allow overwriting any reason on targeted initial-buy rows (dangerous).",
    )
    parser.add_argument(
        "--confirm-force-overwrite",
        action="store_true",
        help="Required with --apply --force-overwrite-custom-reasons on non-test Supabase.",
    )
    parser.add_argument("--apply", action="store_true", help="Perform Supabase updates (default: dry-run).")
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        help="Required with --apply when not using obvious test Supabase URL.",
    )
    parser.add_argument("--audit-file", type=str, default="", help="Append JSONL audit lines on apply.")
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip all GLM calls: Tier 1 stocks unchanged; Tier 3 ETFs use template/generic fallback only.",
    )
    parser.add_argument("--max-tickers", type=int, default=0, help="Process only first N tickers (sorted).")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print summary lines (no per-ticker blocks).",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default="",
        help="Comma-separated tickers to process (must be in candidate set). Overrides --max-tickers.",
    )
    args = parser.parse_args()

    funds = tuple(f.strip() for f in args.funds.split(",") if f.strip())
    if not funds:
        logger.error("Empty --funds")
        return 2

    force_any = bool(args.force_overwrite_custom_reasons)
    placeholder = (args.placeholder_reason or "").strip()

    logger.info("Supabase host fingerprint: %s", _fingerprint_supabase())
    likely_test = _is_likely_test_supabase()
    if likely_test:
        logger.info("Heuristic: SUPABASE_URL looks like a test/local target.")
    else:
        logger.warning("Heuristic: SUPABASE_URL does not look like test/local — treat as production data.")

    if args.apply and not likely_test and not args.confirm_production:
        logger.error("Refusing --apply without --confirm-production on non-test Supabase URL.")
        return 3

    if args.apply and force_any and not likely_test and not args.confirm_force_overwrite:
        logger.error(
            "Refusing --apply with --force-overwrite-custom-reasons without --confirm-force-overwrite "
            "on non-test Supabase URL."
        )
        return 7

    supabase = SupabaseClient(use_service_role=True).supabase
    pg = PostgresClient()

    rows = _fetch_trade_log_in_funds(supabase, funds)
    if not rows:
        logger.info("No trade_log rows in allowlist. Exiting.")
        return 0
    by_ticker = _group_initial_buy_rows_by_ticker(rows, funds)
    if not by_ticker:
        logger.info("No qualifying initial BUY rows in scope. Exiting.")
        return 0

    if args.tickers.strip():
        want = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        keys_upper = {k.upper() for k in by_ticker}
        tickers_sorted = sorted(k for k in by_ticker if k.upper() in want)
        missing = want - keys_upper
        if missing:
            logger.warning(
                "Requested tickers not in candidate set (ignored): %s", ", ".join(sorted(missing))
            )
    else:
        tickers_sorted = sorted(by_ticker.keys())
        if args.max_tickers and args.max_tickers > 0:
            tickers_sorted = tickers_sorted[: args.max_tickers]

    reports = _load_research_reports(pg)
    by_key = _reports_by_match_key(reports)
    sec_rows = _load_research_securities_rows(pg, tickers_sorted)

    # Tier 1 = stock + research report excerpts + GLM. Tier 3 = ETF + securities metadata + GLM
    # (template text only as fallback or with --skip-llm). No Tier 2.
    tier_counts = {1: 0, 3: 0, 0: 0}
    skipped: List[str] = []
    skipped_protected: List[str] = []
    planned: Dict[str, Dict[str, Any]] = {}

    for ticker in tickers_sorted:
        trows = by_ticker[ticker]
        trows_target = [
            r
            for r in trows
            if _reason_is_replaceable(
                str(r.get("reason") or ""),
                placeholder=placeholder,
                webull_prefix=WEBULL_REASON_PREFIX,
                force_any=force_any,
            )
        ]
        if not trows_target:
            if trows:
                skipped_protected.append(ticker)
                logger.info(
                    "Skipping %s: initial-buy row(s) have custom reasons (not placeholder/Webull). "
                    "Use --force-overwrite-custom-reasons to include.",
                    ticker,
                )
            tier_counts[0] += 1
            continue
        funds_here = sorted({str(x["fund"]) for x in trows_target})
        n = len(trows_target)
        tpl_fallback = _tier3_template(ticker)
        sr = sec_rows.get(ticker, {})
        asset_u = (sr.get("asset_class") or "").upper()
        is_etf = tpl_fallback is not None or asset_u == "ETF"

        if is_etf:
            tier = 3
            if tpl_fallback:
                hint = (
                    "Objective category hint (paraphrase the role in your own words; do not copy): "
                    f"{tpl_fallback}"
                )
            else:
                hint = (
                    "Holding is classified as an ETF — describe its portfolio role "
                    "(diversification, sector tilt, inflation hedge, etc.) conservatively."
                )

            if args.skip_llm:
                reason = tpl_fallback or ETF_GENERIC
                source = "ETF template (--skip-llm)"
            else:
                name = (sr.get("name") or "").strip()
                sector = (sr.get("sector") or "").strip()
                desc = (sr.get("description") or "").strip()
                if len(desc) > MAX_ETF_DESCRIPTION_FOR_GLM:
                    desc = desc[: MAX_ETF_DESCRIPTION_FOR_GLM - 3].rstrip() + "..."

                rep_e = _pick_report_for_ticker(ticker, by_key)
                excerpt_extra = ""
                if rep_e:
                    ex = extract_ticker_excerpts_from_content(str(rep_e.get("content") or ""), ticker)
                    if ex:
                        excerpt_extra = (
                            f"\n\nResearch report excerpts where {ticker} appears:\n{ex}"
                        )

                system = (
                    "You write exactly one trade-log sentence for an ETF position. "
                    "Ground it in the metadata below; if details are thin, state a plain "
                    "portfolio role (diversification, sector exposure, inflation hedge). "
                    "No marketing hype. Do not copy hints verbatim."
                )
                user = (
                    f"Ticker: {ticker}\n"
                    f"Name: {name or 'n/a'}\n"
                    f"Sector: {sector or 'n/a'}\n"
                    f"Description / fund objective:\n{desc or 'n/a'}\n\n"
                    f"{hint}{excerpt_extra}\n\n"
                    "Write exactly one sentence (max 28 words) stating why this ETF is held."
                )
                reason = _glm_chat(system, user, False) or ""
                if not reason:
                    reason = tpl_fallback or ETF_GENERIC
                    source = "ETF GLM empty; template fallback"
                else:
                    source = "ETF metadata + GLM"
        else:
            rep = _pick_report_for_ticker(ticker, by_key)
            if not rep:
                logger.info(
                    "No research report match for ticker %s (tickers array / .TO key); "
                    "leaving trade_log reason unchanged.",
                    ticker,
                )
                skipped.append(ticker)
                tier_counts[0] += 1
                continue
            tier = 1
            source = str(rep.get("title") or "research report")
            raw_conclusion = (rep.get("conclusion") or "").strip()
            if len(raw_conclusion) > MAX_CONCLUSION_FOR_GLM:
                conclusion = raw_conclusion[: MAX_CONCLUSION_FOR_GLM - 3].rstrip() + "..."
            else:
                conclusion = raw_conclusion
            body = str(rep.get("content") or "")
            excerpt = extract_ticker_excerpts_from_content(body, ticker)
            if not excerpt:
                logger.info(
                    "Report id=%s matches ticker %s on tickers[] but no symbol hits in body; "
                    "leaving reason unchanged.",
                    rep.get("id"),
                    ticker,
                )
                skipped.append(ticker)
                tier_counts[0] += 1
                continue
            system = (
                "You are writing a one-sentence investment rationale for a trade log. "
                "Be specific and factual. Do not use filler phrases like 'based on the analysis' "
                "or 'according to the report'. Just state the investment thesis directly. "
                "The excerpts only cover passages that mention this ticker; stay anchored to them."
            )
            user = (
                f"Report conclusion (may discuss multiple companies; only claim what fits {ticker}):\n"
                f"{conclusion}\n\n"
                f"Report body excerpts where {ticker} is mentioned:\n{excerpt}\n\n"
                f"Write exactly one sentence (max 25 words) explaining why {ticker} was a buy "
                f"candidate in fall 2025. Focus on valuation, growth drivers, or competitive advantage "
                f"for {ticker} only."
            )
            reason = _glm_chat(system, user, args.skip_llm) or ""
            if not reason:
                logger.warning(
                    "Tier 1 LLM returned empty for ticker %s (report id=%s); leaving reason unchanged.",
                    ticker,
                    rep.get("id"),
                )
                skipped.append(ticker)
                tier_counts[0] += 1
                continue

        if not _validate_reason(reason):
            skipped.append(ticker)
            tier_counts[0] += 1
            continue

        tier_counts[tier] += 1
        row_ids = [str(r["id"]) for r in trows_target]
        planned[ticker] = {
            "reason": reason,
            "tier": tier,
            "source": source,
            "row_count": n,
            "funds": funds_here,
            "row_ids": row_ids,
        }

        if not args.quiet:
            print(f"TICKER: {ticker}")
            print(f"TIER: {tier}")
            print(f"SOURCE: {source}")
            print(f"PROPOSED REASON: {reason}")
            print(f"AFFECTS: {n} trade_log rows (funds: {funds_here})  ids={row_ids}")
            if len(trows) != len(trows_target):
                print(f"  (skipped {len(trows) - len(trows_target)} fund(s) with protected reasons)")
            print("---")

    print()
    print("Summary (planned)")
    print("  Tier 1 (research report + GLM):", tier_counts[1])
    print("  Tier 3 (ETF metadata + GLM, or template if --skip-llm / GLM empty):", tier_counts[3])
    print("  Unchanged (no report match, LLM empty, or no replaceable reason):", tier_counts[0])
    print("  Skipped tickers:", ", ".join(skipped) if skipped else "(none)")
    print(
        "  Skipped (protected custom reasons on initial-buy row):",
        ", ".join(skipped_protected) if skipped_protected else "(none)",
    )

    if not args.apply:
        logger.info("Dry-run complete (--apply not set). No database writes.")
        return 0

    audit_fp = open(args.audit_file, "a", encoding="utf-8") if args.audit_file else None

    updated = 0
    try:
        for ticker, meta in planned.items():
            expected = meta["row_count"]
            row_ids = meta["row_ids"]
            exp_ids = set(row_ids)
            old_rows = (
                supabase.table("trade_log")
                .select("id,fund,reason,ticker")
                .in_("id", row_ids)
                .execute()
            )
            current = old_rows.data or []
            got_ids = {str(r["id"]) for r in current}
            if len(current) == 0:
                logger.warning(
                    "Skipping %s: no rows found for planned ids (likely deleted or id drift); continuing.",
                    ticker,
                )
                continue
            if got_ids != exp_ids:
                logger.error(
                    "Abort apply: ticker %s expected id set %s, got %s — stopping.",
                    ticker,
                    sorted(exp_ids),
                    sorted(got_ids),
                )
                return 5
            if len(current) != expected:
                logger.error(
                    "Abort apply: ticker %s expected %s rows, found %s — stopping without further updates.",
                    ticker,
                    expected,
                    len(current),
                )
                return 5
            for row in current:
                if str(row.get("ticker") or "") != ticker:
                    logger.error(
                        "Abort apply: row %s ticker mismatch (expected %s got %s).",
                        row.get("id"),
                        ticker,
                        row.get("ticker"),
                    )
                    return 5
            new_reason = meta["reason"]
            for row in current:
                old_reason = row.get("reason")
                if audit_fp:
                    audit_fp.write(
                        json.dumps(
                            {
                                "id": row["id"],
                                "fund": row.get("fund"),
                                "ticker": ticker,
                                "old_reason": old_reason,
                                "new_reason": new_reason,
                                "force_overwrite_custom_reasons": force_any,
                                "script": "backfill_initial_buy_reasons",
                                "utc_timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        + "\n"
                    )
                supabase.table("trade_log").update({"reason": new_reason, "action": "BUY"}).eq(
                    "id", row["id"]
                ).eq("reason", old_reason).execute()
            updated += len(current)
    finally:
        if audit_fp:
            audit_fp.close()

    print()
    logger.info("Apply complete. Rows touched: %s", updated)
    return 0


if __name__ == "__main__":
    sys.exit(run())
