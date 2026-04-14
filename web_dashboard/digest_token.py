"""Signed tokens for expiring portfolio digest URLs (issue + user bound)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from itsdangerous import BadSignature, URLSafeSerializer


def _serializer() -> URLSafeSerializer:
    secret = os.getenv("FLASK_SECRET_KEY") or "dev-only-not-for-production"
    return URLSafeSerializer(secret, salt="outbound-digest-v1")


def sign_digest_view_token(user_id: str, issue_id: str) -> str:
    """Opaque token embedding user and issue ids (expiry enforced via issue row in DB)."""
    return _serializer().dumps({"u": user_id, "i": issue_id})


def verify_digest_view_token(token: str) -> Optional[Dict[str, str]]:
    try:
        data = _serializer().loads(token)
        uid = data.get("u")
        iid = data.get("i")
        if not uid or not iid:
            return None
        return {"user_id": str(uid), "issue_id": str(iid)}
    except BadSignature:
        return None


def sign_preview_token(user_id: str, admin_user_id: str) -> str:
    """Short-lived admin preview (validated with max_age in loads)."""
    from itsdangerous import URLSafeTimedSerializer

    secret = os.getenv("FLASK_SECRET_KEY") or "dev-only-not-for-production"
    ts = URLSafeTimedSerializer(secret, salt="outbound-digest-preview-v1")
    return ts.dumps({"u": user_id, "a": admin_user_id, "p": 1})


def verify_preview_token(token: str, max_age_seconds: int = 3600) -> Optional[Dict[str, Any]]:
    from itsdangerous import URLSafeTimedSerializer

    secret = os.getenv("FLASK_SECRET_KEY") or "dev-only-not-for-production"
    ts = URLSafeTimedSerializer(secret, salt="outbound-digest-preview-v1")
    try:
        data = ts.loads(token, max_age=max_age_seconds)
        uid = data.get("u")
        aid = data.get("a")
        if not uid or not aid or data.get("p") != 1:
            return None
        return {"user_id": str(uid), "admin_user_id": str(aid)}
    except BadSignature:
        return None
