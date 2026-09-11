"""Grok Bot weekday X-sweep ingest: token auth, watchlist queue, brief upsert."""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any

from watchlist_access import get_active_watchlist_rows, normalize_ticker

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST_FUNDS = ("Project Chimera", "RRSP Lance Webull")
QUEUE_LIMIT = 5
DAILY_TICKER_CAP = 5
MAX_BRIEFS_PER_REQUEST = 5
MAX_POSTS_PER_TICKER = 8
MAX_THEMES = 20
MAX_THEME_CHARS = 100
MAX_BODY_CHARS = 65536
ELIGIBLE_TIERS = frozenset({"A", "B"})
SKIP_SOURCES = frozenset({"ideas_inbox"})
INGESTED_STATUS = "ingested"


class GrokBotAuthError(Exception):
    """Token missing, unset, or invalid."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class GrokBotRequestError(Exception):
    """Caller-fixable request problem (400/429)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def get_watchlist_funds() -> list[str]:
    """Funds whose A/B watchlists feed the weekday queue.

    Prod default is Chimera + RRSP Lance Webull. Local override:
    ``GROK_WATCHLIST_FUNDS`` (comma-separated) or ``GROK_WATCHLIST_FUND`` (one name).
    """
    multi = (os.getenv("GROK_WATCHLIST_FUNDS") or "").strip()
    if multi:
        return [part.strip() for part in multi.split(",") if part.strip()]
    single = (os.getenv("GROK_WATCHLIST_FUND") or "").strip()
    if single:
        return [single]
    return list(DEFAULT_WATCHLIST_FUNDS)


def get_watchlist_fund() -> str:
    """First configured fund (compat). Prefer get_watchlist_funds()."""
    funds = get_watchlist_funds()
    return funds[0] if funds else DEFAULT_WATCHLIST_FUNDS[0]


def utc_today() -> date:
    return datetime.now(UTC).date()


def verify_grok_bot_token(authorization_header: str | None) -> None:
    """Raise GrokBotAuthError if the Bearer token is missing or wrong."""
    expected = (os.getenv("GROK_BOT_TOKEN") or "").strip()
    if not expected:
        logger.error("GROK_BOT_TOKEN is not set — refusing Grok Bot requests")
        raise GrokBotAuthError("Grok Bot ingest is not configured", 503)

    supplied = _bearer_token(authorization_header)
    if not supplied:
        raise GrokBotAuthError("Authentication required", 401)
    if not secrets.compare_digest(supplied, expected):
        raise GrokBotAuthError("Invalid token", 401)


def _bearer_token(authorization_header: str | None) -> str:
    raw = (authorization_header or "").strip()
    if not raw:
        return ""
    prefix = "Bearer "
    if raw[:7].lower() != prefix.lower():
        return ""
    return raw[7:].strip()


def eligible_watchlist_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A/B active names, excluding Ideas-inbox discovery adds.

    Same ticker on multiple funds is one row with ``funds`` merged; A-tier wins.
    """
    by_ticker: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = normalize_ticker(str(row.get("ticker") or ""))
        if not ticker:
            continue
        if not bool(row.get("is_active", True)):
            continue
        tier = str(row.get("priority_tier") or "C").strip().upper()
        if tier not in ELIGIBLE_TIERS:
            continue
        source = str(row.get("source") or "").strip()
        if source in SKIP_SOURCES:
            continue
        fund = str(row.get("fund") or "").strip()
        existing = by_ticker.get(ticker)
        if existing is None:
            by_ticker[ticker] = {
                "ticker": ticker,
                "priority_tier": tier,
                "funds": [fund] if fund else [],
                "source": source,
                "is_active": True,
            }
            continue
        if fund and fund not in existing["funds"]:
            existing["funds"].append(fund)
        if tier == "A":
            existing["priority_tier"] = "A"
    return list(by_ticker.values())


def select_queue_items(
    watchlist_rows: list[dict[str, Any]],
    last_briefs: dict[str, dict[str, Any]],
    *,
    today: date,
    limit: int = QUEUE_LIMIT,
) -> list[dict[str, Any]]:
    """Pick today's worklist: A then B, skip already-briefed today, never-briefed first."""
    eligible = eligible_watchlist_rows(watchlist_rows)
    candidates: list[dict[str, Any]] = []
    for row in eligible:
        ticker = str(row["ticker"])
        last = last_briefs.get(ticker)
        if last is not None and _as_date(last.get("sweep_date")) == today:
            continue
        candidates.append(row)

    def sort_key(row: dict[str, Any]) -> tuple[int, int, datetime]:
        tier_rank = 0 if row.get("priority_tier") == "A" else 1
        last = last_briefs.get(str(row["ticker"]))
        never = 0 if last is None else 1
        last_at = _as_datetime(last.get("created_at") if last else None)
        return (tier_rank, never, last_at)

    candidates.sort(key=sort_key)
    picked = candidates[: max(0, limit)]
    items: list[dict[str, Any]] = []
    for row in picked:
        ticker = str(row["ticker"])
        last = last_briefs.get(ticker)
        funds = [str(f) for f in (row.get("funds") or []) if f]
        items.append(
            {
                "ticker": ticker,
                "priority_tier": row.get("priority_tier") or "B",
                "fund": funds[0] if funds else None,
                "funds": funds,
                "last_brief_at": _iso(last.get("created_at") if last else None),
                "last_cited_urls": list(last.get("cited_urls") or []) if last else [],
            }
        )
    return items


def fetch_last_briefs(
    pg: Any,
    *,
    funds: list[str],
    tickers: list[str],
) -> dict[str, dict[str, Any]]:
    if not tickers or not funds:
        return {}
    rows = pg.execute_query(
        """
        SELECT DISTINCT ON (ticker)
            ticker, created_at, cited_urls, sweep_date, fund
        FROM grok_x_briefs
        WHERE fund = ANY(%s) AND ticker = ANY(%s)
        ORDER BY ticker, created_at DESC
        """,
        (funds, tickers),
    )
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        ticker = normalize_ticker(str(row.get("ticker") or ""))
        if ticker:
            out[ticker] = dict(row)
    return out


def count_distinct_tickers_for_day(pg: Any, *, funds: list[str], sweep_date: date) -> int:
    if not funds:
        return 0
    rows = pg.execute_query(
        """
        SELECT COUNT(DISTINCT ticker) AS n
        FROM grok_x_briefs
        WHERE fund = ANY(%s) AND sweep_date = %s
        """,
        (funds, sweep_date),
    )
    if not rows:
        return 0
    return int(rows[0].get("n") or 0)


def tickers_already_briefed_today(
    pg: Any,
    *,
    funds: list[str],
    sweep_date: date,
    tickers: list[str],
) -> set[str]:
    if not tickers or not funds:
        return set()
    rows = pg.execute_query(
        """
        SELECT ticker
        FROM grok_x_briefs
        WHERE fund = ANY(%s) AND sweep_date = %s AND ticker = ANY(%s)
        """,
        (funds, sweep_date, tickers),
    )
    return {normalize_ticker(str(r.get("ticker") or "")) for r in rows or []}


def build_queue(
    pg: Any,
    supabase_client: Any,
    *,
    funds: list[str] | None = None,
    today: date | None = None,
    limit: int = QUEUE_LIMIT,
) -> list[dict[str, Any]]:
    today_d = today or utc_today()
    fund_list = list(funds or get_watchlist_funds())
    rows: list[dict[str, Any]] = []
    for fund in fund_list:
        rows.extend(
            get_active_watchlist_rows(supabase_client, fund=fund, fallback_if_empty=False)
        )
    eligible = eligible_watchlist_rows(rows)
    for row in eligible:
        row["funds"] = _order_funds(row.get("funds") or [], fund_list)
    tickers = [str(r["ticker"]) for r in eligible]
    last_briefs = fetch_last_briefs(pg, funds=fund_list, tickers=tickers)
    already_today = count_distinct_tickers_for_day(pg, funds=fund_list, sweep_date=today_d)
    remaining = max(0, DAILY_TICKER_CAP - already_today)
    return select_queue_items(eligible, last_briefs, today=today_d, limit=min(limit, remaining))


def _order_funds(found: list[Any], preferred: list[str]) -> list[str]:
    names = [str(f) for f in found if f]
    ordered = [f for f in preferred if f in names]
    for name in names:
        if name not in ordered:
            ordered.append(name)
    return ordered


def parse_brief_payloads(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload or not isinstance(payload, dict):
        raise GrokBotRequestError("JSON object required")
    if "briefs" in payload:
        raw_list = payload.get("briefs")
        if not isinstance(raw_list, list) or not raw_list:
            raise GrokBotRequestError("briefs must be a non-empty list")
        if len(raw_list) > MAX_BRIEFS_PER_REQUEST:
            raise GrokBotRequestError(f"at most {MAX_BRIEFS_PER_REQUEST} briefs per request")
        return [_normalize_one_brief(item) for item in raw_list]
    return [_normalize_one_brief(payload)]


def _normalize_one_brief(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise GrokBotRequestError("each brief must be an object")
    ticker = normalize_ticker(str(item.get("ticker") or ""))
    if not ticker:
        raise GrokBotRequestError("ticker is required")
    body = item.get("body")
    if not isinstance(body, str) or not body.strip():
        raise GrokBotRequestError("body is required")
    if len(body) > MAX_BODY_CHARS:
        raise GrokBotRequestError(f"body exceeds {MAX_BODY_CHARS} characters")
    sweep_date = _parse_sweep_date(item.get("sweep_date"))
    notable = bool(item.get("notable", False))
    themes = [
        theme[:MAX_THEME_CHARS]
        for theme in _string_list(item.get("themes"), field="themes", limit=MAX_THEMES)
    ]
    posts = _normalize_posts(item.get("posts"))
    cited_urls = [str(p["url"]) for p in posts if p.get("url")]
    fund = str(item.get("fund") or "").strip() or None
    return {
        "ticker": ticker,
        "fund": fund,
        "sweep_date": sweep_date,
        "body": body.strip(),
        "notable": notable,
        "themes": themes,
        "posts": posts,
        "cited_urls": cited_urls,
    }


def _parse_sweep_date(raw: Any) -> date:
    if raw is None or raw == "":
        return utc_today()
    if isinstance(raw, date) and not isinstance(raw, datetime):
        parsed = raw
    else:
        text = str(raw).strip()[:10]
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise GrokBotRequestError("sweep_date must be YYYY-MM-DD") from exc
    today = utc_today()
    if parsed not in (today, today - timedelta(days=1)):
        raise GrokBotRequestError("sweep_date must be today or yesterday (UTC)")
    return parsed


def _string_list(raw: Any, *, field: str, limit: int) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise GrokBotRequestError(f"{field} must be a list of strings")
    if len(raw) > limit:
        raise GrokBotRequestError(f"{field} exceeds {limit} items")
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _normalize_posts(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise GrokBotRequestError("posts must be a list")
    if len(raw) > MAX_POSTS_PER_TICKER:
        raise GrokBotRequestError(f"at most {MAX_POSTS_PER_TICKER} posts per ticker")
    posts: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise GrokBotRequestError("each post must be an object")
        url = str(item.get("url") or "").strip()
        if not url:
            raise GrokBotRequestError("each post needs a url")
        if not url.lower().startswith(("http://", "https://")):
            raise GrokBotRequestError("post url must start with http:// or https://")
        if len(url) > 2000:
            raise GrokBotRequestError("post url is too long")
        post: dict[str, str] = {"url": url}
        post_id = str(item.get("post_id") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if post_id:
            post["post_id"] = post_id[:200]
        if summary:
            post["summary"] = summary[:2000]
        posts.append(post)
    return posts


def watchlist_ticker_funds(
    supabase_client: Any,
    *,
    funds: list[str],
) -> dict[str, list[str]]:
    rows: list[dict[str, Any]] = []
    for fund in funds:
        rows.extend(
            get_active_watchlist_rows(supabase_client, fund=fund, fallback_if_empty=False)
        )
    eligible = eligible_watchlist_rows(rows)
    return {
        str(row["ticker"]): _order_funds(row.get("funds") or [], funds) for row in eligible
    }


def watchlist_ticker_set(
    supabase_client: Any,
    *,
    funds: list[str] | None = None,
    fund: str | None = None,
) -> set[str]:
    fund_list = list(funds) if funds is not None else ([fund] if fund else get_watchlist_funds())
    return set(watchlist_ticker_funds(supabase_client, funds=fund_list).keys())


def _resolve_store_fund(
    brief: dict[str, Any],
    ticker_funds: dict[str, list[str]],
) -> str:
    ticker = str(brief["ticker"])
    allowed = ticker_funds.get(ticker) or []
    requested = str(brief.get("fund") or "").strip()
    if requested:
        if requested not in allowed:
            raise GrokBotRequestError(f"ticker not on watchlist: {ticker} ({requested})")
        return requested
    if not allowed:
        raise GrokBotRequestError(f"ticker not on watchlist: {ticker}")
    return allowed[0]


def upsert_briefs(
    pg: Any,
    *,
    funds: list[str],
    briefs: list[dict[str, Any]],
    ticker_funds: dict[str, list[str]],
) -> list[dict[str, Any]]:
    if not briefs:
        raise GrokBotRequestError("no briefs to store")

    resolved: list[tuple[str, dict[str, Any]]] = []
    unknown: list[str] = []
    for brief in briefs:
        ticker = str(brief["ticker"])
        if ticker not in ticker_funds:
            unknown.append(ticker)
            continue
        resolved.append((_resolve_store_fund(brief, ticker_funds), brief))
    if unknown:
        raise GrokBotRequestError(f"ticker not on watchlist: {', '.join(sorted(set(unknown)))}")

    by_day: dict[date, list[dict[str, Any]]] = {}
    for _store_fund, brief in resolved:
        by_day.setdefault(brief["sweep_date"], []).append(brief)

    for sweep_date, day_briefs in by_day.items():
        existing = tickers_already_briefed_today(
            pg,
            funds=funds,
            sweep_date=sweep_date,
            tickers=[b["ticker"] for b in day_briefs],
        )
        new_tickers = {b["ticker"] for b in day_briefs} - existing
        already = count_distinct_tickers_for_day(pg, funds=funds, sweep_date=sweep_date)
        if already + len(new_tickers) > DAILY_TICKER_CAP:
            raise GrokBotRequestError(
                f"daily cap of {DAILY_TICKER_CAP} tickers reached for {sweep_date.isoformat()}",
                status_code=429,
            )

    stored: list[dict[str, Any]] = []
    for store_fund, brief in resolved:
        stored.append(_upsert_one(pg, fund=store_fund, brief=brief))
    return stored


def _upsert_one(pg: Any, *, fund: str, brief: dict[str, Any]) -> dict[str, Any]:
    rows = pg.execute_query(
        """
        INSERT INTO grok_x_briefs (
            fund, ticker, sweep_date, body, themes, posts, notable, cited_urls, status,
            created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s,
            ARRAY(SELECT jsonb_array_elements_text(%s::jsonb)),
            %s::jsonb,
            %s,
            ARRAY(SELECT jsonb_array_elements_text(%s::jsonb)),
            %s,
            now(), now()
        )
        ON CONFLICT (fund, ticker, sweep_date) DO UPDATE SET
            body = EXCLUDED.body,
            themes = EXCLUDED.themes,
            posts = EXCLUDED.posts,
            notable = EXCLUDED.notable,
            cited_urls = EXCLUDED.cited_urls,
            status = CASE
                WHEN grok_x_briefs.body IS DISTINCT FROM EXCLUDED.body
                    OR grok_x_briefs.posts IS DISTINCT FROM EXCLUDED.posts
                THEN 'ingested'
                ELSE grok_x_briefs.status
            END,
            updated_at = now()
        RETURNING id, fund, ticker, sweep_date, body, themes, posts, notable,
                  cited_urls, status, created_at, updated_at
        """,
        (
            fund,
            brief["ticker"],
            brief["sweep_date"],
            brief["body"],
            json.dumps(brief["themes"]),
            json.dumps(brief["posts"]),
            brief["notable"],
            json.dumps(brief["cited_urls"]),
            INGESTED_STATUS,
        ),
    )
    if not rows:
        raise RuntimeError("upsert returned no row")
    return serialize_brief_row(dict(rows[0]))


def serialize_brief_row(row: dict[str, Any]) -> dict[str, Any]:
    posts = row.get("posts")
    if isinstance(posts, str):
        try:
            posts = json.loads(posts)
        except json.JSONDecodeError:
            posts = []
    return {
        "id": str(row.get("id") or ""),
        "fund": row.get("fund"),
        "ticker": row.get("ticker"),
        "sweep_date": _iso(row.get("sweep_date")),
        "body": row.get("body"),
        "themes": list(row.get("themes") or []),
        "posts": posts if isinstance(posts, list) else [],
        "notable": bool(row.get("notable")),
        "cited_urls": list(row.get("cited_urls") or []),
        "status": row.get("status") or INGESTED_STATUS,
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
