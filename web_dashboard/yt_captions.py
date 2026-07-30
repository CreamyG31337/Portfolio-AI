"""Allowlisted video caption fetch + clean (Phase K1) and source listing (Phase K3).

Primary path uses the caption provider library; a listing/VTT client is the
fallback when the primary path cannot return a body. No DB writes, no scheduler.

``list_source_videos`` / ``list_channel_videos`` / ``list_search_videos`` (K3)
discover candidates for one ``youtube_sources`` row via flat playlist metadata
only (no media, no captions). They raise ``CaptionFetchError`` with the same
``FailureReason`` literals so the poll job has one error vocabulary.

Failure modes:

- ``no_captions`` — disabled / none in preferred languages
- ``blocked`` — egress / provider rate or IP block; set ``YOUTUBE_PROXY_URL`` and
  pace requests (fallback listing client shares the same egress)
- ``age_restricted`` — needs login; skip for v0
- ``unavailable`` — private / removed / unplayable
- ``dependency`` — caption provider or listing client package missing
- ``parse`` — bad URL / empty body after clean
"""

from __future__ import annotations

import html
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# Optional HTTP(S) egress for caption + listing calls. Provider blocks are per
# egress IP and can last hours; the VTT fallback uses the same address, so a
# proxy here applies to both paths.
_PROXY_ENV = "YOUTUBE_PROXY_URL"


def caption_proxy_url() -> Optional[str]:
    """Configured egress proxy, or ``None`` for a direct connection."""
    value = (os.environ.get(_PROXY_ENV) or "").strip()
    return value or None

CaptionKind = Literal["manual", "auto", "vtt_manual", "vtt_auto"]
FetchSource = Literal["youtube_transcript_api", "yt_dlp"]
FailureReason = Literal[
    "no_captions",
    "blocked",
    "age_restricted",
    "unavailable",
    "dependency",
    "parse",
    "unknown",
]

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Exactly 11 id chars, not a slice of a longer run (which would match slugs).
_LOOSE_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{11}(?![A-Za-z0-9_-])")
_TAG_RE = re.compile(r"<[^>]+>")
_TIMESTAMP_ARROW_RE = re.compile(
    r"^\d{2}:\d{2}(?::\d{2})?[.,]\d{3}\s*-->\s*\d{2}:\d{2}(?::\d{2})?[.,]\d{3}"
)
_VTT_META_RE = re.compile(
    r"^(WEBVTT|NOTE|STYLE|REGION|Kind:|Language:)", re.IGNORECASE
)
_BRACKET_NOISE_RE = re.compile(
    r"^\[(?:music|applause|laughter|cheering|silence|inaudible|crosstalk|"
    r"foreign|narrator|blank_audio)[^\]]*\]$",
    re.IGNORECASE,
)
_MUSIC_NOTE_RE = re.compile(r"^[♪♫\s]+$")
_DEFAULT_LANGS: tuple[str, ...] = ("en", "en-US", "en-GB")


class CaptionFetchError(Exception):
    """Raised when captions cannot be retrieved or cleaned."""

    def __init__(self, reason: FailureReason, message: str, video_id: str = "") -> None:
        self.reason: FailureReason = reason
        self.video_id = video_id
        super().__init__(message)


@dataclass(frozen=True)
class CaptionResult:
    """Cleaned caption text plus enough metadata for a later K2 article upsert."""

    video_id: str
    text: str
    language: str
    caption_kind: CaptionKind
    fetch_source: FetchSource
    watch_url: str
    title: Optional[str] = None
    channel: Optional[str] = None
    channel_id: Optional[str] = None
    duration_s: Optional[int] = None
    upload_date: Optional[str] = None  # YYYYMMDD when listing client supplies it
    snippet_count: int = 0
    char_count: int = 0
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def truncated_preview(self) -> str:
        if len(self.text) <= 500:
            return self.text
        return self.text[:500] + "…"


def parse_video_id(url_or_id: str) -> str:
    """Extract an 11-char YouTube video id from a URL or bare id."""
    raw = (url_or_id or "").strip()
    if not raw:
        raise CaptionFetchError("parse", "Empty video URL/id")

    if _VIDEO_ID_RE.match(raw):
        return raw

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = path.lstrip("/").split("/")[0]
        if _VIDEO_ID_RE.match(candidate):
            return candidate

    if "youtube.com" in host or "youtube-nocookie.com" in host:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            candidate = qs["v"][0]
            if _VIDEO_ID_RE.match(candidate):
                return candidate
        for prefix in ("/embed/", "/shorts/", "/live/", "/v/"):
            if path.startswith(prefix):
                candidate = path[len(prefix) :].split("/")[0]
                if _VIDEO_ID_RE.match(candidate):
                    return candidate

    # Last resort: an exactly-11-char token, but only inside something that is
    # actually a YouTube reference. Scanning any string would happily turn a
    # foreign URL slug into a valid-looking id and fetch an unrelated video.
    if _looks_like_youtube(raw, host):
        match = _LOOSE_ID_RE.search(raw)
        if match:
            return match.group(0)

    raise CaptionFetchError("parse", f"Could not parse YouTube video id from: {raw!r}")


def _looks_like_youtube(raw: str, host: str) -> bool:
    if host:
        return (
            host in {"youtu.be", "www.youtu.be"}
            or "youtube.com" in host
            or "youtube-nocookie.com" in host
        )
    # No parseable host — free text that mentions a YouTube link still counts.
    lowered = raw.lower()
    return "youtube.com" in lowered or "youtu.be" in lowered


def watch_url_for(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def clean_caption_lines(lines: Iterable[str]) -> str:
    """Normalize caption cue lines into plain text for summarization."""
    cleaned: list[str] = []
    prev_norm = ""
    for raw in lines:
        line = _normalize_cue_text(raw)
        if not line:
            continue
        if _BRACKET_NOISE_RE.match(line) or _MUSIC_NOTE_RE.match(line):
            continue
        norm = re.sub(r"\s+", " ", line).strip()
        if not norm or norm == prev_norm:
            continue
        # Rolling auto-caption cues often restate the previous cue as a prefix.
        if prev_norm and norm.startswith(prev_norm):
            addition = norm[len(prev_norm) :].strip()
            if addition:
                cleaned.append(addition)
                prev_norm = norm
            continue
        if prev_norm and prev_norm.startswith(norm):
            continue
        overlap_added = _overlap_suffix_addition(prev_norm, norm)
        if overlap_added is not None:
            if overlap_added:
                cleaned.append(overlap_added)
            prev_norm = norm
            continue
        cleaned.append(norm)
        prev_norm = norm

    text = " ".join(cleaned)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    return text.strip()


def parse_vtt_text(vtt: str) -> str:
    """Strip WEBVTT chrome and return cleaned plain text."""
    if not vtt or not vtt.strip():
        return ""

    raw_lines = vtt.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[str] = []
    current: list[str] = []
    for idx, raw_line in enumerate(raw_lines):
        line = raw_line.strip()
        if not line:
            if current:
                cues.append(" ".join(current))
                current = []
            continue
        if _VTT_META_RE.match(line):
            continue
        if _TIMESTAMP_ARROW_RE.match(line):
            if current:
                cues.append(" ".join(current))
                current = []
            continue
        # A bare number is a cue identifier only when a timestamp follows it.
        # Otherwise it is caption text — earnings calls say bare years a lot.
        if line.isdigit() and _next_line_is_timestamp(raw_lines, idx):
            continue
        current.append(line)

    if current:
        cues.append(" ".join(current))

    return clean_caption_lines(cues)


def fetch_caption_text(
    url_or_id: str,
    *,
    languages: Sequence[str] = _DEFAULT_LANGS,
    use_ytdlp_fallback: bool = True,
    include_metadata: bool = True,
) -> CaptionResult:
    """Fetch + clean captions for a video.

    Raises ``CaptionFetchError`` with a stable ``reason`` for soft-fail jobs.
    """
    video_id = parse_video_id(url_or_id)
    langs = tuple(languages) if languages else _DEFAULT_LANGS

    primary_error: Optional[CaptionFetchError] = None
    try:
        result = _fetch_via_transcript_api(video_id, langs)
        if include_metadata:
            result = _maybe_attach_ytdlp_metadata(result)
        return result
    except CaptionFetchError as exc:
        # Note `dependency` is not special-cased: the listing/VTT client alone is
        # a complete path, so a missing caption provider should degrade.
        primary_error = exc
        logger.info(
            "caption provider failed for %s (%s): %s",
            video_id,
            exc.reason,
            exc,
        )

    if use_ytdlp_fallback:
        try:
            return _fetch_via_ytdlp(video_id, langs)
        except CaptionFetchError as exc:
            logger.info(
                "listing client fallback failed for %s (%s): %s",
                video_id,
                exc.reason,
                exc,
            )
            if (
                primary_error is not None
                and primary_error.reason == "dependency"
                and exc.reason == "dependency"
            ):
                raise CaptionFetchError(
                    "dependency",
                    "neither caption provider nor listing client is installed",
                    video_id,
                ) from exc
            # Prefer the more specific primary reason when both fail. A bare
            # `dependency` says nothing about the video, so let the fallback win.
            if primary_error is not None and primary_error.reason not in {
                "unknown",
                "dependency",
            }:
                raise primary_error from exc
            raise

    if primary_error is not None:
        raise primary_error
    raise CaptionFetchError("unknown", f"No caption source succeeded for {video_id}", video_id)


def _next_line_is_timestamp(lines: Sequence[str], idx: int) -> bool:
    """Whether the next non-empty line after ``idx`` is a VTT cue timing line."""
    for candidate in lines[idx + 1 :]:
        stripped = candidate.strip()
        if not stripped:
            return False
        return bool(_TIMESTAMP_ARROW_RE.match(stripped))
    return False


def _normalize_cue_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = text.replace("\n", " ")
    # Also clears auto-VTT inline timing tags (``<00:00:01.000>``).
    text = _TAG_RE.sub("", text)
    return text.strip()


def _overlap_suffix_addition(prev: str, current: str) -> Optional[str]:
    """If ``current`` shares a word-prefix overlap with ``prev`` suffix, return new words.

    Returns ``None`` when there is no meaningful overlap (caller should append whole line).
    """
    if not prev or not current:
        return None
    prev_words = prev.split()
    cur_words = current.split()
    max_overlap = min(len(prev_words), len(cur_words))
    for size in range(max_overlap, 2, -1):  # need at least 3 overlapping words
        if prev_words[-size:] == cur_words[:size]:
            return " ".join(cur_words[size:]).strip()
    return None


def _build_transcript_api(api_cls):
    """Caption provider client, routed through the proxy when one is configured.

    Falls back to a direct client if this version of the library predates
    proxy support, so a missing feature degrades rather than breaking.
    """
    proxy = caption_proxy_url()
    if not proxy:
        return api_cls()
    try:
        from youtube_transcript_api.proxies import GenericProxyConfig as _ProxyConfig
    except ImportError:
        logger.warning(
            "%s is set but caption provider proxy support is unavailable; "
            "fetching directly",
            _PROXY_ENV,
        )
        return api_cls()
    return api_cls(proxy_config=_ProxyConfig(http_url=proxy, https_url=proxy))


def _apply_ytdlp_proxy(opts: dict) -> dict:
    """Add the egress proxy to listing-client options when configured."""
    proxy = caption_proxy_url()
    if proxy:
        opts["proxy"] = proxy
    return opts


def _fetch_via_transcript_api(video_id: str, languages: Sequence[str]) -> CaptionResult:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi as _CaptionProvider
        from youtube_transcript_api._errors import (
            AgeRestricted as _AgeRestricted,
            IpBlocked as _IpBlocked,
            NoTranscriptFound as _NoTranscriptFound,
            RequestBlocked as _RequestBlocked,
            TranscriptsDisabled as _TranscriptsDisabled,
            VideoUnavailable as _VideoUnavailable,
            YouTubeRequestFailed as _ProviderRequestFailed,
        )
    except ImportError as exc:
        raise CaptionFetchError(
            "dependency",
            "caption provider is not installed",
            video_id,
        ) from exc

    api = _build_transcript_api(_CaptionProvider)
    try:
        listing = api.list(video_id)
        transcript = None
        kind: CaptionKind = "auto"
        try:
            transcript = listing.find_manually_created_transcript(list(languages))
            kind = "manual"
        except Exception:
            try:
                transcript = listing.find_generated_transcript(list(languages))
                kind = "auto"
            except Exception:
                # Last resort: any preferred language via find_transcript (may translate).
                transcript = listing.find_transcript(list(languages))
                kind = "auto" if transcript.is_generated else "manual"

        fetched = transcript.fetch()
        snippets = [snippet.text for snippet in fetched]
        text = clean_caption_lines(snippets)
        if not text:
            raise CaptionFetchError(
                "no_captions",
                f"Caption body empty after clean for {video_id}",
                video_id,
            )
        return CaptionResult(
            video_id=video_id,
            text=text,
            language=getattr(transcript, "language_code", languages[0]),
            caption_kind=kind,
            fetch_source="youtube_transcript_api",
            watch_url=watch_url_for(video_id),
            snippet_count=len(snippets),
            char_count=len(text),
        )
    except CaptionFetchError:
        raise
    except _TranscriptsDisabled as exc:
        raise CaptionFetchError(
            "no_captions", f"Transcripts disabled for {video_id}", video_id
        ) from exc
    except _NoTranscriptFound as exc:
        raise CaptionFetchError(
            "no_captions", f"No captions in {list(languages)} for {video_id}", video_id
        ) from exc
    except _AgeRestricted as exc:
        raise CaptionFetchError(
            "age_restricted", f"Age-restricted video {video_id}", video_id
        ) from exc
    except (_RequestBlocked, _IpBlocked) as exc:
        raise CaptionFetchError(
            "blocked",
            f"Caption request blocked for {video_id}",
            video_id,
        ) from exc
    except _VideoUnavailable as exc:
        raise CaptionFetchError(
            "unavailable", f"Video unavailable: {video_id}", video_id
        ) from exc
    except _ProviderRequestFailed as exc:
        raise CaptionFetchError(
            "unknown", f"Caption provider request failed for {video_id}: {exc}", video_id
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        name = type(exc).__name__
        if "Blocked" in name:
            raise CaptionFetchError("blocked", str(exc), video_id) from exc
        if "AgeRestricted" in name:
            raise CaptionFetchError("age_restricted", str(exc), video_id) from exc
        raise CaptionFetchError("unknown", f"{name}: {exc}", video_id) from exc


def _fetch_via_ytdlp(video_id: str, languages: Sequence[str]) -> CaptionResult:
    try:
        import yt_dlp as _listing_client
    except ImportError as exc:
        raise CaptionFetchError(
            "dependency", "listing client is not installed", video_id
        ) from exc

    url = watch_url_for(video_id)
    lang_list = list(languages)

    with tempfile.TemporaryDirectory(prefix="ytcaps_") as tmp:
        outtmpl = str(Path(tmp) / "%(id)s.%(ext)s")
        opts: dict = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": lang_list,
            "subtitlesformat": "vtt",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
        }
        _apply_ytdlp_proxy(opts)
        try:
            with _listing_client.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as exc:
            msg = str(exc).lower()
            if "sign in" in msg or "age" in msg:
                raise CaptionFetchError("age_restricted", str(exc), video_id) from exc
            if "private" in msg or "unavailable" in msg or "removed" in msg:
                raise CaptionFetchError("unavailable", str(exc), video_id) from exc
            raise CaptionFetchError(
                "unknown", f"listing client failed: {exc}", video_id
            ) from exc

        vtt_path, kind = _pick_vtt_file(Path(tmp), video_id, lang_list)
        if vtt_path is None:
            raise CaptionFetchError(
                "no_captions",
                f"listing client wrote no VTT for {video_id} in {lang_list}",
                video_id,
            )
        text = parse_vtt_text(vtt_path.read_text(encoding="utf-8", errors="replace"))
        if not text:
            raise CaptionFetchError(
                "no_captions",
                f"listing client VTT empty after clean for {video_id}",
                video_id,
            )

        language = _language_from_vtt_name(vtt_path.name, lang_list)
        return CaptionResult(
            video_id=video_id,
            text=text,
            language=language,
            caption_kind=kind,
            fetch_source="yt_dlp",
            watch_url=url,
            title=(info or {}).get("title") if info else None,
            channel=(info or {}).get("channel") if info else None,
            channel_id=(info or {}).get("channel_id") if info else None,
            duration_s=_as_int((info or {}).get("duration")) if info else None,
            upload_date=(info or {}).get("upload_date") if info else None,
            snippet_count=0,
            char_count=len(text),
        )


def _language_from_vtt_name(name: str, languages: Sequence[str]) -> str:
    """Pull the language tag out of a listing-client VTT filename.

    Names are ``{id}.{lang}.vtt`` or ``{id}.{lang}.auto.vtt``; splitting on
    position alone picks up ``auto`` on the latter.
    """
    parts = name.lower().split(".")
    for lang in languages:
        if lang.lower() in parts:
            return lang  # preserve the caller's casing, e.g. en-US
    # Listing client can substitute a language we did not ask for; take the last
    # non-marker segment between the video id and the extension.
    for part in reversed(parts[1:-1]):
        if part not in {"auto", "automatic"}:
            return part
    return languages[0] if languages else ""


def _pick_vtt_file(
    directory: Path, video_id: str, languages: Sequence[str]
) -> tuple[Optional[Path], CaptionKind]:
    files = list(directory.glob(f"{video_id}*.vtt"))
    if not files:
        files = list(directory.glob("*.vtt"))
    if not files:
        return None, "vtt_auto"

    # Prefer non-auto (manual) then language order.
    def rank(path: Path) -> tuple[int, int]:
        name = path.name.lower()
        is_auto = ".auto." in name or name.endswith(".auto.vtt")
        # Common names: {id}.{lang}.vtt for manual or auto depending on flags;
        # also {id}.{lang}.auto.vtt in some client versions.
        lang_rank = 99
        for idx, lang in enumerate(languages):
            if f".{lang.lower()}." in name or name.endswith(f".{lang.lower()}.vtt"):
                lang_rank = idx
                break
        return (1 if is_auto else 0, lang_rank)

    best = sorted(files, key=rank)[0]
    name = best.name.lower()
    kind: CaptionKind = (
        "vtt_auto" if (".auto." in name or "automatic" in name) else "vtt_manual"
    )
    # Auto-only writes often yield lang.vtt without .auto. — treat as auto
    # when only auto was requested / no separate manual file exists.
    if kind == "vtt_manual" and len(files) == 1:
        kind = "vtt_auto"
    return best, kind


def _maybe_attach_ytdlp_metadata(result: CaptionResult) -> CaptionResult:
    """Best-effort metadata fill without failing the caption fetch."""
    if result.title and result.channel_id:
        return result
    try:
        import yt_dlp as _listing_client
    except ImportError:
        return result

    opts = _apply_ytdlp_proxy({
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    })
    try:
        with _listing_client.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(result.watch_url, download=False)
    except Exception as exc:
        logger.debug("listing client metadata skip for %s: %s", result.video_id, exc)
        return result

    if not info:
        return result
    return CaptionResult(
        video_id=result.video_id,
        text=result.text,
        language=result.language,
        caption_kind=result.caption_kind,
        fetch_source=result.fetch_source,
        watch_url=result.watch_url,
        title=result.title or info.get("title"),
        channel=result.channel or info.get("channel"),
        channel_id=result.channel_id or info.get("channel_id"),
        duration_s=result.duration_s or _as_int(info.get("duration")),
        upload_date=result.upload_date or info.get("upload_date"),
        snippet_count=result.snippet_count,
        char_count=result.char_count,
        extras=result.extras,
    )


def _as_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Channel / playlist / search listing (Phase K3)
# ---------------------------------------------------------------------------
#
# Discovery for the allowlist poll job. Flat playlist metadata only: one request
# per source, no media and no captions, so a poll of N sources costs N requests
# rather than N x videos. Caption fetch stays in ``fetch_caption_text``.
#
# Failures raise ``CaptionFetchError`` with the same ``FailureReason`` literals
# the caption path uses, so the poller has one vocabulary to write into
# ``youtube_sources.last_error_reason``.

_LISTING_DEFAULT_LIMIT = 5
# Search is the one kind that can reach outside the allowlisted channel, so keep
# N tiny — a curated ``query_text`` (e.g. one ticker's IR call) not a topic sweep.
_SEARCH_MAX_LIMIT = 3
# Flat entries for a channel root come back as tab playlists; recurse a couple
# of levels to reach the video entries without looping forever.
_FLAT_MAX_DEPTH = 3


@dataclass(frozen=True)
class VideoListing:
    """One discovered video, before any caption work is attempted."""

    video_id: str
    watch_url: str
    title: Optional[str] = None
    upload_date: Optional[str] = None  # YYYYMMDD when listing client supplies it
    duration_s: Optional[int] = None


def channel_videos_url(
    *,
    channel_id: Optional[str] = None,
    handle: Optional[str] = None,
    playlist_id: Optional[str] = None,
) -> str:
    """Listing-client target URL for a channel, handle, or playlist.

    Prefers the ``/videos`` tab over the channel root: the root also carries
    shorts / live / playlist tabs, which flat extraction returns as nested
    playlists and which are not uploads in publication order.
    """
    raw_playlist = (playlist_id or "").strip()
    if raw_playlist:
        if raw_playlist.lower().startswith("http"):
            return raw_playlist
        return f"https://www.youtube.com/playlist?list={raw_playlist}"

    cid = (channel_id or "").strip()
    if cid:
        return f"https://www.youtube.com/channel/{cid}/videos"

    from yt_brand_display import undecorate_brand_text

    raw_handle = undecorate_brand_text((handle or "").strip())
    if raw_handle:
        if raw_handle.lower().startswith("http"):
            return raw_handle.rstrip("/") + "/videos"
        return f"https://www.youtube.com/@{raw_handle.lstrip('@')}/videos"

    raise CaptionFetchError(
        "parse", "Need one of channel_id / handle / playlist_id to list videos"
    )


def list_channel_videos(
    *,
    channel_id: Optional[str] = None,
    handle: Optional[str] = None,
    playlist_id: Optional[str] = None,
    limit: int = _LISTING_DEFAULT_LIMIT,
) -> list[VideoListing]:
    """Newest-first uploads for one channel / playlist (no media, no captions)."""
    target = channel_videos_url(
        channel_id=channel_id, handle=handle, playlist_id=playlist_id
    )
    entries = _flat_playlist_entries(target, max(1, int(limit)))
    return _listings_from_entries(entries, max(1, int(limit)))


def list_search_videos(
    query_text: str, *, limit: int = _SEARCH_MAX_LIMIT
) -> list[VideoListing]:
    """Top results for a curated search string, capped at ``_SEARCH_MAX_LIMIT``."""
    query = (query_text or "").strip()
    if not query:
        raise CaptionFetchError("parse", "Empty query_text for search listing")
    capped = max(1, min(int(limit), _SEARCH_MAX_LIMIT))
    entries = _flat_playlist_entries(f"ytsearch{capped}:{query}", capped)
    return _listings_from_entries(entries, capped)


def list_source_videos(
    source_row: Mapping[str, Any], *, limit: Optional[int] = None
) -> list[VideoListing]:
    """Discover newest-first candidates for one ``youtube_sources`` row.

    ``kind`` dispatch: ``search`` uses ``query_text``; every other kind
    (``channel`` / ``ir`` / ``macro`` / ``earnings_search`` / ``playlist``) lists
    uploads from ``channel_id`` → ``handle``. ``playlist`` reads the playlist
    id/URL from ``channel_id`` or ``query_text`` — the table has no dedicated
    column, and adding one is not worth a migration until a playlist source
    exists.
    """
    row = dict(source_row or {})
    kind = str(row.get("kind") or "channel").strip().lower()
    per_poll = _as_int(row.get("max_videos_per_poll")) or _LISTING_DEFAULT_LIMIT
    effective = per_poll if limit is None else min(per_poll, int(limit))
    effective = max(1, effective)

    if kind == "search":
        return list_search_videos(row.get("query_text") or "", limit=effective)

    if kind == "playlist":
        return list_channel_videos(
            playlist_id=(row.get("channel_id") or row.get("query_text") or ""),
            limit=effective,
        )

    return list_channel_videos(
        channel_id=row.get("channel_id"),
        handle=row.get("handle"),
        limit=effective,
    )


def _flat_playlist_entries(target: str, limit: int) -> list[dict]:
    """Run one flat listing extraction and return its (possibly nested) entries."""
    try:
        import yt_dlp as _listing_client
    except ImportError as exc:
        raise CaptionFetchError(
            "dependency", "listing client is not installed"
        ) from exc

    opts = _apply_ytdlp_proxy(
        {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "playlistend": limit,
            "ignoreerrors": True,
        }
    )
    try:
        with _listing_client.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
    except Exception as exc:
        msg = str(exc).lower()
        if "blocked" in msg or "429" in msg or "too many requests" in msg:
            raise CaptionFetchError(
                "blocked", f"listing client blocked: {exc}"
            ) from exc
        if "not found" in msg or "does not exist" in msg or "unavailable" in msg:
            raise CaptionFetchError(
                "unavailable", f"listing target unavailable: {exc}"
            ) from exc
        raise CaptionFetchError(
            "unknown", f"listing client failed: {exc}"
        ) from exc

    if not info:
        raise CaptionFetchError("unavailable", f"listing client returned no info for {target}")
    entries = info.get("entries")
    if entries is None:
        # A bare video URL extracts as a single video, not a playlist.
        return [info]
    return [e for e in entries if e]


def _listings_from_entries(entries: Sequence[Any], limit: int) -> list[VideoListing]:
    """Flatten flat-playlist entries to newest-first ``VideoListing`` objects.

    The listing client preserves the source's own ordering, which for a
    ``/videos`` tab and for search results is newest-first — this does not
    re-sort, because ``upload_date`` is usually absent in flat mode and sorting
    on a mostly-null key would scramble the order the cursor walk depends on.
    """
    listings: list[VideoListing] = []
    seen: set[str] = set()

    def walk(items: Sequence[Any], depth: int) -> None:
        for entry in items:
            if len(listings) >= limit:
                return
            if not isinstance(entry, Mapping):
                continue
            nested = entry.get("entries")
            if nested and depth < _FLAT_MAX_DEPTH:
                walk([e for e in nested if e], depth + 1)
                continue
            video_id = _listing_video_id(entry)
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            listings.append(
                VideoListing(
                    video_id=video_id,
                    watch_url=watch_url_for(video_id),
                    title=(entry.get("title") or None),
                    upload_date=(entry.get("upload_date") or None),
                    duration_s=_as_int(entry.get("duration")),
                )
            )

    walk(list(entries), 0)
    return listings


def _listing_video_id(entry: Mapping[str, Any]) -> Optional[str]:
    """Video id from a flat entry, tolerating tab/playlist rows that have none."""
    candidate = str(entry.get("id") or "").strip()
    if _VIDEO_ID_RE.match(candidate):
        return candidate
    for key in ("url", "webpage_url"):
        raw = str(entry.get(key) or "").strip()
        if not raw:
            continue
        if _VIDEO_ID_RE.match(raw):
            return raw
        try:
            return parse_video_id(raw)
        except CaptionFetchError:
            continue
    return None
