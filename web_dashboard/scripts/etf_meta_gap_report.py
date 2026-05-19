#!/usr/bin/env python3
"""Report ETF group vs sector meta gaps for recent days."""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from dotenv import load_dotenv

load_dotenv(project_root / "web_dashboard" / ".env")

from etf_meta_pipeline import count_missing_etf_article_pairs, print_gap_table  # noqa: E402
from postgres_client import PostgresClient  # noqa: E402


def main() -> None:
    pc = PostgresClient()
    lookback = 14
    print_gap_table(pc, lookback)
    pending = count_missing_etf_article_pairs(pc, lookback)
    print(f"Estimated etf_group runs (@ 6/run): ~{(pending + 5) // 6}")


if __name__ == "__main__":
    main()
