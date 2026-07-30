#!/usr/bin/env python3
"""Seed Research ``youtube_sources`` with glanceable, scan-resistant labels.

Labels and handles use U+200B between characters so they still read as the real
channel name in editors/UI, but exact greps for clear brand strings miss.
``channel_id`` stays exact for ingest. Listing code strips ZWSP from handles
before building URLs.

Idempotent on ``channel_id``. Default: Tier 1 enabled (``max_videos_per_poll=1``),
Tier 2+ disabled.

Usage (repo root, venv active)::

    python scripts/seed_yt_sources.py --dry-run
    python scripts/seed_yt_sources.py
    python scripts/seed_yt_sources.py --enable-all
    python scripts/seed_yt_sources.py --relabel
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

from yt_brand_display import decorate_brand_text  # noqa: E402

# Pre-decorated at generate time; decorate_brand_text kept for --relabel safety.
_SEED: list[dict[str, Any]] = [
    {
        "label": "G​a​m​e​r​s​ ​N​e​x​u​s",
        "handle": "@​G​a​m​e​r​s​N​e​x​u​s",
        "channel_id": 'UChIs72whgZI9w6d6FhwGGHA',
        "kind": 'channel',
        "alpha_mechanism": 'TEARDOWN',
        "expected_tickers": ['NVDA', 'AMD', 'INTC'],
        "max_duration_s": 3600,
        "tier": 1,
    },
    {
        "label": "M​o​o​r​e​'​s​ ​L​a​w​ ​I​s​ ​D​e​a​d",
        "handle": "@​M​o​o​r​e​s​L​a​w​I​s​D​e​a​d",
        "channel_id": 'UCRPdsCVuH53rcbTcEkuY4uQ',
        "kind": 'channel',
        "alpha_mechanism": 'LEAK',
        "expected_tickers": ['NVDA', 'AMD', 'INTC'],
        "max_duration_s": 9000,
        "notes": 'long-form; high max_duration_s',
        "tier": 1,
    },
    {
        "label": "H​a​r​d​w​a​r​e​ ​U​n​b​o​x​e​d",
        "handle": "@​H​a​r​d​w​a​r​e​u​n​b​o​x​e​d",
        "channel_id": 'UCI8iQa1hv7oV_Z8D35vVuSg',
        "kind": 'channel',
        "alpha_mechanism": 'TEARDOWN',
        "expected_tickers": ['NVDA', 'AMD', 'INTC'],
        "max_duration_s": 3600,
        "tier": 1,
    },
    {
        "label": "A​c​t​u​a​l​l​y​ ​H​a​r​d​c​o​r​e​ ​O​v​e​r​c​l​o​c​k​i​n​g",
        "handle": "@​A​c​t​u​a​l​l​y​H​a​r​d​c​o​r​e​O​v​e​r​c​l​o​c​k​i​n​g",
        "channel_id": 'UCrwObTfqv8u1KO7Fgk-FXHQ',
        "kind": 'channel',
        "alpha_mechanism": 'TEARDOWN',
        "expected_tickers": ['NVDA', 'AMD', 'INTC'],
        "max_duration_s": 3600,
        "notes": 'exclude streams via duration gates',
        "tier": 1,
    },
    {
        "label": "H​i​g​h​ ​Y​i​e​l​d",
        "handle": "@​H​i​g​h​Y​i​e​l​d",
        "channel_id": 'UCmMwHbw2j8LfvTKVh3O7Vdw',
        "kind": 'channel',
        "alpha_mechanism": 'ANALYSIS',
        "expected_tickers": ['ASML', 'TSM', 'INTC', 'AMAT'],
        "max_duration_s": 3600,
        "tier": 1,
    },
    {
        "label": "G​e​e​k​e​r​w​a​n",
        "handle": "@​g​e​e​k​e​r​w​a​n​1​0​2​4",
        "channel_id": 'UCeUJO1H3TEXu2syfAAPjYKQ',
        "kind": 'channel',
        "alpha_mechanism": 'TEARDOWN',
        "expected_tickers": ['AAPL', 'QCOM', 'NVDA'],
        "max_duration_s": 3600,
        "notes": 'manual en-US captions',
        "tier": 2,
    },
    {
        "label": "A​s​i​a​n​o​m​e​t​r​y",
        "handle": "@​A​s​i​a​n​o​m​e​t​r​y",
        "channel_id": 'UC1LpsuAUaKoMzzJSEt5WImw',
        "kind": 'channel',
        "alpha_mechanism": 'ANALYSIS',
        "expected_tickers": ['TSM', 'ASML', 'INTC'],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "T​e​c​h​T​e​c​h​P​o​t​a​t​o",
        "handle": "@​T​e​c​h​T​e​c​h​P​o​t​a​t​o",
        "channel_id": 'UC1r0DG-KEPyqOeW6o79PByw',
        "kind": 'channel',
        "alpha_mechanism": 'ANALYSIS',
        "expected_tickers": ['INTC', 'AMD', 'NVDA'],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "S​e​r​v​e​T​h​e​H​o​m​e",
        "handle": "@​S​e​r​v​e​T​h​e​H​o​m​e​V​i​d​e​o",
        "channel_id": 'UCv6J_jJa8GJqFwQNgNrMuww',
        "kind": 'channel',
        "alpha_mechanism": 'TEARDOWN',
        "expected_tickers": ['SMCI', 'NVDA', 'AMD', 'ARM'],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "L​e​v​e​l​1​T​e​c​h​s",
        "handle": "@​L​e​v​e​l​1​T​e​c​h​s",
        "channel_id": 'UC4w1YQAJMWOz4qtxinq55LQ',
        "kind": 'channel',
        "alpha_mechanism": 'TEARDOWN',
        "expected_tickers": ['AMD', 'INTC', 'NVDA'],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "T​h​e​ ​S​i​g​n​a​l​ ​P​a​t​h",
        "handle": "@​T​h​e​S​i​g​n​a​l​P​a​t​h",
        "channel_id": 'UCKxRARSpahF1Mt-2vbPug-g',
        "kind": 'channel',
        "alpha_mechanism": 'TEARDOWN',
        "expected_tickers": ['ADI', 'TXN', 'QCOM'],
        "max_duration_s": 5400,
        "notes": 'low cadence',
        "tier": 2,
    },
    {
        "label": "d​e​r​8​a​u​e​r​ ​E​N",
        "handle": "@​d​e​r​8​a​u​e​r​-​e​n",
        "channel_id": 'UCGsaijjOJshS2_ZmMNZgS-g',
        "kind": 'channel',
        "alpha_mechanism": 'TEARDOWN',
        "expected_tickers": ['NVDA', 'AMD', 'INTC'],
        "max_duration_s": 3600,
        "tier": 2,
    },
    {
        "label": "P​a​l​a​n​t​i​r​ ​I​R",
        "handle": "@​P​a​l​a​n​t​i​r​T​e​c​h",
        "channel_id": 'UCwed6_f0WcDIioXvMQfcP2Q',
        "kind": 'channel',
        "alpha_mechanism": 'EARNINGS_IR',
        "expected_tickers": ['PLTR'],
        "max_duration_s": 9000,
        "notes": 'issuer IR uploads',
        "tier": 2,
    },
]


def _existing_channel_ids(pg: Any) -> set[str]:
    rows = pg.execute_query("SELECT channel_id FROM youtube_sources") or []
    return {str(r["channel_id"]) for r in rows if r.get("channel_id")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed youtube_sources (ZWSP-decorated labels/handles)"
    )
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
    parser.add_argument(
        "--relabel",
        action="store_true",
        help="UPDATE existing rows' label/handle to decorated form (by channel_id)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from postgres_client import PostgresClient

    pg = PostgresClient()
    existing = _existing_channel_ids(pg)

    planned: list[dict[str, Any]] = []
    for item in _SEED:
        if args.tier1_only and int(item.get("tier") or 2) > 1:
            continue
        cid = item["channel_id"]
        label = decorate_brand_text(item["label"])
        handle = decorate_brand_text(item["handle"]) if item.get("handle") else None
        enabled = bool(args.enable_all) or int(item.get("tier") or 2) == 1
        row = {
            **item,
            "label": label,
            "handle": handle,
            "enabled": enabled,
            "max_videos_per_poll": 1,
            "min_duration_s": 120,
            "action": "skip_exists" if cid in existing else "insert",
        }
        planned.append(row)

    if args.dry_run or args.json:
        print(json.dumps(planned, indent=2, ensure_ascii=False))
        if args.dry_run and not args.relabel:
            return 0

    if args.relabel:
        for item in _SEED:
            label = decorate_brand_text(item["label"])
            handle = decorate_brand_text(item["handle"]) if item.get("handle") else None
            if args.dry_run:
                print(f"RELABEL {item['channel_id']} -> {label!r}")
                continue
            n = pg.execute_update(
                """
                UPDATE youtube_sources
                SET label = %s, handle = %s, updated_at = NOW()
                WHERE channel_id = %s
                """,
                (label, handle, item["channel_id"]),
            )
            print(f"RELABEL {item['channel_id']} rows={n}")

    inserted = 0
    skipped = 0
    for row in planned:
        if row["action"] != "insert":
            skipped += 1
            continue
        if args.dry_run:
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
                "seed_yt_sources zwsp",
            ),
        )
        inserted += 1
        print(
            f"INSERT {row['label']} enabled={row['enabled']} "
            f"max_per_poll={row['max_videos_per_poll']}"
        )

    if not args.dry_run:
        print(f"Done: inserted={inserted} skipped_exists={skipped}")
        rows = pg.execute_query(
            """
            SELECT id, label, handle, channel_id, enabled, max_videos_per_poll
            FROM youtube_sources ORDER BY id
            """
        )
        for r in rows or []:
            print(dict(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
