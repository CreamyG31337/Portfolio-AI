#!/usr/bin/env python3
"""K5 source-ROI slice: do stances that cite YouTube transcripts beat the baseline?

Splits ticker_analysis / ticker_meta_analysis stances by whether their
``metadata.evidence.article_ids`` cite a ``YouTube Transcript`` from an allowlisted
channel (``youtube_sources``), only sweep-found videos, or no video (same tickers).
Scores each group with the /track-record rules: after-cost hit vs the day-bucketed
shuffled baseline (``track_record_service.compute_baselines``), computed within the
group, plus mean directional excess after cost. Also prints a per-channel 30d table.

Stances are overlapping daily calls, so effective n is far smaller than shown; treat
per-channel rows as a shortlist, not a verdict.

Usage (on the server, RESEARCH_DATABASE_URL set):
    python web_dashboard/scripts/k5_youtube_source_roi.py

Without DB credentials (e.g. a cloud session with read-only psql): run the SQL from
``--print-sql`` through psql, save its single ``line`` column to a file, then
    python web_dashboard/scripts/k5_youtube_source_roi.py --input rows.txt
Lines that aren't data (psql headers/footers) are skipped.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from track_record_service import (  # noqa: E402
    _BEARISH_STANCES,
    _BULLISH_STANCES,
    _after_cost_outcome,
    compute_baselines,
)

SINCE = "2026-07-30"  # allowlist poll + sweep both live from here
SWEEP_STALENESS_FIX = "2026-09-29"

# One CSV-ish text column per row so it survives restricted psql shells that reject
# output flags. coalesce(...,'') keeps concat_ws from dropping NULLs and shifting columns.
SQL = f"""
with s as (
  select id, ticker, source, stance, as_of from stance_history
  where source in ('ticker_analysis','ticker_meta_analysis') and as_of >= '{SINCE}'
),
cites as (
  select s.id, ra.source_metadata->>'channel' ch,
         (ra.source_metadata->>'channel_id') in
           (select channel_id from youtube_sources where channel_id is not null) allow
  from s join stance_history h on h.id = s.id
  cross join lateral jsonb_array_elements_text(h.metadata->'evidence'->'article_ids') a(aid)
  join research_articles ra on ra.id::text = a.aid
  where ra.article_type = 'YouTube Transcript'
),
agg as (
  select id, bool_or(allow) any_allow, bool_or(not allow) any_sweep,
         string_agg(distinct replace(ch, ',', ' '), '|') chans
  from cites group by id
)
select concat_ws(',', s.id, s.ticker, s.source, s.stance, s.as_of::date, o.horizon_days,
                 coalesce(o.excess_return::text, ''), coalesce(o.cost_bps::text, ''),
                 coalesce(agg.any_allow, false), coalesce(agg.any_sweep, false),
                 coalesce(agg.chans, '')) as line
from s join stance_outcomes o on o.stance_id = s.id
left join agg on agg.id = s.id
where o.horizon_days in (7, 30)
"""


def parse_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    rows = []
    for line in lines:
        p = line.strip().split(",")
        if len(p) < 10 or p[5] not in ("7", "30") or p[6] == "":
            continue
        sid, tk, src, st, d, h, ex, cost, al, sw = p[:10]
        rows.append(
            dict(
                id=sid, ticker=tk, source=src, stance=st, as_of=d, h=int(h),
                excess_return=float(ex), cost_bps=int(cost) if cost else None,
                allow=al in ("t", "true", "True"), sweep=sw in ("t", "true", "True"),
                chans=p[10] if len(p) > 10 else "",
            )
        )
    return rows


def stats(rs: list[dict[str, Any]]) -> tuple[int, float | None, float | None]:
    """(n, edge vs shuffled in pp, mean directional excess after cost)."""
    base = compute_baselines([(r["stance"], r["excess_return"], r["cost_bps"], r["as_of"]) for r in rs])
    hits, dirx = [], []
    for r in rs:
        s = r["stance"].upper()
        if s not in _BULLISH_STANCES | _BEARISH_STANCES:
            continue
        bull = s in _BULLISH_STANCES
        hits.append(_after_cost_outcome(r["excess_return"], r["cost_bps"], bullish=bull))
        if r["cost_bps"] is not None:
            dirx.append((r["excess_return"] if bull else -r["excess_return"]) - r["cost_bps"] / 100)
    scored = [x for x in hits if x is not None]
    actual = sum(scored) / len(scored) if scored else None
    sh = base["shuffled_hit_rate"]
    edge = (actual - sh) * 100 if actual is not None and sh is not None else None
    return len(rs), edge, (sum(dirx) / len(dirx) if dirx else None)


def _fmt(x: float | None, nd: int) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def report(rows: list[dict[str, Any]], min_channel_n: int = 30) -> None:
    yt_tickers = {r["ticker"] for r in rows if r["allow"] or r["sweep"]}

    def group(r: dict[str, Any]) -> str | None:
        if r["allow"]:
            return "Allowlist video"
        if r["sweep"]:
            return "Sweep-only video"
        return "No YouTube, same tickers" if r["ticker"] in yt_tickers else None

    def table(title: str, rs: list[dict[str, Any]]) -> None:
        print(f"\n{title}\n{'group':28} {'h':>3} {'n':>6} {'edge_pp':>8} {'mean_xac':>9}")
        g: dict[tuple[str, int], list] = collections.defaultdict(list)
        for r in rs:
            k = group(r)
            if k:
                g[(k, r["h"])].append(r)
        for (k, h), v in sorted(g.items()):
            n, e, m = stats(v)
            print(f"{k:28} {h:>3} {n:>6} {_fmt(e, 1):>8} {_fmt(m, 2):>9}")

    table(f"ALL since {SINCE}", rows)
    table(f"BEFORE sweep-staleness fix (< {SWEEP_STALENESS_FIX})", [r for r in rows if r["as_of"] < SWEEP_STALENESS_FIX])
    table(f"AFTER fix (>= {SWEEP_STALENESS_FIX})", [r for r in rows if r["as_of"] >= SWEEP_STALENESS_FIX])

    g: dict[tuple[str, bool], list] = collections.defaultdict(list)
    for r in rows:
        if r["h"] == 30 and (r["allow"] or r["sweep"]):
            for c in filter(None, r["chans"].split("|")):
                g[(c, r["allow"])].append(r)
    res = [(k, *stats(v)) for k, v in g.items() if len({x["id"] for x in v}) >= min_channel_n]
    res.sort(key=lambda x: (x[2] is None, -(x[2] or 0)))
    print(f"\nPER CHANNEL 30d (>= {min_channel_n} stances), sorted by edge")
    for (c, allow), n, e, m in res:
        print(f"{c[:34]:34} {'ALLOW' if allow else 'sweep':5} n={n:4} edge={_fmt(e, 1):>6}pp  mean_xac={_fmt(m, 2):>6}")
    print_decision_lists(res)


# K13 thresholds. Deliberately loose on n (stances overlap daily) and asymmetric:
# promotion needs both a positive edge and positive excess; a block needs a clearly
# bad edge or clearly bad excess. Humans approve both lists.
PROMOTE_MIN_EDGE_PP = 3.0
BLOCK_MAX_EDGE_PP = -7.0
BLOCK_MAX_MEAN_XAC = -8.0


def decision_lists(res: list, blocklist: Any = None) -> tuple[list, list]:
    """(promote, block) candidates from per-channel rows ((name, allow), n, edge, mean_xac).

    Only sweep-found channels are candidates; already-blocked channels are left out.
    """
    promote, block = [], []
    for (name, allow), n, edge, xac in res:
        if allow or (blocklist is not None and blocklist.blocks(name=name)):
            continue
        if edge is not None and xac is not None and edge >= PROMOTE_MIN_EDGE_PP and xac > 0:
            promote.append((name, n, edge, xac))
        elif (edge is not None and edge <= BLOCK_MAX_EDGE_PP) or (xac is not None and xac <= BLOCK_MAX_MEAN_XAC):
            block.append((name, n, edge, xac))
    return promote, block


def print_decision_lists(res: list) -> None:
    try:
        from yt_channel_policy import get_blocklist

        blocklist = get_blocklist()
    except Exception:
        blocklist = None
    promote, block = decision_lists(res, blocklist)
    print(f"\nK13 PROMOTE to youtube_sources (sweep, edge >= +{PROMOTE_MIN_EDGE_PP}pp and mean_xac > 0)")
    for name, n, e, m in promote or [("(none)", 0, None, None)]:
        print(f"  {name[:40]:40} n={n:4} edge={_fmt(e, 1):>6}pp  mean_xac={_fmt(m, 2):>6}")
    print(
        f"\nK12 BLOCK candidates (sweep, edge <= {BLOCK_MAX_EDGE_PP}pp or mean_xac <= {BLOCK_MAX_MEAN_XAC}; "
        "add to system_settings.youtube_channel_blocklist)"
    )
    for name, n, e, m in block or [("(none)", 0, None, None)]:
        print(f"  {name[:40]:40} n={n:4} edge={_fmt(e, 1):>6}pp  mean_xac={_fmt(m, 2):>6}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="file of exported 'line' rows instead of querying the DB")
    ap.add_argument("--print-sql", action="store_true", help="print the export SQL and exit")
    ap.add_argument("--min-channel-n", type=int, default=30)
    args = ap.parse_args()
    if args.print_sql:
        print(SQL.strip())
        return
    if args.input:
        lines = Path(args.input).read_text().splitlines()
    else:
        from postgres_client import PostgresClient

        lines = [r["line"] for r in PostgresClient().execute_query(SQL) or []]
    report(parse_lines(lines), args.min_channel_n)


if __name__ == "__main__":
    main()
