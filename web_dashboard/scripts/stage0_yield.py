"""Stage 0 — extraction yield measurement for Phase K.

Answers the question in PHASE_K_SOURCE_LIST.md §7: *what fraction of a channel's
videos produce a ticker-specific, falsifiable, material claim?* A source whose
yield is near zero costs more than it returns no matter how accurate the rest is,
so this is the cheapest way to kill weak sources before building the K3 job.

No price data, no market exposure, no DB writes. Captions are cached on disk, so
re-runs and prompt iteration are free after the first pass.

Usage:
  python web_dashboard/scripts/stage0_yield.py --dry-run          # plumbing only, no LLM
  python web_dashboard/scripts/stage0_yield.py --limit 10         # 10 videos/source
  python web_dashboard/scripts/stage0_yield.py --sources GamersNexus,MunroLive
  python web_dashboard/scripts/stage0_yield.py --limit 25 --out results.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

sys.path.append(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV) if _ENV.exists() else load_dotenv()

from youtube_captions import (  # noqa: E402
    CaptionFetchError,
    caption_proxy_url,
    fetch_caption_text,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("stage0")

DEFAULT_CACHE = Path(__file__).resolve().parent / ".stage0_cache"

# Sources verified in PHASE_K_SOURCE_LIST.md §5 (tech) and §12 (automotive).
# channel_id is authoritative; handle is for display only.
SOURCES: list[dict[str, Any]] = [
    # --- tech / semiconductor ---
    {"label": "GamersNexus", "channel_id": "UChIs72whgZI9w6d6FhwGGHA", "sector": "tech", "max_duration_s": 3600},
    {"label": "MooresLawIsDead", "channel_id": "UCRPdsCVuH53rcbTcEkuY4uQ", "sector": "tech", "max_duration_s": 9000},
    {"label": "HardwareUnboxed", "channel_id": "UCI8iQa1hv7oV_Z8D35vVuSg", "sector": "tech", "max_duration_s": 3600},
    {"label": "Buildzoid", "channel_id": "UCrwObTfqv8u1KO7Fgk-FXHQ", "sector": "tech", "max_duration_s": 3600},
    {"label": "HighYield", "channel_id": "UCmMwHbw2j8LfvTKVh3O7Vdw", "sector": "tech", "max_duration_s": 3600},
    {"label": "Geekerwan", "channel_id": "UCeUJO1H3TEXu2syfAAPjYKQ", "sector": "tech", "max_duration_s": 3600},
    {"label": "Asianometry", "channel_id": "UC1LpsuAUaKoMzzJSEt5WImw", "sector": "tech", "max_duration_s": 3600},
    {"label": "TechTechPotato", "channel_id": "UC1r0DG-KEPyqOeW6o79PByw", "sector": "tech", "max_duration_s": 3600},
    {"label": "ServeTheHome", "channel_id": "UCv6J_jJa8GJqFwQNgNrMuww", "sector": "tech", "max_duration_s": 3600},
    {"label": "Level1Techs", "channel_id": "UC4w1YQAJMWOz4qtxinq55LQ", "sector": "tech", "max_duration_s": 3600},
    {"label": "TheSignalPath", "channel_id": "UCKxRARSpahF1Mt-2vbPug-g", "sector": "tech", "max_duration_s": 5400},
    {"label": "der8auerEN", "channel_id": "UCGsaijjOJshS2_ZmMNZgS-g", "sector": "tech", "max_duration_s": 3600},
    # --- automotive (tier 1) ---
    {"label": "MunroLive", "channel_id": "UCj--iMtToRO_cGG_fpmP5XQ", "sector": "auto", "max_duration_s": 3600},
    {"label": "WeberAuto", "channel_id": "UCtr07mdKhsUwVJjL8Kw_q5A", "sector": "auto", "max_duration_s": 5400},
    {"label": "OutOfSpec", "channel_id": "UCVRZKu68-4tQIk7_3CJ_wKA", "sector": "auto", "max_duration_s": 3600},
]

MIN_DURATION_S = 120  # drop Shorts

CATEGORIES = (
    "PRICING", "DEFECT_RECALL", "SUPPLY_CHAIN", "COMPETITIVE",
    "MA_LEGAL", "PRODUCT_LAUNCH", "DEMAND", "OTHER",
)

EXTRACTION_PROMPT = """You are analysing a transcript from a technical YouTube channel to find claims that could matter to a public company's stock.

Return STRICT JSON only, no prose, matching this schema:
{{
  "claims": [
    {{
      "ticker": "NVDA",
      "company": "Nvidia",
      "category": "one of: {categories}",
      "claim": "one sentence, specific and falsifiable",
      "materiality": "HIGH|MEDIUM|LOW",
      "revenue_share": "MAJORITY|SIGNIFICANT|MINOR|UNKNOWN",
      "novel": true,
      "quote": "short supporting quote from the transcript"
    }}
  ],
  "derived_content": false,
  "derived_evidence": "phrase showing it is repeating others' reporting, or empty"
}}

Rules — follow exactly:
- ONLY include a claim if it names a specific, publicly traded company. No claim about a private company (SpaceX, Valve, Ampere) or an unlisted brand.
- `materiality` is about the affected product's share of THAT company's revenue, not how dramatic the claim sounds. A defect in a minor product line of a huge company is LOW. Set `revenue_share` accordingly.
- `novel` = true only if this appears to be the channel's own measurement, teardown, testing or sourcing. If they are reporting someone else's news, it is false.
- Set `derived_content` true if the transcript mostly repeats other outlets' reporting ("according to an article by", "a report from", "if we look at this tweet").
- If there are no qualifying claims, return {{"claims": [], "derived_content": false, "derived_evidence": ""}}.
- Be strict. An empty list is a correct and useful answer. Do not invent tickers.

TRANSCRIPT (channel: {channel}, title: {title}):
{transcript}
"""

# §8 cheap derived-content heuristic, run alongside the LLM for comparison.
_ATTRIB_RE = re.compile(
    r"according to (an? )?(article|report|post|tweet|story)|"
    r"a (report|story|article) (from|by)|as reported by|"
    r"if we look at this tweet|sources say|rumor has it",
    re.I,
)
_TECH_RE = re.compile(
    r"\bdie size\b|\bcache\b|\bvrm\b|\byield\b|\bnode\b|\btdp\b|\bwafer\b|\blithograph|"
    r"\bthermal\b|\bvoltage\b|\bbenchmark\b|\btorque\b|\bkwh\b|\bbill of materials\b|\bbom\b",
    re.I,
)
_OPINION_RE = re.compile(
    r"\bcrazy\b|\binsane\b|\bdestroy(s|ed)?\b|\bfinished\b|\bmassive\b|\bshocking\b|\bunbelievable\b",
    re.I,
)


@dataclass
class VideoResult:
    video_id: str
    title: str
    duration_s: int | None
    chars: int = 0
    truncated: bool = False
    claims: list[dict] = field(default_factory=list)
    derived_llm: bool = False
    derived_heuristic: bool = False
    tech_density: float = 0.0
    error: str | None = None

    @property
    def qualifying(self) -> list[dict]:
        """Claims that count toward yield: named ticker, not LOW materiality."""
        out = []
        for c in self.claims:
            if not isinstance(c, dict):
                continue
            ticker = str(c.get("ticker") or "").strip().upper()
            if not ticker or ticker in {"N/A", "NONE", "UNKNOWN"}:
                continue
            if str(c.get("materiality") or "").upper() == "LOW":
                continue
            out.append(c)
        return out


def list_videos(channel_id: str, limit: int, max_duration_s: int | None) -> list[dict]:
    """Recent uploads from the /videos tab, excluding Shorts and over-long items.

    The /videos tab is used deliberately: the channel root mixes in multi-hour
    live streams (PHASE_K_SOURCE_LIST.md §4).
    """
    import yt_dlp

    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    opts = {
        "quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
        "playlistend": limit * 3, "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    out: list[dict] = []
    for e in (info.get("entries") or []):
        if not e:
            continue
        dur = e.get("duration")
        if dur is not None:
            if dur < MIN_DURATION_S:
                continue
            if max_duration_s and dur > max_duration_s:
                continue
        if e.get("live_status") in {"is_live", "is_upcoming"}:
            continue
        out.append({"id": e["id"], "title": e.get("title") or "", "duration": dur})
        if len(out) >= limit:
            break
    return out


def cached_caption(video_id: str, cache_dir: Path, use_cache: bool) -> str | None:
    if not use_cache:
        return None
    p = cache_dir / f"{video_id}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


def store_caption(video_id: str, text: str, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{video_id}.txt").write_text(text, encoding="utf-8")


def heuristic_scores(text: str) -> tuple[bool, float]:
    """§8 derived-content heuristic. Returns (looks_derived, tech_density)."""
    words = max(len(text.split()), 1)
    tech = len(_TECH_RE.findall(text))
    opinion = len(_OPINION_RE.findall(text))
    attrib = len(_ATTRIB_RE.findall(text))
    density = 1000.0 * tech / words
    derived = attrib >= 3 or (opinion > tech and attrib >= 1)
    return derived, round(density, 2)


def parse_json_response(raw: str) -> dict:
    """Ollama sometimes wraps JSON in prose or fences despite json_mode."""
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def analyse(ollama, channel: str, title: str, text: str, max_chars: int) -> tuple[dict, bool]:
    truncated = len(text) > max_chars
    prompt = EXTRACTION_PROMPT.format(
        categories="|".join(CATEGORIES),
        channel=channel,
        title=title,
        transcript=text[:max_chars],
    )
    raw = ollama.generate_completion(prompt, json_mode=True, temperature=0.0)
    return parse_json_response(raw or ""), truncated


class BlockedError(RuntimeError):
    """YouTube is rate-limiting this IP; continuing only deepens the block."""


class Throttle:
    """Global pacing + backoff for caption fetches.

    YouTube rate-limits the timedtext endpoint per IP, and the yt-dlp fallback
    shares that IP, so it provides no redundancy here (see §13 of
    docs/PHASE_K_SOURCE_LIST.md). Fetching politely is the only free mitigation.
    """

    def __init__(self, delay: float, max_consecutive_blocks: int) -> None:
        self.delay = delay
        self.max_consecutive = max_consecutive_blocks
        self.consecutive = 0
        self._last = 0.0

    def wait(self) -> None:
        gap = time.time() - self._last
        # Back off exponentially while blocks are accumulating.
        want = self.delay * (2 ** self.consecutive) if self.consecutive else self.delay
        want = min(want, 120.0)
        if gap < want:
            time.sleep(want - gap)
        self._last = time.time()

    def record(self, blocked: bool) -> None:
        if blocked:
            self.consecutive += 1
            if self.consecutive >= self.max_consecutive:
                raise BlockedError(
                    f"{self.consecutive} consecutive blocked fetches — aborting. "
                    "The IP is rate-limited; wait (hours) or route through a proxy."
                )
        else:
            self.consecutive = 0


def process_source(
    src: dict, args: argparse.Namespace, ollama, cache_dir: Path, throttle: Throttle
) -> list[VideoResult]:
    results: list[VideoResult] = []
    try:
        videos = list_videos(src["channel_id"], args.limit, src.get("max_duration_s"))
    except Exception as exc:  # noqa: BLE001
        print(f"  !! {src['label']}: listing failed: {str(exc)[:80]}")
        return results

    for v in videos:
        r = VideoResult(video_id=v["id"], title=v["title"], duration_s=v.get("duration"))
        text = cached_caption(v["id"], cache_dir, not args.no_cache)
        if text is None:
            throttle.wait()
            try:
                cap = fetch_caption_text(v["id"], include_metadata=False)
                text = cap.text
                store_caption(v["id"], text, cache_dir)
                throttle.record(blocked=False)
            except CaptionFetchError as exc:
                r.error = exc.reason
                results.append(r)
                print(f"  -- {v['id']} caption {exc.reason}")
                throttle.record(blocked=(exc.reason == "blocked"))
                continue
            except Exception as exc:  # noqa: BLE001
                r.error = "unexpected"
                results.append(r)
                print(f"  -- {v['id']} {type(exc).__name__}")
                continue

        r.chars = len(text)
        r.derived_heuristic, r.tech_density = heuristic_scores(text)

        if not args.dry_run:
            try:
                data, r.truncated = analyse(
                    ollama, src["label"], v["title"], text, args.max_chars
                )
                claims = data.get("claims")
                r.claims = claims if isinstance(claims, list) else []
                r.derived_llm = bool(data.get("derived_content"))
            except Exception as exc:  # noqa: BLE001
                r.error = f"llm:{type(exc).__name__}"

        n = len(r.qualifying)
        flag = "*" if n else " "
        print(f"  {flag} {v['id']}  {r.chars:>7}c  claims={n}  {v['title'][:52]}")
        results.append(r)
    return results


def report(all_results: dict[str, list[VideoResult]], sources: list[dict], dry: bool) -> dict:
    by_label = {s["label"]: s for s in sources}
    print("\n" + "=" * 82)
    print("STAGE 0 — EXTRACTION YIELD")
    print("=" * 82)
    header = f"{'source':<18}{'sec':<6}{'vids':>5}{'capt':>6}{'yield':>8}{'clms':>6}{'med_kc':>8}{'techd':>7}"
    print(header)
    print("-" * len(header))

    summary: dict[str, Any] = {"sources": {}, "dry_run": dry}
    ticker_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}

    for label, rows in all_results.items():
        ok = [r for r in rows if r.error is None]
        hit = [r for r in ok if r.qualifying]
        claims = sum(len(r.qualifying) for r in ok)
        chars = sorted(r.chars for r in ok) or [0]
        med_kc = chars[len(chars) // 2] / 1000
        dens = sorted(r.tech_density for r in ok) or [0]
        med_d = dens[len(dens) // 2]
        y = (100.0 * len(hit) / len(ok)) if ok else 0.0
        print(f"{label:<18}{by_label[label]['sector']:<6}{len(rows):>5}{len(ok):>6}"
              f"{y:>7.0f}%{claims:>6}{med_kc:>8.1f}{med_d:>7.1f}")
        summary["sources"][label] = {
            "sector": by_label[label]["sector"],
            "videos": len(rows), "captions_ok": len(ok),
            "videos_with_claims": len(hit), "yield_pct": round(y, 1),
            "qualifying_claims": claims,
            "median_kchars": round(med_kc, 1),
            "median_tech_density": med_d,
            "caption_errors": [r.error for r in rows if r.error],
        }
        for r in ok:
            for c in r.qualifying:
                t = str(c.get("ticker", "")).upper()
                ticker_counts[t] = ticker_counts.get(t, 0) + 1
                cat = str(c.get("category", "OTHER")).upper()
                category_counts[cat] = category_counts.get(cat, 0) + 1

    if not dry:
        print("\ntop tickers:", dict(sorted(ticker_counts.items(), key=lambda kv: -kv[1])[:12]))
        print("categories :", dict(sorted(category_counts.items(), key=lambda kv: -kv[1])))
        for sector in ("tech", "auto"):
            rows = [v for k, v in summary["sources"].items() if v["sector"] == sector]
            if rows:
                ok = sum(r["captions_ok"] for r in rows)
                hit = sum(r["videos_with_claims"] for r in rows)
                print(f"\n{sector.upper()} overall yield: {100*hit/ok if ok else 0:.0f}% "
                      f"({hit}/{ok} videos)")
    summary["tickers"] = ticker_counts
    summary["categories"] = category_counts
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase K Stage 0 extraction-yield harness")
    ap.add_argument("--limit", type=int, default=10, help="videos per source (default 10)")
    ap.add_argument("--sources", help="comma-separated labels; default all")
    ap.add_argument("--sector", choices=["tech", "auto"], help="restrict to one sector")
    ap.add_argument("--dry-run", action="store_true", help="fetch captions only, no LLM")
    ap.add_argument("--no-cache", action="store_true", help="ignore the caption cache")
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--max-chars", type=int, default=48000,
                    help="transcript chars sent to the LLM (default 48000)")
    ap.add_argument("--delay", type=float, default=20.0,
                    help="seconds between live caption fetches (default 20). "
                         "YouTube IP-blocks aggressive batching; cached videos are free.")
    ap.add_argument("--max-blocks", type=int, default=5,
                    help="abort after this many consecutive blocked fetches (default 5)")
    ap.add_argument("--out", type=Path, help="write JSON summary here")
    args = ap.parse_args()

    sources = SOURCES
    if args.sector:
        sources = [s for s in sources if s["sector"] == args.sector]
    if args.sources:
        want = {x.strip().lower() for x in args.sources.split(",")}
        sources = [s for s in sources if s["label"].lower() in want]
    if not sources:
        print("No sources matched.")
        sys.exit(1)

    ollama = None
    if not args.dry_run:
        from ollama_client import get_ollama_client

        ollama = get_ollama_client()
        if ollama is None:
            print("Ollama client unavailable — run with --dry-run to test plumbing.")
            sys.exit(1)

    print(f"Stage 0: {len(sources)} sources x {args.limit} videos "
          f"({'DRY RUN, no LLM' if args.dry_run else 'with extraction'})")
    print(f"caption cache: {args.cache_dir}")
    proxy = caption_proxy_url()
    print(f"egress: {proxy or 'DIRECT (rate-limit risk — see §13)'}  delay={args.delay}s\n")

    all_results: dict[str, list[VideoResult]] = {}
    throttle = Throttle(args.delay, args.max_blocks)
    t0 = time.time()
    aborted = None
    for s in sources:
        print(f"[{s['label']}] ({s['sector']})")
        try:
            all_results[s["label"]] = process_source(
                s, args, ollama, args.cache_dir, throttle
            )
        except BlockedError as exc:
            aborted = str(exc)
            print(f"\n!! {exc}")
            break

    summary = report(all_results, sources[: len(all_results)], args.dry_run)
    if aborted:
        summary["aborted"] = aborted
        print("\nPARTIAL RUN — yields above are not comparable across sources.")
    summary["elapsed_s"] = round(time.time() - t0, 1)
    summary["limit"] = args.limit
    print(f"\nelapsed {summary['elapsed_s']}s")

    if args.out:
        args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
