"""Tests for the social_sentiment_analysis queue migration (Q4g).

Covers the queue plumbing (enqueue helper, task handler, handler registration)
and the social_service behaviour it depends on: one LLM call per session,
retiring sessions that can never be analyzed, stable post identity, and
one-session-per-ticker-per-day grouping across platforms.

No DB, network, or model access — everything is faked.
"""

import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import MagicMock, patch

import pytest

WEB_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_dashboard"
if str(WEB_DASHBOARD_PATH) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_PATH))


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakePostgres:
    """Records SQL and replays canned results matched on a substring."""

    def __init__(self, responses: Optional[Sequence[Tuple[str, Any]]] = None):
        self.responses: List[Tuple[str, Any]] = list(responses or [])
        self.queries: List[Tuple[str, Any]] = []
        self.updates: List[Tuple[str, Any]] = []

    def _match(self, sql: str) -> Any:
        for needle, result in self.responses:
            if needle in " ".join(sql.split()):
                return result
        return []

    def execute_query(self, sql: str, params: Any = None) -> Any:
        self.queries.append((" ".join(sql.split()), params))
        return self._match(sql)

    def execute_update(self, sql: str, params: Any = None) -> Any:
        self.updates.append((" ".join(sql.split()), params))
        return 1

    def sql_matching(self, needle: str, *, updates: bool = False) -> List[Tuple[str, Any]]:
        source = self.updates if updates else self.queries
        return [(sql, params) for sql, params in source if needle in sql]


def make_service(postgres: Optional[FakePostgres] = None, ollama: Any = None):
    """Build a SocialSentimentService without touching __init__ (no clients)."""
    from social_service import SocialSentimentService

    service = SocialSentimentService.__new__(SocialSentimentService)
    service.postgres = postgres or FakePostgres()
    service.supabase = MagicMock(name="supabase")
    service.ollama = ollama
    service.reddit = MagicMock(name="reddit")
    service.web_fetch = MagicMock(name="web_fetch")
    return service


def make_llm(response: str) -> MagicMock:
    client = MagicMock(name="ollama_client")
    client.generate_completion.return_value = response
    return client


ANALYSIS_JSON = """
{
    "sentiment_score": 1.2,
    "confidence_score": 0.8,
    "sentiment_label": "BULLISH",
    "summary": "Broadly positive",
    "key_themes": ["earnings"],
    "reasoning": "Posts cite a strong beat",
    "tickers": [
        {"ticker": "AAPL", "confidence": 0.9, "context": "AAPL beat", "is_primary": true}
    ]
}
"""


def session_row(**overrides: Any) -> Dict[str, Any]:
    row = {
        "id": 42,
        "ticker": "AAPL",
        "platform": "combined",
        "session_start": datetime(2026, 8, 12, tzinfo=UTC),
        "post_contents": ["AAPL crushed earnings"],
        "platforms": ["reddit", "stocktwits"],
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------
# Enqueue helper
# --------------------------------------------------------------------------


def test_enqueue_uses_session_id_as_target_key():
    from scheduler.ai_task_workers import (
        QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS,
        enqueue_social_sentiment_analysis_tasks,
    )

    with patch("scheduler.ai_task_workers.enqueue_ai_task") as mock_enqueue:
        stats = enqueue_social_sentiment_analysis_tasks(
            MagicMock(), [101, 202], priority=10, enqueued_by="cron", max_attempts=5
        )

    assert stats == {"attempted": 2, "enqueued": 2, "failed": 0}
    target_keys = [c.kwargs["target_key"] for c in mock_enqueue.call_args_list]
    assert target_keys == ["101", "202"]

    first = mock_enqueue.call_args_list[0].kwargs
    assert first["analysis_type"] == QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS
    assert first["payload"]["session_id"] == 101
    assert first["priority"] == 10
    assert first["max_attempts"] == 5


def test_enqueue_counts_bad_ids_as_failed_without_raising():
    from scheduler.ai_task_workers import enqueue_social_sentiment_analysis_tasks

    with patch("scheduler.ai_task_workers.enqueue_ai_task") as mock_enqueue:
        stats = enqueue_social_sentiment_analysis_tasks(
            MagicMock(), ["not-an-int", None, 0, -5, 7]
        )

    assert stats["attempted"] == 5
    assert stats["enqueued"] == 1
    assert stats["failed"] == 4
    assert mock_enqueue.call_count == 1
    assert mock_enqueue.call_args.kwargs["target_key"] == "7"


def test_enqueue_survives_a_failing_task_and_keeps_going():
    """One bad enqueue must not abort the rest of the batch."""
    from scheduler.ai_task_workers import enqueue_social_sentiment_analysis_tasks

    with patch("scheduler.ai_task_workers.enqueue_ai_task") as mock_enqueue:
        mock_enqueue.side_effect = [RuntimeError("rpc down"), {"ok": True}]
        stats = enqueue_social_sentiment_analysis_tasks(MagicMock(), [1, 2])

    assert stats == {"attempted": 2, "enqueued": 1, "failed": 1}


# --------------------------------------------------------------------------
# Handler registration + argument validation
# --------------------------------------------------------------------------


def test_handler_registered_only_when_job_enabled():
    from scheduler.ai_task_workers import (
        QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS,
        build_task_handlers,
        social_sentiment_analysis_task_handler,
    )

    assert QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS not in build_task_handlers([])

    handlers = build_task_handlers([QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS])
    assert (
        handlers[QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS]
        is social_sentiment_analysis_task_handler
    )


@pytest.mark.parametrize(
    "task",
    [
        {"payload": {}, "target_key": None},
        {"payload": {}, "target_key": "not-an-int"},
        {"payload": {"session_id": "abc"}, "target_key": "abc"},
    ],
)
def test_handler_rejects_task_without_session_id(task):
    from scheduler.ai_task_workers import social_sentiment_analysis_task_handler

    with pytest.raises(ValueError):
        social_sentiment_analysis_task_handler(task, "ollama_primary")


# --------------------------------------------------------------------------
# analyze_sentiment_session
# --------------------------------------------------------------------------


def test_empty_session_is_retired_not_left_pending():
    """A session with no recoverable posts must not block the oldest-first queue."""
    postgres = FakePostgres(
        [
            ("FROM social_sentiment_analysis WHERE session_id", []),
            ("FROM sentiment_sessions ss", [session_row(post_contents=[])]),
        ]
    )
    llm = make_llm(ANALYSIS_JSON)
    service = make_service(postgres, ollama=llm)

    result = service.analyze_sentiment_session(42, ollama=llm, model="test-model")

    assert result is None
    llm.generate_completion.assert_not_called()
    retire = postgres.sql_matching("needs_ai_analysis = FALSE", updates=True)
    assert retire, "session with no content should be retired"
    assert retire[0][1] == (42,)


def test_already_analyzed_session_does_not_call_the_model():
    postgres = FakePostgres(
        [("FROM social_sentiment_analysis WHERE session_id", [{"id": 7}])]
    )
    llm = make_llm(ANALYSIS_JSON)
    service = make_service(postgres, ollama=llm)

    result = service.analyze_sentiment_session(42, ollama=llm, model="test-model")

    assert result is None
    llm.generate_completion.assert_not_called()
    assert postgres.sql_matching("needs_ai_analysis = FALSE", updates=True)


def test_analysis_makes_one_model_call_and_asks_for_tickers():
    """Sentiment + tickers come back together; the old code paid for two calls."""
    postgres = FakePostgres(
        [
            ("FROM social_sentiment_analysis WHERE session_id", []),
            ("FROM sentiment_sessions ss", [session_row()]),
            ("INSERT INTO social_sentiment_analysis", [{"id": 900}]),
        ]
    )
    llm = make_llm(ANALYSIS_JSON)
    service = make_service(postgres, ollama=llm)
    service._lookup_company_info = lambda ticker: {
        "company_name": "Apple Inc.",
        "sector": "Tech",
    }

    result = service.analyze_sentiment_session(42, ollama=llm, model="test-model")

    assert llm.generate_completion.call_count == 1
    prompt = llm.generate_completion.call_args.kwargs["prompt"]
    assert '"tickers"' in prompt, "single call must also request ticker extraction"
    assert "AAPL crushed earnings" in prompt

    assert result is not None
    assert result["analysis_id"] == 900
    assert result["sentiment_label"] == "BULLISH"
    assert result["model_used"] == "test-model"

    assert postgres.sql_matching("INSERT INTO extracted_tickers", updates=True)
    assert postgres.sql_matching("needs_ai_analysis = FALSE", updates=True)


def test_injected_client_overrides_service_default():
    """Queue workers pin one backend per worker, so the passed client must win."""
    postgres = FakePostgres(
        [
            ("FROM social_sentiment_analysis WHERE session_id", []),
            ("FROM sentiment_sessions ss", [session_row()]),
            ("INSERT INTO social_sentiment_analysis", [{"id": 901}]),
        ]
    )
    default_llm = make_llm(ANALYSIS_JSON)
    injected_llm = make_llm(ANALYSIS_JSON)
    service = make_service(postgres, ollama=default_llm)
    service._lookup_company_info = lambda ticker: {}

    service.analyze_sentiment_session(42, ollama=injected_llm, model="glm-4.6")

    injected_llm.generate_completion.assert_called_once()
    default_llm.generate_completion.assert_not_called()
    assert injected_llm.generate_completion.call_args.kwargs["model"] == "glm-4.6"


# --------------------------------------------------------------------------
# _persist_extracted_tickers
# --------------------------------------------------------------------------


def test_persist_extracted_tickers_skips_junk_symbols():
    postgres = FakePostgres()
    service = make_service(postgres)
    service._lookup_company_info = lambda ticker: {}

    inserted = service._persist_extracted_tickers(
        5,
        [
            {"ticker": "AAPL"},
            {"ticker": "aapl"},                       # dupe after upper()
            {"ticker": ""},                           # empty
            {"ticker": "A" * 25},                     # exceeds VARCHAR(20)
            "not-a-dict",                             # wrong shape
            {"ticker": "MSFT"},
        ],
    )

    assert inserted == 2
    rows = postgres.sql_matching("INSERT INTO extracted_tickers", updates=True)
    symbols = [params[1] for _, params in rows]
    assert symbols == ["AAPL", "MSFT"]


@pytest.mark.parametrize("tickers", [None, {}, "AAPL", 7])
def test_persist_extracted_tickers_tolerates_non_list(tickers):
    service = make_service()
    assert service._persist_extracted_tickers(5, tickers) == 0


# --------------------------------------------------------------------------
# _stable_post_id
# --------------------------------------------------------------------------


def test_stable_post_id_prefers_native_id():
    service = make_service()
    post = {"id": "t3_abc123", "url": "https://example.com/x", "body": "hi"}
    assert service._stable_post_id("reddit", post) == "t3_abc123"


def test_stable_post_id_is_stable_across_processes():
    """The old fallback used builtin hash(), which is seed-randomized per run."""
    service = make_service()
    url = "https://reddit.com/r/stocks/comments/xyz"
    expected = f"reddit:{hashlib.sha1(url.encode('utf-8')).hexdigest()}"[:100]

    assert service._stable_post_id("reddit", {"url": url}) == expected
    # Same input, second call: identical, and independent of PYTHONHASHSEED.
    assert service._stable_post_id("reddit", {"url": url}) == expected
    assert str(hash(url)) not in service._stable_post_id("reddit", {"url": url})


def test_stable_post_id_falls_back_to_content_digest():
    service = make_service()
    body = "no id and no url, just text"
    expected = f"stocktwits:c:{hashlib.sha1(body.encode('utf-8')).hexdigest()}"[:100]

    assert service._stable_post_id("stocktwits", {"body": body}) == expected
    # Identical text from a repeated poll collapses to the same id.
    assert service._stable_post_id("stocktwits", {"title": body}) == expected


def test_stable_post_id_fits_column_width():
    service = make_service()
    for post in ({"id": "x" * 500}, {"url": "u" * 500}, {"body": "b" * 500}):
        assert len(service._stable_post_id("reddit", post)) <= 100


# --------------------------------------------------------------------------
# _post_timestamp
# --------------------------------------------------------------------------


@pytest.mark.parametrize("created_utc", [None, 0, "", "garbage"])
def test_post_timestamp_never_returns_epoch(created_utc):
    """Epoch 0 collapsed every affected post into one 1970-01-01 session."""
    service = make_service()
    observed = "2026-08-13T10:00:00+00:00"

    resolved = service._post_timestamp(created_utc, observed)

    assert resolved == observed
    assert "1970" not in str(resolved)


def test_post_timestamp_uses_platform_time_when_present():
    service = make_service()
    created = datetime(2026, 8, 12, 15, 30, tzinfo=UTC)

    resolved = service._post_timestamp(created.timestamp(), "2026-08-13T10:00:00+00:00")

    assert resolved.startswith("2026-08-12T15:30")


# --------------------------------------------------------------------------
# Reddit parsing
# --------------------------------------------------------------------------


def test_reddit_parse_carries_id_and_author():
    """Storage keys on post identity, so the parser must not drop id/author."""
    service = make_service()
    now = datetime.now(UTC)
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "$AAPL looks strong",
                        "selftext": "earnings beat",
                        "ups": 10,
                        "num_comments": 2,
                        "created_utc": now.timestamp(),
                        "url": "https://example.com/aapl",
                        "subreddit": "stocks",
                        "id": "t3_abc123",
                        "author": "someredditor",
                    }
                }
            ]
        }
    }

    posts = service._parse_reddit_search_posts(payload, "AAPL", now - timedelta(days=7))

    assert len(posts) == 1
    assert posts[0]["id"] == "t3_abc123"
    assert posts[0]["author"] == "someredditor"


# --------------------------------------------------------------------------
# create_sentiment_sessions
# --------------------------------------------------------------------------


def _unassigned(post_id: int, platform: str, ticker: str = "AAPL", day: int = 12):
    return {
        "id": post_id,
        "metric_id": 1000 + post_id,
        "ticker": ticker,
        "platform": platform,
        "posted_at": datetime(2026, 8, day, 14, 0, tzinfo=UTC),
        "engagement_score": 5,
    }


def test_sessions_merge_platforms_within_one_day():
    """Reddit + StockTwits for one ticker/day is one conversation, one session."""
    from social_service import SESSION_PLATFORM_COMBINED

    postgres = FakePostgres(
        [
            ("FROM social_posts sp", [_unassigned(1, "reddit"), _unassigned(2, "stocktwits")]),
            ("FROM sentiment_sessions WHERE ticker", []),
            ("INSERT INTO sentiment_sessions", [{"id": 77}]),
        ]
    )
    service = make_service(postgres)

    result = service.create_sentiment_sessions()

    assert result == {"sessions_created": 1, "posts_assigned": 2}
    inserts = postgres.sql_matching("INSERT INTO sentiment_sessions")
    assert len(inserts) == 1
    params = inserts[0][1]
    assert params[0] == "AAPL"
    assert params[1] == SESSION_PLATFORM_COMBINED
    assert params[4] == 2  # post_count covers both platforms


def test_sessions_reuse_existing_session_for_same_ticker_day():
    """Late-arriving posts join the existing session instead of spawning a rival."""
    postgres = FakePostgres(
        [
            ("FROM social_posts sp", [_unassigned(3, "reddit")]),
            ("FROM sentiment_sessions WHERE ticker", [{"id": 55}]),
        ]
    )
    service = make_service(postgres)

    result = service.create_sentiment_sessions()

    assert result["sessions_created"] == 0
    assert result["posts_assigned"] == 1
    assert not postgres.sql_matching("INSERT INTO sentiment_sessions")

    reopened = postgres.sql_matching("SET post_count = post_count", updates=True)
    assert reopened, "existing session should absorb the new posts"
    assert reopened[0][1] == (1, 5, 55)


def test_sessions_claim_posts_via_session_id():
    """Posts are claimed on social_posts.session_id, not via social_metrics."""
    postgres = FakePostgres(
        [
            ("FROM social_posts sp", [_unassigned(8, "reddit"), _unassigned(9, "reddit")]),
            ("FROM sentiment_sessions WHERE ticker", []),
            ("INSERT INTO sentiment_sessions", [{"id": 88}]),
        ]
    )
    service = make_service(postgres)

    service.create_sentiment_sessions()

    claims = postgres.sql_matching("UPDATE social_posts SET session_id", updates=True)
    assert len(claims) == 1
    session_id, post_ids = claims[0][1]
    assert session_id == 88
    assert post_ids == [8, 9]


def test_sessions_split_across_utc_days():
    """One session per ticker per UTC day — different days must not merge."""
    postgres = FakePostgres(
        [
            ("FROM social_posts sp", [_unassigned(4, "reddit", day=12), _unassigned(5, "reddit", day=13)]),
            ("FROM sentiment_sessions WHERE ticker", []),
            ("INSERT INTO sentiment_sessions", [{"id": 99}]),
        ]
    )
    service = make_service(postgres)

    result = service.create_sentiment_sessions()

    assert result["sessions_created"] == 2
    assert len(postgres.sql_matching("INSERT INTO sentiment_sessions")) == 2
