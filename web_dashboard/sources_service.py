"""Helpers for /admin/sources — bulk import classification and field validation.

Pure functions where possible so unit tests need no network / DB.
See docs/PHASE_K_SOURCES_UI_PLAN.md.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Iterable, Optional

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
HANDLE_RE = re.compile(r"^@?[A-Za-z0-9._-]{2,120}$")
VALID_KINDS = frozenset({"channel", "search", "playlist", "ir"})
VALID_MECHANISMS = frozenset(
    {"MARKET_MOVER", "LEAK", "TEARDOWN", "ANALYSIS", "EARNINGS_IR", ""}
)
MAX_BULK_ROWS = 100

# Research deliverable / preview field aliases → canonical keys
_FIELD_ALIASES = {
    "label": "label",
    "name": "label",
    "channel": "label",
    "handle": "handle",
    "channel_handle": "handle",
    "kind": "kind",
    "type": "kind",
    "channel_id": "channel_id",
    "query": "query_text",
    "query_text": "query_text",
    "search": "query_text",
    "alpha_mechanism": "alpha_mechanism",
    "mechanism": "alpha_mechanism",
    "alpha mechanism": "alpha_mechanism",
    "expected_tickers": "expected_tickers",
    "tickers": "expected_tickers",
    "confidence_weight": "confidence_weight",
    "weight": "confidence_weight",
    "notes": "notes",
    "source_of_recommendation": "source_of_recommendation",
    "recommendation": "source_of_recommendation",
}


def normalize_ticker(raw: str) -> Optional[str]:
    token = (raw or "").strip().upper()
    if not token:
        return None
    if not TICKER_RE.match(token):
        return None
    return token


def normalize_tickers(value: Any) -> tuple[list[str], list[str]]:
    """Return (valid_tickers, errors)."""
    errors: list[str] = []
    if value is None or value == "":
        return [], errors
    if isinstance(value, str):
        parts = re.split(r"[,;\s]+", value.strip())
    elif isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        return [], [f"expected_tickers must be list or string, got {type(value).__name__}"]

    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part or not str(part).strip():
            continue
        ticker = normalize_ticker(str(part))
        if ticker is None:
            errors.append(f"invalid ticker: {part!r}")
            continue
        if ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out, errors


def normalize_handle(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if not HANDLE_RE.match(text):
        return None
    if not text.startswith("@"):
        text = "@" + text
    return text


def normalize_kind(raw: Any) -> str:
    kind = str(raw or "channel").strip().lower()
    if kind in {"earnings_search", "earnings-search"}:
        return "search"
    if kind in VALID_KINDS:
        return kind
    return "channel"


def normalize_mechanism(raw: Any) -> Optional[str]:
    if raw is None or raw == "":
        return None
    mech = str(raw).strip().upper().replace(" ", "_").replace("-", "_")
    if mech in VALID_MECHANISMS and mech:
        return mech
    return None


def _canonicalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in raw.items():
        canon = _FIELD_ALIASES.get(str(key).strip().lower())
        if canon is None:
            continue  # unknown keys ignored
        out[canon] = value
    return out


def parse_bulk_payload(format_name: str, payload: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse pasted JSON or CSV into row dicts. Returns (rows, top_level_errors)."""
    errors: list[str] = []
    text = (payload or "").strip()
    if not text:
        return [], ["empty payload"]

    fmt = (format_name or "json").strip().lower()
    rows: list[dict[str, Any]] = []

    if fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return [], [f"invalid JSON: {exc}"]
        if isinstance(data, dict) and "rows" in data:
            data = data["rows"]
        if not isinstance(data, list):
            return [], ["JSON must be an array of objects (or {rows: [...]})"]
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                errors.append(f"row {i}: expected object")
                continue
            rows.append(_canonicalize_row(item))
    elif fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return [], ["CSV missing header row"]
        for i, item in enumerate(reader):
            rows.append(_canonicalize_row({k: v for k, v in item.items() if k is not None}))
    else:
        return [], [f"unsupported format: {format_name!r} (use json or csv)"]

    if len(rows) > MAX_BULK_ROWS:
        return [], [f"too many rows ({len(rows)}); max is {MAX_BULK_ROWS}"]

    return rows, errors


def classify_bulk_rows(
    rows: Iterable[dict[str, Any]],
    *,
    existing_channel_ids: set[str],
    existing_handles: set[str],
    existing_queries: set[str],
) -> dict[str, Any]:
    """Classify preview rows as new | duplicate | invalid."""
    classified: list[dict[str, Any]] = []
    summary = {"new": 0, "duplicate": 0, "invalid": 0}

    for raw in rows:
        row = dict(raw)
        errors: list[str] = []
        warnings: list[str] = []

        label = str(row.get("label") or "").strip()
        kind = normalize_kind(row.get("kind"))
        handle = normalize_handle(row.get("handle"))
        channel_id = (str(row.get("channel_id") or "").strip() or None)
        query_text = (str(row.get("query_text") or "").strip() or None)
        mechanism = normalize_mechanism(row.get("alpha_mechanism"))
        if row.get("alpha_mechanism") not in (None, "") and mechanism is None:
            errors.append(f"invalid alpha_mechanism: {row.get('alpha_mechanism')!r}")

        tickers, ticker_errors = normalize_tickers(row.get("expected_tickers"))
        errors.extend(ticker_errors)

        weight_raw = row.get("confidence_weight", 1.0)
        try:
            weight = float(weight_raw) if weight_raw is not None and weight_raw != "" else 1.0
        except (TypeError, ValueError):
            weight = 1.0
            errors.append(f"invalid confidence_weight: {weight_raw!r}")
        if weight < 0.0 or weight > 2.0:
            errors.append("confidence_weight must be between 0.00 and 2.00")

        if not label:
            errors.append("label is required")

        if kind == "search":
            if not query_text:
                errors.append("query_text is required for kind=search")
        else:
            if not channel_id and not handle:
                errors.append("channel_id or handle is required for non-search kinds")
            if not channel_id and handle:
                warnings.append("channel_id not resolved — will resolve on commit")

        status = "new"
        if errors:
            status = "invalid"
        else:
            if channel_id and channel_id in existing_channel_ids:
                status = "duplicate"
            elif handle and handle.lower() in {h.lower() for h in existing_handles}:
                status = "duplicate"
            elif query_text and query_text in existing_queries:
                status = "duplicate"

        summary[status] = summary.get(status, 0) + 1
        classified.append(
            {
                "label": label,
                "handle": handle,
                "kind": kind,
                "channel_id": channel_id,
                "query_text": query_text,
                "alpha_mechanism": mechanism,
                "expected_tickers": tickers,
                "confidence_weight": weight,
                "notes": (str(row.get("notes") or "").strip() or None),
                "source_of_recommendation": (
                    str(row.get("source_of_recommendation") or "").strip() or None
                ),
                "status": status,
                "warnings": warnings,
                "errors": errors,
            }
        )

    return {"rows": classified, "summary": summary}


def serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Make a DB row JSON-safe."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out
