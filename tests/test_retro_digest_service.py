"""Tests for weekly retro Mailgun digest (ROADMAP G5)."""

from unittest.mock import MagicMock, patch

import pytest

from web_dashboard.retro_digest_service import (
    build_weekly_retro_digest_html,
    get_retro_digest_recipients,
    retro_digest_enabled,
    send_weekly_retro_digest,
)


@pytest.fixture(autouse=True)
def _clear_account_recipient_env(monkeypatch) -> None:
    monkeypatch.delenv("RETRO_DIGEST_RECIPIENT_ACCOUNTS", raising=False)


def test_get_retro_digest_recipients_parses_env(monkeypatch) -> None:
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENTS", "a@test.com, b@test.com ")
    assert get_retro_digest_recipients() == ["a@test.com", "b@test.com"]


def test_get_retro_digest_recipients_resolves_dashboard_account(monkeypatch) -> None:
    monkeypatch.delenv("RETRO_DIGEST_RECIPIENTS", raising=False)
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENT_ACCOUNTS", "Lance Colton")
    client = MagicMock()
    client.supabase.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"full_name": "Lance Colton", "email": "current@test.com"}]
    )

    assert get_retro_digest_recipients(supabase_client=client) == ["current@test.com"]
    client.supabase.table.assert_called_once_with("user_profiles")


def test_get_retro_digest_recipients_skips_ambiguous_account(monkeypatch) -> None:
    monkeypatch.delenv("RETRO_DIGEST_RECIPIENTS", raising=False)
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENT_ACCOUNTS", "Lance Colton")
    client = MagicMock()
    client.supabase.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[
            {"full_name": "Lance Colton", "email": "one@test.com"},
            {"full_name": "lance colton", "email": "two@test.com"},
        ]
    )

    assert get_retro_digest_recipients(supabase_client=client) == []


def test_get_retro_digest_recipients_dedupes_direct_and_account(monkeypatch) -> None:
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENTS", "same@test.com")
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENT_ACCOUNTS", "Lance Colton")
    client = MagicMock()
    client.supabase.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"full_name": "Lance Colton", "email": "same@test.com"}]
    )

    assert get_retro_digest_recipients(supabase_client=client) == ["same@test.com"]


def test_get_retro_digest_recipients_dedupes_case_insensitive(monkeypatch) -> None:
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENTS", "Same@Test.com")
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENT_ACCOUNTS", "Lance Colton")
    client = MagicMock()
    client.supabase.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"full_name": "Lance Colton", "email": "same@test.com"}]
    )

    assert get_retro_digest_recipients(supabase_client=client) == ["Same@Test.com"]


def test_build_weekly_retro_digest_html_empty_data() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    with patch(
        "today_briefing_service.fetch_stance_flips",
        return_value=[],
    ), patch(
        "track_record_service.build_track_record_summary",
        return_value={
            "total_scored": 0,
            "hit_rate_by_source": {},
            "hit_rate_by_verdict": {},
            "best_calls": [],
            "worst_calls": [],
            "counts_by_source": {},
            "counts_by_verdict": {},
        },
    ):
        html = build_weekly_retro_digest_html(pg)
    assert "Weekly stance retro" in html
    assert "No stance flips" in html


def test_send_weekly_retro_digest_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("RETRO_DIGEST_RECIPIENTS", raising=False)
    result = send_weekly_retro_digest(MagicMock())
    assert result["skipped"] is True
    assert result["sent"] == 0


@patch("mailgun_outbound.send_mailgun_message")
@patch("mailgun_outbound.get_mailgun_outbound_params")
def test_send_weekly_retro_digest_sends(mock_params, mock_send, monkeypatch) -> None:
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENTS", "owner@test.com")
    mock_params.return_value = {"api_key": "k", "domain": "mg.test", "from_header": "x", "api_base": "u"}
    pg = MagicMock()
    pg.execute_query.return_value = []
    with patch(
        "today_briefing_service.fetch_stance_flips",
        return_value=[{"ticker": "AAA", "old_stance": "NEUTRAL", "new_stance": "BULLISH", "source": "ticker_meta_analysis"}],
    ), patch(
        "track_record_service.build_track_record_summary",
        return_value={
            "total_scored": 1,
            "hit_rate_by_source": {"ticker_meta_analysis": 1.0},
            "hit_rate_by_verdict": {},
            "best_calls": [],
            "worst_calls": [],
            "counts_by_source": {"ticker_meta_analysis": {"hits": 1, "scored": 1, "misses": 0, "unscoreable": 0}},
            "counts_by_verdict": {},
        },
    ):
        result = send_weekly_retro_digest(pg)
    assert result["sent"] == 1
    mock_send.assert_called_once()


def test_retro_digest_enabled_requires_mailgun(monkeypatch) -> None:
    monkeypatch.setenv("RETRO_DIGEST_RECIPIENTS", "owner@test.com")
    with patch("mailgun_outbound.get_mailgun_outbound_params", return_value=None):
        assert retro_digest_enabled() is False


def test_build_weekly_retro_digest_html_renders_idea_scorecard_tables() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    fake_scorecard = {
        "available": True,
        "overall": {"n": 15, "hit_rate_pct": 60.0, "mean_signed_excess_pct": 2.5},
        "by_direction": [
            {"stance": "BULLISH", "n": 10, "hit_rate_pct": 70.0, "mean_signed_excess_pct": 3.0},
            {"stance": "BEARISH", "n": 5, "hit_rate_pct": 40.0, "mean_signed_excess_pct": 1.5},
        ],
        "by_domain": [
            {"domain": "fool.com", "n": 10, "hit_rate_pct": 70.0, "mean_signed_excess_pct": 3.0},
        ],
        "by_article_type": [
            {"article_type": "Alpha Research", "n": 15, "hit_rate_pct": 60.0, "mean_signed_excess_pct": 2.5},
        ],
        "by_score_band": [
            {"band": "8+", "n": 5, "hit_rate_pct": 80.0, "mean_signed_excess_pct": 4.0},
            {"band": "6-7", "n": 10, "hit_rate_pct": 50.0, "mean_signed_excess_pct": 1.75},
        ],
    }

    with patch("today_briefing_service.fetch_stance_flips", return_value=[]), \
         patch("track_record_service.build_track_record_summary", return_value={"total_scored": 0}), \
         patch("web_dashboard.retro_digest_service.build_idea_scorecard", return_value=fake_scorecard):
        digest = build_weekly_retro_digest_html(pg, horizon_days=30)

    assert "Ideas scorecard (30d)" in digest
    assert "Overall: 60.0% hit rate, +2.50% mean signed excess (15 scored)" in digest
    assert "By direction:" in digest
    assert "BULLISH" in digest
    assert "BEARISH" in digest
    assert "By domain (min n=10):" in digest
    assert "fool.com" in digest
    assert "By score band:" in digest
    assert "8+" in digest
    assert "6-7" in digest


def test_build_weekly_retro_digest_html_renders_no_scored_ideas_when_empty_or_unavailable() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []

    # Case 1: unavailable
    with patch("today_briefing_service.fetch_stance_flips", return_value=[]), \
         patch("track_record_service.build_track_record_summary", return_value={"total_scored": 0}), \
         patch("web_dashboard.retro_digest_service.build_idea_scorecard", return_value={"available": False}):
        digest = build_weekly_retro_digest_html(pg, horizon_days=30)

    assert "Ideas scorecard (30d)" in digest
    assert "<p>No scored ideas yet.</p>" in digest

    # Case 2: available but overall.n == 0
    with patch("today_briefing_service.fetch_stance_flips", return_value=[]), \
         patch("track_record_service.build_track_record_summary", return_value={"total_scored": 0}), \
         patch(
             "web_dashboard.retro_digest_service.build_idea_scorecard",
             return_value={"available": True, "overall": {"n": 0, "hit_rate_pct": None, "mean_signed_excess_pct": None}},
         ):
        digest2 = build_weekly_retro_digest_html(pg, horizon_days=30)

    assert "Ideas scorecard (30d)" in digest2
    assert "<p>No scored ideas yet.</p>" in digest2


def test_build_weekly_retro_digest_html_splits_domain_table_if_over_10() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    domains = [
        {"domain": f"domain{i}.com", "n": 10, "hit_rate_pct": 50.0, "mean_signed_excess_pct": float(20 - i)}
        for i in range(12)
    ]
    fake_scorecard = {
        "available": True,
        "overall": {"n": 120, "hit_rate_pct": 50.0, "mean_signed_excess_pct": 2.0},
        "by_direction": [],
        "by_domain": domains,
        "by_article_type": [],
        "by_score_band": [],
    }

    with patch("today_briefing_service.fetch_stance_flips", return_value=[]), \
         patch("track_record_service.build_track_record_summary", return_value={"total_scored": 0}), \
         patch("web_dashboard.retro_digest_service.build_idea_scorecard", return_value=fake_scorecard):
        digest = build_weekly_retro_digest_html(pg, horizon_days=30)

    # Top 5 and bottom 5 included
    assert "domain0.com" in digest
    assert "domain4.com" in digest
    assert "domain7.com" in digest
    assert "domain11.com" in digest
    # Separator ellipsis included
    assert "…" in digest
