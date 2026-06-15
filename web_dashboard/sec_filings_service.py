"""US SEC (EDGAR) filing-risk detection (ROADMAP G2).

The FORWARD/structural signal the shares-outstanding dilution watch (G3) can't
show: a shelf S-3 means dilution is *coming* before the share count moves; plus
late filings (distress), delisting notices, and activist/accumulation 13D/13G
stakes. US-only by nature — EDGAR has no Canadian filings (`.TO`/`.V` are
covered by G3's share-count watch).

Pure-logic + readers only; the network/scheduling lives in
`scheduler/jobs_sec_filings.py`. SEC HTTP goes through the shared throttled
client (`scheduler/sec_http.py`), never a per-call-site requests session.

Data shapes confirmed live 2026-06-14:
- ``company_tickers.json``: ``{"0": {"cik_str": 1045810, "ticker": "NVDA",
  "title": "NVIDIA CORP"}, ...}`` (~10.4k US entries).
- ``data.sec.gov/submissions/CIK{cik:010d}.json``: ``filings.recent`` is a set
  of PARALLEL arrays (form, filingDate, accessionNumber, primaryDocument, items,
  …) holding the latest ~1000 filings — no pagination needed for a nightly scan.
- 8-K item numbers are inline in the ``items`` array (e.g. "2.02,7.01,9.01"), so
  Item 3.01 (listing deficiency) needs NO extra fetch — substring-match ``items``.
- Schedule 13D is labeled "SCHEDULE 13D/A", not "SC 13D/A" — both spellings are
  matched by the ``13D``/``13G`` substring rule below.

See docs/PHASE_G_PLAN.md G2.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# Ticker→CIK map changes slowly (new listings/renames). Refresh weekly.
_CIK_CACHE_TTL_DAYS = 7

# Categories and directions persisted to filing_events.
CATEGORIES = ("dilution", "distress", "delisting", "activist")
DIRECTIONS = ("risk", "positive", "neutral")

# Dilution / capital-structure registrations and prospectus takedowns. A shelf
# (S-3) is the canonical "dilution is coming" signal; 424B* are takedowns off a
# shelf (dilution happening now). F-1/F-3 are the foreign-issuer equivalents.
_DILUTION_FORMS = {
    "S-1", "S-3", "F-1", "F-3", "424B2", "424B3", "424B4", "424B5", "EFFECT",
}
# Late-filing notifications = distress.
_DISTRESS_FORMS = {"NT 10-Q", "NT 10-K", "NT 20-F", "NT 10-D"}
# Exchange/issuer delisting notifications.
_DELISTING_FORMS = {"25", "25-NSE"}


def parse_company_tickers(raw: Any) -> dict[str, str]:
    """Build ``{TICKER: cik_10digit}`` from company_tickers.json.

    Accepts the live dict shape (index → entry) or a list of entries. Returns
    zero-padded 10-digit CIK strings ready for the submissions URL. Unknown /
    malformed entries are skipped, never raised.
    """
    out: dict[str, str] = {}
    if not raw:
        return out
    entries = raw.values() if isinstance(raw, dict) else raw
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ticker = (entry.get("ticker") or "").upper().strip()
        cik = entry.get("cik_str")
        if not ticker or cik is None:
            continue
        try:
            out[ticker] = f"{int(cik):010d}"
        except (TypeError, ValueError):
            continue
    return out


def _default_cache_path() -> Path:
    return Path(__file__).resolve().parent / ".cache" / "sec_company_tickers.json"


def load_ticker_cik_map(
    *,
    cache_path: Optional[Path] = None,
    ttl_days: int = _CIK_CACHE_TTL_DAYS,
    force_refresh: bool = False,
    fetcher: Optional[Callable[[], Any]] = None,
) -> dict[str, str]:
    """Return ``{TICKER: cik_10digit}``, cached on disk and refreshed weekly.

    ``fetcher`` is injectable for tests; in production it pulls
    ``company_tickers.json`` through the shared throttled SEC client. A fetch
    miss falls back to the (possibly stale) cache, then to an empty map — the
    caller skips-and-logs every unmapped ticker and never errors.
    """
    path = cache_path or _default_cache_path()
    raw: Any = None

    if not force_refresh and path.exists():
        try:
            age = time.time() - path.stat().st_mtime
            if age < ttl_days * 86400:
                raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - cache is best-effort
            logger.debug("CIK cache read failed (%s); will refetch", exc)
            raw = None

    if raw is None:
        fetch = fetcher or _fetch_company_tickers
        fetched = fetch()
        if fetched:
            raw = fetched
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(fetched), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001 - cache write is best-effort
                logger.debug("CIK cache write failed: %s", exc)
        elif path.exists():
            # Fetch failed but a stale cache exists — better than nothing.
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                logger.warning("company_tickers.json fetch failed; using stale CIK cache")
            except Exception:  # noqa: BLE001
                raw = None

    return parse_company_tickers(raw)


def _fetch_company_tickers() -> Any:
    from scheduler.sec_http import fetch_json

    return fetch_json(COMPANY_TICKERS_URL)


def classify_filing(form: str, items: str = "") -> Optional[tuple[str, str]]:
    """Classify a filing into ``(category, direction)`` or ``None`` if not tracked.

    Rules (live-confirmed 2026-06-14):
    - 8-K: only flag Item 3.01 (listing deficiency) → distress/risk. Item numbers
      are inline in ``items`` (e.g. "2.02,7.01,9.01"), so a substring match
      suffices — no per-8-K document fetch. All other 8-Ks are ignored.
    - 13D / 13G (any of "SC 13D/A", "SCHEDULE 13D/A", "SC 13G", …): activist /
      accumulation → positive. The ``13D``/``13G`` substring match handles BOTH
      the "SC" and "SCHEDULE" spellings the feed mixes.
    - Form 25 / 25-NSE: delisting → risk.
    - NT 10-Q / NT 10-K / …: late filing → distress/risk.
    - S-1/S-3/F-1/F-3/424B*/EFFECT (incl. /A amendments): dilution intent → risk.
    - S-8 (employee benefit plan registration): dilution → neutral. Routine and
      un-sizeable without full-text, so flagged but not alarmed.
    """
    f = (form or "").upper().strip()
    if not f:
        return None
    it = items or ""

    # 8-K: only the listing-deficiency item is a tracked risk.
    if f.startswith("8-K"):
        if "3.01" in it:
            return ("distress", "risk")
        return None

    # Activist / accumulation — both "SC 13D/A" and "SCHEDULE 13D/A" spellings.
    # (13F is institutional holdings, not 13D/13G — the substrings don't collide.)
    if "13D" in f or "13G" in f:
        return ("activist", "positive")

    if f in _DELISTING_FORMS:
        return ("delisting", "risk")

    if f in _DISTRESS_FORMS:
        return ("distress", "risk")

    # Routine employee-plan registration: dilution but low-signal.
    base = f.split("/")[0].strip()  # "S-3/A" -> "S-3"
    if base == "S-8":
        return ("dilution", "neutral")

    if base in _DILUTION_FORMS:
        return ("dilution", "risk")

    return None


def _filing_url(cik: str, accession_no: str, primary_document: str) -> str:
    """Build the EDGAR Archives URL for a filing's primary document."""
    acc_nodash = (accession_no or "").replace("-", "")
    try:
        cik_int = int(str(cik).lstrip("0") or "0")
    except (TypeError, ValueError):
        cik_int = 0
    if not acc_nodash or not cik_int:
        return ""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}"
    return f"{base}/{primary_document}" if primary_document else f"{base}/"


def extract_filing_events(
    ticker: str,
    cik: str,
    submissions: Any,
    *,
    since_date: Optional[str] = None,
    max_events: int = 100,
) -> list[dict[str, Any]]:
    """Parse ``submissions.filings.recent`` (parallel arrays) into tracked events.

    Only filings on/after ``since_date`` (ISO ``YYYY-MM-DD``, lexicographically
    comparable) and matching :func:`classify_filing` are returned. No pagination
    — ``recent`` already holds the latest ~1000 filings.
    """
    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    accessions = recent.get("accessionNumber") or []
    items_arr = recent.get("items") or []
    primary_docs = recent.get("primaryDocument") or []
    descriptions = recent.get("primaryDocDescription") or []

    ticker_u = (ticker or "").upper().strip()
    out: list[dict[str, Any]] = []

    for i, form in enumerate(forms):
        filed = dates[i] if i < len(dates) else ""
        if since_date and filed and filed < since_date:
            continue
        items = items_arr[i] if i < len(items_arr) else ""
        cls = classify_filing(form, items)
        if not cls:
            continue
        category, direction = cls
        accession_no = accessions[i] if i < len(accessions) else ""
        if not accession_no:
            continue
        doc = primary_docs[i] if i < len(primary_docs) else ""
        desc = descriptions[i] if i < len(descriptions) else ""
        report_date = report_dates[i] if i < len(report_dates) else ""
        out.append({
            "ticker": ticker_u,
            "cik": str(cik),
            "form_type": form,
            "category": category,
            "direction": direction,
            "filed_at": filed or None,
            "accession_no": accession_no,
            "title": (desc or form) or form,
            "url": _filing_url(cik, accession_no, doc),
            "raw": {
                "form": form,
                "items": items,
                "filingDate": filed,
                "reportDate": report_date,
                "primaryDocument": doc,
            },
        })
        if len(out) >= max_events:
            break
    return out


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate filings by ``accession_no``, preserving first-seen order.

    Mirrors the DB ``UNIQUE (accession_no)`` constraint so reruns / overlapping
    scan windows don't re-insert the same filing.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for ev in events:
        acc = ev.get("accession_no")
        if not acc or acc in seen:
            continue
        seen.add(acc)
        out.append(ev)
    return out


def fetch_recent_filing_alerts(
    postgres: Any, *, tickers: Optional[list[str]] = None, days: int = 14, limit: int = 50
) -> list[dict[str, Any]]:
    """Recent filing events for the Today briefing + dossier, newest first.

    Degrades to an empty list if ``filing_events`` doesn't exist yet (the table
    is applied by a human after this ships — see G2 DB rule), matching
    ``dilution_service.fetch_recent_dilution_flags``.
    """
    params: list[Any] = [days]
    ticker_filter = ""
    if tickers:
        ticker_filter = "AND ticker = ANY(%s)"
        params.append([t.upper() for t in tickers])
    params.append(limit)
    try:
        # Cast date → text: the Today briefing payload is jsonified without a
        # date encoder, so return JSON-safe types only.
        return postgres.execute_query(
            f"""
            SELECT ticker, cik, form_type, category, direction,
                   filed_at::text AS filed_at, accession_no, title, url
            FROM filing_events
            WHERE filed_at >= (CURRENT_DATE - (%s || ' days')::interval)
              {ticker_filter}
            ORDER BY filed_at DESC, created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
    except Exception as exc:  # noqa: BLE001 - table may not exist yet
        logger.warning("fetch_recent_filing_alerts failed (table missing?): %s", exc)
        return []


def default_since_date(lookback_days: int) -> str:
    """ISO ``YYYY-MM-DD`` cutoff ``lookback_days`` before today (UTC)."""
    return (datetime.now(UTC).date() - timedelta(days=lookback_days)).isoformat()
