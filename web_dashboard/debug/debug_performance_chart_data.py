#!/usr/bin/env python3
"""Diagnose dashboard performance chart data (local dev only).

Compares RLS (anon / no JWT) vs service-role row counts and optionally runs the
full chart serialization path. Does not print tokens, keys, or credentials.

Usage (from repo root, venv active):
    python web_dashboard/debug/debug_performance_chart_data.py
    python web_dashboard/debug/debug_performance_chart_data.py --fund "Project Chimera"
    python web_dashboard/debug/debug_performance_chart_data.py --fund TFSA --service-role-only

Requires web_dashboard/.env with SUPABASE_URL and either:
  - SUPABASE_SERVICE_ROLE_KEY / SUPABASE_SECRET_KEY (for --service-role-only / RLS compare)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

_DEBUG_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _DEBUG_DIR.parent
_OUTPUT_DIR = _DEBUG_DIR / "output"
_REPO_ROOT = _WEB_DASHBOARD.parent

sys.path.insert(0, str(_WEB_DASHBOARD))
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _redact_env_status() -> dict[str, bool]:
    """Report which env vars are set — never print values."""
    import os

    keys = (
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SECRET_KEY",
    )
    return {k: bool(os.getenv(k)) for k in keys}


def _row_count(
    label: str,
    client_factory: Callable[[], object],
    fund: Optional[str],
    display_currency: str,
) -> int:
    import flask_data_utils

    original = flask_data_utils.get_supabase_client_flask
    flask_data_utils.get_supabase_client_flask = client_factory  # type: ignore[assignment]
    try:
        from flask_data_utils import calculate_portfolio_value_over_time_flask

        df = calculate_portfolio_value_over_time_flask(
            fund=fund,
            days=None,
            display_currency=display_currency,
        )
        print(f"[{label}] rows={len(df)}")
        return len(df)
    finally:
        flask_data_utils.get_supabase_client_flask = original


def _chart_trace_count(df) -> int:
    from chart_utils import create_portfolio_value_chart
    from plotly_utils import serialize_plotly_figure

    fig = create_portfolio_value_chart(
        df,
        fund_name=None,
        show_normalized=True,
        show_benchmarks=["sp500"],
        show_weekend_shading=False,
        display_currency="CAD",
    )
    payload = json.loads(serialize_plotly_figure(fig))
    trace_count = len(payload.get("data") or [])
    print(f"[chart] plotly traces={trace_count}")
    return trace_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug performance chart data pipeline")
    parser.add_argument(
        "--fund",
        default="Project Chimera",
        help='Fund name, or "all" for aggregate (default: Project Chimera)',
    )
    parser.add_argument(
        "--currency",
        default="CAD",
        help="Display currency (default: CAD)",
    )
    parser.add_argument(
        "--service-role-only",
        action="store_true",
        help="Only run service-role query (skip anon RLS check)",
    )
    parser.add_argument(
        "--save-csv",
        action="store_true",
        help="Write service-role DataFrame to debug/output/ (gitignored)",
    )
    args = parser.parse_args()

    fund = None if args.fund.lower() == "all" else args.fund

    # Load .env without printing secrets
    try:
        from env_loader import load_project_dotenv

        load_project_dotenv()
    except ImportError:
        pass

    print("=" * 72)
    print("Performance chart data diagnostic")
    print("=" * 72)
    print(f"fund={fund!r} currency={args.currency}")
    print("env present:", _redact_env_status())

    from supabase_client import SupabaseClient

    anon_rows = 0
    if not args.service_role_only:
        anon_rows = _row_count(
            "anon (no JWT, simulates missing auth_token)",
            lambda: SupabaseClient(),
            fund,
            args.currency,
        )

    service_rows = _row_count(
        "service_role",
        lambda: SupabaseClient(use_service_role=True),
        fund,
        args.currency,
    )

    if not args.service_role_only and anon_rows == 0 and service_rows > 0:
        print(
            "\n[DIAGNOSIS] Data exists with service role but anon/RLS returns 0 rows.\n"
            "             Chart API likely needs a valid Supabase auth_token cookie."
        )

    if args.save_csv and service_rows > 0:
        import flask_data_utils

        original = flask_data_utils.get_supabase_client_flask
        flask_data_utils.get_supabase_client_flask = (
            lambda: SupabaseClient(use_service_role=True)
        )
        try:
            from flask_data_utils import calculate_portfolio_value_over_time_flask

            df = calculate_portfolio_value_over_time_flask(
                fund=fund,
                days=None,
                display_currency=args.currency,
            )
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_fund = (args.fund or "all").replace(" ", "_")
            out_path = _OUTPUT_DIR / f"performance_chart_{safe_fund}_{stamp}.csv"
            df.to_csv(out_path, index=False)
            print(f"[saved] {out_path.relative_to(_REPO_ROOT)}")
            if service_rows > 1:
                _chart_trace_count(df)
        finally:
            flask_data_utils.get_supabase_client_flask = original

    print("=" * 72)
    return 0 if service_rows > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
