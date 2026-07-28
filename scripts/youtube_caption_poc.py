#!/usr/bin/env python3
"""Phase K1 PoC: video URL -> cleaned caption text (no DB writes).

Usage (from repo root, venv active)::

    python scripts/youtube_caption_poc.py "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    python scripts/youtube_caption_poc.py LPEXkI_4qI4 --no-metadata
    python scripts/youtube_caption_poc.py LPEXkI_4qI4 --out captions.txt

Exit codes:
  0 success
  1 fetch/parse failure (reason printed)
  2 bad CLI usage
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web_dashboard"
for path in (_REPO_ROOT, _WEB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from youtube_captions import CaptionFetchError, fetch_caption_text  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch + clean YouTube captions (Phase K1 PoC)."
    )
    parser.add_argument("url_or_id", help="YouTube watch URL or 11-char video id")
    parser.add_argument(
        "--langs",
        default="en,en-US,en-GB",
        help="Comma-separated language preference (default: en,en-US,en-GB)",
    )
    parser.add_argument(
        "--no-ytdlp-fallback",
        action="store_true",
        help="Disable yt-dlp VTT fallback",
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Skip yt-dlp metadata lookup (faster)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write full cleaned text to this file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary to stdout",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=800,
        help="How many chars of caption text to print (default 800; 0 = all)",
    )
    args = parser.parse_args(argv)

    langs = [part.strip() for part in args.langs.split(",") if part.strip()]
    try:
        result = fetch_caption_text(
            args.url_or_id,
            languages=langs,
            use_ytdlp_fallback=not args.no_ytdlp_fallback,
            include_metadata=not args.no_metadata,
        )
    except CaptionFetchError as exc:
        payload = {
            "ok": False,
            "reason": exc.reason,
            "video_id": exc.video_id,
            "error": str(exc),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"FAIL reason={exc.reason} video_id={exc.video_id}", file=sys.stderr)
            print(exc, file=sys.stderr)
            print(
                "\nNotes: no Google API key/OAuth required for public captions. "
                "If reason=blocked, YouTube is IP-blocking (common on cloud); "
                "try from residential network or add rotating proxies later. "
                "If reason=age_restricted, login/cookies would be needed — out of scope for K1.",
                file=sys.stderr,
            )
        return 1

    if args.out:
        args.out.write_text(result.text, encoding="utf-8")

    summary = {
        "ok": True,
        "video_id": result.video_id,
        "watch_url": result.watch_url,
        "title": result.title,
        "channel": result.channel,
        "channel_id": result.channel_id,
        "duration_s": result.duration_s,
        "upload_date": result.upload_date,
        "language": result.language,
        "caption_kind": result.caption_kind,
        "fetch_source": result.fetch_source,
        "snippet_count": result.snippet_count,
        "char_count": result.char_count,
        "out_file": str(args.out) if args.out else None,
    }

    if args.json:
        summary["text_preview"] = (
            result.text
            if args.preview_chars <= 0
            else result.text[: args.preview_chars]
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    print("OK")
    for key, value in summary.items():
        if key == "ok":
            continue
        print(f"  {key}: {value}")
    print("--- caption text ---")
    if args.preview_chars <= 0:
        print(result.text)
    else:
        preview = result.text[: args.preview_chars]
        print(preview)
        if len(result.text) > args.preview_chars:
            print(f"\n… [{len(result.text) - args.preview_chars} more chars]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
