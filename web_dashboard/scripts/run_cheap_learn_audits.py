#!/usr/bin/env python3
"""Run the six cheap-learn SQL audits (read-only) against Research + Supabase."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(web_dashboard))
sys.path.insert(0, str(web_dashboard.parent))

from env_loader import load_project_dotenv

load_project_dotenv()


def _run_research_query(postgres, sql: str, params: tuple = ()) -> list[dict]:
    return postgres.execute_query(sql, params)


def main() -> int:
    from postgres_client import PostgresClient

    try:
        pg = PostgresClient()
    except Exception as exc:
        print(f"[SKIP] Research DB unavailable: {exc}")
        return 1

    results: dict[str, object] = {}

    # 1. Article supply audit
    results["article_supply_by_type"] = _run_research_query(
        pg,
        """
        SELECT article_type, COUNT(*) AS cnt,
               COUNT(DISTINCT source) AS domains
        FROM research_articles
        WHERE fetched_at >= NOW() - INTERVAL '30 days'
        GROUP BY article_type
        ORDER BY cnt DESC
        """,
    )
    results["etf_analysis_null_sector"] = _run_research_query(
        pg,
        """
        SELECT COUNT(*) AS null_sector_count
        FROM research_articles
        WHERE article_type = 'ETF Analysis'
          AND sector IS NULL
          AND fetched_at >= NOW() - INTERVAL '30 days'
        """,
    )

    # 2. Domain health (table may be in research or absent)
    try:
        results["domain_health"] = _run_research_query(
            pg,
            """
            SELECT domain, status, failure_count, last_success_at, last_failure_at
            FROM research_domain_health
            ORDER BY failure_count DESC NULLS LAST
            LIMIT 20
            """,
        )
    except Exception as exc:
        results["domain_health"] = {"error": str(exc)}

    # 3. Theme coverage (simplified keyword grep)
    themes = {
        "rate_cuts": ["rate cut", "fed cut", "interest rate"],
        "ai_capex": ["ai capex", "data center", "nvidia"],
        "lithium": ["lithium"],
        "geopolitics": ["geopolitic", "sanction", "tariff"],
        "retail_consumer": ["retail sales", "consumer spending"],
    }
    theme_rows = []
    for name, keywords in themes.items():
        pattern = "|".join(keywords)
        rows = _run_research_query(
            pg,
            """
            SELECT COUNT(DISTINCT id) AS articles,
                   COUNT(DISTINCT source) AS domains
            FROM research_articles
            WHERE fetched_at >= NOW() - INTERVAL '30 days'
              AND (title ~* %s OR content ~* %s)
            """,
            (pattern, pattern),
        )
        theme_rows.append({"theme": name, **(rows[0] if rows else {})})
    results["theme_coverage"] = theme_rows

    # 4. Contradiction supply
    results["contradiction_supply"] = _run_research_query(
        pg,
        """
        SELECT COUNT(*) AS rows_14d
        FROM ticker_meta_analysis
        WHERE updated_at >= NOW() - INTERVAL '14 days'
          AND confidence_adjusted < 0.5
          AND jsonb_array_length(COALESCE(contradictions, '[]'::jsonb)) >= 2
        """,
    )

    # 5. Hypothesis evaluable — benchmark_data presence (Supabase)
    try:
        from supabase_client import SupabaseClient

        sb = SupabaseClient(use_service_role=True)
        bench = (
            sb.supabase.table("benchmark_data")
            .select("ticker", count="exact")
            .eq("ticker", "^RUT")
            .limit(1)
            .execute()
        )
        results["benchmark_rut_rows"] = bench.count
    except Exception as exc:
        results["benchmark_rut_rows"] = {"error": str(exc)}

    # 6. Discovery target — watchtower holdings not in watchlist (Supabase)
    try:
        from supabase_client import SupabaseClient

        sb = SupabaseClient(use_service_role=True)
        results["watchtower_holdings_sample"] = (
            sb.supabase.table("etf_holdings_log")
            .select("ticker")
            .limit(5)
            .execute()
            .data
        )
        results["watchtower_note"] = (
            "Full cross-check requires Research etf_holdings_log vs watched_tickers_v2; "
            "run in prod with joined query."
        )
    except Exception as exc:
        results["watchtower_holdings_sample"] = {"error": str(exc)}

    out_path = web_dashboard.parent / "docs" / "cheap_learn_audit_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
