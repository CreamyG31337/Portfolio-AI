"""Unit tests for VPN exit rotation on YouTube IP blocks (no network, no SSH)."""

from __future__ import annotations

from typing import Any

import pytest

import yt_captions  # noqa: E402
import yt_proxy_rotation as rot  # noqa: E402
from yt_captions import CaptionFetchError, CaptionResult, fetch_caption_text  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "YOUTUBE_PROXY_ROTATE_MODE",
        "YOUTUBE_PROXY_CONTROL_URL",
        "YOUTUBE_PROXY_CONTROL_APIKEY",
        "YOUTUBE_PROXY_SSH_HOST",
        "YOUTUBE_PROXY_MAX_ROTATIONS",
        "YOUTUBE_PROXY_CONTAINER",
    ):
        monkeypatch.delenv(var, raising=False)


def _ok_result(video_id: str = "vid") -> CaptionResult:
    return CaptionResult(
        video_id=video_id,
        text="hello world",
        language="en",
        caption_kind="vtt_auto",
        fetch_source="youtube_transcript_api",
        watch_url=f"https://www.youtube.com/watch?v={video_id}",
    )


class TestConfiguration:
    def test_rotation_is_off_by_default(self) -> None:
        assert rot.rotation_mode() == "off"
        assert rot.rotation_enabled() is False

    @pytest.mark.parametrize("mode", ["control", "ssh"])
    def test_known_modes_enable_rotation(
        self, mode: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", mode)
        assert rot.rotation_enabled() is True

    def test_max_rotations_default_and_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert rot.max_rotations() == 3
        monkeypatch.setenv("YOUTUBE_PROXY_MAX_ROTATIONS", "7")
        assert rot.max_rotations() == 7
        monkeypatch.setenv("YOUTUBE_PROXY_MAX_ROTATIONS", "nonsense")
        assert rot.max_rotations() == 3

    def test_rotate_refuses_when_disabled(self) -> None:
        with pytest.raises(rot.RotationError, match="disabled"):
            rot.rotate_exit()

    def test_unknown_mode_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "carrier-pigeon")
        with pytest.raises(rot.RotationError, match="unknown"):
            rot.rotate_exit()


class TestRotateExit:
    def test_reports_ip_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "ssh")
        monkeypatch.setenv("YOUTUBE_PROXY_SSH_HOST", "lance@host")
        ips = iter(["1.1.1.1", "2.2.2.2"])
        monkeypatch.setattr(rot, "current_exit_ip", lambda *a, **k: next(ips))
        monkeypatch.setattr(rot, "_rotate_via_ssh", lambda: None)
        monkeypatch.setattr(rot.time, "sleep", lambda *_a: None)

        result = rot.rotate_exit()
        assert result.changed is True
        assert (result.old_ip, result.new_ip) == ("1.1.1.1", "2.2.2.2")
        assert result.mode == "ssh"

    def test_unchanged_ip_is_an_error_not_a_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A restart that lands on the same exit has not fixed anything."""
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "ssh")
        monkeypatch.setenv("YOUTUBE_PROXY_SSH_HOST", "lance@host")
        monkeypatch.setattr(rot, "current_exit_ip", lambda *a, **k: "1.1.1.1")
        monkeypatch.setattr(rot, "_rotate_via_ssh", lambda: None)
        monkeypatch.setattr(rot.time, "sleep", lambda *_a: None)
        monkeypatch.setattr(rot, "_SETTLE_TIMEOUT_S", 0.01)

        with pytest.raises(rot.RotationError, match="did not change"):
            rot.rotate_exit()

    def test_ssh_mode_requires_a_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "ssh")
        with pytest.raises(rot.RotationError, match="SSH_HOST"):
            rot.rotate_exit()

    def test_control_mode_requires_a_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "control")
        monkeypatch.setattr(rot, "current_exit_ip", lambda *a, **k: "1.1.1.1")
        with pytest.raises(rot.RotationError, match="CONTROL_URL"):
            rot.rotate_exit()


class TestFetchRetriesOnBlock:
    def test_block_rotates_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "ssh")
        calls = {"fetch": 0, "rotate": 0}

        def fake_fetch(url: str, **kwargs: Any) -> CaptionResult:
            assert kwargs["allow_rotation"] is False
            calls["fetch"] += 1
            if calls["fetch"] == 1:
                raise CaptionFetchError("blocked", "429", "vid")
            return _ok_result()

        monkeypatch.setattr(yt_captions, "fetch_caption_text", fake_fetch)
        monkeypatch.setattr(
            rot, "rotate_exit", lambda **_k: calls.__setitem__("rotate", 1)
        )

        got = yt_captions._fetch_with_rotation(
            "vid", languages=("en",), use_ytdlp_fallback=True, include_metadata=False
        )
        assert got.text == "hello world"
        assert calls == {"fetch": 2, "rotate": 1}

    def test_non_block_failures_do_not_rotate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`no_captions` is a fact about the video; every exit will agree."""
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "ssh")
        rotated = {"n": 0}

        def fake_fetch(url: str, **_k: Any) -> CaptionResult:
            raise CaptionFetchError("no_captions", "none", "vid")

        monkeypatch.setattr(yt_captions, "fetch_caption_text", fake_fetch)
        monkeypatch.setattr(rot, "rotate_exit", lambda **_k: rotated.__setitem__("n", 1))

        with pytest.raises(CaptionFetchError) as excinfo:
            yt_captions._fetch_with_rotation(
                "vid", languages=("en",), use_ytdlp_fallback=True, include_metadata=False
            )
        assert excinfo.value.reason == "no_captions"
        assert rotated["n"] == 0

    def test_gives_up_after_max_rotations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "ssh")
        monkeypatch.setenv("YOUTUBE_PROXY_MAX_ROTATIONS", "2")
        calls = {"fetch": 0, "rotate": 0}

        def fake_fetch(url: str, **_k: Any) -> CaptionResult:
            calls["fetch"] += 1
            raise CaptionFetchError("blocked", "429", "vid")

        monkeypatch.setattr(yt_captions, "fetch_caption_text", fake_fetch)
        monkeypatch.setattr(
            rot, "rotate_exit", lambda **_k: calls.__setitem__("rotate", calls["rotate"] + 1)
        )

        with pytest.raises(CaptionFetchError):
            yt_captions._fetch_with_rotation(
                "vid", languages=("en",), use_ytdlp_fallback=True, include_metadata=False
            )
        # 3 attempts (1 + 2 rotations), 2 rotations between them.
        assert calls == {"fetch": 3, "rotate": 2}

    def test_no_rotation_configured_means_one_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"fetch": 0}

        def fake_fetch(url: str, **_k: Any) -> CaptionResult:
            calls["fetch"] += 1
            raise CaptionFetchError("blocked", "429", "vid")

        monkeypatch.setattr(yt_captions, "fetch_caption_text", fake_fetch)
        with pytest.raises(CaptionFetchError):
            yt_captions._fetch_with_rotation(
                "vid", languages=("en",), use_ytdlp_fallback=True, include_metadata=False
            )
        assert calls["fetch"] == 1

    def test_failed_rotation_surfaces_the_original_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOUTUBE_PROXY_ROTATE_MODE", "ssh")

        def fake_fetch(url: str, **_k: Any) -> CaptionResult:
            raise CaptionFetchError("blocked", "429", "vid")

        def boom(**_k: Any) -> None:
            raise rot.RotationError("all exits exhausted")

        monkeypatch.setattr(yt_captions, "fetch_caption_text", fake_fetch)
        monkeypatch.setattr(rot, "rotate_exit", boom)

        with pytest.raises(CaptionFetchError) as excinfo:
            yt_captions._fetch_with_rotation(
                "vid", languages=("en",), use_ytdlp_fallback=True, include_metadata=False
            )
        assert excinfo.value.reason == "blocked"
