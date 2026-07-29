#!/usr/bin/env python3
"""Apply committed KNOWN_BAD_TRADES quarantine rules to congress_trades.

Usage:
    python web_dashboard/scripts/apply_congress_trade_quality.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from dotenv import load_dotenv

env_path = project_root / "web_dashboard" / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from supabase_client import SupabaseClient
from utils.congress_trade_quality import apply_trade_quality_overrides


def main() -> int:
    client = SupabaseClient(use_service_role=True)
    stats = apply_trade_quality_overrides(client)
    print(json.dumps(stats, indent=2))
    return 0 if stats.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
