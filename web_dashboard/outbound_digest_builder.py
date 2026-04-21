"""Build portfolio digest payload using service-role Supabase (no Flask JWT)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from action_queue_service import build_action_queue_items
from portfolio_summary_math import compute_core_summary_metrics, fetch_latest_rates_bulk_with_client
from supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

PORTFOLIO_DIGEST_SLUG = "portfolio_digest"
STABLE_PORTFOLIO_TYPE_ID = "d1111111-1111-4111-8111-111111111111"


def _public_base_url() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or os.getenv("FLASK_PUBLIC_URL") or "").rstrip("/")


def get_user_fund_names_service(client: SupabaseClient, user_id: str) -> List[str]:
    res = client.supabase.rpc("get_user_funds", {"user_uuid": user_id}).execute()
    if not res.data:
        return []
    out: List[str] = []
    for row in res.data:
        fn = row.get("fund_name") if isinstance(row, dict) else None
        if fn:
            out.append(str(fn))
    return out


def get_display_currency_service(client: SupabaseClient, user_id: str) -> str:
    try:
        res = client.supabase.rpc(
            "get_user_preference", {"pref_key": "display_currency", "user_uuid": user_id}
        ).execute()
        val = res.data
        if isinstance(val, str) and val:
            return val.upper()
        if val and isinstance(val, dict) and val.get("currency"):
            return str(val["currency"]).upper()
    except Exception as e:
        logger.debug("get_display_currency_service: %s", e)
    return "CAD"


def fetch_latest_positions_dataframe(client: SupabaseClient, fund_names: List[str]) -> pd.DataFrame:
    if not fund_names:
        return pd.DataFrame()
    all_rows: List[Dict[str, Any]] = []
    batch_size = 1000
    offset = 0
    while True:
        q = client.supabase.table("latest_positions").select("*").in_("fund", fund_names)
        result = q.range(offset, offset + batch_size - 1).execute()
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < batch_size:
            break
        offset += batch_size
        if offset > 50000:
            break
    if not all_rows:
        return pd.DataFrame()
    return pd.DataFrame(all_rows)


def fetch_cash_balances_for_funds(client: SupabaseClient, fund_names: List[str]) -> Dict[str, float]:
    if not fund_names:
        return {"CAD": 0.0, "USD": 0.0}
    balances: Dict[str, float] = {"CAD": 0.0, "USD": 0.0}
    offset = 0
    batch_size = 1000
    while True:
        q = client.supabase.table("cash_balances").select("*").in_("fund", fund_names)
        result = q.range(offset, offset + batch_size - 1).execute()
        if not result.data:
            break
        for row in result.data:
            currency = row.get("currency", "CAD")
            amount = float(row.get("balance", 0) or 0)
            balances[currency] = balances.get(currency, 0.0) + amount
        if len(result.data) < batch_size:
            break
        offset += batch_size
        if offset > 50000:
            break
    return balances


def _top_movers_from_positions(positions_df: pd.DataFrame, limit: int = 5) -> Tuple[List[Dict], List[Dict]]:
    if positions_df.empty or "five_day_pnl_pct" not in positions_df.columns:
        return [], []
    df = positions_df[pd.notna(positions_df["five_day_pnl_pct"])].copy()
    if df.empty:
        return [], []
    gainers = df.nlargest(limit, "five_day_pnl_pct")
    losers = df.nsmallest(limit, "five_day_pnl_pct")
    def row_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "ticker": str(row.get("ticker", "")),
            "company_name": row.get("company") or row.get("company_name"),
            "five_day_pnl_pct": float(row["five_day_pnl_pct"]) if pd.notna(row["five_day_pnl_pct"]) else None,
        }
    # Optimization: to_dict('records') is 10-100x faster than iterrows()
    return [row_to_dict(r) for r in gainers.to_dict('records')], [row_to_dict(r) for r in losers.to_dict('records')]


def fetch_market_brief_dict() -> Optional[Dict[str, Any]]:
    try:
        from market_brief_service import fetch_latest_brief
        from postgres_client import PostgresClient

        pg = PostgresClient()
        row = fetch_latest_brief(pg)
        if not row:
            return None
        out: Dict[str, Any] = {}
        for k, v in dict(row).items():
            if v is None:
                out[k] = None
            elif hasattr(v, "isoformat"):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out
    except Exception as e:
        logger.warning("fetch_market_brief_dict: %s", e)
        return None


def build_digest_payload(
    user_id: str,
    *,
    issue_id: Optional[str] = None,
    preview: bool = False,
) -> Dict[str, Any]:
    """Assemble digest sections for template rendering."""
    client = SupabaseClient(use_service_role=True)
    fund_names = get_user_fund_names_service(client, user_id)
    positions_df = fetch_latest_positions_dataframe(client, fund_names)
    cash = fetch_cash_balances_for_funds(client, fund_names)
    display_currency = get_display_currency_service(client, user_id)

    all_currencies: set[str] = set()
    if not positions_df.empty:
        all_currencies.update(
            positions_df["currency"].fillna("CAD").astype(str).str.upper().unique().tolist()
        )
    all_currencies.update(str(c).upper() for c in cash.keys())
    rate_map = fetch_latest_rates_bulk_with_client(client, list(all_currencies), display_currency)

    summary = compute_core_summary_metrics(positions_df, cash, rate_map, display_currency)
    gainers, losers = _top_movers_from_positions(positions_df, 5)
    market_brief = fetch_market_brief_dict()

    actions: List[Dict[str, Any]] = []
    try:
        actions = build_action_queue_items(client, None, 5, positions_df=positions_df)
    except Exception as e:
        logger.warning("build_digest_payload action queue: %s", e)

    now = datetime.now(timezone.utc)
    return {
        "user_id": user_id,
        "issue_id": issue_id,
        "preview": preview,
        "as_of": now.strftime("%Y-%m-%d %H:%M UTC"),
        "as_of_iso": now.isoformat(),
        "fund_names": fund_names,
        "summary": summary,
        "gainers": gainers,
        "losers": losers,
        "market_brief": market_brief,
        "action_queue": actions[:8],
        "week_label": "Approx. 5 trading days (holdings five_day_* columns)",
        "public_base_url": _public_base_url(),
    }


def resolve_newsletter_type_id(client: SupabaseClient) -> str:
    """Prefer DB row by slug; fall back to stable seed UUID."""
    try:
        r = (
            client.supabase.table("outbound_newsletter_types")
            .select("id")
            .eq("slug", PORTFOLIO_DIGEST_SLUG)
            .limit(1)
            .execute()
        )
        if r.data and r.data[0].get("id"):
            return str(r.data[0]["id"])
    except Exception as e:
        logger.warning("resolve_newsletter_type_id: %s", e)
    return STABLE_PORTFOLIO_TYPE_ID
