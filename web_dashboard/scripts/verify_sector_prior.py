#!/usr/bin/env python3
"""Phase 3c verification: confirm the sector rotation prior block lands in the
ticker meta artifact bundle for tickers with mapped sectors.

Reads from Research + Supabase using the production code path. Does NOT call
Ollama — only builds the bundle the meta LLM would see.

Examples (repo root, venv activated)::

    # Default sample: AAPL plus a handful of common sectors
    python web_dashboard/scripts/verify_sector_prior.py

    # Custom tickers
    python web_dashboard/scripts/verify_sector_prior.py AAPL MSFT JNJ XOM

    # Dump the full bundle text for one ticker (debug)
    python web_dashboard/scripts/verify_sector_prior.py AAPL --dump
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable

_script = Path(__file__).resolve()
_web_root = _script.parent.parent
_project_root = _web_root.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_web_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_web_root / ".env")

from meta_analysis_service import (  # noqa: E402
    TickerMetaAnalysisService,
    artifact_bundle_digest,
)
from postgres_client import PostgresClient  # noqa: E402
from settings import is_meta_analysis_phase3_sector_enabled  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402

DEFAULT_TICKERS = ["AAPL", "MSFT", "JNJ", "XOM", "JPM"]


def _split_blocks(bundle: str) -> dict[str, list[str]]:
    """Split a bundle into ``{section_heading: lines}`` for easy assertions."""
    sections: dict[str, list[str]] = {}
    current_heading: str | None = None
    current_lines: list[str] = []
    for raw in bundle.splitlines():
        if raw.startswith("### "):
            if current_heading is not None:
                sections[current_heading] = current_lines
            current_heading = raw[4:].strip()
            current_lines = []
        else:
            current_lines.append(raw)
    if current_heading is not None:
        sections[current_heading] = current_lines
    return sections


def _summarize_sector_block(lines: list[str]) -> dict[str, str]:
    """Pull the fields we render in `_append_sector_prior_block` for review."""
    out: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line.startswith("- "):
            continue
        key, _, val = line[2:].partition(":")
        if key:
            out[key.strip()] = val.strip()
    return out


def verify_tickers(tickers: Iterable[str], dump: bool) -> int:
    if not is_meta_analysis_phase3_sector_enabled():
        print("META_ANALYSIS_PHASE3_SECTOR is OFF — sector prior block will not be added.")
        print("Set META_ANALYSIS_PHASE3_SECTOR=true to validate Phase 3c.")
        return 2

    ticker_list = list(tickers)
    service = TickerMetaAnalysisService(
        ollama=None,
        supabase=SupabaseClient(use_service_role=True),
        postgres=PostgresClient(),
    )
    print(
        f"Phase 3c verification — flag ON. Building artifact bundles for "
        f"{len(ticker_list)} ticker(s)..."
    )
    print()

    ok = 0
    missing_meta = 0
    missing_sector = 0
    missing_std = 0

    for ticker in ticker_list:
        ticker_u = str(ticker).upper().strip()
        bundle, primary = service.build_artifact_bundle(ticker_u)
        if not bundle:
            print(f"{ticker_u:<8} SKIP   no standard ticker_analysis row")
            missing_std += 1
            continue

        sections = _split_blocks(bundle)
        sector_heading = "Sector rotation prior (ETF flow synthesis)"
        sector_lines = sections.get(sector_heading)
        if sector_lines is None:
            print(f"{ticker_u:<8} FAIL   sector prior block not in bundle (Phase 3c regression)")
            continue

        fields = _summarize_sector_block(sector_lines)
        mapped = fields.get("mapped_sector", "")
        digest = artifact_bundle_digest(bundle)[:12]
        if mapped in ("", "MISSING (no sector on securities row)"):
            print(
                f"{ticker_u:<8} WARN   no securities.sector mapping "
                f"(bundle has block, no prior) digest={digest}"
            )
            missing_sector += 1
            continue
        if "MISSING" in fields.get("sector_meta", ""):
            print(
                f"{ticker_u:<8} WARN   {mapped!r}: no sector_meta_analysis row yet "
                f"digest={digest}"
            )
            missing_meta += 1
            continue

        stance = fields.get("sector_stance", "?")
        rank = fields.get("rotation_rank", "?")
        run_date = fields.get("run_date", "?")
        print(
            f"{ticker_u:<8} OK     sector={mapped!r:<30} "
            f"stance={stance:<10} rank={rank} run_date={run_date} digest={digest}"
        )
        ok += 1

        if dump:
            print()
            print("--- full bundle ---")
            print(bundle)
            print("--- end bundle ---")
            print()

    print()
    print(
        f"Summary: ok={ok} missing_sector_meta_row={missing_meta} "
        f"missing_securities_sector={missing_sector} missing_standard_analysis={missing_std}"
    )
    return 0 if (ok > 0 and missing_std == 0) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", help="Tickers to test (default: a small sample)")
    parser.add_argument("--dump", action="store_true", help="Print full bundle text per ticker")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers] if args.tickers else DEFAULT_TICKERS
    return verify_tickers(tickers, args.dump)


if __name__ == "__main__":
    sys.exit(main())
