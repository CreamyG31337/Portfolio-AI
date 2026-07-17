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
