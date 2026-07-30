#!/usr/bin/env python3
"""Seed Research ``youtube_sources`` from docs/PHASE_K_SOURCE_LIST.md §6.

Idempotent on ``channel_id`` / ``handle`` / ``query_text``. Default: Tier 1
(enabled, ``max_videos_per_poll=1``), Tier 2+ disabled so the experiment can
start as a trickle.

Usage (repo root, venv active)::

    python scripts/seed_youtube_sources.py --dry-run
    python scripts/seed_youtube_sources.py
    python scripts/seed_youtube_sources.py --enable-all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_WEB = _REPO / "web_dashboard"
for path in (_REPO, _WEB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Mirrors docs/PHASE_K_SOURCE_LIST.md §5 tiers + §6 payload.
_SEED: list[dict[str, Any]] = [
    {
        "label": "Gamers Nexus",
        "handle": "@GamersNexus",
        "channel_id": "UChIs72whgZI9w6d6FhwGGHA",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["NVDA", "AMD", "INTC"],
        "max_duration_s": 3600,
        "tier": 1,
    },
    {
        "label": "Moore's Law Is Dead",
        "handle": "@MooresLawIsDead",
        "channel_id": "UCRPdsCVuH53rcbTcEkuY4uQ",
        "kind": "channel",
        "alpha_mechanism": "LEAK",
        "expected_tickers": ["NVDA", "AMD", "INTC"],
        "max_duration_s": 9000,
        "notes": "median 94min; long-form podcast format",
        "tier": 1,
    },
    {
        "label": "Hardware Unboxed",
        "handle": "@Hardwareunboxed",
        "channel_id": "UCI8iQa1hv7oV_Z8D35vVuSg",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["NVDA", "AMD", "INTC"],
        "max_duration_s": 3600,
        "tier": 1,
    },
    {
        "label": "Actually Hardcore Overclocking",
        "handle": "@ActuallyHardcoreOverclocking",
        "channel_id": "UCrwObTfqv8u1KO7Fgk-FXHQ",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["NVDA", "AMD", "INTC"],
        "max_duration_s": 3600,
        "notes": "streams median 191min - keep streams disabled",
        "tier": 1,
    },
    {
        "label": "High Yield",
        "handle": "@HighYield",
        "channel_id": "UCmMwHbw2j8LfvTKVh3O7Vdw",
        "kind": "channel",
        "alpha_mechanism": "ANALYSIS",
        "expected_tickers": ["ASML", "TSM", "INTC", "AMAT"],
        "max_duration_s": 3600,
        "tier": 1,
    },
    {
        "label": "Geekerwan",
        "handle": "@geekerwan1024",
        "channel_id": "UCeUJO1H3TEXu2syfAAPjYKQ",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["AAPL", "QCOM", "NVDA"],
        "max_duration_s": 3600,
        "notes": "manual en-US only, NO auto-en",
        "tier": 2,
    },
    {
        "label": "Asianometry",
        "handle": "@Asianometry",
        "channel_id": "UC1LpsuAUaKoMzzJSEt5WImw",
        "kind": "channel",
        "alpha_mechanism": "ANALYSIS",
        "expected_tickers": ["TSM", "ASML", "INTC"],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "TechTechPotato",
        "handle": "@TechTechPotato",
        "channel_id": "UC1r0DG-KEPyqOeW6o79PByw",
        "kind": "channel",
        "alpha_mechanism": "ANALYSIS",
        "expected_tickers": ["INTC", "AMD", "NVDA"],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "ServeTheHome",
        "handle": "@ServeTheHomeVideo",
        "channel_id": "UCv6J_jJa8GJqFwQNgNrMuww",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["SMCI", "NVDA", "AMD", "ARM"],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "Level1Techs",
        "handle": "@Level1Techs",
        "channel_id": "UC4w1YQAJMWOz4qtxinq55LQ",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["AMD", "INTC", "NVDA"],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "The Signal Path",
        "handle": "@TheSignalPath",
        "channel_id": "UCKxRARSpahF1Mt-2vbPug-g",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["ADI", "TXN", "QCOM"],
        "max_duration_s": 5400,
        "notes": "low cadence, high per-item value",
        "tier": 2,
    },
    {
        "label": "der8auer EN",
        "handle": "@der8auer-en",
        "channel_id": "UCGsaijjOJshS2_ZmMNZgS-g",
        "kind": "channel",
        "alpha_mechanism": "TEARDOWN",
        "expected_tickers": ["NVDA", "AMD", "INTC"],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "Palantir IR",
        "handle": "@PalantirTech",
        "channel_id": "UCwed6_f0WcDIioXvMQfcP2Q",
        "kind": "channel",
        "alpha_mechanism": "EARNINGS_IR",
        "expected_tickers": ["PLTR"],
        "max_duration_s": 9000,
        "notes": "only major issuer posting full earnings calls to YouTube",
        "tier": 2,
    },
]


def _existing_keys(pg: Any) -> tuple[set[str], set[str]]:
    rows = pg.execute_query(
        "SELECT channel_id, handle FROM youtube_sources"
    ) or []
    channels = {str(r["channel_id"]) for r in rows if r.get("channel_id")}
    handles = {str(r["handle"]) for r in rows if r.get("handle")}
    return channels, handles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed youtube_sources from PHASE_K_SOURCE_LIST")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--enable-all",
        action="store_true",
        help="Enable Tier 2+ as well (still max_videos_per_poll=1)",
    )
    parser.add_argument(
        "--tier1-only",
        action="store_true",
        help="Insert only Tier 1 rows (default inserts all; Tier 2 disabled)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from postgres_client import PostgresClient

    pg = PostgresClient()
    channels, handles = _existing_keys(pg)

    planned: list[dict[str, Any]] = []
    for item in _SEED:
        if args.tier1_only and int(item.get("tier") or 2) > 1:
            continue
        cid = item["channel_id"]
        handle = item["handle"]
        if cid in channels or handle in handles:
            planned.append({**item, "action": "skip_exists"})
            continue
        enabled = bool(args.enable_all) or int(item.get("tier") or 2) == 1
        planned.append(
            {
                **item,
                "action": "insert",
                "enabled": enabled,
                "max_videos_per_poll": 1,
                "min_duration_s": 120,
            }
        )

    if args.dry_run or args.json:
        print(json.dumps(planned, indent=2, ensure_ascii=False))
        if args.dry_run:
            return 0

    inserted = 0
    skipped = 0
    for row in planned:
        if row["action"] != "insert":
            skipped += 1
            continue
        pg.execute_update(
            """
            INSERT INTO youtube_sources (
                kind, channel_id, handle, label, alpha_mechanism,
                expected_tickers, enabled, max_videos_per_poll,
                min_duration_s, max_duration_s, notes,
                source_of_recommendation, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, NOW()
            )
            """,
            (
                row["kind"],
                row["channel_id"],
                row["handle"],
                row["label"],
                row.get("alpha_mechanism"),
                row.get("expected_tickers") or [],
                bool(row["enabled"]),
                int(row["max_videos_per_poll"]),
                int(row["min_duration_s"]),
                row.get("max_duration_s"),
                row.get("notes"),
                "PHASE_K_SOURCE_LIST.md",
            ),
        )
        inserted += 1
        print(
            f"INSERT id-pending {row['label']} enabled={row['enabled']} "
            f"max_per_poll={row['max_videos_per_poll']}"
        )

    print(f"Done: inserted={inserted} skipped_exists={skipped}")
    rows = pg.execute_query(
        """
        SELECT id, label, handle, enabled, max_videos_per_poll, max_duration_s
        FROM youtube_sources ORDER BY id
        """
    )
    for r in rows or []:
        print(dict(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
