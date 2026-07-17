"""
Trade-level quarantine for bad congressional disclosures.

KNOWN_BAD_TRADES is the cold-start source of truth: after every ingest upsert,
apply_trade_quality_overrides() matches fingerprints (by bioguide, not politician
id) and marks garbage + ensures a corrected sibling for analysis.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Mapping, Optional, Sequence, TypedDict

from .congress_trade_normalize import (
    CONGRESS_TRADE_UPSERT_ON_CONFLICT,
    normalize_amount,
    normalize_owner,
    normalize_ticker,
    normalize_trade_type,
)

logger = logging.getLogger(__name__)

QUALITY_OK = "ok"
QUALITY_GARBAGE = "garbage"
QUALITY_CORRECTED = "corrected"

ANALYSIS_ELIGIBLE_STATUSES = frozenset({QUALITY_OK, QUALITY_CORRECTED})


class KnownBadTrade(TypedDict, total=False):
    politician_bioguide: str
    ticker: str
    transaction_date: str
    type: str
    amount: str
    owner: str
    suggested_ticker: str
    reason: str


# Match disclosed filing text. Prefer bioguide over politician_id (ids differ across envs).
KNOWN_BAD_TRADES: list[KnownBadTrade] = [
    {
        "politician_bioguide": "C001120",  # Dan Crenshaw
        "ticker": "USOU",
        "transaction_date": "2026-06-01",
        "type": "Purchase",
        "amount": "$1,001 - $15,000",
        "owner": "Not-Disclosed",
        "suggested_ticker": "USO",
        "reason": (
            "PTR #20035024 lists liquidated USOU; likely USO (eFD manual entry). "
            "See disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035024.pdf"
        ),
    },
]


def is_analysis_eligible(quality_status: Any) -> bool:
    """Return True when a trade may be used in conflict/returns/herd/UI defaults."""
    status = (str(quality_status).strip().lower() if quality_status is not None else QUALITY_OK)
    if not status:
        status = QUALITY_OK
    return status in ANALYSIS_ELIGIBLE_STATUSES


def exclude_garbage_from_query(query: Any) -> Any:
    """PostgREST filter: drop quality_status=garbage (NULL treated as ok by neq)."""
    return query.neq("quality_status", QUALITY_GARBAGE)


def _as_date_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return text


def fingerprint_matches_row(rule: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    """Match a disclosed trade row against a registry rule (normalized fields)."""
    if normalize_ticker(row.get("ticker")) != normalize_ticker(rule.get("ticker")):
        return False
    if _as_date_str(row.get("transaction_date")) != _as_date_str(rule.get("transaction_date")):
        return False
    if normalize_trade_type(row.get("type")) != normalize_trade_type(rule.get("type")):
        return False
    if "amount" in rule and rule["amount"]:
        if normalize_amount(row.get("amount")) != normalize_amount(rule["amount"]):
            return False
    if "owner" in rule and rule["owner"]:
        if normalize_owner(row.get("owner")) != normalize_owner(rule["owner"]):
            return False
    return True


def find_matching_rules(
    row: Mapping[str, Any],
    *,
    bioguide: str | None = None,
    rules: Sequence[Mapping[str, Any]] | None = None,
) -> list[KnownBadTrade]:
    """Return registry rules that match this disclosed trade (+ optional bioguide)."""
    active = list(rules) if rules is not None else list(KNOWN_BAD_TRADES)
    matches: list[KnownBadTrade] = []
    for rule in active:
        rule_bio = str(rule.get("politician_bioguide") or "").strip().upper()
        if bioguide is not None and rule_bio and rule_bio != str(bioguide).strip().upper():
            continue
        if fingerprint_matches_row(rule, row):
            matches.append(dict(rule))  # type: ignore[arg-type]
    return matches


def _resolve_bioguide_map(client: Any, bioguides: Sequence[str]) -> dict[str, int]:
    """Map bioguide_id -> politicians.id for this database."""
    unique = sorted({b.strip().upper() for b in bioguides if b and str(b).strip()})
    if not unique:
        return {}
    resp = (
        client.supabase.table("politicians")
        .select("id, bioguide_id")
        .in_("bioguide_id", unique)
        .execute()
    )
    out: dict[str, int] = {}
    for row in resp.data or []:
        bio = str(row.get("bioguide_id") or "").strip().upper()
        pid = row.get("id")
        if bio and pid is not None:
            out[bio] = int(pid)
    return out


def _fetch_candidate_trades(
    client: Any,
    politician_id: int,
    rule: Mapping[str, Any],
    *,
    trade_ids: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    ticker = normalize_ticker(rule.get("ticker"))
    tx_date = _as_date_str(rule.get("transaction_date"))
    tx_type = normalize_trade_type(rule.get("type"))
    query = (
        client.supabase.table("congress_trades")
        .select(
            "id, politician_id, ticker, chamber, transaction_date, disclosure_date, type, amount, "
            "asset_type, price, party, state, owner, notes, quality_status, "
            "quality_reason, suggested_ticker, replacement_trade_id"
        )
        .eq("politician_id", politician_id)
        .eq("ticker", ticker)
        .eq("transaction_date", tx_date)
        .eq("type", tx_type)
    )
    if trade_ids:
        query = query.in_("id", list(trade_ids))
    resp = query.execute()
    rows = list(resp.data or [])
    return [r for r in rows if fingerprint_matches_row(rule, r)]


def _ensure_corrected_sibling(
    client: Any,
    garbage_row: Mapping[str, Any],
    rule: Mapping[str, Any],
) -> Optional[int]:
    """Upsert corrected sibling under suggested_ticker; return its id."""
    suggested = normalize_ticker(rule.get("suggested_ticker"))
    if not suggested:
        logger.warning("Registry rule missing suggested_ticker for %s", rule)
        return None

    politician_id = int(garbage_row["politician_id"])
    amount = normalize_amount(garbage_row.get("amount"))
    owner = normalize_owner(garbage_row.get("owner"))
    tx_type = normalize_trade_type(garbage_row.get("type"))
    tx_date = _as_date_str(garbage_row.get("transaction_date"))
    disclosure = _as_date_str(garbage_row.get("disclosure_date")) or tx_date

    sibling: dict[str, Any] = {
        "politician_id": politician_id,
        "ticker": suggested,
        "chamber": garbage_row.get("chamber") or "House",
        "transaction_date": tx_date,
        "disclosure_date": disclosure,
        "type": tx_type,
        "amount": amount or None,
        "asset_type": garbage_row.get("asset_type"),
        "price": garbage_row.get("price"),
        "party": garbage_row.get("party"),
        "state": garbage_row.get("state"),
        "owner": owner,
        "notes": (
            f"Corrected from disclosed ticker {normalize_ticker(garbage_row.get('ticker'))}. "
            f"{rule.get('reason') or ''}"
        ).strip(),
        "quality_status": QUALITY_CORRECTED,
        "quality_reason": rule.get("reason"),
        "suggested_ticker": suggested,
    }

    client.supabase.table("congress_trades").upsert(
        sibling,
        on_conflict=CONGRESS_TRADE_UPSERT_ON_CONFLICT,
    ).execute()

    # Upsert may not return id; look up by unique key
    lookup = (
        client.supabase.table("congress_trades")
        .select("id, quality_status")
        .eq("politician_id", politician_id)
        .eq("ticker", suggested)
        .eq("transaction_date", tx_date)
        .eq("amount", amount)
        .eq("type", tx_type)
        .eq("owner", owner)
        .limit(1)
        .execute()
    )
    rows = lookup.data or []
    if not rows:
        logger.error("Corrected sibling upsert succeeded but lookup failed for %s", suggested)
        return None

    sibling_id = int(rows[0]["id"])
    # Ensure quality flags if row already existed as ok from a prior ingest
    if rows[0].get("quality_status") != QUALITY_CORRECTED:
        client.supabase.table("congress_trades").update(
            {
                "quality_status": QUALITY_CORRECTED,
                "quality_reason": rule.get("reason"),
                "suggested_ticker": suggested,
                "notes": sibling["notes"],
            }
        ).eq("id", sibling_id).execute()
    return sibling_id


def apply_trade_quality_overrides(
    client: Any,
    trade_ids: Sequence[int] | None = None,
    *,
    rules: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    """Mark fingerprinted bad disclosures as garbage and ensure corrected siblings.

    Idempotent: safe after every scrape / FMP batch / on deploy.
    """
    active_rules: Sequence[Mapping[str, Any]] = (
        list(rules) if rules is not None else list(KNOWN_BAD_TRADES)
    )
    stats = {
        "rules": len(active_rules),
        "matched": 0,
        "marked_garbage": 0,
        "siblings_ensured": 0,
        "linked": 0,
        "skipped": 0,
        "errors": 0,
    }
    if not active_rules:
        return stats

    bioguides = [str(r.get("politician_bioguide") or "") for r in active_rules]
    bio_to_pid = _resolve_bioguide_map(client, bioguides)

    for rule in active_rules:
        bio = str(rule.get("politician_bioguide") or "").strip().upper()
        politician_id = bio_to_pid.get(bio)
        if politician_id is None:
            logger.warning(
                "KNOWN_BAD_TRADES: no politician for bioguide %s — skip rule %s %s",
                bio,
                rule.get("ticker"),
                rule.get("transaction_date"),
            )
            stats["skipped"] += 1
            continue

        try:
            candidates = _fetch_candidate_trades(
                client, politician_id, rule, trade_ids=trade_ids
            )
        except Exception as exc:
            logger.error("Failed fetching candidates for rule %s: %s", rule, exc)
            stats["errors"] += 1
            continue

        for row in candidates:
            stats["matched"] += 1
            trade_id = int(row["id"])
            try:
                needs_mark = row.get("quality_status") != QUALITY_GARBAGE
                if needs_mark:
                    client.supabase.table("congress_trades").update(
                        {
                            "quality_status": QUALITY_GARBAGE,
                            "quality_reason": rule.get("reason"),
                            "suggested_ticker": normalize_ticker(rule.get("suggested_ticker"))
                            or None,
                        }
                    ).eq("id", trade_id).execute()
                    stats["marked_garbage"] += 1

                sibling_id = _ensure_corrected_sibling(client, row, rule)
                if sibling_id is None:
                    stats["errors"] += 1
                    continue
                stats["siblings_ensured"] += 1

                if row.get("replacement_trade_id") != sibling_id:
                    # Trigger allows first-time replacement_trade_id fill on garbage rows
                    client.supabase.table("congress_trades").update(
                        {"replacement_trade_id": sibling_id}
                    ).eq("id", trade_id).execute()
                    stats["linked"] += 1
            except Exception as exc:
                logger.error("Failed applying quality override for trade %s: %s", trade_id, exc)
                stats["errors"] += 1

    logger.info("apply_trade_quality_overrides: %s", stats)
    return stats
