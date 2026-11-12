"""Tests for the alpha-idea → stance_history ledger (ROADMAP §2.8 Z1)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from web_dashboard.idea_stance_service import (
    MAX_TICKERS_PER_ARTICLE,
    SOURCE,
    entry_as_of,
    record_alpha_idea_stances,
)
from web_dashboard.stance_history import EVENT_STANCE_SOURCES, record_stance


def _idea(
    article_id: str = "11111111-1111-1111-1111-111111111111",
    *,
    tickers: list[str] | None = None,
    ticker: str | None = None,
    sentiment: str = "BULLISH",
    fetched_at: datetime = datetime(2026, 11, 3, 15, 0),  # Tuesday, naive = UTC
    idea_score: int = 6,
    low_signal: bool = False,
) -> dict:
    return {
        "id": article_id,
        "ticker": ticker,
        "tickers": tickers if tickers is not None else ["nvda"],
        "sentiment": sentiment,
        "article_type": "Alpha Research",
        "source": "fool.com",
        "fetched_at": fetched_at,
        "title": "Why NVDA could run",
        "idea_score": idea_score,
        "low_signal": low_signal,
    }


# --- entry_as_of: never the fetch day itself -------------------------------------


def test_entry_is_next_weekday_after_fetch() -> None:
    # Tuesday mid-session fetch -> Wednesday close, never Tuesday's own close.
    assert entry_as_of(datetime(2026, 11, 3, 15, 0, tzinfo=UTC)).date().isoformat() == "2026-11-04"


def test_entry_skips_weekend() -> None:
    friday = datetime(2026, 11, 6, 22, 0, tzinfo=UTC)
    saturday = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    assert entry_as_of(friday).date().isoformat() == "2026-11-09"
    assert entry_as_of(saturday).date().isoformat() == "2026-11-09"


def test_entry_treats_naive_as_utc() -> None:
    naive = datetime(2026, 11, 3, 23, 30)
    assert entry_as_of(naive).tzinfo is UTC
    assert entry_as_of(naive).date().isoformat() == "2026-11-04"


# --- record_alpha_idea_stances --------------------------------------------------


@patch("web_dashboard.idea_stance_service.record_stance_safe", return_value=True)
@patch("web_dashboard.idea_stance_service.fetch_directional_ideas")
def test_writes_one_event_stance_per_ticker(mock_fetch: MagicMock, mock_stance: MagicMock) -> None:
    mock_fetch.return_value = [_idea(tickers=["nvda", "AMD", "NVDA"])]

    stats = record_alpha_idea_stances(MagicMock(), days=3)

    assert stats["stances_written"] == 2  # NVDA deduped within the article
    calls = [c.kwargs for c in mock_stance.call_args_list]
    assert [c["ticker"] for c in calls] == ["NVDA", "AMD"]
    first = calls[0]
    assert first["source"] == SOURCE
    assert first["stance"] == "BULLISH"
    assert first["dedupe_on_source_ref"] is True
    assert first["source_ref_id"] == "11111111-1111-1111-1111-111111111111"
    assert first["as_of"].date().isoformat() == "2026-11-04"
    idea = first["metadata"]["idea"]
    assert idea["domain"] == "fool.com"
    assert idea["idea_score"] == 6
    assert idea["ticker_count"] == 2
    # Must NOT feed the H1 evidence-domain table (see module docstring).
    assert "evidence" not in first["metadata"]


@patch("web_dashboard.idea_stance_service.record_stance_safe", return_value=True)
@patch("web_dashboard.idea_stance_service.fetch_directional_ideas")
def test_skips_baskets_and_tickerless(mock_fetch: MagicMock, mock_stance: MagicMock) -> None:
    basket = [f"T{i}" for i in range(MAX_TICKERS_PER_ARTICLE + 1)]
    mock_fetch.return_value = [
        _idea("a", tickers=basket),
        _idea("b", tickers=[]),
        _idea("c", tickers=[], ticker="shop.to"),  # falls back to the single ticker column
    ]

    stats = record_alpha_idea_stances(MagicMock())

    assert stats["skipped_too_many_tickers"] == 1
    assert stats["skipped_no_ticker"] == 1
    assert [c.kwargs["ticker"] for c in mock_stance.call_args_list] == ["SHOP.TO"]


@patch("web_dashboard.idea_stance_service.record_stance_safe", return_value=True)
@patch("web_dashboard.idea_stance_service.fetch_directional_ideas")
def test_bearish_recorded_and_dry_run_writes_nothing(
    mock_fetch: MagicMock, mock_stance: MagicMock
) -> None:
    mock_fetch.return_value = [_idea(sentiment="BEARISH")]

    stats = record_alpha_idea_stances(MagicMock(), dry_run=True)

    assert stats["candidates"] == 1
    assert stats["stances_written"] == 0
    mock_stance.assert_not_called()

    record_alpha_idea_stances(MagicMock())
    assert mock_stance.call_args.kwargs["stance"] == "BEARISH"


# --- record_stance event mode -----------------------------------------------------


def test_event_dedupe_inserts_second_article_with_same_stance() -> None:
    # State dedupe would skip this (latest stance is already BULLISH); event dedupe
    # only checks whether THIS article was already recorded.
    pg = MagicMock()
    pg.execute_query.return_value = []
    as_of = datetime(2026, 11, 4, 21, 0, tzinfo=UTC)

    inserted = record_stance(
        pg,
        ticker="nvda",
        source=SOURCE,
        stance="BULLISH",
        source_ref_id="22222222-2222-2222-2222-222222222222",
        as_of=as_of,
        dedupe_on_source_ref=True,
    )

    assert inserted is True
    check_sql, check_params = pg.execute_query.call_args[0]
    assert "source_ref_id" in check_sql
    assert check_params == ("NVDA", SOURCE, "22222222-2222-2222-2222-222222222222")
    insert_params = pg.execute_update.call_args[0][1]
    assert insert_params[-2] == as_of


def test_event_dedupe_skips_already_recorded_article() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [{"?column?": 1}]

    inserted = record_stance(
        pg, ticker="NVDA", source=SOURCE, stance="BULLISH",
        source_ref_id="22222222-2222-2222-2222-222222222222", dedupe_on_source_ref=True,
    )

    assert inserted is False
    pg.execute_update.assert_not_called()


def test_event_dedupe_requires_source_ref() -> None:
    pg = MagicMock()
    assert record_stance(
        pg, ticker="NVDA", source=SOURCE, stance="BULLISH", dedupe_on_source_ref=True
    ) is False
    pg.execute_query.assert_not_called()


def test_state_mode_default_as_of_is_null_param() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    record_stance(pg, ticker="ABC", source="ticker_analysis", stance="BUY")
    assert pg.execute_update.call_args[0][1][-2] is None  # COALESCE(NULL, now())


# --- stance flips ignore event sources --------------------------------------------


def test_stance_flips_exclude_event_sources() -> None:
    from web_dashboard.today_briefing_service import fetch_stance_flips

    pg = MagicMock()
    pg.execute_query.return_value = []
    fetch_stance_flips(pg, days=2, limit=20)

    sql, params = pg.execute_query.call_args[0]
    assert "source <> ALL(%s)" in sql
    assert params == (2, list(EVENT_STANCE_SOURCES), 20)
    assert SOURCE in EVENT_STANCE_SOURCES
