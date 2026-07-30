"""Unit tests for Phase K2 YouTube transcript -> research_articles (no network, no DB).

Covers the fixture VTT -> clean -> normalize -> ``save_article`` mock path, the
source-ROI grain of ``source``, the ``source_metadata`` contract, idempotent
re-runs on the canonical watch URL, queue vs inline enrichment, and soft-fails.
"""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yt"

# sys.path is set up by tests/conftest.py, which deliberately pins the repo root
# ahead of web_dashboard — do not re-insert them here.
from yt_captions import (  # noqa: E402
    CaptionFetchError,
    CaptionResult,
    parse_vtt_text,
)
from yt_articles import (  # noqa: E402
    ARTICLE_TYPE,
    IngestOutcome,
    content_max_chars,
    enrich_saved_transcript,
    ingest_video,
    normalize_caption_kind,
    normalize_transcript,
    published_at_from_upload_date,
    source_label,
    summarize_transcript,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixture_caption_result(**overrides: Any) -> CaptionResult:
    """A CaptionResult whose body is the real fixture VTT, cleaned like K1 does."""
    vtt = (FIXTURES / "me_at_zoo.en.vtt").read_text(encoding="utf-8")
    text = parse_vtt_text(vtt)
    assert text, "fixture VTT should clean to non-empty text"
    defaults: dict[str, Any] = {
        "video_id": "jNQXAC9IVRw",
        "text": text,
        "language": "en",
        "caption_kind": "vtt_auto",
        "fetch_source": "yt_dlp",
        "watch_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        "title": "Me at the zoo",
        "channel": "jawed",
        "channel_id": "UC4QobU6STFB0P71PMvOGN5A",
        "duration_s": 19,
        "upload_date": "20050424",
        "char_count": len(text),
    }
    defaults.update(overrides)
    return CaptionResult(**defaults)


def _summary_payload() -> dict[str, Any]:
    return {
        "summary": "- Elephants have long trunks.",
        "claims": ["The elephants have really long trunks"],
        "fact_check": "Consistent with the video body.",
        "conclusion": "Neutral for zoo-adjacent tickers.",
        "sentiment": "NEUTRAL",
        "sentiment_score": 0.0,
        "logic_check": "DATA_BACKED",
        "sectors": ["Consumer Discretionary"],
        "tickers": ["SEAS"],
    }


def _fake_repo(*, exists: bool = False, article_id: str = "art-1") -> MagicMock:
    repo = MagicMock()
    repo.article_exists.return_value = exists
    repo.save_article.return_value = article_id
    repo.update_article_analysis.return_value = True
    return repo


@pytest.fixture(autouse=True)
def _stub_ticker_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """``extract_and_validate_tickers`` hits yfinance/network; stub it everywhere."""
    import ticker_validator

    monkeypatch.setattr(
        ticker_validator,
        "extract_and_validate_tickers",
        lambda summary_data, title, content: list(summary_data.get("tickers") or []),
    )


# ---------------------------------------------------------------------------
# Field normalization
# ---------------------------------------------------------------------------


def test_article_type_is_the_exact_roi_string() -> None:
    # Source-ROI slices on this literal; a rename silently orphans history.
    assert ARTICLE_TYPE == "YouTube Transcript"


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"channel_id": "UC4QobU6STFB0P71PMvOGN5A"}, "youtube:UC4QobU6STFB0P71PMvOGN5A"),
        ({"handle": "@Fundamentals"}, "youtube:@Fundamentals"),
        ({"handle": "Fundamentals"}, "youtube:@Fundamentals"),
        ({"channel": "Bloomberg Television"}, "youtube:bloomberg-television"),
        ({}, "youtube:unknown"),
    ],
)
def test_source_label_is_channel_grain(kwargs: dict[str, Any], expected: str) -> None:
    assert source_label(**kwargs) == expected


def test_source_label_never_bare_host() -> None:
    """track_record_service groups ROI by ``source`` — one host label would mix channels."""
    for label in (
        source_label(channel_id="UCabc"),
        source_label(channel="Some Channel"),
        source_label(),
    ):
        assert label.startswith("youtube:")
        assert label != "youtube.com"


def test_source_label_fits_source_column() -> None:
    long_name = "A" * 400
    assert len(source_label(channel="".join(long_name))) <= 100


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("manual", "manual"),
        ("vtt_manual", "manual"),
        ("auto", "auto"),
        ("vtt_auto", "auto"),
        (None, "auto"),
    ],
)
def test_normalize_caption_kind(raw: str | None, expected: str) -> None:
    assert normalize_caption_kind(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("20050424", datetime(2005, 4, 24, tzinfo=UTC)),
        ("2005-04-24", datetime(2005, 4, 24, tzinfo=UTC)),
        ("", None),
        (None, None),
        ("not-a-date", None),
    ],
)
def test_published_at_from_upload_date(raw: str | None, expected: datetime | None) -> None:
    assert published_at_from_upload_date(raw) == expected


def test_normalize_transcript_fields_and_metadata() -> None:
    article = normalize_transcript(_fixture_caption_result())

    assert article.url == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert article.title == "Me at the zoo"
    assert article.source == "youtube:UC4QobU6STFB0P71PMvOGN5A"
    assert article.published_at == datetime(2005, 4, 24, tzinfo=UTC)
    assert "elephants" in article.content
    assert "[Music]" not in article.content
    assert article.truncated is False

    meta = article.source_metadata
    # The K2 acceptance contract.
    assert meta["video_id"] == "jNQXAC9IVRw"
    assert meta["channel_id"] == "UC4QobU6STFB0P71PMvOGN5A"
    assert meta["duration_s"] == 19
    assert meta["caption_lang"] == "en"
    assert meta["caption_kind"] == "auto"
    assert meta["caption_kind_raw"] == "vtt_auto"
    assert meta["fetch_source"] == "yt_dlp"


def test_normalize_transcript_uses_source_row_provenance() -> None:
    row = {
        "id": 7,
        "handle": "@NvidiaIR",
        "label": "NVIDIA Investor Relations",
        "expected_tickers": ["nvda", " amd "],
        "alpha_mechanism": "EARNINGS_IR",
    }
    article = normalize_transcript(
        _fixture_caption_result(channel_id=None, channel=None), source_row=row
    )
    assert article.source == "youtube:@NvidiaIR"
    assert article.expected_tickers == ("NVDA", "AMD")
    assert article.source_metadata["youtube_source_id"] == 7
    assert article.source_metadata["alpha_mechanism"] == "EARNINGS_IR"
    assert article.source_metadata["channel"] == "NVIDIA Investor Relations"


def test_normalize_transcript_falls_back_to_video_id_title() -> None:
    article = normalize_transcript(_fixture_caption_result(title=None))
    assert article.title == "YouTube video jNQXAC9IVRw"


def test_normalize_transcript_truncates_at_hard_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_MAX_CHARS", "50")
    assert content_max_chars() == 50

    article = normalize_transcript(_fixture_caption_result(text="x" * 500))
    assert len(article.content) == 50
    assert article.truncated is True
    assert article.source_metadata["truncated"] is True
    assert article.source_metadata["char_count"] == 50


def test_content_max_chars_ignores_bad_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_MAX_CHARS", "not-a-number")
    assert content_max_chars() == 64_000
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_MAX_CHARS", "0")
    assert content_max_chars() == 64_000


# ---------------------------------------------------------------------------
# Summarize + ticker extraction
# ---------------------------------------------------------------------------


def test_summarize_transcript_uses_transcript_article_type() -> None:
    seen: dict[str, Any] = {}

    def fake_summarize(text: str, *, article_type: str = "") -> dict[str, Any]:
        seen["text"] = text
        seen["article_type"] = article_type
        return _summary_payload()

    result = summarize_transcript(
        title="Me at the zoo",
        content="the elephants have really long trunks",
        summarize_fn=fake_summarize,
    )

    assert seen["article_type"] == ARTICLE_TYPE
    assert seen["text"].startswith("Title: Me at the zoo")
    assert result.summary == "- Elephants have long trunks."
    assert result.sector == "Consumer Discretionary"
    assert result.tickers == ["SEAS"]
    assert result.ok is True


def test_summarize_transcript_keeps_expected_tickers_first() -> None:
    result = summarize_transcript(
        title="NVDA Q4 call",
        content="body",
        expected_tickers=["NVDA"],
        owned_tickers=["NVDA"],
        summarize_fn=lambda text, article_type="": _summary_payload(),
    )
    assert result.tickers == ["NVDA", "SEAS"]
    # Owned holding present -> the owned-ticker relevance tier.
    assert result.relevance_score == pytest.approx(0.8)


def test_summarize_transcript_falls_back_to_expected_tickers_on_empty_summary() -> None:
    result = summarize_transcript(
        title="NVDA Q4 call",
        content="body",
        expected_tickers=["NVDA"],
        summarize_fn=lambda text, article_type="": {},
    )
    assert result.ok is False
    assert result.tickers == ["NVDA"]


# ---------------------------------------------------------------------------
# End-to-end ingest (mocked repo)
# ---------------------------------------------------------------------------


def test_ingest_video_lands_one_article_inline() -> None:
    repo = _fake_repo()
    outcome = ingest_video(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        research_repo=repo,
        use_queue=False,
        fetch_fn=lambda *_a, **_k: _fixture_caption_result(),
        summarize_fn=lambda text, article_type="": _summary_payload(),
    )

    assert isinstance(outcome, IngestOutcome)
    assert outcome.status == "saved"
    assert outcome.landed is True
    assert outcome.article_id == "art-1"

    repo.save_article.assert_called_once()
    kwargs = repo.save_article.call_args.kwargs
    assert kwargs["article_type"] == "YouTube Transcript"
    assert kwargs["url"] == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    assert kwargs["title"] == "Me at the zoo"
    assert kwargs["published_at"] == datetime(2005, 4, 24, tzinfo=UTC)
    assert kwargs["source"] == "youtube:UC4QobU6STFB0P71PMvOGN5A"
    assert "elephants" in kwargs["content"]
    # Summarize is mandatory: ticker meta only reads title + conclusion + sentiment.
    assert kwargs["conclusion"] == "Neutral for zoo-adjacent tickers."
    assert kwargs["sentiment"] == "NEUTRAL"
    assert kwargs["tickers"] == ["SEAS"]
    assert kwargs["source_metadata"]["video_id"] == "jNQXAC9IVRw"


def test_ingest_video_is_idempotent_on_watch_url() -> None:
    repo = _fake_repo(exists=True)
    outcome = ingest_video(
        "jNQXAC9IVRw",
        research_repo=repo,
        use_queue=False,
        fetch_fn=lambda *_a, **_k: _fixture_caption_result(),
        summarize_fn=lambda text, article_type="": _summary_payload(),
    )

    assert outcome.status == "skipped_exists"
    repo.article_exists.assert_called_once_with(
        "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    )
    repo.save_article.assert_not_called()


def test_ingest_video_force_reingests_existing_row() -> None:
    repo = _fake_repo(exists=True)
    outcome = ingest_video(
        "jNQXAC9IVRw",
        research_repo=repo,
        use_queue=False,
        force=True,
        fetch_fn=lambda *_a, **_k: _fixture_caption_result(),
        summarize_fn=lambda text, article_type="": _summary_payload(),
    )
    assert outcome.status == "saved"
    repo.save_article.assert_called_once()


def test_ingest_video_saves_even_when_summarize_is_empty() -> None:
    """The caption body is the expensive part to refetch; keep it, flag no conclusion."""
    repo = _fake_repo()
    outcome = ingest_video(
        "jNQXAC9IVRw",
        research_repo=repo,
        use_queue=False,
        fetch_fn=lambda *_a, **_k: _fixture_caption_result(),
        summarize_fn=lambda text, article_type="": {},
    )
    assert outcome.status == "saved"
    kwargs = repo.save_article.call_args.kwargs
    assert kwargs["conclusion"] is None
    assert "elephants" in kwargs["content"]


def test_ingest_video_soft_fails_on_caption_error() -> None:
    repo = _fake_repo()

    def boom(*_a: Any, **_k: Any) -> CaptionResult:
        raise CaptionFetchError("blocked", "YouTube blocked it", "jNQXAC9IVRw")

    outcome = ingest_video(
        "jNQXAC9IVRw", research_repo=repo, use_queue=False, fetch_fn=boom
    )
    assert outcome.status == "soft_fail"
    assert outcome.reason == "blocked"
    assert outcome.url == "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    repo.save_article.assert_not_called()


@pytest.mark.parametrize("reason", ["no_captions", "age_restricted", "unavailable"])
def test_ingest_video_soft_fails_are_not_exceptions(reason: str) -> None:
    def boom(*_a: Any, **_k: Any) -> CaptionResult:
        raise CaptionFetchError(reason, reason, "jNQXAC9IVRw")  # type: ignore[arg-type]

    outcome = ingest_video(
        "jNQXAC9IVRw", research_repo=_fake_repo(), use_queue=False, fetch_fn=boom
    )
    assert outcome.status == "soft_fail"
    assert outcome.reason == reason


def test_ingest_video_respects_source_duration_gates() -> None:
    repo = _fake_repo()
    outcome = ingest_video(
        "jNQXAC9IVRw",
        research_repo=repo,
        source_row={"id": 1, "min_duration_s": 120},
        use_queue=False,
        fetch_fn=lambda *_a, **_k: _fixture_caption_result(),  # 19s fixture
        summarize_fn=lambda text, article_type="": _summary_payload(),
    )
    assert outcome.status == "skipped_duration"
    repo.save_article.assert_not_called()


def test_ingest_video_reports_save_failure() -> None:
    repo = _fake_repo()
    repo.save_article.return_value = None
    outcome = ingest_video(
        "jNQXAC9IVRw",
        research_repo=repo,
        use_queue=False,
        fetch_fn=lambda *_a, **_k: _fixture_caption_result(),
        summarize_fn=lambda text, article_type="": _summary_payload(),
    )
    assert outcome.status == "error"
    assert outcome.reason == "save_failed"


# ---------------------------------------------------------------------------
# Queue-managed enrichment
# ---------------------------------------------------------------------------


def test_ingest_video_queue_mode_saves_body_then_enqueues() -> None:
    repo = _fake_repo(article_id="art-9")
    calls: list[tuple[Any, Any]] = []

    def fake_enqueue(client: Any, videos: Any, **_k: Any) -> dict[str, int]:
        calls.append((client, list(videos)))
        return {"attempted": 1, "enqueued": 1, "failed": 0}

    def exploding_summarize(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise AssertionError("queue mode must not summarize inline")

    outcome = ingest_video(
        "jNQXAC9IVRw",
        research_repo=repo,
        source_row={"id": 3, "expected_tickers": ["NVDA"]},
        use_queue=True,
        supabase_client=object(),
        fetch_fn=lambda *_a, **_k: _fixture_caption_result(),
        summarize_fn=exploding_summarize,
        enqueue_fn=fake_enqueue,
    )

    assert outcome.status == "queued"
    assert outcome.landed is True
    kwargs = repo.save_article.call_args.kwargs
    assert kwargs["article_type"] == "YouTube Transcript"
    assert kwargs["summary"] is None
    assert "elephants" in kwargs["content"]
    assert kwargs["source_metadata"]["video_id"] == "jNQXAC9IVRw"

    assert len(calls) == 1
    queued = calls[0][1][0]
    assert queued["video_id"] == "jNQXAC9IVRw"
    assert queued["article_id"] == "art-9"
    assert queued["expected_tickers"] == ["NVDA"]
    assert queued["youtube_source_id"] == 3


def test_enrich_saved_transcript_updates_without_touching_body() -> None:
    repo = _fake_repo()
    enrich_saved_transcript(
        research_repo=repo,
        article_id="art-1",
        title="Me at the zoo",
        content="the elephants have really long trunks",
        expected_tickers=["NVDA"],
        summarize_fn=lambda text, article_type="": _summary_payload(),
    )

    repo.save_article.assert_not_called()
    repo.update_article_analysis.assert_called_once()
    args, kwargs = repo.update_article_analysis.call_args
    assert args[0] == "art-1"
    assert kwargs["conclusion"] == "Neutral for zoo-adjacent tickers."
    assert kwargs["sentiment"] == "NEUTRAL"
    assert kwargs["tickers"] == ["NVDA", "SEAS"]


def test_enrich_saved_transcript_raises_so_queue_retries() -> None:
    repo = _fake_repo()
    with pytest.raises(RuntimeError):
        enrich_saved_transcript(
            research_repo=repo,
            article_id="art-1",
            title="t",
            content="body",
            summarize_fn=lambda text, article_type="": {},
        )
    repo.update_article_analysis.assert_not_called()


def test_transcript_summary_queue_job_is_registered() -> None:
    from scheduler.ai_task_workers import (
        QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY,
        build_task_handlers,
        youtube_transcript_summary_task_handler,
    )

    handlers = build_task_handlers([QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY])
    assert (
        handlers[QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY]
        is youtube_transcript_summary_task_handler
    )
    # target_key is the video id, which must fit ai_task_queue.target_key.
    assert len(QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY) <= 40


def test_enqueue_transcript_tasks_dedupes_on_video_id() -> None:
    from scheduler.ai_task_workers import (
        QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY,
        enqueue_youtube_transcript_summary_tasks,
    )

    client = MagicMock()
    client.supabase.rpc.return_value.execute.return_value = MagicMock(data=[{}])

    stats = enqueue_youtube_transcript_summary_tasks(
        client,
        [
            {"video_id": "jNQXAC9IVRw", "article_id": "art-1", "url": "u"},
            {"video_id": "", "article_id": "art-2"},  # invalid -> failed
        ],
    )
    assert stats == {"attempted": 2, "enqueued": 1, "failed": 1}

    name, payload = client.supabase.rpc.call_args[0]
    assert name == "enqueue_ai_task"
    assert payload["p_analysis_type"] == QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY
    assert payload["p_target_key"] == "jNQXAC9IVRw"
    assert payload["p_payload"]["article_id"] == "art-1"


# ---------------------------------------------------------------------------
# save_article source_metadata plumbing (additive-migration guard)
# ---------------------------------------------------------------------------


class _FakePg:
    """Minimal PostgresClient stand-in that records the executed INSERT."""

    def __init__(self, *, columns: set[str]) -> None:
        self.columns = columns
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute_query(self, query: str, params: tuple[Any, ...] | None = None) -> list[dict]:
        if "information_schema.columns" in query:
            wanted = params[0] if params else "tickers"
            return [{"column_name": wanted}] if wanted in self.columns else []
        return []

    def get_connection(self) -> Any:
        outer = self

        class _Ctx:
            def __enter__(self) -> Any:
                class _Conn:
                    def cursor(self) -> Any:
                        class _Cur:
                            def execute(self, query: str, params: tuple[Any, ...]) -> None:
                                outer.executed.append((query, params))

                            def fetchone(self) -> tuple[str, ...]:
                                return ("00000000-0000-0000-0000-000000000001",)

                        return _Cur()

                    def commit(self) -> None:
                        return None

                return _Conn()

            def __exit__(self, *_exc: Any) -> bool:
                return False

        return _Ctx()


def _save_transcript(columns: set[str]) -> tuple[str, tuple[Any, ...]]:
    from research_repository import ResearchRepository

    pg = _FakePg(columns=columns)
    repo = ResearchRepository(postgres_client=pg)
    article = normalize_transcript(_fixture_caption_result())
    article_id = repo.save_article(
        tickers=["NVDA"],
        article_type=ARTICLE_TYPE,
        title=article.title,
        url=article.url,
        content=article.content,
        source=article.source,
        published_at=article.published_at,
        source_metadata=article.source_metadata,
    )
    assert article_id
    assert len(pg.executed) == 1
    return pg.executed[0]


def test_save_article_writes_source_metadata_when_column_exists() -> None:
    query, params = _save_transcript({"tickers", "source_metadata"})
    assert "source_metadata" in query
    assert "COALESCE(EXCLUDED.source_metadata" in query
    # Serialized JSON is the last bound parameter.
    assert '"video_id": "jNQXAC9IVRw"' in params[-1]
    assert query.count("%s") == len(params)


def test_save_article_omits_source_metadata_before_migration() -> None:
    """A deploy that lands before the additive migration must not break ingest."""
    query, params = _save_transcript({"tickers"})
    assert "source_metadata" not in query
    assert query.count("%s") == len(params)


# ---------------------------------------------------------------------------
# Summarizer budget
# ---------------------------------------------------------------------------


def test_transcript_summary_budget_beats_default() -> None:
    from summary_common import compute_summary_max_chars

    assert compute_summary_max_chars(ARTICLE_TYPE) == 16_000
    assert compute_summary_max_chars(ARTICLE_TYPE, high_context=True) == 48_000
    assert compute_summary_max_chars("") == 6_000


def test_transcript_summary_budget_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from summary_common import compute_summary_max_chars

    monkeypatch.setenv("AI_SUMMARY_MAX_CHARS_TRANSCRIPT", "24000")
    assert compute_summary_max_chars(ARTICLE_TYPE) == 24_000
    monkeypatch.setenv("AI_SUMMARY_MAX_CHARS_TRANSCRIPT_LONG", "60000")
    assert compute_summary_max_chars(ARTICLE_TYPE, high_context=True) == 60_000


def test_short_transcript_does_not_force_model() -> None:
    seen: dict[str, Any] = {}

    def fake_summarize(
        text: str, *, article_type: str = "", model: str | None = None
    ) -> dict[str, Any]:
        seen["model"] = model
        return _summary_payload()

    summarize_transcript(
        title="Short clip",
        content="x" * 100,
        summarize_fn=fake_summarize,
    )
    assert seen["model"] is None


def test_long_transcript_routes_to_glm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "settings.get_system_setting",
        lambda key, default=None: None,
    )
    seen: dict[str, Any] = {}

    def fake_summarize(
        text: str, *, article_type: str = "", model: str | None = None
    ) -> dict[str, Any]:
        seen["model"] = model
        return _summary_payload()

    summarize_transcript(
        title="Earnings call",
        content="x" * 16_001,
        summarize_fn=fake_summarize,
    )
    assert seen["model"] == "glm-5.2"


def test_long_duration_routes_to_glm_even_if_body_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "settings.get_system_setting",
        lambda key, default=None: None,
    )
    seen: dict[str, Any] = {}

    def fake_summarize(
        text: str, *, article_type: str = "", model: str | None = None
    ) -> dict[str, Any]:
        seen["model"] = model
        return _summary_payload()

    summarize_transcript(
        title="Hour-long AMA",
        content="x" * 500,
        duration_s=21 * 60,
        summarize_fn=fake_summarize,
    )
    assert seen["model"] == "glm-5.2"


def test_webai_never_auto_selected_for_long_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _setting(key: str, default: Any = None) -> Any:
        if key == "ai_summarizing_model_youtube_transcript":
            return "gemini-2.5-flash"
        return default

    monkeypatch.setattr("settings.get_system_setting", _setting)
    seen: dict[str, Any] = {}

    def fake_summarize(
        text: str, *, article_type: str = "", model: str | None = None
    ) -> dict[str, Any]:
        seen["model"] = model
        return _summary_payload()

    summarize_transcript(
        title="Earnings call",
        content="x" * 16_001,
        summarize_fn=fake_summarize,
    )
    assert seen["model"] == "glm-5.2"
    assert not str(seen["model"]).startswith("gemini-")


def test_scoped_glm_override_honored_for_long_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _setting(key: str, default: Any = None) -> Any:
        if key == "ai_summarizing_model_youtube_transcript":
            return "glm-4.7"
        return default

    monkeypatch.setattr("settings.get_system_setting", _setting)
    seen: dict[str, Any] = {}

    def fake_summarize(
        text: str, *, article_type: str = "", model: str | None = None
    ) -> dict[str, Any]:
        seen["model"] = model
        return _summary_payload()

    summarize_transcript(
        title="Earnings call",
        content="x" * 16_001,
        summarize_fn=fake_summarize,
    )
    assert seen["model"] == "glm-4.7"