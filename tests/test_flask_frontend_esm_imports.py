"""Guard: dashboard page modules must not import npm packages as bare specifiers.

tsc copies `import { Modal } from "flowbite"` into static/js/*.js. Browsers then
throw Failed to resolve module specifier "flowbite", so DOMContentLoaded never
runs and pages hang on "Loading …". Flowbite is already on the page globally;
use data-modal-target / data-modal-hide clicks instead.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_JS = ROOT / "web_dashboard" / "src" / "js"
STATIC_JS = ROOT / "web_dashboard" / "static" / "js"

# Matches `from "flowbite"` / `from 'chart.js'` but not `from './csrf.js'`.
_BARE_FROM = re.compile(r"""from\s+['"](?![./])([^'"]+)['"]""")


def _scan(directory: Path, pattern: str) -> list[str]:
    offenders: list[str] = []
    for path in sorted(directory.glob(pattern)):
        if path.name.endswith(".d.ts") or path.name.endswith(".test.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            match = _BARE_FROM.search(line)
            if match:
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}: {stripped}")
    return offenders


def test_dashboard_ts_has_no_bare_npm_imports() -> None:
    offenders = _scan(SRC_JS, "*.ts")
    assert not offenders, (
        "Bare npm imports break browser ESM (page JS never runs).\n"
        + "\n".join(offenders)
    )


def test_compiled_dashboard_js_has_no_bare_npm_imports() -> None:
    offenders = _scan(STATIC_JS, "*.js")
    assert not offenders, (
        "Compiled JS still has bare npm imports; run `pnpm run build:ts`.\n"
        + "\n".join(offenders)
    )
