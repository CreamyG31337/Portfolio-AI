"""Phase K8 — pull retrieval: find videos about the securities we actually hold.

The allowlist (K3) is a **push** model: 13 curated channels publish, we ingest. §26
measured what that reaches — 8 of 100 production holdings. The other 92 (uranium,
Canadian miners, rails, pipelines, grid equipment) have no path to coverage, because
no channel covers a 100-position book.

This module is the **pull** side. For each holding it asks YouTube directly, using the
company name rather than the symbol (§17: titles say "Cameco", not ``CCO.TO``), then
filters hard *before* spending caption quota.

Two things make this affordable and safe:

* **Listing is free.** ``list_search_videos`` is a flat listing call; only caption
  bodies are rate-limited (~90/day per egress IP, §14). Search wide, fetch narrow.
* **Views are an anti-signal here.** §26.3 measured it: ranking company-name search
  hits by view count returns a dropshipping tutorial for Shopify (17.6M), a geology
  documentary for Oklo (3.0M), and a *VALORANT match* for Vertiv (111k), while the real
  hits — a Centrus CEO interview (4.6k), the Teck/Anglo tie-up (4.7k), G Mining's
  ``TSX:GMIN`` update (8.3k) — sit two to three orders of magnitude below. We therefore
  rank by **name-confirmation strength**, and use views only to break ties among
  already-confirmed candidates. Do not reuse the ATTENTION-side ``no_audience`` reject
  from ``scripts/yt_discover_channels.py`` here; §20's two uses of the corpus need
  opposite view filters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

# Corporate suffixes to strip so "Cameco Corporation" queries as "Cameco" and
# "G Mining Ventures Corp." as "G Mining Ventures". Order matters: longest first.
_SUFFIXES = (
    "class a",
    "class b",
    "holdings",
    "incorporated",
    "corporation",
    "limited",
    "company",
    "group",
    "plc",
    "ltd",
    "inc",
    "corp",
    "co",
    "sa",
    "nv",
    "ag",
)

# A holding whose "company" is a basket. Searching "iShares Core Equity ETF Portfolio"
# returns index explainers, never news, so funds are excluded from pull retrieval.
# Their constituents are covered by the individual holdings that overlap them.
_FUND_MARKERS = (
    "etf",
    "index fund",
    "fund portfolio",
    "trust portfolio",
    " ishares",
    "vanguard",
    "sprott",
    "spdr",
    "invesco",
    "horizons",
    "bmo ",
    "first trust",
)

# Fund names *end* in a basket word: "First Trust Technology AlphaDEX Fund".
# Matching the ending rather than the substring keeps operating companies whose
# names merely contain one of these words. "trust" is deliberately absent — REITs
# end in it and they are real issuers worth searching for.
_FUND_NAME_ENDINGS = (
    "fund",
    "etf",
    "portfolio",
)

# Titles that match a company name but are not *about* the company as an issuer.
# Every one of these was observed in the §26.2 probe.
_JUNK_TITLE_PATTERNS = (
    (r"\bhow it'?s made\b", "manufacturing_show"),
    (r"\bhow (?:a|an|the)\b.{0,30}\bworks?\b", "explainer"),
    (r"\btutorial\b|\bfor beginners\b|\bstep[ -]by[ -]step\b", "tutorial"),
    (r"\bdropship\w*|\bside hustle\b|\bmake money\b|\bpassive income\b", "get_rich"),
    (r"\bunboxing\b|\breview\b.{0,20}\b(?:laptop|phone|headset|keyboard)\b", "product_review"),
    (r"\bdocumentar\w+|\bhistory of\b|\bbillion[- ]year\b", "documentary"),
    (r"\b(?:vct|valorant|esports|gameplay|highlights)\b", "esports"),
    (r"\btraining\b|\bwebinar\b|\bcourse\b|\blesson \d+", "training"),
    (r"\bASMR\b|\bmusic video\b|\blyrics\b", "not_finance"),
)

# Signals that a title is about the *issuer*, not merely the brand. These do the real
# ranking work, since view count cannot (§26.3).
_ISSUER_TITLE_PATTERNS = (
    (r"\b(?:TSX|TSXV|CSE|NYSE|NASDAQ|OTC)\s*[:\-]\s*[A-Z][A-Z0-9.]{0,6}\b", 5, "exchange_tag"),
    (r"\$[A-Z]{1,5}\b", 4, "cashtag"),
    (r"\b(?:CEO|CFO|chairman|president)\b", 3, "executive"),
    (r"\b(?:Q[1-4]|quarterly|full[- ]year)\s+(?:results|earnings|report)", 4, "earnings"),
    (r"\b(?:earnings|guidance|outlook|results)\b", 2, "earnings_word"),
    (r"\b(?:acquisition|acquires?|merger|takeover|tie[- ]up|deal)\b", 3, "mna"),
    (r"\b(?:drill|assay|resource estimate|feasibility|PEA|mineral)\b", 3, "mining_ops"),
    (r"\b(?:stock|shares?|valuation|price target|analyst)\b", 2, "equity_word"),
    (r"\b(?:contract|award|permit|approval|licen[cs]e)\b", 2, "corporate_event"),
    (r"\b(?:interview|discusses|talks about|explains)\b", 2, "interview"),
)


# Score for a title that names the company and says nothing else about it. A bare
# brand mention is not news: "Reading electrical one line drawings | Eaton PSEC" names
# Eaton, and is a vendor training video. Confirmation requires the name *plus* at least
# one issuer signal, so the usable floor is above this.
NAME_ONLY_SCORE = 4
MIN_CONFIRM_SCORE = NAME_ONLY_SCORE + 2

# A very short company name matches too loosely to stand alone: "ADF" (DRX.TO, ADF
# Group) hit the unrelated "ADF Foods", and "Oklo" hits a documentary about the natural
# fission reactor. Names this short must be corroborated by the symbol or an exchange
# tag in the same title. Both false positives came from the first real sweep.
_SHORT_NAME_NEEDS_SYMBOL = 4


def normalize_company_name(company_name: str) -> str:
    """Strip corporate suffixes and casing noise: 'VERTIV HOLDINGS CLASS A' -> 'Vertiv'."""
    name = re.sub(r"[^\w\s&.'-]", " ", str(company_name or "")).strip()
    if not name:
        return ""
    # All-caps names ("VERTIV HOLDINGS CLASS A") title-case badly in queries.
    if name.isupper():
        name = name.title()
    changed = True
    while changed:
        changed = False
        # Trailing punctuation first: "G Mining Ventures Corp." must match "corp".
        name = name.rstrip(" .,&")
        low = name.lower()
        for suffix in _SUFFIXES:
            if not low.endswith(" " + suffix):
                continue
            name = name[: len(name) - len(suffix)].rstrip(" .,&")
            changed = True
            break
    return name.strip()


def is_fund(ticker: str, company_name: str, sector: str | None = None) -> bool:
    """True for ETFs / index baskets, which pull retrieval skips."""
    blob = f" {company_name or ''} {sector or ''} ".lower()
    if any(marker in blob for marker in _FUND_MARKERS):
        return True
    name = str(company_name or "").lower().rstrip(" .,")
    return any(name.endswith(" " + ending) for ending in _FUND_NAME_ENDINGS)


@dataclass(frozen=True)
class HoldingTarget:
    """One security to search for, with the aliases a title might actually use."""

    ticker: str
    company_name: str
    sector: str | None = None

    @property
    def core_name(self) -> str:
        return normalize_company_name(self.company_name)

    @property
    def bare_symbol(self) -> str:
        """``CCO.TO`` -> ``CCO``; exchange tags in titles drop the suffix."""
        return self.ticker.split(".")[0].upper()

    @property
    def aliases(self) -> tuple[str, ...]:
        """Name forms worth matching in a title, longest first."""
        out: list[str] = []
        core = self.core_name
        if core:
            out.append(core)
            # "G Mining Ventures" also appears as "G Mining"; keep a 2-word prefix.
            words = core.split()
            if len(words) > 2:
                out.append(" ".join(words[:2]))
        return tuple(dict.fromkeys(a for a in out if len(a) >= 3))

    def query(self, sector_hint: bool = True) -> str:
        """The search string. Sector hint disambiguates brand collisions (Vertiv/VCT)."""
        core = self.core_name or self.ticker
        if sector_hint and self.sector:
            return f"{core} {self.sector.lower()} stock"
        return f"{core} stock"


@dataclass
class Candidate:
    """A search hit scored for whether it is really about the holding."""

    video_id: str
    title: str
    url: str
    ticker: str
    view_count: int | None = None
    duration_s: int | None = None
    channel_name: str | None = None
    score: int = 0
    matched: tuple[str, ...] = field(default_factory=tuple)
    reject_reason: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.reject_reason is None and self.score > 0


def title_junk_reason(title: str) -> str | None:
    """Why this title is not about an issuer, or None if it survives."""
    for pattern, reason in _JUNK_TITLE_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return reason
    return None


def score_title(title: str, target: HoldingTarget) -> tuple[int, tuple[str, ...]]:
    """Confirmation strength for one title. 0 means the company is not named.

    Name presence is mandatory — an issuer signal alone ("CEO discusses earnings")
    proves nothing about *which* company. Extra points come from issuer vocabulary
    and from the title carrying the symbol itself.
    """
    matched: list[str] = []
    name_hit = False
    for alias in target.aliases:
        if re.search(rf"\b{re.escape(alias)}\b", title, re.IGNORECASE):
            name_hit = True
            matched.append(f"name:{alias}")
            break
    if not name_hit:
        return 0, ()

    score = NAME_ONLY_SCORE
    if re.search(rf"\b{re.escape(target.bare_symbol)}\b", title):
        score += 4
        matched.append("symbol")
    for pattern, weight, label in _ISSUER_TITLE_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            score += weight
            matched.append(label)
    return score, tuple(matched)


def evaluate_listing(listing: Any, target: HoldingTarget) -> Candidate:
    """Score one ``VideoListing`` against a holding, without fetching captions."""
    title = str(getattr(listing, "title", "") or "")
    cand = Candidate(
        video_id=str(getattr(listing, "video_id", "") or ""),
        title=title,
        url=str(getattr(listing, "url", "") or ""),
        ticker=target.ticker,
        view_count=getattr(listing, "view_count", None),
        duration_s=getattr(listing, "duration_s", None),
        channel_name=getattr(listing, "channel_name", None),
    )
    junk = title_junk_reason(title)
    if junk:
        cand.reject_reason = junk
        return cand
    score, matched = score_title(title, target)
    if not score:
        cand.reject_reason = "name_absent"
        return cand
    if len(target.core_name) <= _SHORT_NAME_NEEDS_SYMBOL and "symbol" not in matched:
        # "Oklo" alone also matches the natural reactor documentary; require the
        # ticker or an exchange tag to pin a short name to the issuer.
        cand.reject_reason = "short_name_unconfirmed"
        cand.matched = matched
        return cand
    if score < MIN_CONFIRM_SCORE:
        # Named, but nothing marks it as being about the issuer.
        cand.reject_reason = "no_issuer_signal"
        cand.matched = matched
        return cand
    cand.score, cand.matched = score, matched
    return cand


def rank(candidates: Iterable[Candidate]) -> list[Candidate]:
    """Confirmed hits, best first. Views break ties only — never lead (§26.3)."""
    confirmed = [c for c in candidates if c.confirmed]
    return sorted(confirmed, key=lambda c: (-c.score, -(c.view_count or 0), c.video_id))


def search_holding(
    target: HoldingTarget,
    *,
    limit: int = 12,
    search_fn: Callable[..., Sequence[Any]] | None = None,
) -> list[Candidate]:
    """Search YouTube for one holding and return ranked, confirmed candidates.

    Listing only — costs no caption quota. Caption fetch is the caller's decision,
    made against a ranked list rather than a raw search page.
    """
    if search_fn is None:
        from yt_captions import list_search_videos as search_fn  # type: ignore

    # The sector hint disambiguates brand collisions but can over-constrain a small
    # issuer: "G Mining Ventures basic materials stock" returns nothing while the
    # plain query finds its TSX:GMIN corporate updates. Listing is free (§14), so
    # fall back rather than lose the holding.
    for query in dict.fromkeys([target.query(), target.query(sector_hint=False)]):
        try:
            listings = search_fn(query, limit=limit, max_limit=limit)
        except Exception as exc:
            logger.warning("Search failed for %s (%s): %s", target.ticker, query, exc)
            return []
        hits = rank(evaluate_listing(item, target) for item in listings)
        if hits:
            return hits
    return []


def targets_from_holdings(
    rows: Iterable[Mapping[str, Any]], *, include_funds: bool = False
) -> list[HoldingTarget]:
    """Build search targets from ``securities``-shaped rows, skipping ETFs by default."""
    out: list[HoldingTarget] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        name = str(row.get("company_name") or "").strip()
        if not ticker or not name:
            continue
        sector = row.get("sector")
        if not include_funds and is_fund(ticker, name, sector):
            continue
        if not normalize_company_name(name):
            continue
        out.append(HoldingTarget(ticker=ticker, company_name=name, sector=sector))
    return out
