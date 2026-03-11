#!/usr/bin/env python3
"""
Change-size and generated-file guardrails.

Usage examples:
  python scripts/check_change_guardrails.py --mode staged
  python scripts/check_change_guardrails.py --mode range --base-ref origin/main
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiffStats:
    files: int = 0
    added: int = 0
    deleted: int = 0

    @property
    def changed_lines(self) -> int:
        return self.added + self.deleted


BLOCKED_PATH_PATTERNS = [
    "web_dashboard/static/js/*.js",
    "web_dashboard/static/js/*.js.map",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/node_modules/**",
]


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{result.stderr.strip()}")
    return result.stdout


def _get_range_diff_numstat(base_ref: str) -> str:
    """Get numstat diff for base_ref...HEAD with resilient fallback.

    In shallow CI clones or bot-created branches, Git can fail with
    "no merge base" for three-dot range diffs. In that case, fall back
    to a two-dot diff so guardrails can still evaluate changed files.
    """
    try:
        return _run(["git", "diff", "--numstat", f"{base_ref}...HEAD"])
    except RuntimeError as exc:
        error_text = str(exc).lower()
        if "no merge base" not in error_text:
            raise

        print(
            f"[guardrails] WARN: no merge base for {base_ref}...HEAD; "
            f"falling back to {base_ref}..HEAD",
            file=sys.stderr,
        )
        return _run(["git", "diff", "--numstat", f"{base_ref}..HEAD"])


def _parse_numstat(output: str) -> tuple[DiffStats, list[str]]:
    stats = DiffStats()
    files: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_str, del_str, path = parts[0], parts[1], parts[2]
        files.append(path)
        stats.files += 1
        if add_str.isdigit():
            stats.added += int(add_str)
        if del_str.isdigit():
            stats.deleted += int(del_str)
    return stats, files


def _matches_any(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def _check_generated_ts_policy(changed_files: list[str]) -> list[str]:
    violations: list[str] = []
    changed = {p.replace("\\", "/") for p in changed_files}
    generated_js = [
        p
        for p in changed
        if p.startswith("web_dashboard/static/js/")
        and (p.endswith(".js") or p.endswith(".js.map"))
    ]
    if not generated_js:
        return violations

    ts_sources_changed = {
        p
        for p in changed
        if p.startswith("web_dashboard/src/js/") and p.endswith(".ts")
    }
    if not ts_sources_changed:
        violations.append(
            "Compiled JS changed without TypeScript source changes in web_dashboard/src/js/."
        )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate commit/PR guardrails.")
    parser.add_argument("--mode", choices=["staged", "range"], default="staged")
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--max-files", type=int, default=40)
    parser.add_argument("--max-lines", type=int, default=2000)
    args = parser.parse_args()

    allow_large = os.getenv("ALLOW_LARGE_COMMIT", "").lower() in ("1", "true", "yes", "on")

    if args.mode == "staged":
        diff_output = _run(["git", "diff", "--cached", "--numstat"])
    else:
        diff_output = _get_range_diff_numstat(args.base_ref)

    stats, files = _parse_numstat(diff_output)
    violations: list[str] = []

    blocked_files = [p for p in files if _matches_any(p, BLOCKED_PATH_PATTERNS)]
    if blocked_files:
        violations.append(
            "Blocked generated/runtime paths detected:\n  - " + "\n  - ".join(sorted(blocked_files))
        )

    violations.extend(_check_generated_ts_policy(files))

    if not allow_large:
        if stats.files > args.max_files:
            violations.append(f"File count {stats.files} exceeds max-files {args.max_files}.")
        if stats.changed_lines > args.max_lines:
            violations.append(
                f"Changed lines {stats.changed_lines} exceeds max-lines {args.max_lines}."
            )

    print(
        f"[guardrails] files={stats.files} added={stats.added} "
        f"deleted={stats.deleted} changed={stats.changed_lines}"
    )

    if violations:
        print("[guardrails] FAILED:")
        for violation in violations:
            print(f"- {violation}")
        if not allow_large:
            print("Set ALLOW_LARGE_COMMIT=1 to bypass size thresholds for exceptional cases.")
        return 1

    print("[guardrails] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
