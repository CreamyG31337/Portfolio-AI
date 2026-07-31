#!/usr/bin/env python3
"""Complete Canadian equity issuer universe for Phase K promotion matching.

WHY THIS EXISTS
---------------
``yt_promotion_event_study.py`` originally matched titles against a hand-curated
42-company list built from established producers and our holdings. Paid
promotion concentrates on pre-revenue story juniors that list was built to
exclude (§24). Matching against every TSX / TSXV / CSE issuer avoids that
sample-frame bias without selecting the universe from high-view titles
(outcome selection).

Sources (public exchange directories, no API key):
  - TSX / TSXV: ``https://www.tsx.com/json/company-directory/search/{tsx|tsxv}/^*``
  - CSE: daily market summary text under ``market-reports.thecse.com``
    (the Excel "Stock List" on listings.thecse.com is currently an empty stub)

The downloaded list is cached under ``web_dashboard/data/canadian_issuers/``
with ``retrieved_at`` so a study run is reproducible from the committed file.

Usage::

    python web_dashboard/scripts/canadian_issuer_universe.py --refresh
    python web_dashboard/scripts/canadian_issuer_universe.py --stats
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
_DEFAULT_CACHE_DIR = _WEB_DASHBOARD / "data" / "canadian_issuers"
_DEFAULT_CACHE_PATH = _DEFAULT_CACHE_DIR / "issuers.json"

TSX_DIRECTORY_URL = "https://www.tsx.com/json/company-directory/search/{exchange}/%5E*"
CSE_SUMMARY_URL = (
    "https://market-reports.thecse.com/CSEListed/Daily/Summary/"
    "CSEListed.Daily.Market.Summary.{day}.txt"
)

_UA = {"User-Agent": "LLM-Micro-Cap-research/1.0 (issuer-universe; read-only)"}

# Yahoo / yfinance suffixes for Canadian listings.
_EXCHANGE_YF_SUFFIX = {"TSX": ".TO", "TSXV": ".V", "CSE": ".CN"}

# Legal-form suffixes stripped to build a matchable company alias.
# Require a separator before the suffix so "Cameco" is not peeled to "Came"
# by the `co` alternative.
_LEGAL_SUFFIX_RE = re.compile(
    r"""
    [\s,]+
    (
        incorporated | inc\.? |
        corporation | corp\.? |
        company | co\.? |
        limited | ltd\.? |
        unlimited\s+liability\s+corporation | ulc |
        llc | l\.l\.c\.? |
        l\.?p\.? | limited\s+partnership |
        plc | n\.?v\.? | s\.?a\.? |
        gmbh | ag | pty | plc
    )
    \.?$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Optional trailing sector/legal wrappers — generate a shorter alias when safe.
_TRAILING_SECTOR_RE = re.compile(
    r"""
    [\s,]+
    (
        resources? | mining | minerals? | exploration |
        energy | energies | oil\s*&\s*gas | oil\s+and\s+gas |
        gold | silver | copper | uranium | lithium | metals? |
        holdings? | ventures? | capital | group | partners?
    )
    \.?$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Exact-match alias rejects — sector/macro words that would match pundit titles.
_ALIAS_STOPWORDS = frozenset(
    {
        "GOLD",
        "SILVER",
        "COPPER",
        "URANIUM",
        "LITHIUM",
        "NICKEL",
        "ENERGY",
        "MINING",
        "MINERALS",
        "RESOURCES",
        "METALS",
        "OIL",
        "GAS",
        "POWER",
        "TECH",
        "TECHNOLOGY",
        "CAPITAL",
        "VENTURES",
        "HOLDINGS",
        "GROUP",
        "TRUST",
        "FUND",
        "BANK",
        "REAL",
        "ESTATE",
        "HEALTH",
        "LIFE",
        "WORLD",
        "GLOBAL",
        "NORTH",
        "SOUTH",
        "EAST",
        "WEST",
        "FIRST",
        "NEXT",
        "BEST",
        "CANADA",
        "CANADIAN",
        "AMERICAN",
        "ROYALTY",
        "INCOME",
        "GROWTH",
        "VALUE",
        "NEW",
        "OLD",
        "ONE",
        "TWO",
        "THE",
        "AND",
        "FOR",
        "INC",
        "CORP",
        "LTD",
        "CO",
        "COMPANY",
        # Single-token names that are ordinary English / promo-title vocabulary.
        "DISCOVERY",
        "DECADE",
        "RISE",
        "WELL",
        "SHOW",
        "NEWS",
        "LONG",
        "MINE",
        "PLAN",
        "DEAL",
        "BEAR",
        "PATH",
        "LEAD",
        "LINE",
        "FOOD",
        "RATE",
        "WAVE",
        "ROCK",
        "CODE",
        "DOSE",
        "SURE",
        "ASIA",
        "ARMY",
        "MASSIVE",
        "STRIKE",
        "BLOCK",
        "BUILDING",
    }
)

# Prefer ordinary shares; skip these instrument suffixes when seen on symbols.
# (Applied in is_equity_issuer via regex — listed here for documentation.)
# .WT/.WS warrants, .RT rights, .DB debentures, .PR/.PF preferreds.

_ETF_NAME_RE = re.compile(
    r"\b(ETF|ETN|Exchange\s+Traded|Index\s+Fund|Enhanced\s+High\s+Income|"
    r"2X|3X|Inverse|Covered\s+Call)\b",
    re.IGNORECASE,
)

_MIN_ALIAS_LEN = 4
# Single-token sector peels shorter than this are dropped ("Discovery Mining"→"Discovery"
# would match every discovery headline).
_MIN_PEEL_SINGLE_TOKEN_LEN = 10


@dataclass(frozen=True)
class IssuerRecord:
    """One equity issuer from an exchange directory."""

    symbol: str  # yfinance-style, e.g. CCO.TO / MMA.V / PHOS.CN
    exchange: str  # TSX | TSXV | CSE
    name: str
    aliases: tuple[str, ...]
    raw_symbol: str  # exchange-native symbol without YF suffix


@dataclass(frozen=True)
class IssuerTarget:
    """Match target with the same ``.ticker`` / ``.matches`` surface as TickerTarget."""

    ticker: str
    exchange: str
    name: str
    patterns: tuple[Any, ...]

    def matches(self, text: str) -> bool:
        return any(rx.search(text) for rx in self.patterns)


def _http_get(url: str, timeout: float = 120.0, retries: int = 3) -> bytes:
    last_err: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=_UA)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - network retries
            last_err = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last_err})")


def strip_legal_suffixes(name: str) -> str:
    """Remove trailing Inc/Corp/Ltd/… once or twice (Corp. Ltd. chains)."""
    text = (name or "").strip()
    for _ in range(3):
        nxt = _LEGAL_SUFFIX_RE.sub("", text).rstrip(" ,.-")
        if nxt == text:
            break
        text = nxt
    return text.strip()


def alias_candidates(name: str) -> list[str]:
    """Build matchable aliases from an issuer legal name."""
    primary = strip_legal_suffixes(name)
    out: list[str] = []
    seen: set[str] = set()

    def add(alias: str, *, peeled: bool = False) -> None:
        cleaned = re.sub(r"\s+", " ", (alias or "").strip(" ,.-"))
        if len(cleaned) < _MIN_ALIAS_LEN:
            return
        if peeled and " " not in cleaned and len(cleaned) < _MIN_PEEL_SINGLE_TOKEN_LEN:
            # Drop "Discovery Mining" → "Discovery" style peels.
            return
        key = cleaned.casefold()
        if key in seen:
            return
        if cleaned.upper() in _ALIAS_STOPWORDS:
            return
        seen.add(key)
        out.append(cleaned)

    add(primary, peeled=False)
    # One optional sector-word peel (Midnight Sun Mining -> Midnight Sun).
    peeled = _TRAILING_SECTOR_RE.sub("", primary).rstrip(" ,.-")
    if peeled and peeled.casefold() != primary.casefold():
        add(peeled, peeled=True)
    return out


def is_equity_issuer(name: str, raw_symbol: str) -> bool:
    """Drop ETFs / structured products / warrants from the match universe."""
    sym = (raw_symbol or "").upper()
    # Warrants / rights / debentures (FOO.WT, FOO.WT.A, FOO.DB.A).
    if re.search(r"\.(WT|WS|W|RT|RS|DB)(\.|$)", sym):
        return False
    # Preferred shares: FOO.PR.A
    if re.search(r"\.(PR|PF)(\.|$)", sym):
        return False
    if _ETF_NAME_RE.search(name or ""):
        return False
    # Unit / bond trusts on the TMX directory (keep mining cos named *.UN rarely).
    if sym.endswith(".UN") and re.search(r"\b(Trust|Fund)\b", name or "", re.I):
        return False
    return True


def yfinance_symbol(raw_symbol: str, exchange: str) -> str:
    """Map exchange-native symbol to yfinance ticker."""
    raw = (raw_symbol or "").strip().upper()
    if not raw:
        raise ValueError("empty symbol")
    # Already suffixed (rare).
    if raw.endswith((".TO", ".V", ".CN", ".NE")):
        return raw
    suffix = _EXCHANGE_YF_SUFFIX[exchange]
    # yfinance uses hyphens for class shares: TECK.B -> TECK-B.TO
    base = raw.replace(".", "-")
    return f"{base}{suffix}"


def _compile_patterns(raw_symbol: str, aliases: Sequence[str]) -> tuple[Any, ...]:
    """Company-name aliases + cashtag only.

    Bare ticker symbols are *not* matched as words: too many Canadian listings use
    English-word tickers (MINE, PLAN, NEWS, LONG, RISE) that light up every
    video description. Cashtags ($PHOS) stay unambiguous.
    """
    patterns: list[Any] = []
    base = raw_symbol.split(".")[0].split("-")[0].upper()
    if len(base) >= 2:
        patterns.append(
            re.compile(rf"(?<![A-Za-z0-9])\${re.escape(base)}(?![A-Za-z0-9])", re.IGNORECASE)
        )
    for alias in aliases:
        patterns.append(
            re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
        )
    return tuple(patterns)


def parse_tsx_directory_payload(
    payload: dict[str, Any], *, exchange: str
) -> list[IssuerRecord]:
    """Parse TMX company-directory JSON into issuer records."""
    results = payload.get("results") or []
    out: list[IssuerRecord] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        raw_symbol = str(row.get("symbol") or "").strip().upper()
        name = str(row.get("name") or "").strip()
        if not raw_symbol or not name:
            continue
        if not is_equity_issuer(name, raw_symbol):
            continue
        aliases = tuple(alias_candidates(name))
        out.append(
            IssuerRecord(
                symbol=yfinance_symbol(raw_symbol, exchange),
                exchange=exchange,
                name=name,
                aliases=aliases,
                raw_symbol=raw_symbol,
            )
        )
    return out


def parse_cse_daily_summary(text: str, *, as_of: date) -> list[IssuerRecord]:
    """Parse CSE daily market summary (tab-separated Stock / Symbol / …)."""
    out: list[IssuerRecord] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if "\t" not in line:
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2:
            continue
        name, raw_symbol = parts[0], parts[1].upper()
        if not name or not raw_symbol:
            continue
        if raw_symbol == "SYMBOL" or name.upper() == "STOCK":
            continue
        if raw_symbol in seen:
            continue
        if not is_equity_issuer(name, raw_symbol):
            continue
        aliases = tuple(alias_candidates(name))
        seen.add(raw_symbol)
        out.append(
            IssuerRecord(
                symbol=yfinance_symbol(raw_symbol, "CSE"),
                exchange="CSE",
                name=name,
                aliases=aliases,
                raw_symbol=raw_symbol,
            )
        )
    if not out:
        raise ValueError(f"CSE summary for {as_of.isoformat()} parsed zero issuers")
    return out


def fetch_tsx_exchange(exchange: str) -> tuple[list[IssuerRecord], dict[str, Any]]:
    """Download one TMX directory (tsx or tsxv)."""
    key = exchange.lower()
    if key not in ("tsx", "tsxv"):
        raise ValueError(f"unsupported TMX exchange: {exchange}")
    url = TSX_DIRECTORY_URL.format(exchange=key)
    raw = _http_get(url)
    payload = json.loads(raw.decode("utf-8"))
    label = "TSX" if key == "tsx" else "TSXV"
    records = parse_tsx_directory_payload(payload, exchange=label)
    meta = {
        "url": url,
        "count": len(records),
        "directory_length": payload.get("length"),
        "last_updated": payload.get("last_updated"),
    }
    return records, meta


def fetch_cse_summary(*, as_of: Optional[date] = None) -> tuple[list[IssuerRecord], dict[str, Any]]:
    """Download the most recent CSE daily summary (walk back up to 10 calendar days)."""
    start = as_of or date.today()
    last_err: Exception | None = None
    for i in range(0, 12):
        day = start - timedelta(days=i)
        # Skip weekends lightly; summaries still exist for some holidays — try all.
        url = CSE_SUMMARY_URL.format(day=day.isoformat())
        try:
            raw = _http_get(url)
        except urllib.error.HTTPError as exc:
            last_err = exc
            continue
        except Exception as exc:  # noqa: BLE001 - network surface
            last_err = exc
            continue
        text = raw.decode("utf-8", errors="replace")
        records = parse_cse_daily_summary(text, as_of=day)
        meta = {"url": url, "count": len(records), "as_of": day.isoformat()}
        return records, meta
    raise RuntimeError(f"Could not fetch CSE daily summary near {start}: {last_err}")


def _dedupe_prefer_senior(records: Iterable[IssuerRecord]) -> list[IssuerRecord]:
    """One record per match alias collision on raw base symbol; prefer TSX > TSXV > CSE."""
    rank = {"TSX": 0, "TSXV": 1, "CSE": 2}
    by_raw: dict[str, IssuerRecord] = {}
    for rec in records:
        key = rec.raw_symbol.upper()
        prev = by_raw.get(key)
        if prev is None or rank.get(rec.exchange, 9) < rank.get(prev.exchange, 9):
            by_raw[key] = rec
    return sorted(by_raw.values(), key=lambda r: (r.exchange, r.symbol))


def build_universe_payload(
    *,
    retrieved_at: Optional[date] = None,
    tsx_records: Optional[list[IssuerRecord]] = None,
    tsxv_records: Optional[list[IssuerRecord]] = None,
    cse_records: Optional[list[IssuerRecord]] = None,
    source_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble the on-disk JSON document (testable without network)."""
    day = retrieved_at or date.today()
    merged = _dedupe_prefer_senior(
        list(tsx_records or []) + list(tsxv_records or []) + list(cse_records or [])
    )
    return {
        "retrieved_at": day.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": source_meta or {},
        "issuer_count": len(merged),
        "issuers": [
            {
                "symbol": r.symbol,
                "exchange": r.exchange,
                "name": r.name,
                "aliases": list(r.aliases),
                "raw_symbol": r.raw_symbol,
            }
            for r in merged
        ],
    }


def download_universe(*, as_of: Optional[date] = None) -> dict[str, Any]:
    """Hit public exchange directories and return a cacheable payload."""
    print("Downloading TSX directory...", flush=True)
    tsx, tsx_meta = fetch_tsx_exchange("tsx")
    print(f"  TSX equities: {len(tsx)}", flush=True)
    print("Downloading TSXV directory...", flush=True)
    tsxv, tsxv_meta = fetch_tsx_exchange("tsxv")
    print(f"  TSXV equities: {len(tsxv)}", flush=True)
    print("Downloading CSE daily summary...", flush=True)
    cse, cse_meta = fetch_cse_summary(as_of=as_of)
    print(f"  CSE equities: {len(cse)} (as_of {cse_meta.get('as_of')})", flush=True)
    return build_universe_payload(
        retrieved_at=as_of or date.today(),
        tsx_records=tsx,
        tsxv_records=tsxv,
        cse_records=cse,
        source_meta={"TSX": tsx_meta, "TSXV": tsxv_meta, "CSE": cse_meta},
    )


def rebuild_aliases_in_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Recompute aliases from stored legal names (no network)."""
    issuers = []
    for row in payload.get("issuers") or []:
        name = str(row.get("name") or "")
        updated = dict(row)
        updated["aliases"] = alias_candidates(name)
        issuers.append(updated)
    out = dict(payload)
    out["issuers"] = issuers
    out["issuer_count"] = len(issuers)
    return out


def save_universe(payload: dict[str, Any], path: Path = _DEFAULT_CACHE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Also write a dated copy for provenance beside the canonical file.
    retrieved = str(payload.get("retrieved_at") or date.today().isoformat())
    dated = path.with_name(f"issuers_{retrieved}.json")
    if dated != path:
        dated.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def load_universe(path: Path = _DEFAULT_CACHE_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Issuer cache missing: {path}. Run with --refresh to download."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def records_from_payload(payload: dict[str, Any]) -> list[IssuerRecord]:
    out: list[IssuerRecord] = []
    for row in payload.get("issuers") or []:
        out.append(
            IssuerRecord(
                symbol=str(row["symbol"]),
                exchange=str(row["exchange"]),
                name=str(row["name"]),
                aliases=tuple(row.get("aliases") or ()),
                raw_symbol=str(row.get("raw_symbol") or row["symbol"]),
            )
        )
    return out


def targets_from_records(records: Sequence[IssuerRecord]) -> list[IssuerTarget]:
    """Compile regex targets for title/description matching."""
    targets: list[IssuerTarget] = []
    for rec in records:
        patterns = _compile_patterns(rec.raw_symbol, rec.aliases)
        if not patterns:
            continue
        targets.append(
            IssuerTarget(
                ticker=rec.symbol,
                exchange=rec.exchange,
                name=rec.name,
                patterns=patterns,
            )
        )
    return targets


def load_issuer_targets(path: Path = _DEFAULT_CACHE_PATH) -> tuple[list[IssuerTarget], dict[str, Any]]:
    """Load committed cache → match targets + metadata."""
    payload = load_universe(path)
    records = records_from_payload(payload)
    return targets_from_records(records), payload


def exchange_of_ticker(ticker: str, targets: Sequence[IssuerTarget]) -> Optional[str]:
    want = ticker.upper()
    for t in targets:
        if t.ticker.upper() == want:
            return t.exchange
    # Suffix fallback when target list unavailable.
    u = want
    if u.endswith(".CN"):
        return "CSE"
    if u.endswith(".V"):
        return "TSXV"
    if u.endswith(".TO"):
        return "TSX"
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Canadian issuer universe (TSX/TSXV/CSE)")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Download directories and write cache",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print counts from the on-disk cache",
    )
    parser.add_argument(
        "--rebuild-aliases",
        action="store_true",
        help="Recompute aliases from cached names (no network)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=_DEFAULT_CACHE_PATH,
        help="Cache JSON path",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.rebuild_aliases:
        payload = rebuild_aliases_in_payload(load_universe(args.cache))
        saved = save_universe(payload, args.cache)
        print(f"Rebuilt aliases for {payload['issuer_count']} issuers -> {saved}")
        return 0

    if args.refresh:
        payload = download_universe()
        saved = save_universe(payload, args.cache)
        print(f"Wrote {payload['issuer_count']} issuers -> {saved}")
        by_ex: dict[str, int] = {}
        for row in payload["issuers"]:
            by_ex[row["exchange"]] = by_ex.get(row["exchange"], 0) + 1
        print("by exchange:", by_ex)
        return 0

    payload = load_universe(args.cache)
    print(f"retrieved_at={payload.get('retrieved_at')} issuers={payload.get('issuer_count')}")
    by_ex: dict[str, int] = {}
    for row in payload.get("issuers") or []:
        by_ex[str(row.get("exchange"))] = by_ex.get(str(row.get("exchange")), 0) + 1
    print("by exchange:", by_ex)
    if args.stats:
        print("sources:", json.dumps(payload.get("sources") or {}, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
