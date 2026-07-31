#!/usr/bin/env python3
"""YouTube promotion event study - Phase K Stage 1 (attention-alpha falsification).

WHY THIS EXISTS
---------------
Two independent research models (§19) asserted that for TSX/TSXV mining and uranium
juniors, a promotional YouTube video produces a measurable abnormal price/volume
move within 24-48h, then reverses. Neither supplied a dated example
(``dated_example: UNVERIFIED``). This is the only "attention alpha is live"
finding in five research rounds, and it was unmeasured.

§22 then showed the claim was argued from subscriber counts while median views on
the mining interview corpus are 2,350-13,000. So ``view_count`` is the independent
variable: effect size must be reported per view bucket, with the high-view tail
oversampled. A null on median-view videos proves nothing.

§24 showed the original 42-name curated list selected *against* the phenomenon
(established producers, not pre-revenue story juniors). Matching now defaults to
the complete TSX/TSXV/CSE issuer directory (``canadian_issuer_universe.py``) —
complete rather than curated, so it cannot be biased toward or against promotion.
Do **not** build the universe from high-view titles (outcome selection).

METHODOLOGY (mirrors insider_event_study.py guardrails)
------------------------------------------------------
1. EVENT DATE = publish date from non-flat metadata (flat listing returns None).
2. ENTRY = first close STRICTLY AFTER the event date.
3. EVENTS DEDUPED to (ticker, event_date).
4. HEADLINE = high-view - low-view excess spread (not absolute alone).
5. NULL = day-bucketed random relabelling of bucket labels.
6. Curve at t+1 / t+2 / t+5 / t+21; pre-event drift t-5->t-1; abnormal volume.
7. Zero caption fetches. Zero LLM. Zero DB writes.
8. CSE fraction reported early (tradeability) before price download.

Run from project root:
  python web_dashboard/scripts/yt_promotion_event_study.py
  python web_dashboard/scripts/yt_promotion_event_study.py --per-channel 100
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
_SCRIPTS = _REPO_ROOT / "scripts"
for p in (str(_WEB_DASHBOARD), str(_REPO_ROOT), str(_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

warnings.filterwarnings("ignore")

# View buckets - fixed from §22 before seeing results. Do not retune.
VIEW_LOW_MAX = 10_000  # exclusive upper bound for "low" (median territory)
VIEW_HIGH_MIN = 50_000  # inclusive lower bound for "high" (tail)

HORIZONS = (1, 2, 5, 21)
PRE_EVENT_START = 5  # calendar days before event
PRE_EVENT_END = 1
VOLUME_LOOKBACK = 20  # trading sessions
PRICE_BATCH = 50
META_DELAY_S = 0.75  # light pacing between metadata calls

# §19 double-nominated promotion corpus (+ Palisades from §22 measurement)
# + The Deep Dive (§24 counterexample; youtube_sources id 14).
DEFAULT_CHANNELS: tuple[str, ...] = (
    "@ResourceTalks",
    "@CRUXInvestor",
    "@MiningStockEdu",
    "@UraniumInsider",
    "@PalisadeRadio",
    "UC04_rUstP7vyLANZ0rJYz_A",  # The Deep Dive (@TheDeepDiveCa)
)

# Company-name aliases required - titles say "Denison", not "DNN" (§17 lesson).
# One ticker per company name: duplicate aliases across symbols would classify
# a single-company video as multi and drop it.
DEFAULT_TICKER_SPECS: tuple[str, ...] = (
    # Uranium / nuclear fuel cycle (prefer the listing Chimera / docs name)
    "CCO.TO:Cameco",
    "DNN:Denison",
    "NXE.TO:NexGen:Nexgen",
    "GLO.TO:Global Atomic",
    "UEC:Uranium Energy",
    "UUUU:Energy Fuels",
    "LEU:Centrus",
    "URG:Ur-Energy:Ur Energy",
    "UROY:Uranium Royalty",
    "URNM:Sprott Uranium",
    "ISO.V:IsoEnergy:Iso Energy",
    "WUC.CN:Western Uranium",
    "SASK.V:Atha:Atha Energy",
    "FSY.TO:Forsys",
    "OKLO:Oklo",
    "SMR:NuScale",
    "CEG:Constellation",
    # Gold / precious (one symbol per name)
    "GMIN.TO:G Mining:GMining",
    "EDV.TO:Endeavour Mining",
    "AEM.TO:Agnico",
    "K.TO:Kinross",
    "ABX.TO:Barrick",
    "NEM:Newmont",
    "WDO.TO:Wesdome",
    "OGC.TO:OceanaGold:Oceanagold",
    "SSL.TO:Sandstorm",
    "PAAS:Pan American",
    "AGI:Alamos",
    "BTO.TO:B2Gold:B2gold",
    "TXG.TO:Torex",
    "CG.TO:Centerra",
    "FNV:Franco-Nevada:Franco Nevada",
    "WPM:Wheaton",
    "AG:First Majestic",
    "HL:Hecla",
    "CDE:Coeur",
    "SA:Seabridge",
    "NG:NovaGold:Novagold",
    "IAG:IAMGOLD:Iamgold",
    "EQX:Equinox",
    "ARIS.TO:Aris Mining",
    "OR.TO:Osisko",
)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def parse_upload_date(raw: Optional[str]) -> Optional[date]:
    """Parse listing-client ``YYYYMMDD``; reject missing/malformed rather than guess."""
    text = (raw or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def view_bucket(views: Optional[int]) -> Optional[str]:
    """Map view_count to low / mid / high. None views -> None (unbucketable)."""
    if views is None or views < 0:
        return None
    if views < VIEW_LOW_MAX:
        return "low"
    if views < VIEW_HIGH_MIN:
        return "mid"
    return "high"


def matching_tickers(text: str, targets: Sequence[Any]) -> list[str]:
    """Return tickers whose alias patterns hit ``text`` (title and/or description)."""
    hit: list[str] = []
    for target in targets:
        if target.matches(text):
            hit.append(target.ticker)
    return hit


def classify_match(tickers: Sequence[str]) -> str:
    """``none`` / ``single`` / ``multi`` - only ``single`` becomes an event."""
    n = len(set(tickers))
    if n == 0:
        return "none"
    if n == 1:
        return "single"
    return "multi"


@dataclass
class RawEvent:
    video_id: str
    ticker: str
    event_date: date
    view_count: Optional[int]
    channel: str
    title: str
    bucket: Optional[str]


def dedupe_events(events: Sequence[RawEvent]) -> list[RawEvent]:
    """One event per (ticker, event_date). Keep the highest-view video as representative."""
    best: dict[tuple[str, date], RawEvent] = {}
    for ev in events:
        key = (ev.ticker, ev.event_date)
        prev = best.get(key)
        if prev is None:
            best[key] = ev
            continue
        prev_views = prev.view_count if prev.view_count is not None else -1
        cur_views = ev.view_count if ev.view_count is not None else -1
        if cur_views > prev_views:
            best[key] = ev
    return sorted(best.values(), key=lambda e: (e.event_date, e.ticker))


def _close_after(series: list[dict[str, Any]], target: date) -> tuple[date, float] | None:
    """First close STRICTLY after target (entry must be tradeable, never same-session)."""
    for row in series:
        if row["date"] > target:
            return row["date"], float(row["close"])
    return None


def _close_on_or_before(series: list[dict[str, Any]], target: date) -> float | None:
    best = None
    for row in series:
        if row["date"] <= target:
            best = float(row["close"])
        else:
            break
    return best


def _row_on_or_before(series: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    best = None
    for row in series:
        if row["date"] <= target:
            best = row
        else:
            break
    return best


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or a == 0:
        return None
    return (b - a) / a * 100.0


def _summarise(label: str, values: list[float]) -> dict[str, Any]:
    if not values:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "hit_rate": sum(1 for v in values if v > 0) / len(values),
    }


def honesty_label(n: int) -> str:
    if n < 5:
        return "no verdict (n<5 proves nothing)"
    if n < 30:
        return "directional only (n<30)"
    return "interpretable sample"


# ---------------------------------------------------------------------------
# Price / volume download
# ---------------------------------------------------------------------------


def _download_ohlcv(
    tickers: list[str], start: date, end: date
) -> dict[str, list[dict[str, Any]]]:
    """Batch-download Close + Volume. One call per PRICE_BATCH tickers."""
    import pandas as pd
    import yfinance as yf

    out: dict[str, list[dict[str, Any]]] = {}
    for i in range(0, len(tickers), PRICE_BATCH):
        batch = tickers[i : i + PRICE_BATCH]
        print(f"  prices {i + 1}-{i + len(batch)} of {len(tickers)}...", flush=True)
        try:
            data = yf.download(
                batch,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
            )
        except Exception as exc:
            print(f"    batch failed: {exc}")
            continue
        if data is None or data.empty:
            continue

        multi = isinstance(data.columns, pd.MultiIndex)
        available = set(data.columns.get_level_values(0)) if multi else set()

        for symbol in batch:
            try:
                if multi:
                    if symbol not in available:
                        continue
                    frame = data[symbol]
                else:
                    frame = data
                closes = frame["Close"].dropna()
                volumes = frame["Volume"] if "Volume" in frame.columns else None
            except Exception:
                continue
            series: list[dict[str, Any]] = []
            for idx, val in closes.items():
                if val != val:
                    continue
                vol = None
                if volumes is not None:
                    try:
                        v = volumes.loc[idx]
                        vol = float(v) if v == v else None
                    except Exception:
                        vol = None
                series.append({"date": idx.date(), "close": float(val), "volume": vol})
            if series:
                out[symbol] = sorted(series, key=lambda r: r["date"])
    return out


def _trailing_median_volume(
    series: list[dict[str, Any]], before: date, lookback: int = VOLUME_LOOKBACK
) -> float | None:
    vols = [
        float(r["volume"])
        for r in series
        if r["date"] < before and r.get("volume") is not None and r["volume"] > 0
    ]
    if len(vols) < max(5, lookback // 2):
        return None
    return float(statistics.median(vols[-lookback:]))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class MetadataBlocked(RuntimeError):
    """Raised when YouTube blocks metadata fetches - stop rather than invent dates."""


def _list_channel_videos(spec: str, limit: int) -> list[Any]:
    """List by channel_id (UC…) or @handle. Zero caption fetches."""
    from yt_captions import list_channel_videos

    text = (spec or "").strip()
    if text.startswith("UC") and len(text) >= 20 and "/" not in text:
        return list_channel_videos(channel_id=text, limit=limit)
    return list_channel_videos(handle=text, limit=limit)


def _resolve_metadata(video_id: str) -> Any:
    from yt_captions import CaptionFetchError, fetch_video_metadata

    try:
        return fetch_video_metadata(video_id)
    except CaptionFetchError as exc:
        if exc.reason == "blocked":
            raise MetadataBlocked(
                f"Metadata fetch blocked on {video_id}: {exc}. "
                "Stopping rather than inventing publish dates (Phase K §13)."
            ) from exc
        raise


def _empty_attrition() -> dict[str, int]:
    return {
        "listed": 0,
        "title_matched": 0,
        "title_multi": 0,
        "title_none": 0,
        "dates_resolved": 0,
        "dates_missing": 0,
        "desc_demoted_multi": 0,
        "after_dedupe": 0,
    }


def list_videos(
    channels: Sequence[str], per_channel: int
) -> tuple[list[dict[str, Any]], int]:
    """Flat-list every channel. Returns video dicts + total listed count."""
    videos: list[dict[str, Any]] = []
    listed = 0
    for handle in channels:
        print(f"  listing {handle} (limit {per_channel})...", flush=True)
        try:
            listings = _list_channel_videos(handle, per_channel)
        except Exception as exc:
            print(f"    listing failed: {exc}")
            continue
        listed += len(listings)
        for v in listings:
            videos.append(
                {
                    "video_id": v.video_id,
                    "title": v.title or "",
                    "view_count": v.view_count,
                    "channel": handle,
                    "channel_name": v.channel_name,
                }
            )
    return videos, listed


def title_match_candidates(
    videos: Sequence[dict[str, Any]], targets: Sequence[Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Title-only match. Only single-ticker hits become candidates."""
    attrition = _empty_attrition()
    attrition["listed"] = len(videos)
    candidates: list[dict[str, Any]] = []
    for v in videos:
        hits = matching_tickers(v["title"], targets)
        kind = classify_match(hits)
        if kind == "none":
            attrition["title_none"] += 1
            continue
        if kind == "multi":
            attrition["title_multi"] += 1
            continue
        attrition["title_matched"] += 1
        candidates.append({**v, "ticker": hits[0]})
    return candidates, attrition


def resolve_event_dates(
    candidates: Sequence[dict[str, Any]],
    targets: Sequence[Any],
    *,
    meta_delay_s: float = META_DELAY_S,
    meta_cache: Optional[dict[str, Any]] = None,
) -> tuple[list[RawEvent], dict[str, int]]:
    """Metadata for publish date + description re-match. No captions."""
    attrition = _empty_attrition()
    attrition["listed"] = -1  # filled by caller if needed
    attrition["title_matched"] = len(candidates)
    cache = meta_cache if meta_cache is not None else {}
    raw: list[RawEvent] = []

    for i, cand in enumerate(candidates):
        vid = cand["video_id"]
        if vid not in cache:
            if i and meta_delay_s > 0:
                time.sleep(meta_delay_s)
            print(f"  metadata {i + 1}/{len(candidates)} {vid}...", flush=True)
            try:
                cache[vid] = _resolve_metadata(vid)
            except MetadataBlocked:
                raise
            except Exception as exc:
                print(f"    skip: {exc}")
                attrition["dates_missing"] += 1
                cache[vid] = None
                continue
        meta = cache[vid]
        if meta is None:
            attrition["dates_missing"] += 1
            continue

        event_date = parse_upload_date(meta.upload_date)
        if event_date is None:
            attrition["dates_missing"] += 1
            print(f"    skip: no upload_date for {vid}")
            continue

        blob = f"{cand['title']}\n{meta.description or ''}"
        hits = matching_tickers(blob, targets)
        kind = classify_match(hits)
        if kind == "multi":
            attrition["desc_demoted_multi"] += 1
            continue
        if kind == "none":
            ticker = cand["ticker"]
        else:
            ticker = hits[0]

        views = cand["view_count"]
        if meta.view_count is not None:
            views = meta.view_count
        attrition["dates_resolved"] += 1
        raw.append(
            RawEvent(
                video_id=vid,
                ticker=ticker,
                event_date=event_date,
                view_count=views,
                channel=cand["channel"],
                title=cand["title"],
                bucket=view_bucket(views),
            )
        )

    events = dedupe_events(raw)
    attrition["after_dedupe"] = len(events)
    return events, attrition


def build_events(
    *,
    channels: Sequence[str],
    targets: Sequence[Any],
    per_channel: int,
    meta_delay_s: float = META_DELAY_S,
) -> tuple[list[RawEvent], dict[str, int]]:
    """List -> match -> metadata -> single-ticker dated events. Prints attrition."""
    videos, listed = list_videos(channels, per_channel)
    candidates, attrition = title_match_candidates(videos, targets)
    attrition["listed"] = listed
    print(
        f"  listed={attrition['listed']} title_single={attrition['title_matched']} "
        f"title_multi={attrition['title_multi']} title_none={attrition['title_none']}"
    )
    events, date_attr = resolve_event_dates(
        candidates, targets, meta_delay_s=meta_delay_s
    )
    attrition["dates_resolved"] = date_attr["dates_resolved"]
    attrition["dates_missing"] = date_attr["dates_missing"]
    attrition["desc_demoted_multi"] = date_attr["desc_demoted_multi"]
    attrition["after_dedupe"] = date_attr["after_dedupe"]
    print(
        f"  dates_resolved={attrition['dates_resolved']} "
        f"dates_missing={attrition['dates_missing']} "
        f"desc_demoted_multi={attrition['desc_demoted_multi']} "
        f"after_dedupe={attrition['after_dedupe']}"
    )
    return events, attrition


def format_attrition_row(label: str, attrition: dict[str, int], priced: int | None = None) -> str:
    """One markdown-ish attrition summary line for §23-style tables."""
    parts = [
        f"listed={attrition.get('listed', 0)}",
        f"title_single={attrition.get('title_matched', 0)}",
        f"title_multi={attrition.get('title_multi', 0)}",
        f"title_none={attrition.get('title_none', 0)}",
        f"desc_demoted={attrition.get('desc_demoted_multi', 0)}",
        f"dated={attrition.get('dates_resolved', 0)}",
        f"deduped={attrition.get('after_dedupe', 0)}",
    ]
    if priced is not None:
        parts.append(f"priced={priced}")
    return f"{label}: " + " -> ".join(parts)


def report_tradeability(
    events: Sequence[RawEvent], targets: Sequence[Any]
) -> dict[str, Any]:
    """CSE vs TSX/TSXV mix — print before pricing (§24 tradeability check)."""
    from canadian_issuer_universe import exchange_of_ticker

    counts = {"CSE": 0, "TSX": 0, "TSXV": 0, "OTHER": 0}
    high_counts = {"CSE": 0, "TSX": 0, "TSXV": 0, "OTHER": 0}
    for ev in events:
        ex = exchange_of_ticker(ev.ticker, targets) or "OTHER"
        if ex not in counts:
            ex = "OTHER"
        counts[ex] += 1
        if ev.bucket == "high":
            high_counts[ex] += 1
    n = len(events) or 1
    n_high = sum(high_counts.values()) or 1
    cse_frac = counts["CSE"] / n
    high_cse_frac = high_counts["CSE"] / n_high if sum(high_counts.values()) else 0.0
    print("\n[TRADEABILITY] exchange mix of matched events (before prices)")
    print(
        f"  all events: TSX={counts['TSX']} TSXV={counts['TSXV']} "
        f"CSE={counts['CSE']} other={counts['OTHER']}  "
        f"(CSE share {cse_frac:.1%} of {len(events)})"
    )
    print(
        f"  high-view (>=50k): TSX={high_counts['TSX']} TSXV={high_counts['TSXV']} "
        f"CSE={high_counts['CSE']} other={high_counts['OTHER']}  "
        f"(CSE share {high_cse_frac:.1%} of {sum(high_counts.values())})"
    )
    if sum(high_counts.values()) and high_cse_frac >= 0.5:
        print(
            "  NOTE: majority of high-view promotion events are CSE-listed. "
            "If CSE is not tradeable in these accounts this is a §10-style "
            "'excellent signal, untradeable' finding — state it, do not bury it."
        )
    return {
        "counts": counts,
        "high_counts": high_counts,
        "cse_frac": cse_frac,
        "high_cse_frac": high_cse_frac,
    }


def _excess_at_horizon(
    series: list[dict[str, Any]],
    bseries: list[dict[str, Any]],
    event_date: date,
    horizon_days: int,
    end: date,
) -> float | None:
    entry = _close_after(series, event_date)
    bentry = _close_after(bseries, event_date)
    if not entry or not bentry:
        return None
    exit_date = entry[0] + timedelta(days=horizon_days)
    if exit_date > end:
        return None
    exit_px = _close_on_or_before(series, exit_date)
    bexit = _close_on_or_before(bseries, exit_date)
    r = _pct(entry[1], exit_px)
    br = _pct(bentry[1], bexit)
    if r is None or br is None:
        return None
    return r - br


def _pre_event_excess(
    series: list[dict[str, Any]],
    bseries: list[dict[str, Any]],
    event_date: date,
) -> float | None:
    """Excess return from close on/before t-5 to close on/before t-1."""
    t_start = event_date - timedelta(days=PRE_EVENT_START)
    t_end = event_date - timedelta(days=PRE_EVENT_END)
    a0 = _close_on_or_before(series, t_start)
    a1 = _close_on_or_before(series, t_end)
    b0 = _close_on_or_before(bseries, t_start)
    b1 = _close_on_or_before(bseries, t_end)
    # Require the end close to actually be before the event (no leakage).
    end_row = _row_on_or_before(series, t_end)
    if end_row is None or end_row["date"] >= event_date:
        return None
    r = _pct(a0, a1)
    br = _pct(b0, b1)
    if r is None or br is None:
        return None
    return r - br


def _abnormal_volume(
    series: list[dict[str, Any]], event_date: date
) -> float | None:
    entry = _close_after(series, event_date)
    if not entry:
        return None
    entry_date = entry[0]
    entry_row = next((r for r in series if r["date"] == entry_date), None)
    if not entry_row or not entry_row.get("volume"):
        return None
    baseline = _trailing_median_volume(series, entry_date)
    if not baseline or baseline <= 0:
        return None
    return float(entry_row["volume"]) / baseline


def score_events(
    events: Sequence[RawEvent],
    closes: dict[str, list[dict[str, Any]]],
    bench_closes: dict[str, list[dict[str, Any]]],
    bench_of: dict[str, str],
    end: date,
) -> tuple[list[dict[str, Any]], int]:
    """Attach excess curves / pre-drift / volume; return priced rows + skip count."""
    priced: list[dict[str, Any]] = []
    skipped = 0
    for ev in events:
        series = closes.get(ev.ticker)
        bseries = bench_closes.get(bench_of.get(ev.ticker, ""))
        if not series or not bseries:
            skipped += 1
            continue
        # Require at least t+1 priceable to count as usable.
        e1 = _excess_at_horizon(series, bseries, ev.event_date, 1, end)
        if e1 is None:
            skipped += 1
            continue
        row: dict[str, Any] = {
            "ticker": ev.ticker,
            "event_date": ev.event_date.isoformat(),
            "bucket": ev.bucket,
            "view_count": ev.view_count,
            "channel": ev.channel,
            "video_id": ev.video_id,
            "pre_drift": _pre_event_excess(series, bseries, ev.event_date),
            "abn_volume": _abnormal_volume(series, ev.event_date),
        }
        for h in HORIZONS:
            row[f"t+{h}"] = _excess_at_horizon(series, bseries, ev.event_date, h, end)
        priced.append(row)
    return priced, skipped


def _print_bucket_table(
    priced: Sequence[dict[str, Any]], key: str, label: str
) -> None:
    print(f"\n{label}")
    print(f"{'bucket':<8} {'n':>5} {'mean':>9} {'median':>9} {'hit':>8}")
    for bucket in ("low", "mid", "high"):
        vals = [
            float(r[key])
            for r in priced
            if r.get("bucket") == bucket and r.get(key) is not None
        ]
        s = _summarise(bucket, vals)
        if not s["n"]:
            print(f"{bucket:<8} {0:>5}")
            continue
        print(
            f"{bucket:<8} {s['n']:>5} {s['mean']:>+8.2f}% {s['median']:>+8.2f}% "
            f"{s['hit_rate']:>7.1%}"
        )
    low = [float(r[key]) for r in priced if r.get("bucket") == "low" and r.get(key) is not None]
    high = [float(r[key]) for r in priced if r.get("bucket") == "high" and r.get(key) is not None]
    if low and high:
        spread = statistics.mean(high) - statistics.mean(low)
        print(f"{'SPREAD':<8} {'':>5} {spread:>+8.2f}%  (high - low)")


def _day_bucketed_null(
    priced: Sequence[dict[str, Any]], key: str = "t+1"
) -> None:
    """Hold day's outcomes fixed; expected high-bucket hit rate under random labels."""
    per_day: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in priced:
        b = r.get("bucket")
        val = r.get(key)
        if b not in ("low", "high") or val is None:
            continue
        per_day[str(r["event_date"])].append((b, float(val)))

    exp_high_hits = 0.0
    n_high = 0
    for day_rows in per_day.values():
        total = len(day_rows)
        if not total:
            continue
        pos = sum(1 for _b, e in day_rows if e > 0)
        h = sum(1 for b, _e in day_rows if b == "high")
        exp_high_hits += h * pos / total
        n_high += h
    if not n_high:
        print("\nno-skill baseline: insufficient high/low co-occurrence by day")
        return
    high_vals = [
        float(r[key])
        for r in priced
        if r.get("bucket") == "high" and r.get(key) is not None
    ]
    if not high_vals:
        return
    actual = sum(1 for v in high_vals if v > 0) / len(high_vals)
    baseline = exp_high_hits / n_high
    print(
        f"\nno-skill baseline for high-view {key} hit rate: {baseline:.1%} "
        f"(actual {actual:.1%}, edge {actual - baseline:+.1%})"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="YouTube promotion event study (Phase K Stage 1). Zero captions."
    )
    parser.add_argument(
        "--per-channel",
        type=int,
        default=100,
        help="Videos to list per channel (default 100 - deep enough for high-view tail)",
    )
    parser.add_argument(
        "--channels",
        default=",".join(DEFAULT_CHANNELS),
        help="Comma-separated handles or UC… channel ids",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Override ticker specs (comma-separated TICKER:Alias:...). "
        "Empty with --universe curated = DEFAULT_TICKER_SPECS; "
        "ignored for --universe exchange.",
    )
    parser.add_argument(
        "--universe",
        choices=("exchange", "curated", "both"),
        default="both",
        help="Match universe: complete exchange directory (default both=compare "
        "attrition curated-42 vs exchange, price on exchange).",
    )
    parser.add_argument(
        "--issuer-cache",
        default="",
        help="Path to canadian_issuers JSON (default web_dashboard/data/.../issuers.json)",
    )
    parser.add_argument(
        "--meta-delay",
        type=float,
        default=META_DELAY_S,
        help="Seconds between metadata fetches (default 0.75)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    from benchmarks import resolve_benchmark
    from canadian_issuer_universe import load_issuer_targets
    from yt_discover_channels import TickerTarget

    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    curated_specs = (
        [s.strip() for s in args.tickers.split(",") if s.strip()]
        if args.tickers.strip()
        else list(DEFAULT_TICKER_SPECS)
    )
    curated_targets: list[Any] = [TickerTarget.parse(s) for s in curated_specs]

    exchange_targets: list[Any] = []
    issuer_meta: dict[str, Any] = {}
    if args.universe in ("exchange", "both"):
        cache_path = Path(args.issuer_cache) if args.issuer_cache else None
        if cache_path is None:
            exchange_targets, issuer_meta = load_issuer_targets()
        else:
            exchange_targets, issuer_meta = load_issuer_targets(cache_path)

    if args.universe == "curated":
        study_targets = curated_targets
        study_label = "curated-42"
    else:
        study_targets = exchange_targets
        study_label = "complete-exchange"

    print("=" * 66)
    print("YOUTUBE PROMOTION EVENT STUDY - Phase K Stage 1")
    print("entry = first close after publish date | view_count = IV")
    print("=" * 66)
    print(f"channels ({len(channels)}): {', '.join(channels)}")
    print(f"study universe: {study_label} ({len(study_targets)} targets)")
    if issuer_meta:
        print(
            f"issuer cache retrieved_at={issuer_meta.get('retrieved_at')} "
            f"count={issuer_meta.get('issuer_count')}"
        )

    print("\n[1] Listing channels (no captions)...")
    videos, listed = list_videos(channels, args.per_channel)
    print(f"  listed={listed} video rows={len(videos)}")

    # Side-by-side title attrition (same video set; no metadata yet).
    curated_cands, curated_title_attr = title_match_candidates(videos, curated_targets)
    curated_title_attr["listed"] = listed
    exch_cands, exch_title_attr = title_match_candidates(videos, study_targets)
    exch_title_attr["listed"] = listed

    print("\n[1b] TITLE ATTRITION — curated-42 vs study universe")
    print(
        format_attrition_row(
            "curated-42",
            {
                **curated_title_attr,
                "desc_demoted_multi": 0,
                "dates_resolved": 0,
                "after_dedupe": 0,
            },
        )
    )
    print(
        format_attrition_row(
            study_label,
            {
                **exch_title_attr,
                "desc_demoted_multi": 0,
                "dates_resolved": 0,
                "after_dedupe": 0,
            },
        )
    )
    delta_single = exch_title_attr["title_matched"] - curated_title_attr["title_matched"]
    print(
        f"  delta title_single (exchange - curated): {delta_single:+d} "
        f"of {listed} listed"
    )

    if args.universe == "both":
        # Full curated attrition for the comparison table (metadata shared via cache).
        print("\n[1c] Metadata + description re-match (curated-42 comparison arm)...")
        meta_cache: dict[str, Any] = {}
        try:
            _curated_events, curated_attr = resolve_event_dates(
                curated_cands,
                curated_targets,
                meta_delay_s=args.meta_delay,
                meta_cache=meta_cache,
            )
        except MetadataBlocked as exc:
            print(f"\nBLOCKER: {exc}")
            return 2
        curated_attr["listed"] = listed
        curated_attr["title_matched"] = curated_title_attr["title_matched"]
        curated_attr["title_multi"] = curated_title_attr["title_multi"]
        curated_attr["title_none"] = curated_title_attr["title_none"]
    else:
        meta_cache = {}
        curated_attr = curated_title_attr

    print(f"\n[1d] Metadata + description re-match (study={study_label})...")
    try:
        events, attrition = resolve_event_dates(
            exch_cands,
            study_targets,
            meta_delay_s=args.meta_delay,
            meta_cache=meta_cache,
        )
    except MetadataBlocked as exc:
        print(f"\nBLOCKER: {exc}")
        print("No results written. Resolve egress / quota before retrying.")
        return 2

    attrition["listed"] = listed
    attrition["title_matched"] = exch_title_attr["title_matched"]
    attrition["title_multi"] = exch_title_attr["title_multi"]
    attrition["title_none"] = exch_title_attr["title_none"]
    print(
        f"  dates_resolved={attrition['dates_resolved']} "
        f"dates_missing={attrition['dates_missing']} "
        f"desc_demoted_multi={attrition['desc_demoted_multi']} "
        f"after_dedupe={attrition['after_dedupe']}"
    )

    print("\n[ATTRITION TABLE]")
    if args.universe == "both":
        print(format_attrition_row("curated-42", curated_attr))
    print(format_attrition_row(study_label, attrition))

    if not events:
        print("\nNo dated single-ticker events after attrition. Nothing to price.")
        print(f"attrition: {attrition}")
        return 0

    bucket_counts: dict[str, int] = defaultdict(int)
    for ev in events:
        bucket_counts[ev.bucket or "unknown"] += 1
    print(
        "  view buckets after dedupe: "
        + ", ".join(f"{k}={v}" for k, v in sorted(bucket_counts.items(), key=str))
    )

    # Tradeability before any price download (§24 / §10).
    report_tradeability(events, study_targets)

    tickers = sorted({e.ticker for e in events})
    bench_of: dict[str, str] = {}
    for t in tickers:
        symbol, _fallback = resolve_benchmark(t)
        bench_of[t] = symbol

    dates = [e.event_date for e in events]
    start = min(dates) - timedelta(days=30)
    end = min(date.today(), max(dates) + timedelta(days=max(HORIZONS) + 10))

    print(f"\n[2] Downloading prices {start} .. {end}")
    closes = _download_ohlcv(tickers, start, end)
    bench_symbols = sorted(set(bench_of.values()))
    bench_closes = _download_ohlcv(bench_symbols, start, end)
    print(
        f"  prices for {len(closes)}/{len(tickers)} tickers, "
        f"{len(bench_closes)}/{len(bench_symbols)} benchmarks"
    )

    priced, skipped = score_events(events, closes, bench_closes, bench_of, end)
    print(f"  usable priced events: {len(priced)} ({skipped} unpriceable)")

    n = len(priced)
    print("\n" + "=" * 66)
    print(f"RESULTS - effective n={n} - {honesty_label(n)}")
    print("=" * 66)
    if args.universe == "both":
        print(format_attrition_row("curated-42", curated_attr))
    print(format_attrition_row(study_label, attrition, priced=n))

    if n == 0:
        print("\nNULL - no priceable events. Nothing to interpret.")
        return 0

    # Pre-event drift (selection confounder).
    pre_vals = [float(r["pre_drift"]) for r in priced if r.get("pre_drift") is not None]
    print("\nPRE-EVENT DRIFT (t-5 -> t-1 excess)")
    if pre_vals:
        s = _summarise("pre", pre_vals)
        print(
            f"  n={s['n']} mean={s['mean']:+.2f}% median={s['median']:+.2f}% "
            f"hit={s['hit_rate']:.1%}"
        )
        if s["mean"] > 2.0:
            print(
                "  WARNING: names are already running before the video. "
                "Post-event moves may be selection, not causation - "
                "this can invalidate the whole result."
            )
    else:
        print("  (no pre-event windows priceable)")

    # Excess return curve by bucket.
    for h in HORIZONS:
        _print_bucket_table(priced, f"t+{h}", f"EXCESS RETURN t+{h}d vs benchmark")

    print("\nABNORMAL VOLUME (entry / trailing 20-session median)")
    print(f"{'bucket':<8} {'n':>5} {'mean':>9} {'median':>9}")
    for bucket in ("low", "mid", "high"):
        vals = [
            float(r["abn_volume"])
            for r in priced
            if r.get("bucket") == bucket and r.get("abn_volume") is not None
        ]
        if not vals:
            print(f"{bucket:<8} {0:>5}")
            continue
        print(
            f"{bucket:<8} {len(vals):>5} {statistics.mean(vals):>8.2f}x "
            f"{statistics.median(vals):>8.2f}x"
        )
    low_v = [
        float(r["abn_volume"])
        for r in priced
        if r.get("bucket") == "low" and r.get("abn_volume") is not None
    ]
    high_v = [
        float(r["abn_volume"])
        for r in priced
        if r.get("bucket") == "high" and r.get("abn_volume") is not None
    ]
    if low_v and high_v:
        print(
            f"{'SPREAD':<8} {'':>5} "
            f"{statistics.mean(high_v) - statistics.mean(low_v):>+8.2f}x  (high - low)"
        )

    _day_bucketed_null(priced, "t+1")

    # Shape read across horizons for the high-view bucket (the claim's mechanism).
    print("\n" + "=" * 66)
    print("SHAPE READ (high-view bucket) - claim is spike-then-reverse")
    print("=" * 66)
    high_curve: list[tuple[int, float | None, int]] = []
    for h in HORIZONS:
        vals = [
            float(r[f"t+{h}"])
            for r in priced
            if r.get("bucket") == "high" and r.get(f"t+{h}") is not None
        ]
        mean = statistics.mean(vals) if vals else None
        high_curve.append((h, mean, len(vals)))
        if mean is None:
            print(f"  t+{h}: n=0")
        else:
            print(f"  t+{h}: n={len(vals)} mean={mean:+.2f}%")

    # Verdict - plain language, no threshold tuning.
    # Honesty for the *claim* is gated on the high-view bucket (§22), not overall n.
    high_t1 = [
        float(r["t+1"])
        for r in priced
        if r.get("bucket") == "high" and r.get("t+1") is not None
    ]
    low_t1 = [
        float(r["t+1"])
        for r in priced
        if r.get("bucket") == "low" and r.get("t+1") is not None
    ]
    mid_t1 = [
        float(r["t+1"])
        for r in priced
        if r.get("bucket") == "mid" and r.get("t+1") is not None
    ]
    print("\n" + "=" * 66)
    print(f"VERDICT - overall {honesty_label(n)}; high-view {honesty_label(len(high_t1))}")
    print("=" * 66)
    high_n = len(high_t1)
    if high_n < 5:
        print(
            f"High-view sample too small (n={high_n}). Record attrition; "
            "do not interpret the attention claim. "
            "Low/mid rows are UNTESTABLE for attention alpha, not a null."
        )
        if low_t1 or mid_t1:
            print(
                f"(sub-10k / mid-view rows present: low n={len(low_t1)}, "
                f"mid n={len(mid_t1)} — directional context only.)"
            )
    else:
        spread_t1 = (
            statistics.mean(high_t1) - statistics.mean(low_t1) if low_t1 else None
        )
        high_med = statistics.median(high_t1)
        means = [m for _h, m, _n in high_curve if m is not None]
        spike = statistics.mean(high_t1) > 1.0
        # Reverse: t+21 mean below t+1 mean (promotion wave ends).
        t1_m = next((m for h, m, _n in high_curve if h == 1), None)
        t21_m = next((m for h, m, _n in high_curve if h == 21), None)
        reverses = (
            t1_m is not None and t21_m is not None and t21_m < t1_m - 0.5
        )
        monotonic_up = (
            len(means) >= 3 and all(means[i] <= means[i + 1] for i in range(len(means) - 1))
        )
        if spread_t1 is not None:
            print(
                f"high-low t+1 spread: {spread_t1:+.2f}% "
                f"(high mean {statistics.mean(high_t1):+.2f}%, "
                f"high median {high_med:+.2f}%, high n={high_n})"
            )
        if high_n < 30:
            print(
                f"High-view n={high_n} is directional only — do not treat as confirmatory."
            )
        if spike and reverses and (spread_t1 is None or spread_t1 > 0):
            if high_med <= 0:
                print(
                    "Mean shape looks spike-then-reverse but high-view median t+1 "
                    f"is {high_med:+.2f}% (mean likely outlier-driven). "
                    "INCONCLUSIVE — inspect the event inventory."
                )
            else:
                print(
                    "Shape consistent with spike-then-reverse on the high-view tail. "
                    f"Treat as {honesty_label(high_n)} - do not auto-trade."
                )
        elif monotonic_up and spike:
            print(
                "Monotonic post-event drift (not spike-then-reverse). "
                "Falsifies the stated mechanism even if t+1 is positive."
            )
        elif not spike and (spread_t1 is None or abs(spread_t1) < 1.0):
            print(
                "NULL - no measurable high-view excess at t+1 relative to low-view, "
                "and no spike-then-reverse shape. "
                "The §19 attention-alpha claim is not supported in this sample."
            )
        else:
            print(
                "INCONCLUSIVE - numbers do not cleanly match spike-then-reverse "
                "nor a flat null. See tables above; do not tune thresholds."
            )

    print("\nEVENT INVENTORY (priced)")
    for r in sorted(priced, key=lambda x: (-(x.get("view_count") or 0), x["event_date"])):
        t1 = r.get("t+1")
        t1_s = f"{t1:+.2f}%" if t1 is not None else "n/a"
        print(
            f"  {r['event_date']} {r['ticker']:<12} "
            f"views={str(r.get('view_count') or '?'):>8} "
            f"bucket={str(r.get('bucket') or '?'):<4} "
            f"ch={r['channel']:<24} t+1={t1_s}  {r['video_id']}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
