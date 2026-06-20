"""Track-record aggregates from stance_outcomes (ROADMAP §2.4)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from postgres_client import PostgresClient


def _finite_decimal(value: Any) -> Decimal | None:
    """Parse a numeric DB value; reject None/NaN/Inf (yfinance gaps write Decimal('NaN'))."""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    if not d.is_finite():
        return None
    return d


def _hit_from_row(row: dict[str, Any]) -> bool | None:
    stance = (row.get("stance") or "").upper()
    ex = _finite_decimal(row.get("excess_return"))
    if ex is None:
        return None
    bullish = stance in {"BUY", "BULLISH", "VERY_BULLISH"}
    bearish = stance in {"SELL", "BEARISH", "VERY_BEARISH", "AVOID"}
    if bullish:
        return ex > 0
    if bearish:
        return ex < 0
    return None


def build_track_record_summary(
    postgres: PostgresClient | None = None,
    *,
    horizon_days: int = 30,
) -> dict[str, Any]:
    pg = postgres or PostgresClient()
    rows = pg.execute_query(
        """
        SELECT sh.source, sh.stance, sh.confidence, sh.metadata,
               so.excess_return, so.ticker_return, so.benchmark_return,
               sh.ticker, sh.as_of
        FROM stance_outcomes so
        JOIN stance_history sh ON sh.id = so.stance_id
        WHERE so.horizon_days = %s
        ORDER BY so.scored_at DESC
        """,
        (horizon_days,),
    )

    by_source: dict[str, dict[str, int]] = {}
    by_verdict: dict[str, dict[str, int]] = {}
    hits: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []

    def _bump(bucket: dict[str, int], hit: bool | None) -> None:
        # Unscoreable rows (e.g. legacy HOLD outcomes) must not sit in the
        # denominator: they can never be hits and would bias rates downward.
        if hit is None:
            bucket["unscoreable"] += 1
            return
        bucket["scored"] += 1
        if hit:
            bucket["hits"] += 1
        else:
            bucket["misses"] += 1

    for row in rows:
        source = row.get("source") or "unknown"
        bucket = by_source.setdefault(
            source, {"scored": 0, "hits": 0, "misses": 0, "unscoreable": 0}
        )
        hit = _hit_from_row(row)
        _bump(bucket, hit)
        if hit is True:
            hits.append(dict(row))
        elif hit is False:
            misses.append(dict(row))

        meta = row.get("metadata") or {}
        if isinstance(meta, str):
            meta = {}
        verdict = (meta.get("verdict") or "").upper() or "UNKNOWN"
        vb = by_verdict.setdefault(
            verdict, {"scored": 0, "hits": 0, "misses": 0, "unscoreable": 0}
        )
        _bump(vb, hit)

    def _rate(bucket: dict[str, int]) -> float | None:
        if bucket["scored"] == 0:
            return None
        return round(bucket["hits"] / bucket["scored"], 4)

    def _excess_magnitude(row: dict[str, Any]) -> float:
        ex = _finite_decimal(row.get("excess_return"))
        if ex is None:
            return 0.0
        return float(ex)

    # "Best/worst" should mean by excess-return magnitude, not insertion order.
    hits.sort(key=_excess_magnitude, reverse=True)
    misses.sort(key=_excess_magnitude)

    return {
        "horizon_days": horizon_days,
        "total_scored": len(rows),
        "hit_rate_by_source": {k: _rate(v) for k, v in by_source.items()},
        "hit_rate_by_verdict": {k: _rate(v) for k, v in by_verdict.items()},
        "best_calls": hits[:5],
        "worst_calls": misses[:5],
        "counts_by_source": by_source,
        "counts_by_verdict": by_verdict,
    }
