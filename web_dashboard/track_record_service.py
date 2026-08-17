"""Track-record aggregates from stance_outcomes (ROADMAP §2.4 / Phase H1 source-ROI)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
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


def _date_key(as_of: Any) -> str:
    """Day bucket for baseline permutation. Falls back to a single bucket if unparseable."""
    if isinstance(as_of, datetime):
        return as_of.date().isoformat()
    if isinstance(as_of, date):
        return as_of.isoformat()
    return str(as_of or "")[:10]


def compute_baselines(baseline_rows: list[tuple[str, float, Any]]) -> dict[str, Any]:
    """Null models, so a hit rate can be interpreted instead of merely reported.

    A hit rate on its own says nothing: the median individual stock underperforms an
    index routinely, so a mostly-long book can print sub-50% with entirely ordinary
    luck. The question is not "is it above 50%" but "is it above what no skill would
    have produced on these same tickers over these same windows".

    Three baselines, all computed from the SAME scored rows -- no re-scoring, no
    price fetches, no extra table. ``excess_return`` is already stored per row against
    the correct benchmark, so every null model is a relabelling of existing outcomes:

    * ``always_bullish``  -- call everything BULLISH. The "why not just buy them all"
      test.
    * ``always_bearish``  -- the mirror, included because it makes an asymmetric
      market obvious at a glance.
    * ``shuffled``        -- keep the exact mix of bullish/bearish calls the system
      actually made, but assign them to rows at random. This is the sharpest null:
      it destroys only the pairing between label and outcome, so beating it means the
      model's directional choices carried information.

    The shuffled figure is the **exact expectation** under permutation, not a Monte
    Carlo estimate: within a day bucket of T rows holding ``pos`` positive-excess and
    ``neg`` negative-excess outcomes, a bullish label lands on a winner with
    probability pos/T, so E[hits] = (b*pos + e*neg)/T. Deterministic, no RNG, no seed
    to get wrong, no flaky tests.

    Bucketing by day is deliberate: stances are strongly correlated within a session
    (a market drop makes every bullish call miss at once), and permuting within the
    day preserves that structure instead of pretending the rows are independent.
    """
    by_day: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for stance, excess, as_of in baseline_rows:
        by_day[_date_key(as_of)].append((stance, excess))

    n = 0
    always_bullish_hits = 0
    always_bearish_hits = 0
    shuffled_hits = 0.0

    # Per-direction actual vs expected. This is the sharper cut: a lopsided label mix
    # (this book is ~86% bullish) means the pooled shuffled null is dominated by the
    # bullish side and can barely move, so a real edge in the minority class would be
    # invisible in the aggregate. The two directions' expected hits sum to the pooled
    # shuffled figure by construction, so the breakdown stays internally consistent.
    dir_stats = {
        "bullish": {"n": 0, "hits": 0, "expected": 0.0},
        "bearish": {"n": 0, "hits": 0, "expected": 0.0},
    }

    for bucket in by_day.values():
        total = len(bucket)
        if not total:
            continue
        pos = sum(1 for _s, ex in bucket if ex > 0)
        neg = sum(1 for _s, ex in bucket if ex < 0)
        bullish = sum(1 for s, _ex in bucket if s.upper() in _BULLISH_STANCES)
        bearish = sum(1 for s, _ex in bucket if s.upper() in _BEARISH_STANCES)

        n += total
        always_bullish_hits += pos
        always_bearish_hits += neg
        labelled = bullish + bearish
        if labelled:
            shuffled_hits += (bullish * pos + bearish * neg) / total

        dir_stats["bullish"]["n"] += bullish
        dir_stats["bearish"]["n"] += bearish
        dir_stats["bullish"]["hits"] += sum(
            1 for s, ex in bucket if s.upper() in _BULLISH_STANCES and ex > 0
        )
        dir_stats["bearish"]["hits"] += sum(
            1 for s, ex in bucket if s.upper() in _BEARISH_STANCES and ex < 0
        )
        # Expected hits if this bucket's labels were dealt out at random.
        dir_stats["bullish"]["expected"] += bullish * pos / total
        dir_stats["bearish"]["expected"] += bearish * neg / total

    if n == 0:
        return {
            "n": 0,
            "always_bullish_hit_rate": None,
            "always_bearish_hit_rate": None,
            "shuffled_hit_rate": None,
            "by_direction": {},
        }

    by_direction: dict[str, dict[str, Any]] = {}
    for name, stats in dir_stats.items():
        count = stats["n"]
        if not count:
            continue
        rate = stats["hits"] / count
        expected = stats["expected"] / count
        by_direction[name] = {
            "n": count,
            "hits": stats["hits"],
            "hit_rate": round(rate, 4),
            "expected_hit_rate": round(expected, 4),
            "edge": round(rate - expected, 4),
        }

    return {
        "n": n,
        "always_bullish_hit_rate": round(always_bullish_hits / n, 4),
        "always_bearish_hit_rate": round(always_bearish_hits / n, 4),
        "shuffled_hit_rate": round(shuffled_hits / n, 4),
        "day_buckets": len(by_day),
        "by_direction": by_direction,
    }


def _mechanism_key_from_metadata(meta: dict[str, Any]) -> str:
    proposal = meta.get("falsifiable_proposal")
    if isinstance(proposal, dict):
        key = str(proposal.get("mechanism_key") or "").strip()
        if key:
            return key
        mech = str(proposal.get("mechanism") or "").strip()
        if mech:
            from falsifiable_proposal import mechanism_key

            return mechanism_key(mech) or "unspecified"
    return "unspecified"


def _hit_from_row_after_cost(row: dict[str, Any]) -> bool | None:
    """Prefer belief_status / directional excess_after_cost when present."""
    belief = (row.get("belief_status") or "").strip().lower()
    if belief == "supported":
        return True
    if belief == "refuted":
        return False
    if belief == "inconclusive":
        return None
    eac = _finite_decimal(row.get("excess_after_cost"))
    if eac is not None:
        if abs(eac) < Decimal("0.25"):
            return None
        return eac > 0
    return _hit_from_row(row)


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
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
    try:
        rows = pg.execute_query(
            """
            SELECT sh.source, sh.stance, sh.confidence, sh.metadata,
                   so.excess_return, so.excess_after_cost, so.belief_status, so.cost_bps,
                   so.ticker_return, so.benchmark_return,
                   so.benchmark_symbol, sh.ticker, sh.as_of
            FROM stance_outcomes so
            JOIN stance_history sh ON sh.id = so.stance_id
            WHERE so.horizon_days = %s
              AND COALESCE(so.scoring_version, 1) = %s
            ORDER BY so.scored_at DESC
            """,
            (horizon_days, scoring_version),
        )
    except Exception:
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
    by_mechanism: dict[str, dict[str, int]] = {}
    excess_by_source: dict[str, list[float]] = defaultdict(list)
    excess_after_cost_by_mechanism: dict[str, list[float]] = defaultdict(list)
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
    baseline_rows: list[tuple[str, float, Any]] = []

    for row in rows:
        # Tautological rows are dropped before any aggregate touches them, so they
        # cannot land in hit rates, excess means, best/worst calls, or coverage.
        if is_broad_index_etf(row.get("ticker")):
            broad_index_etf_excluded += 1
            continue

        source = row.get("source") or "unknown"
        bucket = by_source.setdefault(source, _empty_count_bucket())
        hit = _hit_from_row_after_cost(row)
        _bump(bucket, hit)
        if hit is True:
            hits.append(dict(row))
        elif hit is False:
            misses.append(dict(row))

        meta = _parse_metadata(row.get("metadata"))
        mech_key = _mechanism_key_from_metadata(meta)
        mb = by_mechanism.setdefault(mech_key, _empty_count_bucket())
        _bump(mb, hit)
        eac = _finite_decimal(row.get("excess_after_cost"))
        if hit is not None and eac is not None:
            excess_after_cost_by_mechanism[mech_key].append(float(eac))

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

        # Baselines need the RAW excess (the market outcome) paired with the label,
        # so a null model can reassign labels to the same outcomes. Directional
        # excess would bake the label in and make every baseline trivially equal.
        raw_ex = _finite_decimal(row.get("excess_return"))
        if hit is not None and raw_ex is not None:
            baseline_rows.append(
                ((row.get("stance") or "").upper(), float(raw_ex), row.get("as_of"))
            )

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

    baselines = compute_baselines(baseline_rows)

    # The headline number is the EDGE, not the raw rate. Reporting a bare hit rate
    # invites comparison against 50%, which is the wrong null for a mostly-long book.
    overall_scored = sum(b["scored"] for b in by_source.values())
    overall_hits = sum(b["hits"] for b in by_source.values())
    overall_rate = (overall_hits / overall_scored) if overall_scored else None
    shuffled = baselines.get("shuffled_hit_rate")
    always_bullish = baselines.get("always_bullish_hit_rate")
    baselines["actual_hit_rate"] = round(overall_rate, 4) if overall_rate is not None else None
    baselines["edge_vs_shuffled"] = (
        round(overall_rate - shuffled, 4)
        if overall_rate is not None and shuffled is not None
        else None
    )
    baselines["edge_vs_always_bullish"] = (
        round(overall_rate - always_bullish, 4)
        if overall_rate is not None and always_bullish is not None
        else None
    )

    # Multiple-testing note: without N you cannot deflate. Expected false
    # positives at alpha=0.05 if every claim were noise.
    candidates_tested = overall_scored
    expected_false_positives_alpha_05 = (
        round(0.05 * candidates_tested, 2) if candidates_tested else 0.0
    )

    by_mechanism_rows: list[dict[str, Any]] = []
    for mech, counts in by_mechanism.items():
        scored_m = int(counts.get("scored") or 0)
        mean_eac, _med = _mean_median(excess_after_cost_by_mechanism.get(mech) or [])
        by_mechanism_rows.append(
            {
                "mechanism_key": mech,
                "n": scored_m,
                "hits": int(counts.get("hits") or 0),
                "hit_rate": _rate_from_counts(counts),
                "mean_excess_after_cost": mean_eac,
                "expected_false_positives_alpha_05": round(0.05 * scored_m, 2),
            }
        )
    by_mechanism_rows.sort(key=lambda r: (-int(r["n"]), str(r["mechanism_key"])))

    return {
        "horizon_days": horizon_days,
        "total_scored": len(rows),
        "candidates_tested": candidates_tested,
        "expected_false_positives_alpha_05": expected_false_positives_alpha_05,
        "baselines": baselines,
        # Excess-return keys below are DIRECTIONAL: positive always means the call
        # was right, for bearish stances too. Declared in the payload so downstream
        # consumers (including the AI assistant, which reads this dict verbatim)
        # cannot mistake it for raw benchmark-relative excess.
        "excess_metric": "directional_after_cost",
        "scoring_version": scoring_version,
        "broad_index_etf_excluded": broad_index_etf_excluded,
        "hit_rate_by_source": {k: _rate_from_counts(v) for k, v in by_source.items()},
        "hit_rate_by_verdict": {k: _rate_from_counts(v) for k, v in by_verdict.items()},
        "hit_rate_by_confidence_band": hit_rate_by_confidence_band,
        "by_mechanism": by_mechanism_rows,
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
