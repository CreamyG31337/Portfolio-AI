"""Tests for idea scorecard service (ROADMAP §2.8)."""

from decimal import Decimal
from unittest.mock import MagicMock

from web_dashboard.benchmarks import SCORING_VERSION
from web_dashboard.idea_scorecard_service import build_idea_scorecard


def test_signed_excess_flips_for_bearish() -> None:
    """Signed excess = excess_return for BULLISH, -excess_return for BEARISH.

    A call is a hit when signed_excess > 0.
    """
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = [
        # BULLISH: +4.0 is a hit, -2.0 is a miss
        {"stance": "BULLISH", "excess_return": 4.0, "domain": "fool.com", "idea_score": 7},
        {"stance": "BULLISH", "excess_return": -2.0, "domain": "fool.com", "idea_score": 7},
        # BEARISH: -6.0 raw excess means stock lagged benchmark -> BEARISH was right (+6.0 signed excess, hit!)
        {"stance": "BEARISH", "excess_return": -6.0, "domain": "bear.com", "idea_score": 6},
        # BEARISH: +3.0 raw excess means stock beat benchmark -> BEARISH was wrong (-3.0 signed excess, miss!)
        {"stance": "BEARISH", "excess_return": 3.0, "domain": "bear.com", "idea_score": 6},
    ]

    res = build_idea_scorecard(mock_pg, horizon_days=30)

    assert res["available"] is True
    overall = res["overall"]
    assert overall["n"] == 4
    # Hits: BULLISH (+4.0) and BEARISH (-6.0 raw -> +6.0 signed) = 2 hits of 4 = 50.0%
    assert overall["hit_rate_pct"] == 50.0
    # Mean signed excess: (4.0 - 2.0 + 6.0 - 3.0) / 4 = 5.0 / 4 = 1.25
    assert overall["mean_signed_excess_pct"] == 1.25

    by_dir = {d["stance"]: d for d in res["by_direction"]}
    assert "BULLISH" in by_dir
    assert "BEARISH" in by_dir

    bear = by_dir["BEARISH"]
    assert bear["n"] == 2
    assert bear["hit_rate_pct"] == 50.0
    # Bear signed excess: (6.0 - 3.0) / 2 = 1.5
    assert bear["mean_signed_excess_pct"] == 1.5

    bull = by_dir["BULLISH"]
    assert bull["n"] == 2
    assert bull["hit_rate_pct"] == 50.0
    # Bull signed excess: (4.0 - 2.0) / 2 = 1.0
    assert bull["mean_signed_excess_pct"] == 1.0


def test_min_n_filtering_on_domains_and_sorting() -> None:
    """by_domain includes only groups with n >= min_n, sorted by mean_signed_excess_pct desc."""
    mock_pg = MagicMock()
    rows = []
    # top.com: 10 rows, mean excess = +5.0
    for _ in range(10):
        rows.append({"stance": "BULLISH", "excess_return": 5.0, "domain": "top.com", "idea_score": 7})
    # mid.com: 10 rows, mean excess = +2.0
    for _ in range(10):
        rows.append({"stance": "BULLISH", "excess_return": 2.0, "domain": "mid.com", "idea_score": 7})
    # small.com: 9 rows (below default min_n=10), mean excess = +10.0
    for _ in range(9):
        rows.append({"stance": "BULLISH", "excess_return": 10.0, "domain": "small.com", "idea_score": 7})

    mock_pg.execute_query.return_value = rows

    # Default min_n = 10 -> small.com excluded
    res = build_idea_scorecard(mock_pg, min_n=10)
    assert res["available"] is True
    domains = [d["domain"] for d in res["by_domain"]]
    assert domains == ["top.com", "mid.com"]
    assert "small.com" not in domains
    assert res["by_domain"][0]["mean_signed_excess_pct"] == 5.0
    assert res["by_domain"][1]["mean_signed_excess_pct"] == 2.0

    # Custom min_n = 5 -> small.com included and sorted first due to higher excess
    res5 = build_idea_scorecard(mock_pg, min_n=5)
    domains5 = [d["domain"] for d in res5["by_domain"]]
    assert domains5 == ["small.com", "top.com", "mid.com"]
    assert res5["by_domain"][0]["mean_signed_excess_pct"] == 10.0


def test_score_bands() -> None:
    """Group ideas into '8+', '6-7', and '<6' based on idea_score."""
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = [
        # 8+ band
        {"stance": "BULLISH", "excess_return": 4.0, "idea_score": 9},
        {"stance": "BULLISH", "excess_return": 2.0, "idea_score": 8},
        # 6-7 band
        {"stance": "BULLISH", "excess_return": 3.0, "idea_score": 7},
        {"stance": "BULLISH", "excess_return": -1.0, "idea_score": 6},
        # <6 band
        {"stance": "BULLISH", "excess_return": 5.0, "idea_score": 5},
        {"stance": "BULLISH", "excess_return": -1.0, "idea_score": 2},
        {"stance": "BULLISH", "excess_return": -4.0, "idea_score": None},
    ]

    res = build_idea_scorecard(mock_pg)
    assert res["available"] is True
    bands = {b["band"]: b for b in res["by_score_band"]}

    assert "8+" in bands
    assert bands["8+"]["n"] == 2
    assert bands["8+"]["hit_rate_pct"] == 100.0
    assert bands["8+"]["mean_signed_excess_pct"] == 3.0

    assert "6-7" in bands
    assert bands["6-7"]["n"] == 2
    assert bands["6-7"]["hit_rate_pct"] == 50.0
    assert bands["6-7"]["mean_signed_excess_pct"] == 1.0

    assert "<6" in bands
    assert bands["<6"]["n"] == 3
    assert bands["<6"]["hit_rate_pct"] == 33.3
    assert bands["<6"]["mean_signed_excess_pct"] == 0.0


def test_db_error_returns_available_false() -> None:
    """DB exceptions must never raise; log warning and return {'available': False}."""
    mock_pg = MagicMock()
    mock_pg.execute_query.side_effect = RuntimeError("connection lost")

    res = build_idea_scorecard(mock_pg)
    assert res == {"available": False}


def test_empty_results_returns_zero_n() -> None:
    """When no rows match, return available=True with overall n=0 and empty breakdowns."""
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = []

    res = build_idea_scorecard(mock_pg)
    assert res["available"] is True
    assert res["overall"]["n"] == 0
    assert res["overall"]["hit_rate_pct"] is None
    assert res["overall"]["mean_signed_excess_pct"] is None
    assert res["by_direction"] == []
    assert res["by_domain"] == []
    assert res["by_article_type"] == []
    assert res["by_score_band"] == []


def test_by_article_type_and_nested_metadata() -> None:
    """Extracts domain, article_type, and score from nested metadata if unflattened."""
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = [
        {
            "stance": "BULLISH",
            "excess_return": 3.0,
            "metadata": {
                "idea": {
                    "domain": "alpha.com",
                    "article_type": "Alpha Research",
                    "idea_score": 8,
                }
            },
        },
        {
            "stance": "BULLISH",
            "excess_return": -1.0,
            "metadata": {
                "idea": {
                    "domain": "alpha.com",
                    "article_type": "Opportunity Discovery",
                    "idea_score": 6,
                }
            },
        },
    ]

    res = build_idea_scorecard(mock_pg, min_n=1)
    assert res["available"] is True
    by_type = {t["article_type"]: t for t in res["by_article_type"]}
    assert "Alpha Research" in by_type
    assert by_type["Alpha Research"]["n"] == 1
    assert by_type["Alpha Research"]["hit_rate_pct"] == 100.0

    assert "Opportunity Discovery" in by_type
    assert by_type["Opportunity Discovery"]["n"] == 1
    assert by_type["Opportunity Discovery"]["hit_rate_pct"] == 0.0


def test_filters_invalid_excess_and_non_directional_stances() -> None:
    """Rejects NaN/None excess and non-directional stances (e.g. HOLD)."""
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = [
        {"stance": "BULLISH", "excess_return": Decimal("NaN")},
        {"stance": "BULLISH", "excess_return": None},
        {"stance": "HOLD", "excess_return": 5.0},
        {"stance": "RISK", "excess_return": -2.0},
        {"stance": "BUY", "excess_return": 4.0},  # BUY is in BULLISH_STANCES
    ]

    res = build_idea_scorecard(mock_pg)
    assert res["available"] is True
    assert res["overall"]["n"] == 1
    assert res["overall"]["hit_rate_pct"] == 100.0


def test_sql_query_arguments() -> None:
    """Verifies horizon_days and SCORING_VERSION are passed to execute_query."""
    mock_pg = MagicMock()
    mock_pg.execute_query.return_value = []

    build_idea_scorecard(mock_pg, horizon_days=90)
    args, kwargs = mock_pg.execute_query.call_args
    sql, params = args
    assert "source = 'alpha_idea'" in sql
    assert params == (90, SCORING_VERSION)
