#!/usr/bin/env python3
"""Phase H1 source-ROI report: hit rate + excess by source and article domain.

Read-only against Research DB. Writes docs/source_roi_report_results.json and
prints tables suitable for pasting into docs/ROADMAP.md.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

web_dashboard = Path(__file__).resolve().parent.parent
repo_root = web_dashboard.parent
sys.path.insert(0, str(web_dashboard))
sys.path.insert(0, str(repo_root))

from env_loader import load_project_dotenv  # noqa: E402

load_project_dotenv()

_MIN_SCORED_WARN = 12
_OUT_JSON = repo_root / "docs" / "source_roi_report_results.json"


def _pct(rate: float | None) -> str:
    if rate is None:
        return "—"
    return f"{100.0 * rate:.1f}%"


def _fmt_excess(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}"


def _print_source_table(summary: dict[str, Any]) -> None:
    horizon = summary.get("horizon_days")
    print(f"\n=== by_source (horizon={horizon}d) ===")
    print(
        f"{'source':<28} {'scored':>6} {'hits':>5} {'hit_rate':>8} "
        f"{'mean_ex':>9} {'med_ex':>9}"
    )
    rates = summary.get("hit_rate_by_source") or {}
    counts = summary.get("counts_by_source") or {}
    avg_ex = summary.get("avg_excess_by_source") or {}
    med_ex = summary.get("median_excess_by_source") or {}
    for src in sorted(rates.keys()):
        c = counts.get(src) or {}
        scored = int(c.get("scored") or 0)
        warn = " [low-n]" if 0 < scored < _MIN_SCORED_WARN else ""
        print(
            f"{src:<28} {scored:>6} {int(c.get('hits') or 0):>5} "
            f"{_pct(rates.get(src)):>8} {_fmt_excess(avg_ex.get(src)):>9} "
            f"{_fmt_excess(med_ex.get(src)):>9}{warn}"
        )


def _print_domain_table(summary: dict[str, Any]) -> None:
    horizon = summary.get("horizon_days")
    rows = summary.get("by_domain") or []
    print(f"\n=== by_domain top (horizon={horizon}d) ===")
    if not rows:
        print("  (none — no scoreable stances with resolvable article domains)")
        return
    print(
        f"{'domain':<28} {'scored':>7} {'hits':>6} {'hit_rate':>8} "
        f"{'mean_ex':>9} {'touches':>7}"
    )
    for row in rows:
        scored = float(row.get("scored") or 0)
        warn = " [low-n]" if 0 < scored < _MIN_SCORED_WARN else ""
        print(
            f"{str(row.get('domain')):<28} {scored:>7.2f} "
            f"{float(row.get('hits') or 0):>6.2f} {_pct(row.get('hit_rate')):>8} "
            f"{_fmt_excess(row.get('mean_excess')):>9} "
            f"{int(row.get('stance_touches') or 0):>7}{warn}"
        )


def _print_coverage(summary: dict[str, Any]) -> None:
    print("\n=== evidence_coverage ===")
    cov = summary.get("evidence_coverage") or {}
    for src in sorted(cov.keys()):
        c = cov[src]
        print(
            f"  {src:<28} rows={c.get('rows')} "
            f"evidence={c.get('pct_with_evidence')}% "
            f"article_ids={c.get('pct_with_article_ids')}%"
        )
    attrib = summary.get("domain_attribution") or {}
    print(
        f"  attribution: scoreable_with_ids={attrib.get('stances_with_article_ids_scoreable')} "
        f"resolved={attrib.get('stances_with_resolved_domain')} "
        f"unresolved_lookups={attrib.get('unresolved_article_id_lookups')}"
    )


def _print_confidence(summary: dict[str, Any]) -> None:
    bands = summary.get("hit_rate_by_confidence_band") or {}
    if not bands:
        return
    print("\n=== confidence bands ===")
    counts = summary.get("counts_by_confidence_band") or {}
    for band in ("lt_0.5", "0.5_to_0.75", "gte_0.75"):
        if band not in bands and band not in counts:
            continue
        c = counts.get(band) or {}
        print(
            f"  {band:<14} hit_rate={_pct(bands.get(band))} "
            f"({c.get('hits', 0)}/{c.get('scored', 0)})"
        )


def main() -> int:
    from postgres_client import PostgresClient
    from track_record_service import build_track_record_summary

    try:
        pg = PostgresClient()
    except Exception as exc:
        print(f"[SKIP] Research DB unavailable: {exc}")
        return 1

    results: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "min_scored_warn": _MIN_SCORED_WARN,
        "horizons": {},
    }

    for horizon in (7, 30, 90):
        summary = build_track_record_summary(pg, horizon_days=horizon)
        results["horizons"][str(horizon)] = summary
        total = int(summary.get("total_scored") or 0)
        scoreable = sum(
            int((summary.get("counts_by_source") or {}).get(s, {}).get("scored") or 0)
            for s in (summary.get("counts_by_source") or {})
        )
        print(f"\n######## horizon={horizon}d total_rows={total} scoreable={scoreable} ########")
        if scoreable < _MIN_SCORED_WARN:
            print(
                f"  (sample-size warning: scoreable={scoreable} < {_MIN_SCORED_WARN}; "
                "treat rates as provisional)"
            )
        if total == 0 and horizon == 90:
            print("  (skipping empty 90d detail)")
            continue
        _print_source_table(summary)
        _print_domain_table(summary)
        _print_coverage(summary)
        _print_confidence(summary)

    _OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _OUT_JSON.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {_OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
