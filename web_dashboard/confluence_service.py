"""Cross-signal confluence scorer (ROADMAP G4).

Counts when multiple independent signal families align on a ticker within a
short window. No LLM — reads existing tables/services only.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, UTC
from typing import Any

from stance_history import record_stance_safe

logger = logging.getLogger(__name__)

WINDOW_DAYS_DEFAULT = 10
SOCIAL_LOOKBACK_DAYS = 14
SOCIAL_MIN_DAILY_ROWS = 7
SOCIAL_Z_THRESHOLD = 2.0
MIN_SCORE_PERSIST = 2
MIN_SCORE_LEDGER = 3
DEDUPE_WINDOW_DAYS = 10

FAMILY_SIGNALS = "signals"

BULLISH_FLIP_STANCES = frozenset({"BULLISH", "BUY", "VERY_BULLISH"})
BEARISH_FLIP_STANCES = frozenset({"BEARISH", "SELL", "VERY_BEARISH", "AVOID"})

_PAGE_SIZE = 1000


def _empty_hits() -> dict[str, Any]:
    return {"bullish": set(), "risk": set(), "details": {}}


def _sorted_families(families: set[str]) -> list[str]:
    return sorted(families)


def build_confluence_events_from_hits(
    ticker_hits: dict[str, dict[str, Any]],
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Pure: turn per-ticker family hits into 0–2 confluence event dicts."""
    as_of = as_of or datetime.now(UTC)
    events: list[dict[str, Any]] = []
    for ticker, hits in ticker_hits.items():
        bullish = set(hits.get("bullish") or ())
        risk = set(hits.get("risk") or ())
        details = dict(hits.get("details") or {})
        if len(bullish) >= MIN_SCORE_PERSIST:
            events.append({
                "ticker": ticker.upper(),
                "as_of": as_of,
                "direction": "bullish",
                "score": len(bullish),
                "families": _sorted_families(bullish),
                "details": {k: details[k] for k in _sorted_families(bullish) if k in details},
            })
        if len(risk) >= MIN_SCORE_PERSIST:
            events.append({
                "ticker": ticker.upper(),
                "as_of": as_of,
                "direction": "risk",
                "score": len(risk),
                "families": _sorted_families(risk),
                "details": {k: details[k] for k in _sorted_families(risk) if k in details},
            })
    return events


def _production_fund_names(supabase_client: Any) -> list[str]:
    try:
        res = (
            supabase_client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
        )
        return [r["name"] for r in (res.data or []) if r.get("name")]
    except Exception as exc:
        logger.warning("confluence: production-fund lookup failed: %s", exc)
        return []


def collect_scope_tickers(supabase_client: Any) -> list[str]:
    """Production-fund holdings + active watchlist (mirrors dilution_watch)."""
    tickers: set[str] = set()
    production_funds = _production_fund_names(supabase_client)
    try:
        offset = 0
        while True:
            holdings_query = supabase_client.supabase.table("latest_positions").select(
                "ticker,fund"
            )
            if production_funds:
                holdings_query = holdings_query.in_("fund", production_funds)
            pos = holdings_query.range(offset, offset + _PAGE_SIZE - 1).execute()
            page = pos.data or []
            for row in page:
                if row.get("ticker"):
                    tickers.add(str(row["ticker"]).upper())
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        offset = 0
        while True:
            wl = (
                supabase_client.supabase.table("watched_tickers_v2")
                .select("ticker")
                .eq("is_active", True)
                .range(offset, offset + _PAGE_SIZE - 1)
                .execute()
            )
            page = wl.data or []
            for row in page:
                if row.get("ticker"):
                    tickers.add(str(row["ticker"]).upper())
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
    except Exception as exc:
        logger.warning("confluence ticker load failed: %s", exc)
    return sorted(tickers)


def _apply_stance_flips(
    hits: dict[str, dict[str, Any]],
    flips: list[dict[str, Any]],
) -> None:
    for flip in flips:
        ticker = str(flip.get("ticker") or "").upper()
        if not ticker:
            continue
        to_stance = str(flip.get("to_stance") or "").upper()
        bucket = hits.setdefault(ticker, _empty_hits())
        detail = {
            "from_stance": flip.get("from_stance"),
            "to_stance": flip.get("to_stance"),
            "flipped_at": str(flip.get("flipped_at") or ""),
            "source": flip.get("source"),
        }
        if to_stance in BULLISH_FLIP_STANCES:
            bucket["bullish"].add("stance_flip_bullish")
            bucket["details"]["stance_flip_bullish"] = detail
        elif to_stance in BEARISH_FLIP_STANCES:
            bucket["risk"].add("stance_flip_bearish")
            bucket["details"]["stance_flip_bearish"] = detail


def _apply_insider_clusters(
    hits: dict[str, dict[str, Any]],
    clusters: list[dict[str, Any]],
) -> None:
    for cluster in clusters:
        ticker = str(cluster.get("ticker") or "").upper()
        if not ticker:
            continue
        bucket = hits.setdefault(ticker, _empty_hits())
        bucket["bullish"].add("insider_cluster")
        bucket["details"]["insider_cluster"] = {
            "insider_count": cluster.get("insider_count"),
            "buy_count": cluster.get("buy_count"),
            "latest_buy": cluster.get("latest_buy"),
        }


def _fetch_congress_purchase_tickers(
    supabase_client: Any,
    tickers: set[str],
    *,
    window_days: int,
) -> set[str]:
    if not tickers:
        return set()
    cutoff = (datetime.now(UTC).date() - timedelta(days=window_days)).isoformat()
    ticker_list = sorted(tickers)
    found: set[str] = set()
    try:
        # Scope the ticker filter to the DB instead of scanning every congressional
        # purchase market-wide; batch to stay well under Supabase IN-list limits.
        for i in range(0, len(ticker_list), 100):
            batch = ticker_list[i : i + 100]
            res = (
                supabase_client.supabase.table("congress_trades_enriched")
                .select("ticker")
                .eq("type", "Purchase")
                .neq("quality_status", "garbage")
                .gte("transaction_date", cutoff)
                .in_("ticker", batch)
                .execute()
            )
            for row in res.data or []:
                t = str(row.get("ticker") or "").upper()
                if t:
                    found.add(t)
    except Exception as exc:
        logger.warning("confluence congress fetch failed: %s", exc)
    return found


def _detect_social_spike_tickers(
    postgres: Any,
    tickers: list[str],
) -> set[str]:
    if not tickers:
        return set()
    try:
        rows = postgres.execute_query(
            """
            SELECT ticker, created_at::date AS day,
                   COALESCE(volume, 0) + COALESCE(post_count, 0) AS activity
            FROM social_metrics
            WHERE ticker = ANY(%s)
              AND created_at >= NOW() - (%s || ' days')::interval
            ORDER BY ticker, day
            """,
            (tickers, SOCIAL_LOOKBACK_DAYS),
        )
    except Exception as exc:
        logger.warning("confluence social_metrics fetch failed: %s", exc)
        return set()

    by_ticker: dict[str, dict[date, int]] = defaultdict(dict)
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        day = row.get("day")
        if not ticker or not day:
            continue
        activity = int(row.get("activity") or 0)
        by_ticker[ticker][day] = by_ticker[ticker].get(day, 0) + activity

    spiking: set[str] = set()
    for ticker, daily in by_ticker.items():
        if len(daily) < SOCIAL_MIN_DAILY_ROWS:
            continue
        days_sorted = sorted(daily.keys())
        values = [daily[d] for d in days_sorted]
        latest = values[-1]
        history = values[:-1] or values
        if len(history) < 2:
            continue
        mean = statistics.mean(history)
        if mean <= 0:
            continue
        try:
            std = statistics.pstdev(history)
        except statistics.StatisticsError:
            continue
        if std == 0:
            if latest > mean:
                spiking.add(ticker)
            continue
        if latest > mean + SOCIAL_Z_THRESHOLD * std:
            spiking.add(ticker)
    return spiking


def _fetch_signal_hits(
    supabase_client: Any,
    tickers: set[str],
    *,
    window_days: int,
) -> dict[str, dict[str, Any]]:
    if not tickers:
        return {}
    cutoff = (datetime.now(UTC).date() - timedelta(days=window_days)).isoformat()
    ticker_list = sorted(tickers)
    latest_by_ticker: dict[str, dict[str, Any]] = {}
    try:
        # signal_analysis holds ~1 row/ticker/day, so a 10d window is ~10 rows/ticker.
        # Keep batch_size * window_rows under the 1000-row REST cap or later tickers in
        # the batch get truncated away and silently miss the signals family.
        # TODO(confluence): If the window widens or signal cadence increases (>20 rows/ticker
        # per 50-ticker batch), paginate or tighten the per-batch .limit(1000) — see PR #393 review.
        for i in range(0, len(ticker_list), 50):
            batch = ticker_list[i : i + 50]
            res = (
                supabase_client.supabase.table("signal_analysis")
                .select("ticker,analysis_date,structure_signal,overall_signal,confidence_score")
                .in_("ticker", batch)
                .gte("analysis_date", cutoff)
                .order("analysis_date", desc=True)
                .limit(1000)
                .execute()
            )
            for row in res.data or []:
                t = str(row.get("ticker") or "").upper()
                if t and t not in latest_by_ticker:
                    latest_by_ticker[t] = row
    except Exception as exc:
        logger.warning("confluence signal_analysis fetch failed: %s", exc)
        return {}

    hits: dict[str, dict[str, Any]] = {}
    for ticker, row in latest_by_ticker.items():
        structure = row.get("structure_signal") or {}
        if isinstance(structure, str):
            try:
                structure = json.loads(structure)
            except json.JSONDecodeError:
                structure = {}
        trend = str(structure.get("trend") or "").upper()
        breakout = structure.get("breakout")
        is_breakout = breakout is True or str(breakout).lower() == "true"
        if trend == "UPTREND" or is_breakout:
            hits[ticker] = {
                "trend": trend,
                "breakout": is_breakout,
                "analysis_date": str(row.get("analysis_date") or ""),
                "overall_signal": row.get("overall_signal"),
            }
    return hits


def _fetch_filing_hits(
    postgres: Any, tickers: list[str], *, window_days: int
) -> dict[str, dict[str, set[str]]]:
    if not tickers:
        return {}
    try:
        rows = postgres.execute_query(
            """
            SELECT ticker, direction, category, form_type, filed_at
            FROM filing_events
            WHERE ticker = ANY(%s)
              AND filed_at >= (CURRENT_DATE - (%s || ' days')::interval)
            """,
            (tickers, window_days),
        )
    except Exception as exc:
        logger.warning("confluence filing_events fetch failed: %s", exc)
        return {}

    out: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"bullish": set(), "risk": set()}
    )
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        direction = str(row.get("direction") or "").lower()
        if direction == "positive":
            out[ticker]["bullish"].add("filing_positive")
        elif direction == "risk":
            out[ticker]["risk"].add("filing_risk")
    return dict(out)


def _fetch_dilution_hits(postgres: Any, tickers: list[str], *, window_days: int) -> set[str]:
    if not tickers:
        return set()
    try:
        rows = postgres.execute_query(
            """
            SELECT DISTINCT ticker
            FROM dilution_observations
            WHERE ticker = ANY(%s)
              AND flagged = TRUE
              AND as_of >= (CURRENT_DATE - (%s || ' days')::interval)
            """,
            (tickers, window_days),
        )
        return {str(r["ticker"]).upper() for r in rows if r.get("ticker")}
    except Exception as exc:
        logger.warning("confluence dilution_observations fetch failed: %s", exc)
        return set()


def gather_ticker_hits(
    postgres: Any,
    supabase_client: Any,
    tickers: list[str],
    *,
    window_days: int = WINDOW_DAYS_DEFAULT,
) -> dict[str, dict[str, Any]]:
    """Collect all family hits for the given ticker scope."""
    ticker_set = {t.upper() for t in tickers}
    hits: dict[str, dict[str, Any]] = {}

    from today_briefing_service import fetch_stance_flips

    flips = fetch_stance_flips(postgres, days=window_days, limit=500)
    _apply_stance_flips(hits, flips)

    try:
        from insider_clusters_service import build_insider_cluster_buys

        clusters = build_insider_cluster_buys(
            supabase_client, days=max(window_days, 7), limit=200
        )
        _apply_insider_clusters(hits, clusters)
    except Exception as exc:
        logger.warning("confluence insider clusters failed: %s", exc)

    for ticker in _fetch_congress_purchase_tickers(
        supabase_client, ticker_set, window_days=window_days
    ):
        bucket = hits.setdefault(ticker, _empty_hits())
        bucket["bullish"].add("congress_purchase")
        bucket["details"]["congress_purchase"] = {"type": "Purchase"}

    for ticker in _detect_social_spike_tickers(postgres, list(ticker_set)):
        bucket = hits.setdefault(ticker, _empty_hits())
        bucket["bullish"].add("social_spike")
        bucket["details"]["social_spike"] = {"lookback_days": SOCIAL_LOOKBACK_DAYS}

    signal_hits = _fetch_signal_hits(supabase_client, ticker_set, window_days=window_days)
    for ticker, detail in signal_hits.items():
        bucket = hits.setdefault(ticker, _empty_hits())
        bucket["bullish"].add(FAMILY_SIGNALS)
        bucket["details"][FAMILY_SIGNALS] = detail

    filing_hits = _fetch_filing_hits(postgres, list(ticker_set), window_days=window_days)
    for ticker, dirs in filing_hits.items():
        bucket = hits.setdefault(ticker, _empty_hits())
        if "filing_positive" in dirs["bullish"]:
            bucket["bullish"].add("filing_positive")
            bucket["details"]["filing_positive"] = {"direction": "positive"}
        if "filing_risk" in dirs["risk"]:
            bucket["risk"].add("filing_risk")
            bucket["details"]["filing_risk"] = {"direction": "risk"}

    for ticker in _fetch_dilution_hits(postgres, list(ticker_set), window_days=window_days):
        bucket = hits.setdefault(ticker, _empty_hits())
        bucket["risk"].add("dilution_flag")
        bucket["details"]["dilution_flag"] = {"flagged": True}

    # Stance flips and insider clusters are fetched market-wide (not ticker-scoped),
    # so restrict the final result to the production holdings + watchlist scope.
    return {t: h for t, h in hits.items() if t in ticker_set}


def compute_confluence_for_tickers(
    postgres: Any,
    supabase_client: Any,
    tickers: list[str],
    *,
    window_days: int = WINDOW_DAYS_DEFAULT,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Score confluence for tickers (fetches families then builds events)."""
    hits = gather_ticker_hits(
        postgres, supabase_client, tickers, window_days=window_days
    )
    return build_confluence_events_from_hits(hits, as_of=as_of)


def _families_json(families: list[str]) -> str:
    return json.dumps(families)


def _confluence_already_recorded(
    postgres: Any,
    *,
    ticker: str,
    direction: str,
    families: list[str],
    window_days: int = DEDUPE_WINDOW_DAYS,
) -> bool:
    rows = postgres.execute_query(
        """
        SELECT 1 FROM confluence_events
        WHERE ticker = %s AND direction = %s AND families = %s::jsonb
          AND as_of >= NOW() - (%s || ' days')::interval
        LIMIT 1
        """,
        (ticker, direction, _families_json(families), window_days),
    )
    return bool(rows)


def persist_confluence_event(postgres: Any, event: dict[str, Any]) -> bool:
    """Insert one event if not deduped. Returns True if inserted."""
    ticker = str(event["ticker"]).upper()
    direction = str(event["direction"])
    families = list(event["families"])
    if _confluence_already_recorded(
        postgres, ticker=ticker, direction=direction, families=families
    ):
        return False
    try:
        postgres.execute_update(
            """
            INSERT INTO confluence_events (ticker, as_of, direction, score, families, details)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                ticker,
                event.get("as_of") or datetime.now(UTC),
                direction,
                int(event["score"]),
                _families_json(families),
                json.dumps(event.get("details") or {}),
            ),
        )
        return True
    except Exception as exc:
        logger.warning("confluence insert failed for %s: %s", ticker, exc)
        return False


def run_confluence_scan(
    postgres: Any,
    supabase_client: Any,
    *,
    window_days: int = WINDOW_DAYS_DEFAULT,
) -> dict[str, int]:
    """Full job body: scope tickers, score, persist, ledger hook."""
    tickers = collect_scope_tickers(supabase_client)
    events = compute_confluence_for_tickers(
        postgres, supabase_client, tickers, window_days=window_days
    )
    inserted = 0
    skipped_dedupe = 0
    stances_written = 0
    for event in events:
        if persist_confluence_event(postgres, event):
            inserted += 1
        else:
            skipped_dedupe += 1
        if (
            event["direction"] == "bullish"
            and int(event["score"]) >= MIN_SCORE_LEDGER
        ):
            if record_stance_safe(
                postgres,
                ticker=event["ticker"],
                source="confluence",
                stance="BULLISH",
                confidence=None,
                metadata={
                    "families": event["families"],
                    "score": event["score"],
                },
            ):
                stances_written += 1
    return {
        "tickers": len(tickers),
        "events": len(events),
        "inserted": inserted,
        "skipped_dedupe": skipped_dedupe,
        "stances_written": stances_written,
    }


def fetch_recent_confluence_events(
    postgres: Any,
    *,
    tickers: list[str] | None = None,
    days: int = 2,
    limit: int = 20,
    min_score: int = MIN_SCORE_PERSIST,
) -> list[dict[str, Any]]:
    """Recent confluence rows for Today briefing and dossier timeline."""
    params: list[Any] = [days, min_score]
    ticker_filter = ""
    if tickers:
        ticker_filter = "AND ticker = ANY(%s)"
        params.append([t.upper() for t in tickers])
    params.append(limit)
    try:
        return postgres.execute_query(
            f"""
            SELECT ticker, direction, score,
                   families,
                   as_of::text AS as_of,
                   details
            FROM confluence_events
            WHERE as_of >= NOW() - (%s || ' days')::interval
              AND score >= %s
              {ticker_filter}
            ORDER BY score DESC, as_of DESC
            LIMIT %s
            """,
            tuple(params),
        )
    except Exception as exc:
        logger.warning("fetch_recent_confluence_events failed (table missing?): %s", exc)
        return []
