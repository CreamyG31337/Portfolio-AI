#!/usr/bin/env python3
"""Supabase clients for AI Assistant pulse/tools.

Watchlist and ``signal_analysis`` reads must succeed under RLS. The user-JWT
Flask client often falls back to anon (no cookie / expired access token), which
returns empty watchlists. Shared research tables are therefore read with the
service role after a fund ACL check (same pattern as watchlist mutations).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def user_can_access_fund(fund: str | None) -> bool:
    """True when fund is unset, outside a request, or listed for the current user."""
    fund_s = (fund or "").strip()
    if not fund_s:
        return True
    try:
        from flask import has_request_context

        if not has_request_context():
            return True
        from flask_data_utils import get_available_funds_flask

        return fund_s in (get_available_funds_flask() or [])
    except Exception as exc:
        logger.debug("fund ACL check skipped: %s", exc)
        return True


def get_assistant_research_supabase(fund: str | None = None) -> Any | None:
    """Service-role Supabase client for pulse/tools research reads.

    Returns ``None`` when the user cannot access ``fund``. Falls back to the
    Flask user-JWT client when service role cannot be constructed.
    """
    if not user_can_access_fund(fund):
        logger.warning(
            "assistant research supabase denied: no access to fund=%r", fund
        )
        return None

    try:
        from supabase_client import SupabaseClient

        return SupabaseClient(use_service_role=True)
    except Exception as exc:
        logger.warning(
            "assistant service-role client unavailable (%s); trying user JWT",
            exc,
        )
        try:
            from flask_data_utils import get_supabase_client_flask

            return get_supabase_client_flask()
        except Exception as exc2:
            logger.warning("assistant user supabase unavailable: %s", exc2)
            return None
