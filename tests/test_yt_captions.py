"""Unit tests for Phase K1 YouTube caption fetch/clean (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yt"

# sys.path is set up by tests/conftest.py, which deliberately pins the repo root
# ahead of web_dashboard — do not re-insert them here.
from yt_captions import (  # noqa: E402
    CaptionFetchError,
    CaptionResult,
    clean_caption_lines,
    fetch_caption_text,
    parse_video_id,
    parse_vtt_text,
    watch_url_for,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("jNQXAC9IVRw", "jNQXAC9IVRw"),
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw", "jNQXAC9IVRw"),
        ("https://youtu.be/jNQXAC9IVRw", "jNQXAC9IVRw"),
        ("https://www.youtube.com/shorts/jNQXAC9IVRw", "jNQXAC9IVRw"),
        ("https://www.youtube.com/embed/jNQXAC9IVRw", "jNQXAC9IVRw"),
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=12s", "jNQXAC9IVRw"),
    ],
)
def test_parse_video_id(raw: str, expected: str) -> None:
    assert parse_video_id(raw) == expected


def test_parse_video_id_rejects_empty() -> None:
    with pytest.raises(CaptionFetchError) as exc:
        parse_video_id("  ")
    assert exc.value.reason == "parse"


@pytest.mark.parametrize(
    "raw",
    [
        # The loose 11-char scan must not turn a foreign slug into a video id.
        "https://example.com/articles/some-long-slug-here",
        "https://vimeo.com/1234567890",
        "https://seekingalpha.com/article/nvidia-earnings-recap",
        "https://www.youtube.com/watch?v=TOOSHORT",
        "https://www.youtube.com/results?search_query=nvda+earnings",
    ],
)
def test_parse_video_id_rejects_non_video_urls(raw: str) -> None:
    with pytest.raises(CaptionFetchError) as exc:
        parse_video_id(raw)
    assert exc.value.reason == "parse"


def test_parse_video_id_finds_id_in_free_text() -> None:
    raw = "worth a look: https://www.youtube.com/watch?v=jNQXAC9IVRw thanks"
    assert parse_video_id(raw) == "jNQXAC9IVRw"


def test_watch_url_for() -> None:
    assert watch_url_for("jNQXAC9IVRw") == "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def test_parse_vtt_strips_music_and_joins() -> None:
    vtt = (FIXTURES / "me_at_zoo.en.vtt").read_text(encoding="utf-8")
    text = parse_vtt_text(vtt)
    assert "[Music]" not in text
    assert "♪" not in text
    assert "elephants" in text
    assert "long trunks" in text
    assert "that's cool" in text


def test_parse_vtt_collapses_rolling_auto_captions() -> None:
    vtt = (FIXTURES / "rolling_auto.en.vtt").read_text(encoding="utf-8")
    text = parse_vtt_text(vtt)
    # Should not repeat the full rolling prefix many times.
    assert text.lower().count("welcome to the earnings call") == 1
    assert "discuss results" in text.lower()
    assert "quarter four" in text.lower()


def test_parse_vtt_keeps_numeric_caption_text() -> None:
    """A bare number is a cue id only when a timestamp follows it."""
    vtt = (
        "WEBVTT\n\n"
        "1\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "2025\n\n"
        "2\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "was a record year\n"
    )
    assert parse_vtt_text(vtt) == "2025 was a record year"


def test_clean_caption_lines_from_timedtext_fixture() -> None:
    rows = json.loads((FIXTURES / "timedtext_snippets.json").read_text(encoding="utf-8"))
    text = clean_caption_lines(row["text"] for row in rows)
    assert "[Music]" not in text
    assert text.count("we may file on Form 8K with the") == 1
    assert "disclosure" in text
    assert "Form 8K" in text


_ERROR_NAMES = (
    "AgeRestricted",
    "IpBlocked",
    "NoTranscriptFound",
    "RequestBlocked",
    "TranscriptsDisabled",
    "VideoUnavailable",
    "YouTubeRequestFailed",
)


def _make_errors_module(**overrides: type) -> MagicMock:
    """Stand-in for ``youtube_transcript_api._errors``.

    Every name is a real exception class so ``except`` clauses stay valid;
    unspecified ones can never match because nothing raises them.
    """
    errors = MagicMock()
    for name in _ERROR_NAMES:
        setattr(errors, name, overrides.get(name) or type(name, (Exception,), {}))
    return errors


def _install_fake_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    transcript_api: object | None = None,
    errors: object | None = None,
    yt_dlp: object | None = None,
) -> None:
    """Swap the optional caption deps in ``sys.modules``.

    Narrower than patching ``builtins.__import__``, which would intercept every
    lazy import anywhere in the call.
    """
    if transcript_api is not None:
        monkeypatch.setitem(sys.modules, "youtube_transcript_api", transcript_api)
    if errors is not None:
        monkeypatch.setitem(sys.modules, "youtube_transcript_api._errors", errors)
    if yt_dlp is not None:
        monkeypatch.setitem(sys.modules, "yt_dlp", yt_dlp)


def test_fetch_caption_text_uses_transcript_api(monkeypatch: pytest.MonkeyPatch) -> None:
    snippet = MagicMock(text="Hello from the call")
    transcript = MagicMock()
    transcript.language_code = "en"
    transcript.is_generated = True
    transcript.fetch.return_value = [snippet]

    listing = MagicMock()
    listing.find_manually_created_transcript.side_effect = Exception("none")
    listing.find_generated_transcript.return_value = transcript

    api = MagicMock()
    api.list.return_value = listing

    fake_mod = MagicMock()
    fake_mod.YouTubeTranscriptApi.return_value = api

    _install_fake_modules(
        monkeypatch, transcript_api=fake_mod, errors=_make_errors_module()
    )

    result = fetch_caption_text(
        "jNQXAC9IVRw",
        include_metadata=False,
        use_ytdlp_fallback=False,
    )
    assert isinstance(result, CaptionResult)
    assert result.video_id == "jNQXAC9IVRw"
    assert result.fetch_source == "youtube_transcript_api"
    assert result.caption_kind == "auto"
    assert result.text == "Hello from the call"
    assert result.char_count == len(result.text)


def test_fetch_maps_blocked_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class RequestBlocked(Exception):
        pass

    fake_mod = MagicMock()
    api = MagicMock()
    api.list.side_effect = RequestBlocked("blocked")
    fake_mod.YouTubeTranscriptApi.return_value = api

    _install_fake_modules(
        monkeypatch,
        transcript_api=fake_mod,
        errors=_make_errors_module(RequestBlocked=RequestBlocked),
    )

    with pytest.raises(CaptionFetchError) as exc:
        fetch_caption_text("jNQXAC9IVRw", include_metadata=False, use_ytdlp_fallback=False)
    assert exc.value.reason == "blocked"


def _make_fake_yt_dlp(vtt_filename: str) -> MagicMock:
    """Listing-client stub that drops one VTT into the caller's temp dir."""
    vtt_src = (FIXTURES / "me_at_zoo.en.vtt").read_text(encoding="utf-8")

    class FakeYDL:
        def __init__(self, opts: dict) -> None:
            self.opts = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = False) -> dict:
            # outtmpl is like /tmp/xxx/%(id)s.%(ext)s — write beside pattern dir
            dest_dir = Path(self.opts["outtmpl"]).parent
            (dest_dir / vtt_filename).write_text(vtt_src, encoding="utf-8")
            return {
                "id": "jNQXAC9IVRw",
                "title": "Me at the zoo",
                "channel": "jawed",
                "channel_id": "UC4QobU6STFB0P71PMvOGN5A",
                "duration": 19,
                "upload_date": "20050424",
            }

    fake_yt_dlp = MagicMock()
    fake_yt_dlp.YoutubeDL = FakeYDL
    return fake_yt_dlp


def _make_failing_transcript_api(exc: Exception) -> MagicMock:
    fake_ytt = MagicMock()
    api = MagicMock()
    api.list.side_effect = exc
    fake_ytt.YouTubeTranscriptApi.return_value = api
    return fake_ytt


def test_fetch_falls_back_to_ytdlp_vtt(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoTranscriptFound(Exception):
        pass

    _install_fake_modules(
        monkeypatch,
        transcript_api=_make_failing_transcript_api(NoTranscriptFound("none")),
        errors=_make_errors_module(NoTranscriptFound=NoTranscriptFound),
        yt_dlp=_make_fake_yt_dlp("jNQXAC9IVRw.en.vtt"),
    )

    result = fetch_caption_text("jNQXAC9IVRw", include_metadata=False)
    assert result.fetch_source == "yt_dlp"
    assert result.title == "Me at the zoo"
    assert result.language == "en"
    assert "elephants" in result.text
    assert "[Music]" not in result.text


def test_ytdlp_language_ignores_auto_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """``{id}.{lang}.auto.vtt`` must not report its language as ``auto``."""

    class NoTranscriptFound(Exception):
        pass

    _install_fake_modules(
        monkeypatch,
        transcript_api=_make_failing_transcript_api(NoTranscriptFound("none")),
        errors=_make_errors_module(NoTranscriptFound=NoTranscriptFound),
        yt_dlp=_make_fake_yt_dlp("jNQXAC9IVRw.en.auto.vtt"),
    )

    result = fetch_caption_text("jNQXAC9IVRw", include_metadata=False)
    assert result.language == "en"
    assert result.caption_kind == "vtt_auto"


def test_missing_transcript_api_still_falls_back_to_ytdlp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Listing client alone is a complete path — a missing dep must degrade, not fail."""
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
    _install_fake_modules(monkeypatch, yt_dlp=_make_fake_yt_dlp("jNQXAC9IVRw.en.vtt"))

    result = fetch_caption_text("jNQXAC9IVRw", include_metadata=False)
    assert result.fetch_source == "yt_dlp"
    assert "elephants" in result.text


def test_both_deps_missing_reports_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
    monkeypatch.setitem(sys.modules, "yt_dlp", None)

    with pytest.raises(CaptionFetchError) as exc:
        fetch_caption_text("jNQXAC9IVRw", include_metadata=False)
    assert exc.value.reason == "dependency"
    assert "neither" in str(exc.value)
