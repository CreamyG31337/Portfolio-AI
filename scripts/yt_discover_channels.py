#!/usr/bin/env python3
"""Discover candidate YouTube channels from keyword search, spending zero caption fetches.

Phase K, `PHASE_K_TREND_LAYER_PLAN.md` §3 / `PHASE_K_SOURCE_RESEARCH_PROMPT.md` §9.

Why this exists
---------------
Caption *fetch* is quota-limited to roughly 90/IP/day
(`PHASE_K_SOURCE_LIST.md` §14). Listing is **not** — it stayed available
throughout the block that failed 137 of 150 fetches (§13). So candidate
discovery can run at volume for free, and only survivors should ever cost a
fetch.

Method (cheapest signal first, mirroring what actually worked in five research
rounds):

1. Run many queries; aggregate hits to *channels*, not videos.
2. Rank by **distinct-query recurrence** — the double-nomination signal that beat
   every individual model ranking in §16 / §17 / §19.
3. Apply structural rejects from listing metadata alone — **median view count**
   (no audience means ATTENTION is impossible by construction), Shorts-farm
   duration, thin sample.
4. Title-scan for tradeable share — the filter that killed space (0-3%) and
   displays (26%) for free.
5. Score promotion tells from titles, before any transcript exists.

Queries should target the *observation*, not the ticker: ticker-targeted queries
select for promotional content by construction (§19).

Usage (repo root, venv active)::

    python scripts/yt_discover_channels.py --queries-file queries.txt --tickers MU,NVDA
    python scripts/yt_discover_channels.py -q "transformer lead times" -q "switchgear shortage"
    python scripts/yt_discover_channels.py --queries-file q.txt --json out.json --per-query 20

Exit codes:
  0 ran (even if nothing survived ranking)
  1 every query failed to list
  2 bad CLI usage
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web_dashboard"
for path in (_REPO_ROOT, _WEB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

logger = logging.getLogger("yt_discover_channels")

# --- Scoring vocabulary -----------------------------------------------------
# Title-level only. Transcript-level filters (friction words, caption gaps) are
# K7 and need a body; these run before we have spent a single fetch.

# Promotion tells, §19 (double-nominated by both research models).
_PROMO_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bmulti[- ]?bagger\b", "multibagger"),
    (r"\bgame[- ]?changer\b", "game-changer"),
    (r"\b10x\b|\b100x\b", "Nx-upside"),
    (r"\bmust[- ]own\b|\bmust[- ]buy\b", "must-own"),
    (r"\bbefore it'?s too late\b", "urgency"),
    (r"\bnext (big|huge)\b", "next-big"),
    (r"\bexplodes?\b|\bskyrockets?\b|\bsoars?\b", "hype-verb"),
    (r"\bhidden gem\b|\bunder the radar\b", "hidden-gem"),
    (r"\bprice target\b|\bPT \$", "price-target"),
    (r"\btop \d+ (uranium|gold|mining|lithium|ai|energy)\b", "listicle-pick"),
    (r"\bCEO interview\b|\binterview with\b", "interview-format"),
    (r"\bsponsored\b|\bpaid (content|production)\b", "disclosed-paid"),
)

# Macro-narration tells, §17 (both models) — high token volume, ~zero density.
_MACRO_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bTAM\b|\bCAGR\b", "tam-cagr"),
    (r"\bhyperscalers?\b", "hyperscaler"),
    (r"\bthe grid can'?t keep up\b", "grid-macro"),
    (r"\b(nuclear|ai|energy) (renaissance|boom|revolution)\b", "narrative-boom"),
    (r"\bstructural (deficit|shortage)\b", "structural-deficit"),
    (r"\bwhy .* (will|could) (soar|crash|explode)\b", "clickbait-thesis"),
)

# Primary-observation tells — weak positive evidence from a title alone.
_PRIMARY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bteardown\b|\bdisassembl", "teardown"),
    (r"\bwe (tested|measured|benchmark)", "measured"),
    (r"\bservice call\b|\bin the field\b|\bon site\b", "field"),
    (r"\blead times?\b|\bbackorder|\bshortage\b", "supply-observation"),
    (r"\bfailure (mode|rate|analysis)\b|\bteardown\b", "failure-analysis"),
    (r"\bpart number\b|\berror code\b", "part-level"),
)

_CASHTAG_RE = re.compile(r"\$[A-Z]{1,5}\b")
_SHORTS_MAX_S = 120


def _compile(patterns: Sequence[tuple[str, str]]) -> tuple[tuple[Any, str], ...]:
    return tuple((re.compile(pat, re.IGNORECASE), label) for pat, label in patterns)


_PROMO = _compile(_PROMO_PATTERNS)
_MACRO = _compile(_MACRO_PATTERNS)
_PRIMARY = _compile(_PRIMARY_PATTERNS)


@dataclass(frozen=True)
class TickerTarget:
    """A ticker plus the company/brand names that actually appear in titles."""

    ticker: str
    patterns: tuple[Any, ...]

    @staticmethod
    def parse(spec: str) -> "TickerTarget":
        """``VRT:Vertiv:Liebert`` -> symbol plus alias names, all matched."""
        parts = [p.strip() for p in spec.split(":") if p.strip()]
        if not parts:
            raise ValueError(f"empty ticker spec: {spec!r}")
        ticker = parts[0].upper()
        # The bare symbol (sans exchange suffix) plus every supplied alias.
        terms = [ticker.split(".")[0]] + parts[1:]
        patterns = tuple(
            re.compile(
                rf"(?<![A-Za-z0-9])\$?{re.escape(term)}(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
            for term in terms
            if len(term) >= 2
        )
        return TickerTarget(ticker=ticker, patterns=patterns)

    def matches(self, title: str) -> bool:
        return any(rx.search(title) for rx in self.patterns)


@dataclass
class ChannelCandidate:
    """One channel aggregated across every query that surfaced it."""

    channel_id: str
    channel_name: Optional[str] = None
    queries: set[str] = field(default_factory=set)
    titles: list[str] = field(default_factory=list)
    durations: list[int] = field(default_factory=list)
    views: list[int] = field(default_factory=list)
    video_ids: set[str] = field(default_factory=set)

    # -- derived ------------------------------------------------------------
    @property
    def query_recurrence(self) -> int:
        """Distinct queries that surfaced this channel. The primary rank key."""
        return len(self.queries)

    @property
    def median_duration_s(self) -> Optional[int]:
        vals = [d for d in self.durations if d]
        return int(median(vals)) if vals else None

    @property
    def median_views(self) -> Optional[int]:
        """Median views across sampled videos — the audience-reach measure.

        The ATTENTION mechanism depends entirely on how many people actually
        watched, and every research round estimated *subscriber* counts instead,
        which is a much worse proxy: subs measure accumulated audience, views
        measure who saw this video.
        """
        vals = [v for v in self.views if v]
        return int(median(vals)) if vals else None

    def tag_hits(self, compiled: Sequence[tuple[Any, str]]) -> dict[str, int]:
        hits: dict[str, int] = {}
        for title in self.titles:
            for rx, label in compiled:
                if rx.search(title):
                    hits[label] = hits.get(label, 0) + 1
        return hits

    def ticker_hits(self, targets: Sequence["TickerTarget"]) -> dict[str, int]:
        """Count titles mentioning each target, by symbol **or company name**.

        Names matter more than symbols here. `PHASE_K_SOURCE_LIST.md` §3
        measured tradeable share by scanning for *company* mentions, and video
        titles overwhelmingly say "Eaton" and "Vertiv" rather than ETN and VRT.
        Matching symbols alone reports ~0% for every channel and would fake an
        absence result. Deliberately crude otherwise: a cheap pre-filter, not
        the K2 extractor.
        """
        hits: dict[str, int] = {}
        for target in targets:
            n = sum(1 for t in self.titles if target.matches(t))
            if n:
                hits[target.ticker] = n
        return hits

    def structural_rejects(self, *, min_titles: int, min_views: int) -> list[str]:
        """Disqualifiers computable from listing metadata alone."""
        reasons: list[str] = []
        med = self.median_duration_s
        if med is not None and med < _SHORTS_MAX_S:
            reasons.append(f"shorts_farm(median={med}s)")
        views = self.median_views
        if views is not None and views < min_views:
            # Nobody is watching, so ATTENTION is impossible by construction and
            # INFORMATION is unlikely to be worth a fetch.
            reasons.append(f"no_audience(median={views:,} views)")
        if len(self.titles) < min_titles:
            reasons.append(f"thin_sample({len(self.titles)})")
        if not self.channel_id:
            reasons.append("no_channel_id")
        return reasons


def _load_queries(args: argparse.Namespace) -> list[str]:
    queries: list[str] = list(args.query or [])
    if args.queries_file:
        path = Path(args.queries_file)
        if not path.exists():
            raise SystemExit(f"queries file not found: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                queries.append(text)
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    return [q for q in queries if not (q.lower() in seen or seen.add(q.lower()))]


def discover(
    queries: Sequence[str],
    *,
    per_query: int,
    delay_s: float,
) -> tuple[dict[str, ChannelCandidate], int]:
    """Run every query and aggregate hits by channel. Returns (candidates, failures)."""
    from yt_captions import CaptionFetchError, list_search_videos

    candidates: dict[str, ChannelCandidate] = {}
    failures = 0

    for idx, query in enumerate(queries, start=1):
        if idx > 1 and delay_s > 0:
            time.sleep(delay_s)
        try:
            # max_limit is raised past the ingest-path default on purpose: this
            # is a discovery sweep that spends no caption fetches and writes
            # nothing to research_articles (see list_search_videos docstring).
            listings = list_search_videos(
                query, limit=per_query, max_limit=per_query
            )
        except CaptionFetchError as exc:
            failures += 1
            logger.warning("query %r failed (%s): %s", query, exc.reason, exc)
            continue
        except Exception as exc:  # listing client can raise its own types
            failures += 1
            logger.warning("query %r failed: %s", query, exc)
            continue

        logger.info("[%d/%d] %-45s -> %d hits", idx, len(queries), query[:45], len(listings))
        for item in listings:
            cid = (item.channel_id or "").strip()
            if not cid:
                # Without attribution the hit cannot be aggregated; skip rather
                # than inventing a synthetic key that would split one channel.
                continue
            cand = candidates.get(cid)
            if cand is None:
                cand = ChannelCandidate(channel_id=cid, channel_name=item.channel_name)
                candidates[cid] = cand
            cand.channel_name = cand.channel_name or item.channel_name
            cand.queries.add(query)
            cand.video_ids.add(item.video_id)
            if item.title:
                cand.titles.append(item.title)
            if item.duration_s:
                cand.durations.append(int(item.duration_s))
            if item.view_count:
                cand.views.append(int(item.view_count))

    return candidates, failures


def score(
    candidates: dict[str, ChannelCandidate],
    *,
    tickers: Sequence[TickerTarget],
    min_titles: int,
    min_views: int,
) -> list[dict[str, Any]]:
    """Rank candidates, recurrence first. Rejects are annotated, never dropped."""
    rows: list[dict[str, Any]] = []
    for cand in candidates.values():
        promo = cand.tag_hits(_PROMO)
        macro = cand.tag_hits(_MACRO)
        primary = cand.tag_hits(_PRIMARY)
        tick = cand.ticker_hits(tickers) if tickers else {}
        n_titles = max(1, len(cand.titles))
        cashtags = sum(1 for t in cand.titles if _CASHTAG_RE.search(t))

        rows.append(
            {
                "channel_id": cand.channel_id,
                "channel_name": cand.channel_name,
                "query_recurrence": cand.query_recurrence,
                "queries": sorted(cand.queries),
                "videos_seen": len(cand.video_ids),
                "median_duration_s": cand.median_duration_s,
                "median_views": cand.median_views,
                "total_views_sampled": sum(cand.views),
                # Share of sampled titles naming a ticker we care about. This is
                # the tradeable-share proxy that rejected two sectors for free.
                "ticker_title_share": round(sum(tick.values()) / n_titles, 3),
                "ticker_hits": tick,
                "promotion_score": round(sum(promo.values()) / n_titles, 3),
                "promotion_tells": promo,
                "macro_score": round(sum(macro.values()) / n_titles, 3),
                "macro_tells": macro,
                "primary_score": round(sum(primary.values()) / n_titles, 3),
                "primary_tells": primary,
                "cashtag_share": round(cashtags / n_titles, 3),
                "structural_rejects": cand.structural_rejects(
                    min_titles=min_titles, min_views=min_views
                ),
                "sample_titles": cand.titles[:5],
            }
        )

    rows.sort(
        key=lambda r: (
            not r["structural_rejects"],  # clean candidates first
            r["query_recurrence"],
            r["median_views"] or 0,
            r["primary_score"],
            r["ticker_title_share"],
            -r["promotion_score"],
        ),
        reverse=True,
    )
    return rows


def _print_report(rows: Sequence[dict[str, Any]], *, top: int) -> None:
    if not rows:
        print("\nNo channels aggregated. Every query failed or returned no attribution.")
        return

    print(f"\n{'=' * 78}\nCANDIDATES (ranked; {len(rows)} channels)\n{'=' * 78}")
    header = (
        f"{'recur':>5} {'medviews':>9} {'prim':>5} {'promo':>5} {'macro':>5} "
        f"{'tick%':>6} {'meds':>5}  channel"
    )
    print(header)
    print("-" * 78)
    for row in rows[:top]:
        flag = " !" if row["structural_rejects"] else "  "
        print(
            f"{row['query_recurrence']:>5} "
            f"{(f"{row['median_views']:,}" if row['median_views'] else '-'):>9} "
            f"{row['primary_score']:>5.2f} "
            f"{row['promotion_score']:>5.2f} "
            f"{row['macro_score']:>5.2f} "
            f"{row['ticker_title_share'] * 100:>5.0f}% "
            f"{str(row['median_duration_s'] or '-'):>5}"
            f"{flag}{row['channel_name'] or row['channel_id']}"
        )
        if row["structural_rejects"]:
            print(f"{'':>34}rejects: {', '.join(row['structural_rejects'])}")

    print("\nColumns: recur=distinct queries surfacing it (primary rank key), "
          "medviews=median views/video,\n         prim/promo/macro=tells per title, "
          "tick%=share of titles naming a target company,\n         meds=median "
          "duration s, !=structural reject")
    print("\nNote: no captions were fetched. Verify handles and run the Stage 0 "
          "harness on survivors only.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover candidate channels from keyword search (no caption fetches)."
    )
    parser.add_argument("-q", "--query", action="append", help="Query (repeatable)")
    parser.add_argument("--queries-file", help="File of queries, one per line, # comments ok")
    parser.add_argument(
        "--tickers",
        default="",
        help=(
            "Comma-separated targets for the tradeable-share scan. Add company/brand "
            "aliases with colons — titles say the name, not the symbol: "
            "'VRT:Vertiv:Liebert,ETN:Eaton,CCO.TO:Cameco'"
        ),
    )
    parser.add_argument("--per-query", type=int, default=20, help="Results per query (default 20)")
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds between queries (default 1.0). Listing is not quota-limited, "
        "but pacing keeps us well clear of it.",
    )
    parser.add_argument(
        "--min-titles",
        type=int,
        default=2,
        help="Flag channels seen fewer than N times as thin_sample (default 2)",
    )
    parser.add_argument(
        "--min-views",
        type=int,
        default=2000,
        help="Flag channels whose median views fall below N as no_audience (default 2000). "
        "Attention alpha is impossible without an audience; information alpha rarely "
        "survives one either.",
    )
    parser.add_argument("--top", type=int, default=30, help="Rows to print (default 30)")
    parser.add_argument("--json", help="Write full ranked results to this path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    queries = _load_queries(args)
    if not queries:
        parser.error("need at least one --query or --queries-file")

    tickers = [
        TickerTarget.parse(spec) for spec in args.tickers.split(",") if spec.strip()
    ]

    print(f"Running {len(queries)} queries x {args.per_query} results "
          f"({len(queries) * args.per_query} listings, 0 caption fetches)")

    candidates, failures = discover(
        queries, per_query=args.per_query, delay_s=args.delay
    )
    if failures == len(queries):
        print("ERROR: every query failed to list. Check network / proxy / listing client.")
        return 1

    rows = score(
        candidates,
        tickers=tickers,
        min_titles=args.min_titles,
        min_views=args.min_views,
    )
    _print_report(rows, top=args.top)

    if args.json:
        Path(args.json).write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nWrote {len(rows)} rows -> {args.json}")

    if failures:
        print(f"\n{failures} of {len(queries)} queries failed to list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
