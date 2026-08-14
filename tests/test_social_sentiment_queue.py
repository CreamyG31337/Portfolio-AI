"""Social sentiment AI pipeline: queue wiring and session lifecycle.

Covers the two failures that kept social_sentiment_analysis empty for seven
months -- nothing enqueued the work, and a session that could not be analyzed
stayed pending forever at the head of an oldest-first queue.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from web_dashboard.scheduler.ai_task_workers import (
    QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS,
    build_task_handlers,
    enqueue_social_sentiment_analysis_tasks,
    social_sentiment_analysis_task_handler,
)


class FakeSupabase:
    def __init__(self):
        self.calls = []

    def rpc(self, function_name, payload):
        self.calls.append((function_name, payload))
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class FakePostgres:
    """Minimal PostgresClient stand-in driven by canned query results."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.queries = []
        self.updates = []

    def execute_query(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))
        return self.results.pop(0) if self.results else []

    def execute_update(self, query, params=None):
        self.updates.append((" ".join(query.split()), params))
        return 1


# --- enqueue -----------------------------------------------------------------


def test_enqueue_uses_session_id_as_target_key():
    client = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_social_sentiment_analysis_tasks(
        client, [11, 12], priority=7, enqueued_by="backfill", max_attempts=5
    )

    assert stats == {"attempted": 2, "enqueued": 2, "failed": 0}
    assert len(client.supabase.calls) == 2
    fn, payload = client.supabase.calls[0]
    assert fn == "enqueue_ai_task"
    assert payload["p_analysis_type"] == QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS
    # target_key drives active-row dedupe, so it must be the session id.
    assert payload["p_target_key"] == "11"
    assert payload["p_payload"]["session_id"] == 11
    assert payload["p_priority"] == 7
    assert payload["p_max_attempts"] == 5


def test_enqueue_counts_bad_ids_as_failed_without_raising():
    client = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_social_sentiment_analysis_tasks(client, [5, "nope", 0, -3])

    assert stats["enqueued"] == 1
    assert stats["failed"] == 3


def test_handler_registered_only_when_job_enabled():
    assert QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS not in build_task_handlers(["ticker_analysis"])

    handlers = build_task_handlers([QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS])
    assert handlers[QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS] is social_sentiment_analysis_task_handler


def test_handler_rejects_task_without_session_id():
    with pytest.raises(ValueError, match="missing session_id"):
        social_sentiment_analysis_task_handler({"payload": {}, "target_key": "abc"}, "glm")


# --- session lifecycle -------------------------------------------------------


def _service(postgres, ollama=None):
    """Build a SocialSentimentService without touching real clients."""
    from web_dashboard.social_service import SocialSentimentService

    service = SocialSentimentService.__new__(SocialSentimentService)
    service.postgres = postgres
    service.ollama = ollama
    service.supabase = None
    return service


def test_empty_session_is_retired_not_left_pending():
    # No analysis yet, then a session whose posts are gone (metrics deleted).
    postgres = FakePostgres([[], [{"id": 7, "ticker": "AAA", "platform": "reddit", "post_contents": []}]])
    service = _service(postgres)

    assert service.analyze_sentiment_session(7) is None

    retire = [u for u in postgres.updates if "needs_ai_analysis = FALSE" in u[0]]
    assert retire, "an unanalyzable session must be retired, or it blocks the queue"
    assert retire[0][1] == (7,)


def test_already_analyzed_session_does_not_call_the_model():
    postgres = FakePostgres([[{"id": 99}]])
    ollama = SimpleNamespace(
        generate_completion=lambda **kw: pytest.fail("must not re-analyze")
    )
    service = _service(postgres, ollama)

    assert service.analyze_sentiment_session(7) is None
    assert any("needs_ai_analysis = FALSE" in u[0] for u in postgres.updates)


def test_analysis_makes_one_model_call_and_asks_for_tickers():
    calls = []

    def generate_completion(**kwargs):
        calls.append(kwargs)
        return (
            '{"sentiment_score": 1.5, "confidence_score": 0.8, '
            '"sentiment_label": "BULLISH", "summary": "s", "key_themes": ["t"], '
            '"reasoning": "r", "tickers": [{"ticker": "AAA", "confidence": 0.9}]}'
        )

    postgres = FakePostgres([
        [],                                                          # no existing analysis
        [{"id": 7, "ticker": "AAA", "platform": "combined",
          "platforms": ["reddit", "stocktwits"],
          "session_start": datetime(2026, 8, 1, tzinfo=timezone.utc),
          "post_contents": ["AAA looks strong"]}],                   # session
        [{"id": 4242}],                                              # insert RETURNING id
    ])
    service = _service(postgres, SimpleNamespace(generate_completion=generate_completion))
    service._lookup_company_info = lambda t: {"company_name": "A Co", "sector": "Tech"}

    result = service.analyze_sentiment_session(7, model="glm-5.2")

    # Ticker extraction used to be a second round-trip over the same content.
    assert len(calls) == 1
    assert '"tickers"' in calls[0]["prompt"]
    # A merged session must tell the model which platforms it is looking at.
    assert "reddit, stocktwits" in calls[0]["prompt"]
    assert calls[0]["model"] == "glm-5.2"
    assert result["sentiment_label"] == "BULLISH"
    assert result["model_used"] == "glm-5.2"
    assert any("INSERT INTO extracted_tickers" in u[0] for u in postgres.updates)


def test_injected_client_overrides_service_default():
    injected = []
    postgres = FakePostgres([
        [],
        [{"id": 7, "ticker": "AAA", "platform": "combined",
          "platforms": ["reddit"],
          "session_start": datetime(2026, 8, 1, tzinfo=timezone.utc),
          "post_contents": ["x"]}],
        [{"id": 1}],
    ])

    def injected_completion(**kwargs):
        injected.append(kwargs)
        return '{"sentiment_label": "NEUTRAL", "tickers": []}'

    shared = SimpleNamespace(
        generate_completion=lambda **kw: pytest.fail("worker must not use the shared client")
    )
    service = _service(postgres, shared)

    service.analyze_sentiment_session(
        7, ollama=SimpleNamespace(generate_completion=injected_completion), model="granite4.1:8b"
    )

    assert len(injected) == 1


def test_persist_extracted_tickers_skips_junk_symbols():
    postgres = FakePostgres()
    service = _service(postgres)
    service._lookup_company_info = lambda t: {"company_name": None, "sector": None}

    inserted = service._persist_extracted_tickers(1, [
        {"ticker": "AAA"},
        {"ticker": "aaa"},                       # same symbol, different case
        {"ticker": "THIS IS NOT A TICKER AT ALL"},  # longer than VARCHAR(20)
        {"ticker": ""},
        "not-a-dict",
    ])

    assert inserted == 1


def test_persist_extracted_tickers_tolerates_non_list():
    service = _service(FakePostgres())
    assert service._persist_extracted_tickers(1, None) == 0
    assert service._persist_extracted_tickers(1, {"ticker": "AAA"}) == 0


# --- collector: post identity, timestamps, dedupe -----------------------------


def test_stable_post_id_prefers_native_id():
    service = _service(FakePostgres())
    assert service._stable_post_id("reddit", {"id": "abc123", "url": "u"}) == "abc123"


def test_stable_post_id_is_stable_across_processes():
    """The old fallback was str(hash(url)), which Python reseeds per process."""
    service = _service(FakePostgres())
    post = {"url": "https://reddit.com/r/stocks/comments/xyz/title/"}

    first = service._stable_post_id("reddit", post)
    second = service._stable_post_id("reddit", post)

    assert first == second
    # Precomputed from sha1 of the URL -- pins the value across interpreters.
    import hashlib
    expected = "reddit:" + hashlib.sha1(post["url"].encode("utf-8")).hexdigest()
    assert first == expected


def test_stable_post_id_falls_back_to_content_digest():
    service = _service(FakePostgres())
    got = service._stable_post_id("stocktwits", {"body": "hello"})
    assert got.startswith("stocktwits:c:")


def test_stable_post_id_fits_column_width():
    service = _service(FakePostgres())
    got = service._stable_post_id("reddit", {"id": "x" * 500})
    assert len(got) <= 100


def test_post_timestamp_never_returns_epoch():
    """Missing created_utc used to yield 1970-01-01, collapsing every Reddit
    post for a ticker into a single session."""
    from datetime import datetime, timezone

    service = _service(FakePostgres())
    observed = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    assert service._post_timestamp(0, observed) is observed
    assert service._post_timestamp(None, observed) is observed
    assert service._post_timestamp("garbage", observed) is observed

    real = service._post_timestamp(1754049600, observed)
    assert real.startswith("2025-08-01T")


def test_reddit_parse_carries_id_and_author():
    """id/author are needed downstream for dedupe and attribution."""
    from datetime import datetime, timedelta, timezone

    service = _service(FakePostgres())
    now = datetime.now(timezone.utc)
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "t3_abc",
                        "author": "someuser",
                        "subreddit": "stocks",
                        "title": "$AAA to the moon",
                        "selftext": "",
                        "created_utc": now.timestamp(),
                        "url": "https://reddit.com/x",
                        "ups": 5,
                        "num_comments": 2,
                    }
                }
            ]
        }
    }

    posts = service._parse_reddit_search_posts(payload, "AAA", now - timedelta(days=7))

    assert len(posts) == 1
    assert posts[0]["id"] == "t3_abc"
    assert posts[0]["author"] == "someuser"
    assert posts[0]["created_utc"]


# --- session grouping ---------------------------------------------------------


def _post(pid, ticker, platform, when, metric_id=1, engagement=0):
    return {
        "id": pid, "metric_id": metric_id, "ticker": ticker,
        "platform": platform, "posted_at": when, "engagement_score": engagement,
    }


def test_sessions_merge_platforms_within_one_day():
    """A ticker's StockTwits and Reddit chatter for a day is one conversation.

    The old grouping was (ticker, platform, 4-hour window), which split the
    same day into up to 12 separate LLM calls.
    """
    day1 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    postgres = FakePostgres([
        [
            _post(1, "AAA", "reddit", day1.replace(hour=10), engagement=5),
            _post(2, "AAA", "stocktwits", day1.replace(hour=20), engagement=3),
            _post(3, "AAA", "reddit", day1.replace(hour=1) + timedelta(days=1)),
        ],
        [], [{"id": 100}],   # day 1: no existing session -> insert
        [], [{"id": 101}],   # day 2: no existing session -> insert
    ])
    service = _service(postgres)

    result = service.create_sentiment_sessions()

    # Two calendar days, not two platforms x six windows.
    assert result["sessions_created"] == 2
    assert result["posts_assigned"] == 3

    inserts = [q for q in postgres.queries if "INSERT INTO sentiment_sessions" in q[0]]
    assert len(inserts) == 2
    ticker, platform, start, end, post_count, engagement = inserts[0][1]
    assert (ticker, platform) == ("AAA", "combined")
    assert start == day1
    assert end == day1 + timedelta(days=1)
    assert post_count == 2          # both platforms in one session
    assert engagement == 8


def test_sessions_reuse_existing_session_for_same_ticker_day():
    """Late-arriving posts join the existing session instead of forking one."""
    day1 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    postgres = FakePostgres([
        [_post(9, "AAA", "reddit", day1.replace(hour=23), engagement=4)],
        [{"id": 500}],   # a session already covers this ticker/day
    ])
    service = _service(postgres)

    result = service.create_sentiment_sessions()

    assert result["sessions_created"] == 0
    assert result["posts_assigned"] == 1
    assert not [q for q in postgres.queries if "INSERT INTO sentiment_sessions" in q[0]]
    bumped = [u for u in postgres.updates if "post_count = post_count" in u[0]]
    assert bumped and bumped[0][1] == (1, 4, 500)


def test_sessions_claim_posts_via_session_id():
    """social_posts.session_id is the authoritative link, not the metric hop."""
    day1 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    postgres = FakePostgres([
        [_post(1, "AAA", "reddit", day1.replace(hour=10))],
        [], [{"id": 100}],
    ])
    service = _service(postgres)

    service.create_sentiment_sessions()

    claim = [u for u in postgres.updates if "UPDATE social_posts SET session_id" in u[0]]
    assert claim, "posts must be claimed by session_id"
    assert claim[0][1] == (100, [1])
