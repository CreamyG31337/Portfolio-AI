"""Idea scorecard aggregates from stance_outcomes (ROADMAP §2.8).

Slices performance of directional idea articles (source='alpha_idea')
recorded in ``stance_history`` and scored in ``stance_outcomes`` across:
- Overall hit rate and signed excess return
- Direction (BULLISH vs BEARISH)
- Domain (source publication, min_n filtered)
- Article type (Alpha Research vs Opportunity Discovery)
- Score band (inbox ranking score: 8+, 6-7, <6)
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import logging
from typing import Any

try:
    from benchmarks import SCORING_VERSION
    from stance_history import BEARISH_STANCES, BULLISH_STANCES
except ImportError:
    from web_dashboard.benchmarks import SCORING_VERSION
    from web_dashboard.stance_history import BEARISH_STANCES, BULLISH_STANCES

logger = logging.getLogger(__name__)

SCORE_BANDS = ("8+", "6-7", "<6")


def _finite_float(val: Any) -> float | None:
    """Parse numeric DB / mock value; reject None/NaN/Inf."""
    if val is None:
        return None
    try:
        d = Decimal(str(val))
    except Exception:
        return None
    if not d.is_finite():
        return None
    return float(d)


def _score_band(score: Any) -> str:
    """Map idea_score integer into canonical bands ('8+', '6-7', '<6')."""
    if score is None:
        return "<6"
    try:
        val = int(float(score))
    except (TypeError, ValueError):
        return "<6"
    if val >= 8:
        return "8+"
    if val >= 6:
        return "6-7"
    return "<6"


def _aggregate(
    items: list[float],
    *,
    key_name: str | None = None,
    key_value: Any = None,
) -> dict[str, Any]:
    """Calculate n, hit_rate_pct, and mean_signed_excess_pct for signed excess returns.

    Excess return is already in percent units.
    A call is considered a hit when signed_excess > 0.
    """
    n = len(items)
    if n == 0:
        res: dict[str, Any] = {
            "n": 0,
            "hit_rate_pct": None,
            "mean_signed_excess_pct": None,
        }
    else:
        hits = sum(1 for x in items if x > 0)
        res = {
            "n": n,
            "hit_rate_pct": round(100.0 * hits / n, 1),
            "mean_signed_excess_pct": round(sum(items) / n, 2),
        }
    if key_name is not None:
        res[key_name] = key_value
        if key_name == "band":
            res["score_band"] = key_value
    return res


def build_idea_scorecard(
    postgres: Any | None = None,
    *,
    horizon_days: int = 30,
    min_n: int = 10,
    scoring_version: int = SCORING_VERSION,
) -> dict[str, Any]:
    """Aggregate outcomes of alpha_idea stances for the given horizon.

    Returns:
    - overall: {n, hit_rate_pct, mean_signed_excess_pct}
    - by_direction: list of {stance, n, hit_rate_pct, mean_signed_excess_pct}
    - by_domain: list of {domain, n, hit_rate_pct, mean_signed_excess_pct} (n >= min_n)
    - by_article_type: list of {article_type, n, hit_rate_pct, mean_signed_excess_pct}
    - by_score_band: list of {band, n, hit_rate_pct, mean_signed_excess_pct} ("8+", "6-7", "<6")

    On any DB error, logs a warning and returns {"available": False}. Never raises.
    """
    try:
        if postgres is None:
            try:
                from postgres_client import PostgresClient
            except ImportError:
                from web_dashboard.postgres_client import PostgresClient
            pg = PostgresClient()
        else:
            pg = postgres

        rows = pg.execute_query(
            """
            SELECT
                sh.stance,
                sh.metadata->'idea'->>'domain' AS domain,
                sh.metadata->'idea'->>'article_type' AS article_type,
                sh.metadata->'idea'->>'idea_score' AS idea_score,
                so.excess_return
            FROM stance_outcomes so
            JOIN stance_history sh ON sh.id = so.stance_id
            WHERE sh.source = 'alpha_idea'
              AND so.horizon_days = %s
              AND COALESCE(so.scoring_version, 1) = %s
            """,
            (horizon_days, scoring_version),
        )
    except Exception as exc:
        logger.warning("build_idea_scorecard query failed: %s", exc)
        return {"available": False}

    try:
        if rows is None:
            rows = []

        all_excess: list[float] = []
        by_dir_items: dict[str, list[float]] = defaultdict(list)
        by_domain_items: dict[str, list[float]] = defaultdict(list)
        by_type_items: dict[str, list[float]] = defaultdict(list)
        by_band_items: dict[str, list[float]] = defaultdict(list)

        for row in rows:
            raw_excess = _finite_float(row.get("excess_return"))
            if raw_excess is None:
                continue

            stance = str(row.get("stance") or "").strip().upper()
            if stance in BULLISH_STANCES:
                signed_excess = raw_excess
            elif stance in BEARISH_STANCES:
                signed_excess = -raw_excess
            else:
                continue

            all_excess.append(signed_excess)
            by_dir_items[stance].append(signed_excess)

            # Domain extraction (supports flattened query result or nested metadata dict)
            domain = row.get("domain")
            if domain is None and isinstance(row.get("metadata"), dict):
                domain = row.get("metadata", {}).get("idea", {}).get("domain")
            domain_str = str(domain or "unknown").strip()
            by_domain_items[domain_str].append(signed_excess)

            # Article type extraction
            art_type = row.get("article_type")
            if art_type is None and isinstance(row.get("metadata"), dict):
                art_type = row.get("metadata", {}).get("idea", {}).get("article_type")
            art_type_str = str(art_type or "unknown").strip()
            by_type_items[art_type_str].append(signed_excess)

            # Score band extraction
            score_val = row.get("idea_score")
            if score_val is None and isinstance(row.get("metadata"), dict):
                score_val = row.get("metadata", {}).get("idea", {}).get("idea_score")
            band = _score_band(score_val)
            by_band_items[band].append(signed_excess)

        overall = _aggregate(all_excess)

        by_direction: list[dict[str, Any]] = [
            _aggregate(items, key_name="stance", key_value=st)
            for st, items in by_dir_items.items()
        ]
        by_direction.sort(key=lambda d: (-d["n"], d["stance"]))

        by_domain: list[dict[str, Any]] = [
            _aggregate(items, key_name="domain", key_value=dom)
            for dom, items in by_domain_items.items()
            if len(items) >= min_n
        ]
        by_domain.sort(key=lambda d: (-(d["mean_signed_excess_pct"] or 0.0), -d["n"], d["domain"]))

        by_article_type: list[dict[str, Any]] = [
            _aggregate(items, key_name="article_type", key_value=at)
            for at, items in by_type_items.items()
        ]
        by_article_type.sort(key=lambda d: (-d["n"], d["article_type"]))

        by_score_band: list[dict[str, Any]] = [
            _aggregate(by_band_items[band], key_name="band", key_value=band)
            for band in SCORE_BANDS
            if band in by_band_items and by_band_items[band]
        ]

        return {
            "available": True,
            "overall": overall,
            "by_direction": by_direction,
            "by_domain": by_domain,
            "by_article_type": by_article_type,
            "by_score_band": by_score_band,
        }
    except Exception as exc:
        logger.warning("build_idea_scorecard aggregation failed: %s", exc)
        return {"available": False}
