#!/usr/bin/env python3
"""Resolve Supabase clients for dashboard queries (Flask request context)."""

from __future__ import annotations

from typing import Optional


def get_user_scoped_supabase_client(user_token: Optional[str] = None):
    """User-scoped client for RLS-backed reads/writes in the active Flask request."""
    from supabase_client import SupabaseClient

    if user_token:
        return SupabaseClient(user_token=user_token, refresh_token=None)

    try:
        from flask import has_request_context

        if has_request_context():
            from flask_data_utils import get_supabase_client_flask

            client = get_supabase_client_flask()
            if client:
                return client
    except (ImportError, RuntimeError):
        pass

    return None
