"""Track-record aggregates from stance_outcomes (ROADMAP §2.4 / Phase H1 source-ROI)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from statistics import median
from typing import Any

from postgres_client import PostgresClient

_DOMAIN_TOP_N = 25

_CONF_BAND_LOW = "lt_0.5"
_CONF_BAND_MID = "0.5_to_0.75"
_CONF_BAND_HIGH = "gte_0.75"


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


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _article_ids_from_metadata(meta: dict[str, Any]) -> list[str]:
    evidence = meta.get("evidence")
    if not isinstance(evidence, dict):
        return []
    ids = evidence.get("article_ids") or []
    if not isinstance(ids, list):
        return []
    out: list[str] = []
    for item in ids:
        if item is None:
            continue
        s = str(item).strip()
        if s:
            out.append(s)
    return out


def _confidence_band(confidence: Any) -> str | None:
    conf = _finite_decimal(confidence)
    if conf is None:
        return None
    if conf < Decimal("0.5"):
        return _CONF_BAND_LOW
    if conf < Decimal("0.75"):
        return _CONF_BAND_MID
    return _CONF_BAND_HIGH


def _empty_count_bucket() -> dict[str, int]:
    return {"scored": 0, "hits": 0, "misses": 0, "unscoreable": 0}


def _rate_from_counts(bucket: dict[str, Any]) -> float | None:
    scored = float(bucket.get("scored") or 0)
    if scored <= 0:
        return None
    return round(float(bucket.get("hits") or 0) / scored, 4)


def _mean_median(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    mean_v = round(sum(values) / len(values), 6)
    med_v = round(float(median(values)), 6)
    return mean_v, med_v


def _fetch_article_domains(
    pg: PostgresClient,
    article_ids: list[str],
) -> dict[str, str]:
    """Map article UUID → research_articles.source hostname (domain)."""
    if not article_ids:
        return {}
    # Dedupe while preserving order for stable ANY payloads.
    unique = list(dict.fromkeys(article_ids))
    rows = pg.execute_query(
        """
        SELECT id::text AS id, source
        FROM research_articles
        WHERE id = ANY(%s::uuid[])
        """,
        (unique,),
    )
    out: dict[str, str] = {}
    for row in rows:
        aid = str(row.get("id") or "").strip()
        domain = (row.get("source") or "").strip()
        if aid and domain:
            out[aid] = domain
    return out


def build_track_record_summary(
    postgres: PostgresClient | None = None,
    *,
    horizon_days: int = 30,
    domain_top_n: int = _DOMAIN_TOP_N,
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
    by_conf_band: dict[str, dict[str, int]] = {}
    excess_by_source: dict[str, list[float]] = defaultdict(list)
    hits: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []

    # Coverage + domain prep (first pass collects article ids)
    coverage_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"rows": 0, "with_evidence": 0, "with_article_ids": 0}
    )
    all_article_ids: list[str] = []
    scoreable_for_domain: list[tuple[dict[str, Any], bool, float, list[str]]] = []

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
        bucket = by_source.setdefault(source, _empty_count_bucket())
        hit = _hit_from_row(row)
        _bump(bucket, hit)
        if hit is True:
            hits.append(dict(row))
        elif hit is False:
            misses.append(dict(row))

        meta = _parse_metadata(row.get("metadata"))
        verdict = (meta.get("verdict") or "").upper() or "UNKNOWN"
        vb = by_verdict.setdefault(verdict, _empty_count_bucket())
        _bump(vb, hit)

        band = _confidence_band(row.get("confidence"))
        if band is not None:
            cb = by_conf_band.setdefault(band, _empty_count_bucket())
            _bump(cb, hit)

        ex = _finite_decimal(row.get("excess_return"))
        if hit is not None and ex is not None:
            excess_by_source[source].append(float(ex))

        cov = coverage_totals[source]
        cov["rows"] += 1
        evidence = meta.get("evidence")
        if isinstance(evidence, dict):
            cov["with_evidence"] += 1
        article_ids = _article_ids_from_metadata(meta)
        if article_ids:
            cov["with_article_ids"] += 1
            all_article_ids.extend(article_ids)
            if hit is not None and ex is not None:
                scoreable_for_domain.append((row, hit, float(ex), article_ids))

    id_to_domain = _fetch_article_domains(pg, all_article_ids)

    # Fractional domain attribution: weight 1/N per distinct resolved domain.
    domain_scored: dict[str, float] = defaultdict(float)
    domain_hits: dict[str, float] = defaultdict(float)
    domain_excess_wsum: dict[str, float] = defaultdict(float)
    domain_touches: dict[str, int] = defaultdict(int)
    unresolved_article_ids = 0
    stances_with_resolved_domain = 0

    for _row, hit, excess, article_ids in scoreable_for_domain:
        domains: list[str] = []
        seen: set[str] = set()
        for aid in article_ids:
            domain = id_to_domain.get(aid)
            if not domain:
                unresolved_article_ids += 1
                continue
            if domain not in seen:
                seen.add(domain)
                domains.append(domain)
        if not domains:
            continue
        stances_with_resolved_domain += 1
        n = len(domains)
        weight = 1.0 / n
        for domain in domains:
            domain_touches[domain] += 1
            domain_scored[domain] += weight
            if hit:
                domain_hits[domain] += weight
            domain_excess_wsum[domain] += excess * weight

    def _rate(bucket: dict[str, int]) -> float | None:
        return _rate_from_counts(bucket)

    def _excess_magnitude(row: dict[str, Any]) -> float:
        ex = _finite_decimal(row.get("excess_return"))
        if ex is None:
            return 0.0
        return float(ex)

    hits.sort(key=_excess_magnitude, reverse=True)
    misses.sort(key=_excess_magnitude)

    avg_excess_by_source: dict[str, float | None] = {}
    median_excess_by_source: dict[str, float | None] = {}
    for source, values in excess_by_source.items():
        mean_v, med_v = _mean_median(values)
        avg_excess_by_source[source] = mean_v
        median_excess_by_source[source] = med_v
    # Ensure every source key appears even with no scoreable excess.
    for source in by_source:
        avg_excess_by_source.setdefault(source, None)
        median_excess_by_source.setdefault(source, None)

    # Nested confidence bands: overall + optional per-source not required by plan;
    # expose global hit_rate_by_confidence_band + counts.
    hit_rate_by_confidence_band = {k: _rate(v) for k, v in by_conf_band.items()}

    by_domain_rows: list[dict[str, Any]] = []
    for domain, scored in domain_scored.items():
        hits_w = domain_hits.get(domain, 0.0)
        mean_ex = (
            round(domain_excess_wsum[domain] / scored, 6) if scored > 0 else None
        )
        by_domain_rows.append(
            {
                "domain": domain,
                "scored": round(scored, 4),
                "hits": round(hits_w, 4),
                "hit_rate": round(hits_w / scored, 4) if scored > 0 else None,
                "mean_excess": mean_ex,
                "stance_touches": domain_touches.get(domain, 0),
            }
        )
    by_domain_rows.sort(key=lambda r: (-float(r["scored"]), r["domain"]))
    by_domain_rows = by_domain_rows[: max(0, domain_top_n)]

    evidence_coverage: dict[str, dict[str, Any]] = {}
    for source, cov in coverage_totals.items():
        n = cov["rows"] or 0
        evidence_coverage[source] = {
            "rows": n,
            "with_evidence": cov["with_evidence"],
            "with_article_ids": cov["with_article_ids"],
            "pct_with_evidence": (
                round(100.0 * cov["with_evidence"] / n, 1) if n else None
            ),
            "pct_with_article_ids": (
                round(100.0 * cov["with_article_ids"] / n, 1) if n else None
            ),
        }

    return {
        "horizon_days": horizon_days,
        "total_scored": len(rows),
        "hit_rate_by_source": {k: _rate(v) for k, v in by_source.items()},
        "hit_rate_by_verdict": {k: _rate(v) for k, v in by_verdict.items()},
        "hit_rate_by_confidence_band": hit_rate_by_confidence_band,
        "avg_excess_by_source": avg_excess_by_source,
        "median_excess_by_source": median_excess_by_source,
        "best_calls": hits[:5],
        "worst_calls": misses[:5],
        "counts_by_source": by_source,
        "counts_by_verdict": by_verdict,
        "counts_by_confidence_band": by_conf_band,
        "by_domain": by_domain_rows,
        "evidence_coverage": evidence_coverage,
        "domain_attribution": {
            "stances_with_article_ids_scoreable": len(scoreable_for_domain),
            "stances_with_resolved_domain": stances_with_resolved_domain,
            "unresolved_article_id_lookups": unresolved_article_ids,
            "top_n": domain_top_n,
        },
    }
