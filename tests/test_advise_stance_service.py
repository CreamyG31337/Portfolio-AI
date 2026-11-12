"""Tests for Today advise_pack stance ledger service (ROADMAP §2.8 Z3)."""

from unittest.mock import MagicMock, patch

import pytest

from web_dashboard.advise_stance_service import (
    DEFAULT_LIMIT,
    SOURCE,
    get_supported_funds,
    map_action_to_stance,
    normalize_score_to_confidence,
    record_advise_pack_stances,
)
from web_dashboard.scheduler.jobs_advise_pack_ledger import (
    JOB_ID,
    advise_pack_ledger_job,
)
from web_dashboard.today_briefing_service import build_advise_pack


def test_action_mapping_directional() -> None:
    """BUY/ADD/ACCUMULATE -> BULLISH; SELL/TRIM/EXIT/REDUCE -> BEARISH."""
    assert map_action_to_stance("BUY") == "BULLISH"
    assert map_action_to_stance("buy") == "BULLISH"
    assert map_action_to_stance("ADD") == "BULLISH"
    assert map_action_to_stance("ACCUMULATE") == "BULLISH"

    assert map_action_to_stance("SELL") == "BEARISH"
    assert map_action_to_stance("sell") == "BEARISH"
    assert map_action_to_stance("TRIM") == "BEARISH"
    assert map_action_to_stance("EXIT") == "BEARISH"
    assert map_action_to_stance("REDUCE") == "BEARISH"


def test_action_mapping_nondirectional() -> None:
    """RISK/WATCH/HOLD/other are kept as-is (non-directional)."""
    assert map_action_to_stance("RISK") == "RISK"
    assert map_action_to_stance("WATCH") == "WATCH"
    assert map_action_to_stance("HOLD") == "HOLD"
    assert map_action_to_stance("CUSTOM_ACTION") == "CUSTOM_ACTION"
    assert map_action_to_stance("") == ""


def test_score_normalization() -> None:
    """Scores on 0..1, 0..10, and 0..100 scales are normalised to 0.0..1.0."""
    assert normalize_score_to_confidence(0.85) == 0.85
    assert normalize_score_to_confidence(85.0) == 0.85
    assert normalize_score_to_confidence(7.5) == 0.75
    assert normalize_score_to_confidence(0.0) == 0.0
    assert normalize_score_to_confidence(100.0) == 1.0
    assert normalize_score_to_confidence(None) is None
    assert normalize_score_to_confidence("not_a_number") is None
    assert normalize_score_to_confidence(-5.0) == 0.0
    assert normalize_score_to_confidence(150.0) == 1.0


@patch("web_dashboard.advise_stance_service.record_stance_safe", return_value=True)
@patch("web_dashboard.advise_stance_service.build_advise_pack")
def test_state_dedupe_call_shape(mock_build: MagicMock, mock_record: MagicMock) -> None:
    """Advise pack rows write with state dedupe (dedupe_on_source_ref=False) and expected metadata."""
    mock_build.return_value = (
        [
            {
                "ticker": "NVDA",
                "action": "BUY",
                "score": 82.5,
                "reasons": ["queue:BUY", "queue_ai:ALIGNED", "meta_conflict", "fourth_reason"],
            }
        ],
        "advise",
    )
    pg = MagicMock()
    sb = MagicMock()

    stats = record_advise_pack_stances(pg, sb, funds=["Project Chimera"])

    assert stats["funds"] == 1
    assert stats["rows_seen"] == 1
    assert stats["written"] == 1
    assert stats["skipped_nondirectional"] == 0
    assert stats["errors"] == 0

    assert mock_record.call_count == 1
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["ticker"] == "NVDA"
    assert call_kwargs["source"] == SOURCE
    assert call_kwargs["stance"] == "BULLISH"
    assert call_kwargs["confidence"] is None  # drifting score must not defeat state dedupe
    assert call_kwargs["metadata"]["score"] == 0.825
    assert call_kwargs["fund_key"] == "Project Chimera"
    assert call_kwargs["dedupe_on_source_ref"] is False
    assert call_kwargs["metadata"] == {
        "advise_source": "advise",
        "rank": 1, "score": 0.825,
        "action": "BUY",
        "reasons": ["queue:BUY", "queue_ai:ALIGNED", "meta_conflict"],
    }


@patch("web_dashboard.advise_stance_service.record_stance_safe", return_value=True)
@patch("web_dashboard.advise_stance_service.build_advise_pack")
def test_fallback_candidate_rows(mock_build: MagicMock, mock_record: MagicMock) -> None:
    """Rows from signal_fallback (using 'advise' key and 'reason' string) map and record properly."""
    mock_build.return_value = (
        [
            {
                "ticker": "TSLA",
                "advise": "SELL",
                "confidence": 0.72,
                "reason": "signal:SELL fear=HIGH",
            }
        ],
        "signal_fallback",
    )
    pg = MagicMock()
    sb = MagicMock()

    stats = record_advise_pack_stances(pg, sb, funds=[None])

    assert stats["funds"] == 1
    assert stats["rows_seen"] == 1
    assert stats["written"] == 1
    assert stats["errors"] == 0

    assert mock_record.call_count == 1
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["ticker"] == "TSLA"
    assert call_kwargs["source"] == SOURCE
    assert call_kwargs["stance"] == "BEARISH"
    assert call_kwargs["confidence"] is None
    assert call_kwargs["metadata"]["score"] == 0.72
    assert call_kwargs["fund_key"] == ""
    assert call_kwargs["dedupe_on_source_ref"] is False
    assert call_kwargs["metadata"] == {
        "advise_source": "signal_fallback",
        "rank": 1, "score": 0.72,
        "action": "SELL",
        "reasons": ["signal:SELL fear=HIGH"],
    }


@patch("web_dashboard.advise_stance_service.record_stance_safe", return_value=True)
@patch("web_dashboard.advise_stance_service.build_advise_pack")
def test_nondirectional_stances_handling(mock_build: MagicMock, mock_record: MagicMock) -> None:
    """Non-directional stances (e.g. RISK, WATCH) are recorded as-is by default; skipped if requested."""
    mock_build.return_value = (
        [
            {"ticker": "ABC", "action": "RISK", "score": 60.0, "reasons": ["high_fear"]},
            {"ticker": "XYZ", "action": "WATCH", "score": 50.0, "reasons": ["monitor"]},
        ],
        "advise",
    )
    pg = MagicMock()
    sb = MagicMock()

    # Default: record as-is
    stats = record_advise_pack_stances(pg, sb, funds=["TEST"], skip_nondirectional=False)
    assert stats["rows_seen"] == 2
    assert stats["written"] == 2
    assert stats["skipped_nondirectional"] == 0
    assert mock_record.call_count == 2
    assert mock_record.call_args_list[0].kwargs["stance"] == "RISK"
    assert mock_record.call_args_list[1].kwargs["stance"] == "WATCH"

    mock_record.reset_mock()

    # With skip_nondirectional=True: skip non-directional
    stats_skip = record_advise_pack_stances(pg, sb, funds=["TEST"], skip_nondirectional=True)
    assert stats_skip["rows_seen"] == 2
    assert stats_skip["written"] == 0
    assert stats_skip["skipped_nondirectional"] == 2
    mock_record.assert_not_called()


@patch("web_dashboard.advise_stance_service.record_stance_safe", return_value=True)
@patch("web_dashboard.advise_stance_service.build_advise_pack")
def test_per_fund_error_isolation(mock_build: MagicMock, mock_record: MagicMock) -> None:
    """Failure building pack for one fund is isolated and does not stop other funds."""
    def _flaky_build(pg, sb, fund=None, limit=DEFAULT_LIMIT):
        if fund == "FailingFund":
            raise RuntimeError("DB connection dropped for FailingFund")
        return (
            [{"ticker": "AAPL", "action": "BUY", "score": 90.0, "reasons": ["strong"]}],
            "advise",
        )

    mock_build.side_effect = _flaky_build
    pg = MagicMock()
    sb = MagicMock()

    stats = record_advise_pack_stances(pg, sb, funds=["FailingFund", "Project Chimera"])

    assert stats["errors"] == 1
    assert stats["funds"] == 1
    assert stats["rows_seen"] == 1
    assert stats["written"] == 1
    assert mock_record.call_count == 1
    assert mock_record.call_args.kwargs["fund_key"] == "Project Chimera"


@patch("web_dashboard.scheduler.jobs_advise_pack_ledger.log_job_execution")
@patch("utils.job_tracking.mark_job_failed")
@patch("utils.job_tracking.mark_job_started")
@patch("web_dashboard.advise_stance_service.record_advise_pack_stances")
def test_job_fails_when_all_funds_fail(
    mock_record_stances: MagicMock,
    mock_started: MagicMock,
    mock_failed: MagicMock,
    mock_log: MagicMock,
) -> None:
    """When all funds error, advise_pack_ledger_job marks the job failed (scheduler jobs don't re-raise)."""
    mock_record_stances.return_value = {
        "funds": 0,
        "rows_seen": 0,
        "written": 0,
        "skipped_nondirectional": 0,
        "errors": 2,
    }

    advise_pack_ledger_job()

    mock_started.assert_called_once()
    mock_failed.assert_called_once()
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] is False  # success=False
    assert "failed for all funds" in mock_log.call_args[0][2]


@patch("web_dashboard.advise_stance_service.build_advise_pack")
def test_default_records_all_funds_pack_only(mock_build: MagicMock) -> None:
    """Default run records only Today's all-funds pack, so calls aren't double-counted per fund."""
    from web_dashboard.advise_stance_service import record_advise_pack_stances as rec

    mock_build.return_value = ([], "none")
    rec(MagicMock(), MagicMock(), dry_run=True)
    assert mock_build.call_count == 1
    assert mock_build.call_args.kwargs["fund"] is None


@patch("web_dashboard.scheduler.jobs_advise_pack_ledger.log_job_execution")
@patch("utils.job_tracking.mark_job_completed")
@patch("utils.job_tracking.mark_job_started")
@patch("web_dashboard.advise_stance_service.record_advise_pack_stances")
def test_job_succeeds_when_funds_succeed(
    mock_record_stances: MagicMock,
    mock_started: MagicMock,
    mock_completed: MagicMock,
    mock_log: MagicMock,
) -> None:
    """When funds succeed, advise_pack_ledger_job marks completed and logs execution."""
    mock_record_stances.return_value = {
        "funds": 2,
        "rows_seen": 15,
        "written": 12,
        "skipped_nondirectional": 0,
        "errors": 0,
    }

    advise_pack_ledger_job()

    mock_started.assert_called_once()
    mock_completed.assert_called_once()
    mock_log.assert_called_once()
    assert mock_log.call_args[0][1] is True  # success=True


def test_get_supported_funds_fallback() -> None:
    """When DB query fails or returns empty, falls back gracefully."""
    sb = MagicMock()
    sb.supabase.table.side_effect = Exception("DB offline")
    sb.get_available_funds.return_value = []

    funds = get_supported_funds(sb)
    assert None in funds
    assert "Project Chimera" in funds


@patch("advise_service.rank_candidate_pack")
@patch("track_record_service.build_track_record_summary")
@patch("action_queue_service.build_action_queue_items")
def test_build_advise_pack_helper(
    mock_action_queue: MagicMock,
    mock_track_record: MagicMock,
    mock_rank: MagicMock,
) -> None:
    """build_advise_pack helper calls rank_candidate_pack and returns (pack, source)."""
    mock_action_queue.return_value = [{"ticker": "MSFT", "action": "BUY"}]
    mock_track_record.return_value = {"total_scored": 50}
    mock_rank.return_value = ([{"ticker": "MSFT", "advise": "BUY", "score": 80.0}], "advise")

    pg = MagicMock()
    pg.execute_query.return_value = []
    sb = MagicMock()

    pack, source = build_advise_pack(pg, sb, fund="TEST", limit=8)

    assert source == "advise"
    assert len(pack) == 1
    assert pack[0]["ticker"] == "MSFT"
    mock_rank.assert_called_once()
