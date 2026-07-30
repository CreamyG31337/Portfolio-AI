"""Unit tests for the Phase K3 YouTube allowlist poll job (no network, no DB).

Covers flat-playlist listing parse/order, the ``kind`` dispatch, the
cursor walk + advance rule, per-source and global caps, soft-fail isolation, the
``youtube_sources`` health/cursor writes, and that disabled rows are never read.

``ingest_video`` and the listing client are both mocked; ``PostgresClient`` and
``ResearchRepository`` are fakes.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

# sys.path is set up by tests/conftest.py, which deliberately pins the repo root
# ahead of web_dashboard — do not re-insert them here.
from yt_captions import (  # noqa: E402
    CaptionFetchError,
    VideoListing,
    channel_videos_url,
    list_channel_videos,
    list_search_videos,
    list_source_videos,
)
from scheduler.jobs_yt import (  # noqa: E402
    PollSummary,
    load_enabled_sources,
    max_per_run,
    poll_source,
    poll_youtube_sources,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _source_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": 1,
        "kind": "channel",
        "channel_id": "UC4QobU6STFB0P71PMvOGN5A",
        "handle": None,
        "query_text": None,
        "label": "Test IR Channel",
        "enabled": True,
        "expected_tickers": ["NVDA"],
        "max_videos_per_poll": 5,
        "min_duration_s": 120,
        "max_duration_s": None,
        "last_video_id": None,
    }
    row.update(overrides)
    return row


def _listing(*video_ids: str) -> list[VideoListing]:
    return [
        VideoListing(
            video_id=vid,
            watch_url=f"https://www.youtube.com/watch?v={vid}",
            title=f"Video {vid}",
        )
        for vid in video_ids
    ]


class _FakePg:
    """Captures SELECTs and UPDATEs so tests can assert on the SQL written."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.queries: list[tuple[str, Any]] = []
        self.updates: list[tuple[str, Any]] = []

    def execute_query(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        self.queries.append((sql, params))
        return list(self.rows)

    def execute_update(self, sql: str, params: Any = None) -> int:
        self.updates.append((sql, params))
        return 1

    def update_sql(self) -> str:
        return " | ".join(sql for sql, _ in self.updates)


def _fake_repo(existing: set[str] | None = None) -> MagicMock:
    known = existing or set()
    repo = MagicMock()
    repo.article_exists.side_effect = lambda url: url in known
    return repo


def _outcome(status: str, reason: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(status=status, reason=reason)


def _no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def pg() -> _FakePg:
    return _FakePg()


# ---------------------------------------------------------------------------
# Listing helper (listing client mocked)
# ---------------------------------------------------------------------------


def _install_fake_ytdlp(monkeypatch: pytest.MonkeyPatch, info: Any) -> dict[str, Any]:
    """Install a fake ``yt_dlp`` module; returns a dict capturing the call."""
    captured: dict[str, Any] = {}

    class _FakeYDL:
        def __init__(self, opts: dict[str, Any]) -> None:
            captured["opts"] = opts

        def __enter__(self) -> "_FakeYDL":
            return self

        def __exit__(self, *_exc: Any) -> bool:
            return False

        def extract_info(self, target: str, download: bool = True) -> Any:
            captured["target"] = target
            captured["download"] = download
            if isinstance(info, Exception):
                raise info
            return info

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=_FakeYDL))
    return captured


def _flat_entry(video_id: str, **extra: Any) -> dict[str, Any]:
    entry = {"id": video_id, "title": f"Video {video_id}", "_type": "url"}
    entry.update(extra)
    return entry


def test_channel_videos_url_prefers_videos_tab() -> None:
    assert channel_videos_url(channel_id="UC123") == (
        "https://www.youtube.com/channel/UC123/videos"
    )
    assert channel_videos_url(handle="nvidia") == (
        "https://www.youtube.com/@nvidia/videos"
    )
    assert channel_videos_url(handle="@nvidia") == (
        "https://www.youtube.com/@nvidia/videos"
    )
    assert channel_videos_url(playlist_id="PLabc") == (
        "https://www.youtube.com/playlist?list=PLabc"
    )


def test_channel_videos_url_needs_an_identifier() -> None:
    with pytest.raises(CaptionFetchError) as exc:
        channel_videos_url()
    assert exc.value.reason == "parse"


def test_list_channel_videos_preserves_newest_first_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_ytdlp(
        monkeypatch,
        {
            "entries": [
                _flat_entry("aaaaaaaaaaa", duration=1800, upload_date="20260728"),
                _flat_entry("bbbbbbbbbbb", duration=600),
                _flat_entry("ccccccccccc"),
            ]
        },
    )

    videos = list_channel_videos(channel_id="UC123", limit=5)

    assert [v.video_id for v in videos] == [
        "aaaaaaaaaaa",
        "bbbbbbbbbbb",
        "ccccccccccc",
    ]
    assert videos[0].watch_url == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    assert videos[0].duration_s == 1800
    assert videos[0].upload_date == "20260728"
    assert videos[2].duration_s is None
    # Flat listing only: metadata request, no media, no captions.
    assert captured["opts"]["extract_flat"] == "in_playlist"
    assert captured["opts"]["skip_download"] is True
    assert captured["download"] is False
    assert captured["target"] == "https://www.youtube.com/channel/UC123/videos"


def test_list_channel_videos_respects_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _install_fake_ytdlp(
        monkeypatch,
        {"entries": [_flat_entry(f"vid{i:08d}") for i in range(10)]},
    )

    videos = list_channel_videos(channel_id="UC123", limit=2)

    assert len(videos) == 2
    assert captured["opts"]["playlistend"] == 2


def test_list_channel_videos_flattens_nested_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ytdlp(
        monkeypatch,
        {
            "entries": [
                {"_type": "playlist", "entries": [_flat_entry("aaaaaaaaaaa")]},
                _flat_entry("bbbbbbbbbbb"),
            ]
        },
    )

    videos = list_channel_videos(channel_id="UC123", limit=5)

    assert [v.video_id for v in videos] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]


def test_list_channel_videos_recovers_id_from_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ytdlp(
        monkeypatch,
        {
            "entries": [
                # A tab row with no usable id must be dropped, not guessed at.
                {"_type": "playlist", "id": "UC123", "title": "Videos"},
                {
                    "id": "not-a-video-id-at-all",
                    "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
                },
            ]
        },
    )

    videos = list_channel_videos(channel_id="UC123", limit=5)

    assert [v.video_id for v in videos] == ["bbbbbbbbbbb"]


def test_list_channel_videos_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_ytdlp(
        monkeypatch,
        {"entries": [_flat_entry("aaaaaaaaaaa"), _flat_entry("aaaaaaaaaaa")]},
    )

    assert len(list_channel_videos(channel_id="UC123", limit=5)) == 1


@pytest.mark.parametrize(
    "error,expected_reason",
    [
        (RuntimeError("HTTP Error 429: Too Many Requests"), "blocked"),
        (RuntimeError("This channel does not exist"), "unavailable"),
        (RuntimeError("something else entirely"), "unknown"),
    ],
)
def test_listing_maps_ytdlp_errors_to_failure_reasons(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected_reason: str
) -> None:
    _install_fake_ytdlp(monkeypatch, error)

    with pytest.raises(CaptionFetchError) as exc:
        list_channel_videos(channel_id="UC123", limit=5)
    assert exc.value.reason == expected_reason


def test_listing_missing_ytdlp_is_a_dependency_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "yt_dlp", None)

    with pytest.raises(CaptionFetchError) as exc:
        list_channel_videos(channel_id="UC123", limit=5)
    assert exc.value.reason == "dependency"


def test_list_search_videos_caps_n_tiny(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _install_fake_ytdlp(
        monkeypatch, {"entries": [_flat_entry(f"vid{i:08d}") for i in range(10)]}
    )

    videos = list_search_videos("NVDA earnings call", limit=50)

    # Search is the one kind that can reach outside the channel allowlist.
    assert len(videos) == 3
    assert captured["target"] == "ytsearch3:NVDA earnings call"


def test_list_search_videos_rejects_empty_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_ytdlp(monkeypatch, {"entries": []})

    with pytest.raises(CaptionFetchError) as exc:
        list_search_videos("   ")
    assert exc.value.reason == "parse"


def test_list_source_videos_dispatches_on_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_ytdlp(monkeypatch, {"entries": [_flat_entry("aaaaaaaaaaa")]})

    list_source_videos(_source_row(kind="ir"))
    assert captured["target"].endswith("/channel/UC4QobU6STFB0P71PMvOGN5A/videos")

    list_source_videos(_source_row(kind="search", query_text="NVDA earnings"))
    assert captured["target"] == "ytsearch3:NVDA earnings"

    list_source_videos(_source_row(kind="playlist", channel_id="PLxyz"))
    assert captured["target"] == "https://www.youtube.com/playlist?list=PLxyz"


def test_list_source_videos_uses_max_videos_per_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_fake_ytdlp(
        monkeypatch, {"entries": [_flat_entry(f"vid{i:08d}") for i in range(10)]}
    )

    list_source_videos(_source_row(max_videos_per_poll=2))
    assert captured["opts"]["playlistend"] == 2

    # An explicit limit is a real override — it may widen the row's own cap
    # (ops catch-up / poller lookback) as well as narrow it.
    list_source_videos(_source_row(max_videos_per_poll=2), limit=8)
    assert captured["opts"]["playlistend"] == 8


def test_cursor_holds_when_null_and_ingest_cap_leaves_backlog(
    pg: _FakePg, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catch-up safeguard: do not seal newest when ingest cap leaves videos unconsidered."""
    monkeypatch.setenv("YOUTUBE_LIST_LOOKBACK", "5")
    result = poll_source(
        _source_row(last_video_id=None, max_videos_per_poll=1),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing(
            "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd", "eeeeeeeeeee"
        ),
        ingest_fn=lambda *a, **k: _outcome("saved"),
        sleep_fn=_no_sleep,
    )

    assert result.listed == 5
    assert result.landed == 1
    assert result.capped is True
    assert result.cursor_advanced_to is None
    assert "last_video_id" not in pg.update_sql()


def test_cursor_seals_null_when_entire_listing_considered(
    pg: _FakePg, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOUTUBE_LIST_LOOKBACK", "5")
    result = poll_source(
        _source_row(last_video_id=None, max_videos_per_poll=5),
        postgres_client=pg,
        research_repo=_fake_repo(existing={"https://www.youtube.com/watch?v=aaaaaaaaaaa"}),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa"),
        ingest_fn=lambda *a, **k: _outcome("saved"),
        sleep_fn=_no_sleep,
    )

    assert result.skipped_exists == 1
    assert result.cursor_advanced_to == "aaaaaaaaaaa"


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------


def test_load_enabled_sources_filters_disabled_and_orders_stably() -> None:
    pg = _FakePg(rows=[_source_row(id=1), _source_row(id=2)])

    load_enabled_sources(pg)

    sql, params = pg.queries[0]
    assert "enabled = true" in sql
    assert "ORDER BY id" in sql
    assert params is None


def test_load_enabled_sources_scopes_to_one_id() -> None:
    pg = _FakePg(rows=[_source_row(id=3)])

    load_enabled_sources(pg, source_id=3)

    sql, params = pg.queries[0]
    assert "enabled = true" in sql
    assert "id = %s" in sql
    assert params == (3,)


def test_poll_skips_disabled_sources(pg: _FakePg) -> None:
    # The fake returns no rows because the SELECT filters on enabled = true.
    summary = poll_youtube_sources(
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa"),
        ingest_fn=lambda *a, **k: _outcome("saved"),
        sleep_fn=_no_sleep,
    )

    assert summary.sources_polled == 0
    assert summary.landed == 0
    assert pg.updates == []


# ---------------------------------------------------------------------------
# Cursor walk + advance rule
# ---------------------------------------------------------------------------


def test_poll_source_ingests_new_videos_and_marks_polled(pg: _FakePg) -> None:
    calls: list[str] = []

    def ingest(url: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(url)
        return _outcome("saved")

    result = poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa", "bbbbbbbbbbb"),
        ingest_fn=ingest,
        sleep_fn=_no_sleep,
    )

    assert result.landed == 2
    assert result.attempted == 2
    assert [u.rsplit("=", 1)[-1] for u in calls] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert "last_polled_at = NOW()" in pg.updates[0][0]


def test_poll_source_stops_at_cursor(pg: _FakePg) -> None:
    calls: list[str] = []

    def ingest(url: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(url.rsplit("=", 1)[-1])
        return _outcome("saved")

    result = poll_source(
        _source_row(last_video_id="bbbbbbbbbbb"),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing(
            "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"
        ),
        ingest_fn=ingest,
        sleep_fn=_no_sleep,
    )

    # Newest-first walk halts at the cursor; older videos are not re-walked.
    assert calls == ["aaaaaaaaaaa"]
    assert result.landed == 1


def test_poll_source_skips_already_ingested_without_fetching(pg: _FakePg) -> None:
    calls: list[str] = []
    repo = _fake_repo({"https://www.youtube.com/watch?v=aaaaaaaaaaa"})

    def ingest(url: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(url)
        return _outcome("saved")

    result = poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=repo,
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa", "bbbbbbbbbbb"),
        ingest_fn=ingest,
        sleep_fn=_no_sleep,
    )

    # The URL check is a DB read; captions are never fetched for a known video.
    assert result.skipped_exists == 1
    assert result.landed == 1
    assert result.attempted == 1
    assert len(calls) == 1


def test_cursor_advances_to_newest_listed_on_success(pg: _FakePg) -> None:
    result = poll_source(
        _source_row(last_video_id="bbbbbbbbbbb"),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa", "bbbbbbbbbbb"),
        ingest_fn=lambda *a, **k: _outcome("saved"),
        sleep_fn=_no_sleep,
    )

    assert result.cursor_advanced_to == "aaaaaaaaaaa"
    sql = pg.update_sql()
    assert "last_video_id = %s" in sql
    assert "last_seen_at = NOW()" in sql
    assert "last_success_at = NOW()" in sql
    assert "consecutive_failures = 0" in sql
    assert "aaaaaaaaaaa" in str(pg.updates[-1][1])


def test_cursor_advances_past_permanent_soft_fail(pg: _FakePg) -> None:
    """A caption-less video must not stall the source forever."""

    def ingest(url: str, **_kwargs: Any) -> SimpleNamespace:
        if url.endswith("aaaaaaaaaaa"):
            return _outcome("soft_fail", "no_captions")
        return _outcome("saved")

    result = poll_source(
        _source_row(last_video_id="ccccccccccc"),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing(
            "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"
        ),
        ingest_fn=ingest,
        sleep_fn=_no_sleep,
    )

    assert result.soft_failed == 1
    assert result.landed == 1
    assert result.cursor_advanced_to == "aaaaaaaaaaa"


def test_cursor_holds_on_retriable_soft_fail(pg: _FakePg) -> None:
    """``blocked`` is a rate-limit problem — retry the same window next poll."""
    result = poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa", "bbbbbbbbbbb"),
        ingest_fn=lambda *a, **k: _outcome("soft_fail", "blocked"),
        sleep_fn=_no_sleep,
    )

    assert result.soft_failed == 2
    assert result.cursor_advanced_to is None
    sql = pg.update_sql()
    assert "last_video_id" not in sql
    assert "consecutive_failures = consecutive_failures + 1" in sql
    assert "blocked" in str(pg.updates[-1][1])


def test_listing_failure_leaves_cursor_and_records_reason(pg: _FakePg) -> None:
    def boom(row: Any, limit: Any = None) -> Any:
        raise CaptionFetchError("blocked", "listing blocked")

    result = poll_source(
        _source_row(last_video_id="bbbbbbbbbbb"),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=boom,
        ingest_fn=lambda *a, **k: _outcome("saved"),
        sleep_fn=_no_sleep,
    )

    assert result.listing_error == "blocked"
    assert result.cursor_advanced_to is None
    sql = pg.update_sql()
    assert "last_video_id" not in sql
    assert "consecutive_failures = consecutive_failures + 1" in sql


def test_unexpected_listing_exception_is_soft(pg: _FakePg) -> None:
    def boom(row: Any, limit: Any = None) -> Any:
        raise ValueError("yt-dlp changed its API shape")

    result = poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=boom,
        ingest_fn=lambda *a, **k: _outcome("saved"),
        sleep_fn=_no_sleep,
    )

    assert result.listing_error == "unknown"


def test_no_captions_clears_captions_ok(pg: _FakePg) -> None:
    poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa"),
        ingest_fn=lambda *a, **k: _outcome("soft_fail", "no_captions"),
        sleep_fn=_no_sleep,
    )

    sql = pg.update_sql()
    assert "captions_ok = false" in sql
    assert "no_captions" in str(pg.updates[-1][1])


def test_blocked_does_not_clear_captions_ok(pg: _FakePg) -> None:
    """A rate-limit block says nothing about whether the channel has captions."""
    poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa"),
        ingest_fn=lambda *a, **k: _outcome("soft_fail", "blocked"),
        sleep_fn=_no_sleep,
    )

    assert "captions_ok" not in pg.update_sql()


def test_duration_skip_counts_as_considered(pg: _FakePg) -> None:
    result = poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa"),
        ingest_fn=lambda *a, **k: _outcome("skipped_duration", "duration"),
        sleep_fn=_no_sleep,
    )

    assert result.skipped_duration == 1
    assert result.cursor_advanced_to == "aaaaaaaaaaa"
    assert "last_success_at = NOW()" in pg.update_sql()


# ---------------------------------------------------------------------------
# Soft-fail isolation
# ---------------------------------------------------------------------------


def test_soft_fail_continues_to_next_video(pg: _FakePg) -> None:
    seen: list[str] = []

    def ingest(url: str, **_kwargs: Any) -> SimpleNamespace:
        vid = url.rsplit("=", 1)[-1]
        seen.append(vid)
        if vid == "aaaaaaaaaaa":
            return _outcome("soft_fail", "age_restricted")
        return _outcome("saved")

    result = poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing(
            "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"
        ),
        ingest_fn=ingest,
        sleep_fn=_no_sleep,
    )

    assert seen == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    assert result.landed == 2
    assert result.soft_failed == 1


def test_ingest_raising_does_not_abort_the_walk(pg: _FakePg) -> None:
    seen: list[str] = []

    def ingest(url: str, **_kwargs: Any) -> SimpleNamespace:
        vid = url.rsplit("=", 1)[-1]
        seen.append(vid)
        if vid == "aaaaaaaaaaa":
            raise RuntimeError("unexpected explosion")
        return _outcome("saved")

    result = poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa", "bbbbbbbbbbb"),
        ingest_fn=ingest,
        sleep_fn=_no_sleep,
    )

    assert seen == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert result.errors == 1
    assert result.landed == 1
    # An unexplained raise is retriable, so the cursor holds.
    assert result.cursor_advanced_to is None


def test_one_dead_source_does_not_stop_the_allowlist() -> None:
    pg = _FakePg(rows=[_source_row(id=1), _source_row(id=2, channel_id="UCsecond")])

    def list_fn(row: Any, limit: Any = None) -> Any:
        if row["id"] == 1:
            raise CaptionFetchError("unavailable", "channel deleted")
        return _listing("bbbbbbbbbbb")

    summary = poll_youtube_sources(
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=list_fn,
        ingest_fn=lambda *a, **k: _outcome("saved"),
        sleep_fn=_no_sleep,
    )

    assert summary.sources_polled == 2
    assert summary.listing_errors == 1
    assert summary.landed == 1


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


def test_per_source_cap_limits_ingest_but_listing_uses_lookback(
    pg: _FakePg, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOUTUBE_LIST_LOOKBACK", "25")
    limits: list[Any] = []

    def list_fn(row: Any, limit: Any = None) -> Any:
        limits.append(limit)
        return _listing("aaaaaaaaaaa")

    poll_source(
        _source_row(max_videos_per_poll=2),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=list_fn,
        ingest_fn=lambda *a, **k: _outcome("saved"),
        remaining_budget=10,
        sleep_fn=_no_sleep,
    )

    assert limits == [25]


def test_global_budget_still_bounds_listing_floor(
    pg: _FakePg, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOUTUBE_LIST_LOOKBACK", "25")
    limits: list[Any] = []

    def list_fn(row: Any, limit: Any = None) -> Any:
        limits.append(limit)
        return _listing("aaaaaaaaaaa")

    poll_source(
        _source_row(max_videos_per_poll=5),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=list_fn,
        ingest_fn=lambda *a, **k: _outcome("saved"),
        remaining_budget=2,
        sleep_fn=_no_sleep,
    )

    # Listing is max(ingest_budget=2, lookback=25).
    assert limits == [25]


def test_global_cap_stops_later_sources() -> None:
    pg = _FakePg(
        rows=[
            _source_row(id=1),
            _source_row(id=2, channel_id="UCsecond"),
            _source_row(id=3, channel_id="UCthird"),
        ]
    )
    touched: list[int] = []

    def list_fn(row: Any, limit: Any = None) -> Any:
        touched.append(row["id"])
        return _listing("aaaaaaaaaaa", "bbbbbbbbbbb")

    summary = poll_youtube_sources(
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=list_fn,
        ingest_fn=lambda *a, **k: _outcome("saved"),
        max_videos=2,
        sleep_fn=_no_sleep,
    )

    assert summary.landed == 2
    assert summary.capped is True
    # Source 1 exhausts the budget; 2 and 3 are not listed at all this run.
    assert touched == [1]
    assert summary.sources_polled == 1


def test_cap_hit_mid_source_holds_the_cursor(pg: _FakePg) -> None:
    result = poll_source(
        _source_row(max_videos_per_poll=5),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing(
            "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"
        ),
        ingest_fn=lambda *a, **k: _outcome("saved"),
        remaining_budget=2,
        sleep_fn=_no_sleep,
    )

    assert result.landed == 2
    assert result.capped is True
    # Videos below the cap were never considered, so the cursor must not jump.
    assert result.cursor_advanced_to is None


def test_max_per_run_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_INGEST_MAX_PER_RUN", "7")
    assert max_per_run() == 7

    monkeypatch.setenv("YOUTUBE_INGEST_MAX_PER_RUN", "0")
    assert max_per_run() == 20

    monkeypatch.setenv("YOUTUBE_INGEST_MAX_PER_RUN", "not-a-number")
    assert max_per_run() == 20

    monkeypatch.delenv("YOUTUBE_INGEST_MAX_PER_RUN")
    assert max_per_run() == 20


# ---------------------------------------------------------------------------
# Dry run + provenance
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing(pg: _FakePg) -> None:
    calls: list[str] = []

    result = poll_source(
        _source_row(),
        postgres_client=pg,
        research_repo=_fake_repo(),
        list_fn=lambda row, limit=None: _listing("aaaaaaaaaaa", "bbbbbbbbbbb"),
        ingest_fn=lambda url, **k: calls.append(url) or _outcome("saved"),
        dry_run=True,
        sleep_fn=_no_sleep,
    )

    assert calls == []
    assert pg.updates == []
    assert result.considered == 2
    assert result.landed == 0


def test_ingest_receives_source_row_and_holdings(pg: _FakePg) -> None:
    captured: dict[str, Any] = {}

    def ingest(url: str, **kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        captured["url"] = url
        return _outcome("saved")

    row = _source_row()
    poll_source(
        row,
        postgres_client=pg,
        research_repo=_fake_repo(),
        owned_tickers=["NVDA", "AMD"],
        list_fn=lambda r, limit=None: _listing("aaaaaaaaaaa"),
        ingest_fn=ingest,
        sleep_fn=_no_sleep,
    )

    # Provenance (expected_tickers, duration gates) rides on source_row so the
    # landed article keeps channel-grain attribution.
    assert captured["source_row"] is row
    assert captured["owned_tickers"] == ["NVDA", "AMD"]
    assert captured["url"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa"


def test_summary_message_is_human_readable() -> None:
    summary = PollSummary(sources_polled=2, landed=3, attempted=4, considered=4)
    assert "2 sources" in summary.message
    assert "3 landed" in summary.message
