#!/usr/bin/env python3
"""Compile Python files and report syntax/indent errors. Run from repo root."""
import py_compile
import sys
from pathlib import Path

# Exclude dirs with many generated/test files so the check finishes quickly
SKIP_PARTS = ("__pycache__", ".venv", "venv", "node_modules", "scripts", "debug", "schema", "test_files", "examples")

def main() -> int:
    root = Path(__file__).resolve().parent.parent
    to_compile: list[Path] = []
    # Main app and library code only (no web_dashboard/scripts, debug, etc.)
    for name in ("config", "data", "portfolio", "financial", "market_data", "utils", "display", "verification", "tests", "scripts"):
        path = root / name
        if not path.exists():
            continue
        if path.is_file() and path.suffix == ".py":
            to_compile.append(path)
        elif path.is_dir():
            to_compile.extend(path.rglob("*.py"))
    # web_dashboard: top-level .py and key subdirs only (skip scripts/, debug/, schema/)
    wd = root / "web_dashboard"
    if wd.is_dir():
        to_compile.extend(wd.glob("*.py"))
        for sub in ("routes", "signals", "utils", "pages", "scheduler", "data", "flask_*.py"):
            if sub.endswith(".py"):
                to_compile.extend(wd.glob(sub))
            else:
                d = wd / sub
                if d.is_dir():
                    to_compile.extend(d.rglob("*.py"))
    errors: list[tuple[str, str]] = []
    count = 0
    for p in to_compile:
        if p.suffix != ".py":
            continue
        s = str(p)
        if any(skip in s for skip in SKIP_PARTS):
            continue
        count += 1
        try:
            py_compile.compile(s, doraise=True)
        except py_compile.PyCompileError as e:
            try:
                rel = p.relative_to(root)
            except ValueError:
                rel = p
            errors.append((str(rel), str(e.msg)))
    for path, msg in errors:
        print(f"{path}: {msg}")
    if errors:
        print(f"\n{len(errors)} error(s) in {count} file(s) checked.")
        return 1
    print(f"OK: {count} file(s) compiled.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
