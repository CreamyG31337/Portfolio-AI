#!/usr/bin/env python3
"""AI Assistant chat session persistence (Supabase ``ai_assistant_chats``).

One active transcript per ``(user_id, fund)``. Flask uses the service-role
client after auth; RLS also allows the owning user directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

MAX_STORED_TURNS = 40
MAX_CONTENT_CHARS = 20_000
ALLOWED_ROLES = frozenset({"user", "assistant"})


def _supabase():
    from supabase_client import SupabaseClient

    return SupabaseClient(use_service_role=True)


def _normalize_fund(fund: str | None) -> str:
    return str(fund or "").strip()


def _normalize_messages(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in ALLOWED_ROLES:
            continue
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "\n…[truncated]"
        msg: dict[str, Any] = {"role": role, "content": content}
        ts = item.get("ts")
        if ts:
            msg["ts"] = str(ts)
        out.append(msg)
    return out[-MAX_STORED_TURNS:]


def load_chat(user_id: str, fund: str) -> dict[str, Any]:
    """Return ``{fund, model, messages, updated_at}`` (empty messages if none)."""
    fund_s = _normalize_fund(fund)
    empty = {"fund": fund_s, "model": None, "messages": [], "updated_at": None}
    if not user_id or not fund_s:
        return empty
    try:
        client = _supabase()
        result = (
            client.supabase.table("ai_assistant_chats")
            .select("fund, model, messages, updated_at")
            .eq("user_id", user_id)
            .eq("fund", fund_s)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return empty
        row = rows[0]
        return {
            "fund": fund_s,
            "model": row.get("model"),
            "messages": _normalize_messages(row.get("messages")),
            "updated_at": row.get("updated_at"),
        }
    except Exception as exc:
        logger.warning("load_chat failed user=%s fund=%s: %s", user_id, fund_s, exc)
        return empty


def replace_messages(
    user_id: str,
    fund: str,
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Upsert the full capped message list for ``(user_id, fund)``."""
    fund_s = _normalize_fund(fund)
    if not user_id or not fund_s:
        raise ValueError("user_id and fund are required")
    normalized = _normalize_messages(messages)
    now = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "user_id": user_id,
        "fund": fund_s,
        "messages": normalized,
        "updated_at": now,
    }
    if model is not None:
        payload["model"] = str(model).strip() or None
    client = _supabase()

    # Preserve existing created_at if upserting
    try:
        existing = (
            client.supabase.table("ai_assistant_chats")
            .select("created_at")
            .eq("user_id", user_id)
            .eq("fund", fund_s)
            .limit(1)
            .execute()
        )
        if existing.data and existing.data[0].get("created_at"):
            payload["created_at"] = existing.data[0]["created_at"]
    except Exception as exc:
        logger.warning("Failed to fetch existing created_at for %s/%s: %s", user_id, fund_s, exc)

    (
        client.supabase.table("ai_assistant_chats")
        .upsert(payload, on_conflict="user_id,fund")
        .execute()
    )
    return {
        "fund": fund_s,
        "model": payload.get("model"),
        "messages": normalized,
        "updated_at": now,
    }


def append_turns(
    user_id: str,
    fund: str,
    turns: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Append one or more turns to the stored transcript (capped)."""
    current = load_chat(user_id, fund)
    merged = list(current.get("messages") or []) + _normalize_messages(turns)
    return replace_messages(
        user_id,
        fund,
        merged,
        model=model if model is not None else current.get("model"),
    )


def clear_chat(user_id: str, fund: str) -> None:
    """Delete the transcript row for ``(user_id, fund)``."""
    fund_s = _normalize_fund(fund)
    if not user_id or not fund_s:
        raise ValueError("user_id and fund are required")
    client = _supabase()
    (
        client.supabase.table("ai_assistant_chats")
        .delete()
        .eq("user_id", user_id)
        .eq("fund", fund_s)
        .execute()
    )


def reset_webai_session(user_id: str) -> None:
    """Best-effort reset of on-disk WebAI Gemini continuity for this user."""
    if not user_id:
        return
    # PersistentConversationSession only allows [a-zA-Z0-9_-]
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in str(user_id))
    if not safe:
        return
    try:
        from webai_wrapper import PersistentConversationSession

        PersistentConversationSession(session_id=safe).reset_sync()
    except Exception as exc:
        logger.info("WebAI session reset skipped for %s: %s", safe, exc)
