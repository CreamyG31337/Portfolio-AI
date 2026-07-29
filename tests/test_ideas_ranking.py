"""Ideas inbox ranking (P4).

The score itself is SQL, so these are structural guards rather than arithmetic
checks: they assert the properties that were actually at risk of regressing --
the two query paths drifting apart, the sentiment guard being dropped from the
demote term, and relevance_score creeping back into the ranking.
"""

from __future__ import annotations

import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from ideas_quality import (  # noqa: E402
    IDEA_SCORE_MAX,
    LOW_SIGNAL_THRESHOLD,
    SENTIMENT_EXEMPT_RULES,
    SENTIMENT_GUARDED_RULES,
    idea_score_sql,
    sql_pattern,
)


def test_score_ceiling_matches_the_documented_maximum() -> None:
    """+3 sentiment, +2 tickers, +3 claims, +1 conclusion."""
    assert IDEA_SCORE_MAX == 9
    assert 0 < LOW_SIGNAL_THRESHOLD < IDEA_SCORE_MAX


def test_structural_signals_outweigh_regex_terms() -> None:
    """The lesson of the cleanup passes, encoded as a test.

    Structure (sentiment/tickers/claims/conclusion) contributes +9; the phrasing
    regexes only ever subtract. If someone later adds a positive regex term or
    inflates the demote weights past the structural ceiling, ranking starts
    tracking model phrasing -- which drifts silently on every prompt change.
    """
    sql = idea_score_sql()
    # Seven terms total; the first carries no sign, so positives are 1 + 3.
    assert sql.count("ELSE 0 END)") == 7
    assert sql.count("+ (CASE WHEN") == 3
    assert sql.count("- (CASE WHEN") == 3
    # Demote weights must not exceed what structure can earn.
    assert "THEN 6 ELSE 0 END)" in sql and "THEN 2 ELSE 0 END)" in sql


def test_demote_term_keeps_the_sentiment_guard() -> None:
    """The Sinda protection.

    Sentiment-exempt rules may fire on the title alone; everything else must be
    conjoined with the neutral-sentiment predicate, or a boilerplate-looking title
    carrying a real directional call gets demoted -- exactly the false positive the
    cleanup script was fixed for.
    """
    sql = idea_score_sql()
    for rule in SENTIMENT_EXEMPT_RULES:
        assert sql_pattern(rule) in sql, rule.reason
    for rule in SENTIMENT_GUARDED_RULES:
        assert sql_pattern(rule) in sql, rule.reason
    assert "upper(ra.sentiment) = 'NEUTRAL'" in sql
    # The guarded alternation and the neutral check are ANDed together.
    guarded_start = sql.index(sql_pattern(SENTIMENT_GUARDED_RULES[0]))
    assert " AND (ra.sentiment IS NULL" in sql[guarded_start:]


def test_relevance_score_is_not_a_scoring_term() -> None:
    """It is derived from logic_check, a genre label that rates junk 0.9.

    It survives only as a late ORDER BY tiebreaker; it must never re-enter the
    score expression itself.
    """
    assert "relevance_score" not in idea_score_sql()


def test_both_query_paths_share_the_score_and_ordering() -> None:
    """The fallback runs when idea_triage is unavailable -- i.e. when nobody is
    watching. It must rank identically, or the inbox degrades invisibly."""
    import today_briefing_service as svc

    primary = svc._fetch_alpha_ideas_query.__code__.co_names
    fallback = svc._fetch_alpha_ideas_fallback.__code__.co_names
    for shared in ("idea_score_sql", "_rank_and_limit_sql", "_IDEA_COLUMNS"):
        assert shared in primary, shared
        assert shared in fallback, shared

    order = svc._rank_and_limit_sql()
    assert "ORDER BY idea_score DESC, relevance_score DESC NULLS LAST" in order
    # The withheld count is a window function over the UNFILTERED set; computing it
    # after the WHERE would always report zero.
    assert order.index("OVER ()") < order.index("WHERE %s OR NOT low_signal")
