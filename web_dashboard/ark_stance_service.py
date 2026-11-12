"""Nightly ARK active-fund buys → stance_history ledger (ROADMAP §2.8 L4).

WHY THIS EXISTS
---------------
A 2020–2026 backtest (scripts/ark_history_study.py, roadmap row L3b) found stocks
ARK's active ETFs buy go on to trail the benchmark (vs QQQ: -7.1% over 63 trading
days, 95% CI excludes 0).

This job records each new ARK buy as a BEARISH call so the existing stance_outcomes
scorer grades the rule forward with no human review.

THE RULE
--------
- Monitored funds: ARKK, ARKW, ARKG, ARKQ, ARKF, ARKX.
- Trade notifications pulled from public API (arkfunds.io).
- Lookback default: 5 calendar days.
- Candidate = (trade_date, ticker) with at least one fund Buy.
- Same-fund wash: ignore a fund's Buy if that SAME fund also Sold that ticker on the same date.
- Foreign listings: skip tickers with spaces or starting with a digit.
- 30-day throttle: record only the FIRST buy of a ticker within any 30-day window.
- Entry as_of: next weekday after trade date at ~21:00 UTC (entry_as_of).
- source = "precursor:ark_buy", stance = "BEARISH", dedupe_on_source_ref=True.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
import logging
import time
from typing import Any
import uuid

import requests

try:
    from idea_stance_service import entry_as_of
    from stance_history import record_stance_safe
except ImportError:
    from web_dashboard.idea_stance_service import entry_as_of
    from web_dashboard.stance_history import record_stance_safe

logger = logging.getLogger(__name__)

SOURCE = "precursor:ark_buy"
STANCE = "BEARISH"
ARK_FUNDS: tuple[str, ...] = ("ARKK", "ARKW", "ARKG", "ARKQ", "ARKF", "ARKX")
DEFAULT_LOOKBACK_DAYS = 5
THROTTLE_DAYS = 30
USER_AGENT = "portfolio-research/1.0"
REQUEST_TIMEOUT = 60
_TRADE_HOUR_UTC = 20


def fetch_fund_trades(
    fund: str,
    date_from: str,
    date_to: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Fetch trade list for a single ARK fund from arkfunds.io API."""
    url = (
        f"https://arkfunds.io/api/v2/etf/trades"
        f"?symbol={fund}&date_from={date_from}&date_to={date_to}&limit=100000"
    )
    headers = {"User-Agent": USER_AGENT}
    client = session or requests
    resp = client.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        trades = data.get("trades")
        if isinstance(trades, list):
            return trades
    return []


def is_foreign_ticker(ticker: str) -> bool:
    """Return True if ticker represents a foreign listing (contains space or starts with digit)."""
    t = (ticker or "").strip()
    if not t:
        return False
    return (" " in t) or t[0].isdigit()


def record_ark_stances(
    postgres: Any | None = None,
    *,
    days: int = DEFAULT_LOOKBACK_DAYS,
    dry_run: bool = False,
    pause_seconds: float = 1.0,
    funds: tuple[str, ...] = ARK_FUNDS,
    target_date: date | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, int]:
    """Fetch recent ARK trades and write BEARISH stances for new buys.

    Returns stats dict: trades_fetched, candidates, skipped_throttle, skipped_wash,
    skipped_foreign, stances_written, api_errors.
    """
    stats = {
        "trades_fetched": 0,
        "candidates": 0,
        "skipped_throttle": 0,
        "skipped_wash": 0,
        "skipped_foreign": 0,
        "stances_written": 0,
        "api_errors": 0,
    }

    if date_to is None:
        end_d = target_date or datetime.now(UTC).date()
        date_to = end_d.isoformat()
    if date_from is None:
        end_d = date.fromisoformat(date_to)
        start_d = end_d - timedelta(days=days)
        date_from = start_d.isoformat()

    all_trades: list[dict[str, Any]] = []
    for i, fund in enumerate(funds):
        if i > 0 and pause_seconds > 0:
            time.sleep(pause_seconds)
        try:
            fund_trades = fetch_fund_trades(fund, date_from, date_to)
            all_trades.extend(fund_trades)
        except Exception as exc:
            logger.warning("Failed to fetch ARK trades for fund %s: %s", fund, exc)
            stats["api_errors"] += 1

    stats["trades_fetched"] = len(all_trades)

    # Group trades by (trade_date, ticker, fund) -> list of trades
    trades_by_date_ticker: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for trade in all_trades:
        raw_date = str(trade.get("date") or "").strip()
        trade_date = raw_date[:10]
        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            continue

        raw_ticker = str(trade.get("ticker") or "").strip().upper()
        if not raw_ticker:
            continue

        fund_name = str(trade.get("fund") or "").strip().upper()
        trades_by_date_ticker[(trade_date, raw_ticker)][fund_name].append(trade)

    # Identify candidates
    candidate_items: list[dict[str, Any]] = []

    for (trade_date, ticker), fund_map in trades_by_date_ticker.items():
        # Check if there was any Buy for this ticker on this date
        has_any_buy = any(
            str(t.get("direction") or "").strip().lower() == "buy"
            for t_list in fund_map.values()
            for t in t_list
        )
        if not has_any_buy:
            continue

        # Skip foreign listings
        if is_foreign_ticker(ticker):
            stats["skipped_foreign"] += 1
            continue

        # Evaluate same-fund wash
        valid_buys: list[dict[str, Any]] = []
        buying_funds: set[str] = set()

        for fund_name, t_list in fund_map.items():
            fund_has_buy = any(str(t.get("direction") or "").strip().lower() == "buy" for t in t_list)
            fund_has_sell = any(str(t.get("direction") or "").strip().lower() == "sell" for t in t_list)

            if fund_has_buy and fund_has_sell:
                # Same-fund wash: ignore fund's Buy
                stats["skipped_wash"] += 1
                continue
            elif fund_has_buy:
                buying_funds.add(fund_name)
                for t in t_list:
                    if str(t.get("direction") or "").strip().lower() == "buy":
                        valid_buys.append(t)

        if not valid_buys:
            continue

        stats["candidates"] += 1

        total_shares = sum(int(t.get("shares") or 0) for t in valid_buys)
        total_etf_pct = round(sum(float(t.get("etf_percent") or 0.0) for t in valid_buys), 6)

        candidate_items.append(
            {
                "trade_date": trade_date,
                "ticker": ticker,
                "funds": sorted(buying_funds),
                "shares": total_shares,
                "etf_percent": total_etf_pct,
            }
        )

    # Process candidates in chronological order for in-run throttle
    candidate_items.sort(key=lambda c: (c["trade_date"], c["ticker"]))

    in_run_as_ofs: dict[str, list[datetime]] = defaultdict(list)

    if postgres is None and not dry_run:
        try:
            from postgres_client import PostgresClient
            postgres = PostgresClient()
        except Exception as exc:
            logger.warning("PostgresClient unavailable for ark trade ledger: %s", exc)

    for cand in candidate_items:
        trade_date = cand["trade_date"]
        ticker = cand["ticker"]

        trade_dt = datetime.strptime(trade_date, "%Y-%m-%d").replace(
            hour=_TRADE_HOUR_UTC, minute=0, second=0, microsecond=0, tzinfo=UTC
        )
        as_of = entry_as_of(trade_dt)

        window_start = as_of - timedelta(days=THROTTLE_DAYS)

        # 1. Check in-run throttle
        if any(window_start <= prev <= as_of for prev in in_run_as_ofs.get(ticker, [])):
            stats["skipped_throttle"] += 1
            continue

        # 2. Check DB throttle
        is_throttled = False
        if postgres is not None:
            try:
                existing = postgres.execute_query(
                    """
                    SELECT 1 FROM stance_history
                    WHERE ticker = %s
                      AND source = %s
                      AND as_of >= %s
                      AND as_of <= %s
                    LIMIT 1
                    """,
                    (ticker, SOURCE, window_start, as_of),
                )
                if existing:
                    is_throttled = True
            except Exception as exc:
                logger.warning("Error checking 30d throttle for %s: %s", ticker, exc)

        if is_throttled:
            stats["skipped_throttle"] += 1
            continue

        in_run_as_ofs[ticker].append(as_of)

        if dry_run:
            continue

        source_ref_id = uuid.uuid5(uuid.NAMESPACE_URL, f"ark-buy:{trade_date}:{ticker}")
        metadata = {
            "ark": {
                "trade_date": trade_date,
                "funds": cand["funds"],
                "shares": cand["shares"],
                "etf_percent": cand["etf_percent"],
                "rule": "first ARK active-fund buy in 30d -> BEARISH",
                "study": "roadmap L3b",
            }
        }

        if record_stance_safe(
            postgres,
            ticker=ticker,
            source=SOURCE,
            stance=STANCE,
            confidence=None,
            fund_key="",
            source_ref_id=source_ref_id,
            metadata=metadata,
            as_of=as_of,
            dedupe_on_source_ref=True,
        ):
            stats["stances_written"] += 1

    return stats
