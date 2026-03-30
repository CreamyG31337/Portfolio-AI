#!/usr/bin/env python3
"""One-off: refresh Yahoo benchmark/commodity data into ``benchmark_data`` (includes futures QC).

PowerShell::

    cd web_dashboard
    ..\\venv\\Scripts\\python.exe run_benchmark_refresh.py

Optional explicit env file(s) (last wins for duplicate keys)::

    ..\\venv\\Scripts\\python.exe run_benchmark_refresh.py --env-file C:\\path\\to\\.env

Also honors process environment: if ``SUPABASE_SERVICE_ROLE_KEY`` is already set (e.g. CI),
``.env`` files are optional.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_here = Path(__file__).resolve().parent
_root = _here.parent


def _candidate_env_paths(extra: list[Path]) -> list[Path]:
    out: list[Path] = []
    for base in (_here, _root):
        out.append((base / ".env").resolve())

    raw = os.environ.get("PORTFOLIO_ENV_FILE", "")
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            out.append(Path(part).expanduser().resolve())

    for p in extra:
        out.append(p.expanduser().resolve())

    seen: set[Path] = set()
    unique: list[Path] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _load_env_files(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """Returns (found_and_loaded, missing).

    Earlier files use ``override=False`` so a shell-exported ``SUPABASE_*`` wins. The last file
    (typically ``--env-file``) uses ``override=True`` so it can override prior dotenv keys.
    """
    loaded: list[Path] = []
    missing: list[Path] = []
    for p in paths:
        if not p.is_file():
            missing.append(p)
            continue
        loaded.append(p)
    for i, p in enumerate(loaded):
        load_dotenv(p, override=(i == len(loaded) - 1 and i >= 0))
    return loaded, missing


def _service_key_ok() -> bool:
    return bool(os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def _url_ok() -> bool:
    return bool(os.getenv("SUPABASE_URL"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run benchmark_refresh_job (Yahoo → benchmark_data).")
    parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        type=Path,
        help="Additional .env path (repeatable). Loaded last so values override earlier files.",
    )
    args = parser.parse_args(argv)

    candidates = _candidate_env_paths([Path(p) for p in args.env_file])
    loaded, missing = _load_env_files(candidates)

    sys.path.insert(0, str(_here))
    sys.path.insert(0, str(_root))

    if not _url_ok() or not _service_key_ok():
        print("benchmark_refresh: Supabase credentials not available.", file=sys.stderr)
        print("  SUPABASE_URL set:", _url_ok(), file=sys.stderr)
        print("  service role / secret key set:", _service_key_ok(), file=sys.stderr)
        print("  .env files loaded:", file=sys.stderr)
        for p in loaded:
            print(f"    OK  {p}", file=sys.stderr)
        for p in missing:
            print(f"    —   {p} (not found)", file=sys.stderr)
        print(
            "  Fix: add web_dashboard/.env or repo-root .env, set PORTFOLIO_ENV_FILE, "
            "pass --env-file, or export SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.",
            file=sys.stderr,
        )
        return 1

    from scheduler.jobs_metrics import benchmark_refresh_job

    benchmark_refresh_job()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
