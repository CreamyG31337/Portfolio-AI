"""Shared low-value rules for the Ideas inbox — single source of truth.

Three consumers, one rule table:

* ``low_value_alpha_reason`` (scheduler/jobs_common.py) — drops junk BEFORE extraction,
  saving FlareSolverr/Ollama budget.
* ``cleanup_ideas_inbox.py`` — auto-dismisses junk already in the pool.
* Inbox ranking SQL — demotes whatever slips through.

WHY THESE RULES EXIST
---------------------
``logic_check`` is a GENRE label, not a quality label: the summarizer prompt defines
DATA_BACKED as "primarily reporting official data/metrics" and routes real analysis to
NEUTRAL. But ``relevance_for_logic_check`` maps DATA_BACKED to the TOP score (0.9), so
ETF constituent tables outrank actual theses. Measured 2026-07-27 over 14 days:
stockanalysis.com averaged 0.86 with a 43% junk rate, while fool.com averaged 0.74
with 0%. These rules are the compensating control until that mapping is revisited.

THE CENTRAL DESIGN CONSTRAINT
-----------------------------
The pre-extraction filter sees ONLY title and URL. Sentiment and conclusion do not
exist yet — the article has not been summarized. So the guard that makes post-hoc
cleanup safe is unavailable at filter time, and the two stages cannot use the same
rule set.

This is not theoretical. On the first cleanup dry run:

    "Sinda Analyst Ratings and Price Targets | NYSE:SIND | Benzinga"
        matched price_targets_page, but its conclusion read "three major banks
        agreeing on a price target significantly above the current trading price"
        — a real signal. It was the only match in the batch with non-NEUTRAL
        sentiment; every true boilerplate row was DATA_BACKED/NEUTRAL.

Post-extraction the sentiment guard spares it. Pre-extraction nothing would have, and
the article would have been dropped before anyone could see it was worth keeping — a
silent false negative visible only as a `low_value` log line.

Hence ``prefilter``: a rule is only allowed to drop an article pre-extraction when its
title (optionally plus a URL path) is unambiguous on its own. Everything else is
demote-only, where sentiment is available to protect it.
"""

from __future__ import annotations

from typing import NamedTuple


class LowValueRule(NamedTuple):
    """One boilerplate pattern.

    Attributes:
        reason: Stable audit label, logged by the pre-filter and stored in
            ``idea_triage.notes`` by the cleanup so any drop can be traced.
        core: Pattern body WITHOUT word-boundary anchors. Boundaries are added per
            engine (Python ``\\b`` vs Postgres ``\\m``/``\\M``) so a rule cannot be
            written correctly for one engine and silently wrong for the other.
        url: Optional URL-path pattern that must ALSO match before the rule fires.
            Used where the title alone is ambiguous.
        prefilter: Safe to drop before extraction on title+URL alone.
        sentiment_exempt: May be dismissed post-hoc even with directional sentiment.
            Only for titles that are boilerplate no matter what the model concluded.
    """

    reason: str
    core: str
    url: str | None = None
    prefilter: bool = False
    sentiment_exempt: bool = False


RULES: tuple[LowValueRule, ...] = (
    # --- Unambiguous: an ETF constituent table is boilerplate however it is labelled.
    LowValueRule("holdings_list", r"Holdings List", prefilter=True, sentiment_exempt=True),
    # --- Auto-generated quote/price pages. Long-standing rules, now shared so the
    #     cleanup sweep catches old rows too (previously only the pre-filter knew them,
    #     so pages ingested before the rule existed sat in the inbox forever).
    LowValueRule("quote_overview", r"[Ss]tock\s+[Pp]rice\s*&\s*Overview",
                 prefilter=True, sentiment_exempt=True),
    LowValueRule("quote_overview", r"stock\s+quote", prefilter=True, sentiment_exempt=True),
    LowValueRule("price_history", r"stock\s+price\s+history",
                 prefilter=True, sentiment_exempt=True),
    LowValueRule("listing_index", r"All Stock News", prefilter=True, sentiment_exempt=True),
    # --- Title ambiguous alone; URL path confirms it is the generated index page.
    #     Real articles say "X's dividend history suggests...".
    LowValueRule("dividend_history", r"Dividend History", url=r"/dividend", prefilter=True),
    LowValueRule("event_calendar", r"(Corporate\s+)?Event Calendar",
                 url=r"/calendar", prefilter=True),
    # --- DEMOTE-ONLY. Never pre-filtered: see the Sinda case in the module docstring.
    #     Benzinga publishes genuine single-upgrade notes and real cluster-buy stories
    #     under titles that match these exactly. Only safe once sentiment exists.
    LowValueRule("price_targets_page", r"Analyst Ratings and Price Targets"),
    LowValueRule("insider_activity_page", r"Insider Trading Activity"),
)

# Anchored on a leading "Latest" because genuine analysis almost never starts that
# way, whereas auto-generated aggregator pages do ("Latest Azitra Stock News").
LISTING_INDEX_RULE = LowValueRule(
    "listing_index", r"latest\b.*\b(news|articles?|analysis)", prefilter=True,
    sentiment_exempt=True,
)


def python_pattern(rule: LowValueRule) -> str:
    """Word-boundary-anchored pattern for Python's ``re``."""
    return rf"\b{rule.core}\b"


def sql_pattern(rule: LowValueRule) -> str:
    """Word-boundary-anchored pattern for Postgres ``~*`` (ARE uses \\m and \\M)."""
    return rf"\m{rule.core}\M"


def sql_alternation(rules: tuple[LowValueRule, ...]) -> str:
    return "|".join(sql_pattern(r) for r in rules) if rules else "(?!)"


PREFILTER_RULES = tuple(r for r in RULES if r.prefilter)
SENTIMENT_EXEMPT_RULES = tuple(r for r in RULES if r.sentiment_exempt)
SENTIMENT_GUARDED_RULES = tuple(r for r in RULES if not r.sentiment_exempt)

# --- Conclusion patterns --------------------------------------------------
# The model frequently admits an article is worthless in its own conclusion while
# still labelling it DATA_BACKED. Phrases lifted from live conclusions.
#
# Deliberately a TIEBREAKER, never the primary mechanism: phrasing drifts whenever the
# model or prompt version changes and nothing alerts you when it does. Prefer the
# structural signals (sentiment / claims / tickers), which held up on every live case.
NO_CATALYST_CONCLUSION_RE = (
    r"static snapshot"
    r"|routine (maintenance|compositional)"
    r"|does not offer new"
    r"|no new fundamental"
    r"|no upcoming"
    r"|simply indicates a lack"
)

#: SQL predicate: true when sentiment carries no direction.
NEUTRAL_SENTIMENT_SQL = "(ra.sentiment IS NULL OR upper(ra.sentiment) = 'NEUTRAL')"

# Domains that publish structured data rather than analysis. NOT auto-blocked:
# measured 2026-07-27, stockanalysis.com was 43% junk but 57% useful, so filtering
# beats banning. Surfaced for operator judgement in alpha_research_domains.
STRUCTURED_DATA_DOMAINS = ("stockanalysis.com",)
