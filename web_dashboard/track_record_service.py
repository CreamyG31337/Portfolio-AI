"""Track-record aggregates from stance_outcomes (ROADMAP §2.4 / Phase H1 source-ROI)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from statistics import median
from typing import Any

from benchmarks import SCORING_VERSION
from postgres_client import PostgresClient

_DOMAIN_TOP_N = 25

_CONF_BAND_LOW = "lt_0.5"
_CONF_BAND_MID = "0.5_to_0.75"
_CONF_BAND_HIGH = "gte_0.75"

# Shared by _hit_from_row and _directional_excess so the two can never disagree
# about what counts as a directional call.
_BULLISH_STANCES = frozenset({"BUY", "BULLISH", "VERY_BULLISH"})
_BEARISH_STANCES = frozenset({"SELL", "BEARISH", "VERY_BEARISH", "AVOID"})

# ETFs that track substantially the same index as the benchmark they are scored
# against, making their excess return ~0 by construction. "BULLISH on VOO" vs the
# S&P 500 is not a prediction -- it is the benchmark wearing a hat -- but it lands
# in the hit rate as a coin flip and drags every aggregate toward 50%.
#
# Excluded from AGGREGATES ONLY. The stances stay in stance_history and are still
# scored into stance_outcomes, so this is reversible and loses no data.
#
# Deliberately NOT listed (these are genuine directional calls with real tracking
# error vs a broad benchmark): QQQ (Nasdaq-100 is a real tilt vs the S&P 500) and
# every sector/thematic fund -- ROBO, BUG, CIBR, FTXL, URNJ, FXD, LIT, URA, HURA.TO.
BROAD_INDEX_ETFS = frozenset({
    "VOO", "VTI", "SPY", "IVV", "SPLG", "ITOT",      # US broad market -> ^GSPC
    "IWM", "VTWO",                                    # US small cap    -> ^RUT
    "XIC.TO", "XIU.TO", "ZCN.TO", "VCN.TO",           # Canada broad    -> ^GSPTSE
})


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
    if stance in _BULLISH_STANCES:
        return ex > 0
    if stance in _BEARISH_STANCES:
        return ex < 0
    return None


def _directional_excess(row: dict[str, Any]) -> float | None:
    """Excess return signed so that **positive always means the call was right**.

    Raw ``excess_return`` is measured against the benchmark, not against the call.
    A correct BEARISH stance therefore carries a *negative* excess return, so
    averaging raw excess across a mixed book cancels good bearish calls against
    good bullish ones and reports skill as its own opposite.

    Observed in prod before this fix: ``action_queue_ai_review`` (a SELL/RISK-heavy
    source) showed **hit_rate=68.0% with mean_excess=-4.24** -- the source was right
    about direction most of the time while its own quality metric ranked it worst.

    Returns None for non-directional stances (RISK/WATCH/NEUTRAL), matching
    :func:`_hit_from_row` so hit counts and excess aggregates stay on the same rows.
    """
    ex = _finite_decimal(row.get("excess_return"))
    if ex is None:
        return None
    stance = (row.get("stance") or "").upper()
    if stance in _BULLISH_STANCES:
        return float(ex)
    if stance in _BEARISH_STANCES:
        return -float(ex)
    return None


def is_broad_index_etf(ticker: Any) -> bool:
    """True when a stance's excess return is ~0 by construction (see BROAD_INDEX_ETFS)."""
    return str(ticker or "").strip().upper() in BROAD_INDEX_ETFS


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
    scoring_version: int = SCORING_VERSION,
) -> dict[str, Any]:
    pg = postgres or PostgresClient()
    # Filtered to one scoring_version on purpose: rows scored under different
    # benchmark schemes were measured against different yardsticks, and averaging
    # across them reintroduces exactly the apples-to-oranges problem the per-ticker
    # benchmark work fixed. A future scheme change bumps the version and this query
    # keeps returning a self-consistent set.
    rows = pg.execute_query(
        """
        SELECT sh.source, sh.stance, sh.confidence, sh.metadata,
               so.excess_return, so.ticker_return, so.benchmark_return,
               so.benchmark_symbol, sh.ticker, sh.as_of
        FROM stance_outcomes so
        JOIN stance_history sh ON sh.id = so.stance_id
        WHERE so.horizon_days = %s
          AND COALESCE(so.scoring_version, 1) = %s
        ORDER BY so.scored_at DESC
        """,
        (horizon_days, scoring_version),
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

    broad_index_etf_excluded = 0

    for row in rows:
        # Tautological rows are dropped before any aggregate touches them, so they
        # cannot land in hit rates, excess means, best/worst calls, or coverage.
        if is_broad_index_etf(row.get("ticker")):
            broad_index_etf_excluded += 1
            continue

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

        dir_ex = _directional_excess(row)
        if hit is not None and dir_ex is not None:
            excess_by_source[source].append(dir_ex)

        cov = coverage_totals[source]
        cov["rows"] += 1
        evidence = meta.get("evidence")
        if isinstance(evidence, dict):
            cov["with_evidence"] += 1
        article_ids = _article_ids_from_metadata(meta)
        if article_ids:
            cov["with_article_ids"] += 1
            all_article_ids.extend(article_ids)
            if hit is not None and dir_ex is not None:
                scoreable_for_domain.append((row, hit, dir_ex, article_ids))

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
        # Directional, not raw: sorting best/worst by raw excess ranked a correct
        # BEARISH call (negative excess) as the worst call in the book.
        dir_ex = _directional_excess(row)
        return dir_ex if dir_ex is not None else 0.0

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
        # Excess-return keys below are DIRECTIONAL: positive always means the call
        # was right, for bearish stances too. Declared in the payload so downstream
        # consumers (including the AI assistant, which reads this dict verbatim)
        # cannot mistake it for raw benchmark-relative excess.
        "excess_metric": "directional",
        "scoring_version": scoring_version,
        "broad_index_etf_excluded": broad_index_etf_excluded,
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
