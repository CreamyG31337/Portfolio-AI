"""Shared low-value patterns for the Ideas inbox.

One definition, three consumers:

* the pre-extraction filter (stops NEW junk before it costs FlareSolverr/Ollama time)
* the one-shot inbox cleanup (auto-dismisses junk already in the pool)
* the inbox ranking SQL (demotes anything that slipped through)

Keeping them here rather than inline at each site means tuning happens in one
place. A pattern that is too aggressive silently drops real articles, so every
addition should be narrow, anchored, and paired with a negative test case.

BACKGROUND -- why these patterns exist at all
---------------------------------------------
`logic_check` is a GENRE label, not a quality label: the summarizer prompt defines
DATA_BACKED as "primarily reporting official data/metrics" and routes real analysis
to NEUTRAL. But `relevance_for_logic_check` maps DATA_BACKED to the TOP score (0.9),
so ETF holdings tables outrank actual theses. Until that mapping is revisited, these
patterns are the compensating control.

Observed live (2026-07-27), top of the inbox by relevance_score:
    0.90  DATA_BACKED  NEUTRAL  "IEUS Holdings List - iShares MSCI Europe Small-Cap ETF"
          conclusion: "static snapshot ... no single stock dominating"
    0.90  DATA_BACKED  NEUTRAL  "EES Holdings List - WisdomTree U.S. SmallCap Fund"
          conclusion: "static snapshot of the EES ETF's holdings"
"""

from __future__ import annotations

# --- Title patterns -------------------------------------------------------
# POSIX alternation for Postgres `~*`. Kept as one string so the SQL sites stay
# readable; TITLE_REASONS below maps each branch back to an auditable label.
#
# Only `Holdings List` is safe on the title alone. The others are ambiguous in
# isolation -- real articles say "X's dividend history suggests...", and Benzinga
# publishes genuine single-upgrade notes -- so those are paired with a URL path
# check at the call site (see URL_CONFIRMED_REASONS).
BOILERPLATE_TITLE_RE = (
    r"\mHoldings List\M"
    r"|\mDividend History\M"
    r"|\m(Corporate\s+)?Event Calendar\M"
    r"|\mAnalyst Ratings and Price Targets\M"
)

TITLE_REASONS: tuple[tuple[str, str], ...] = (
    ("holdings_list", r"\mHoldings List\M"),
    ("dividend_history", r"\mDividend History\M"),
    ("event_calendar", r"\m(Corporate\s+)?Event Calendar\M"),
    ("price_targets_page", r"\mAnalyst Ratings and Price Targets\M"),
    # Added after the first cleanup pass cleared the holdings dumps and exposed the
    # next layer of aggregator pages underneath. Both are Benzinga-style index pages
    # whose own conclusions admit they carry nothing:
    #   "Lumentum Holdings Insider Trading Activity" -> "no activity in the most
    #    recent period"
    #   "Byrna Technologies Insider Trading Activity" -> "providing no new bullish
    #    or bearish signals"
    # Guarded by NEUTRAL sentiment, so a genuine cluster-buy story (which the model
    # labels BULLISH) is never caught by the same phrase.
    ("insider_activity_page", r"\mInsider Trading Activity\M"),
    ("listing_index", r"\mAll Stock News\M"),
)

# Reasons whose title text is ambiguous enough to need a URL path confirmation
# before dropping an article pre-extraction.
URL_CONFIRMED_REASONS: dict[str, str] = {
    "dividend_history": r"/dividend",
    "event_calendar": r"/calendar",
    "price_targets_page": r"/ratings|/forecast",
}

# --- Conclusion patterns --------------------------------------------------
# The model frequently admits an article is worthless in its own conclusion while
# still labelling it DATA_BACKED. These phrases are lifted from live conclusions.
#
# Deliberately a TIEBREAKER, never the primary mechanism: phrasing drifts whenever
# the model or prompt version changes, and nothing alerts you when it does. Prefer
# the structural signals (sentiment / claims / tickers) for ranking.
NO_CATALYST_CONCLUSION_RE = (
    r"static snapshot"
    r"|routine (maintenance|compositional)"
    r"|does not offer new"
    r"|no new fundamental"
    r"|no upcoming"
    r"|simply indicates a lack"
)

# Domains that publish structured data rather than analysis. Not a blocklist on
# its own -- surfaced so the operator can disable them in alpha_research_domains.
STRUCTURED_DATA_DOMAINS = ("stockanalysis.com",)

# --- Sentiment guard ------------------------------------------------------
# Titles alone are unsafe for the ambiguous reasons. Caught live on the first
# cleanup dry run:
#
#   "Sinda Analyst Ratings and Price Targets | NYSE:SIND | Benzinga"
#       matched price_targets_page, but the conclusion read "three major banks
#       agreeing on a price target significantly above the current trading price"
#       -- a real signal, and the ONLY match in the batch with non-NEUTRAL
#       sentiment. Every genuine boilerplate row was DATA_BACKED/NEUTRAL.
#
# So: a directional sentiment means the model found something worth saying, and
# the row is spared. `holdings_list` is exempt because an ETF constituent table is
# boilerplate no matter how the sentiment field came out.
SENTIMENT_EXEMPT_REASONS = frozenset({"holdings_list"})

#: SQL predicate: true when sentiment carries no direction.
NEUTRAL_SENTIMENT_SQL = "(ra.sentiment IS NULL OR upper(ra.sentiment) = 'NEUTRAL')"
