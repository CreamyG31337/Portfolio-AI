"""Point-in-time SQL helpers (AQuA transfer Phase 1).

Analysis lookbacks prefer immutable ``available_at`` when the column exists.
"""

from __future__ import annotations

from typing import Any

_article_has_available_at: bool | None = None
_social_has_available_at: bool | None = None


def reset_pit_column_cache() -> None:
    """Test helper."""
    global _article_has_available_at, _social_has_available_at
    _article_has_available_at = None
    _social_has_available_at = None


def research_articles_have_available_at(postgres: Any) -> bool:
    global _article_has_available_at
    if _article_has_available_at is not None:
        return _article_has_available_at
    try:
        rows = postgres.execute_query(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'research_articles' AND column_name = 'available_at'
            LIMIT 1
            """
        )
        _article_has_available_at = bool(rows)
    except Exception:
        _article_has_available_at = False
    return _article_has_available_at


def social_metrics_have_available_at(postgres: Any) -> bool:
    global _social_has_available_at
    if _social_has_available_at is not None:
        return _social_has_available_at
    try:
        rows = postgres.execute_query(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'social_metrics' AND column_name = 'available_at'
            LIMIT 1
            """
        )
        _social_has_available_at = bool(rows)
    except Exception:
        _social_has_available_at = False
    return _social_has_available_at


def article_as_of_expr(postgres: Any) -> str:
    if research_articles_have_available_at(postgres):
        return "COALESCE(available_at, fetched_at)"
    return "fetched_at"


def social_as_of_expr(postgres: Any) -> str:
    if social_metrics_have_available_at(postgres):
        return "COALESCE(available_at, created_at)"
    return "created_at"
