"""Thesis / Insights service — org-wide human thesis threads in Research DB."""

from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

VALID_DISPOSITIONS = frozenset({"bullish", "bearish", "neutral"})
VALID_INTENTS = frozenset({"seek_entry", "seek_exit", "monitor"})
VALID_ENTRY_KINDS = frozenset({"opening", "comment", "review", "llm_reply"})
VALID_EVIDENCE_KINDS = frozenset({
    "user_url",
    "research_article",
    "ticker_analysis",
    "ticker_meta_analysis",
    "confluence_event",
    "stance_history",
})
VALID_RELATIONS = frozenset({"supports", "contradicts", "context"})


def _normalize_ticker(ticker: str) -> str:
    return (ticker or "").upper().strip()


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in row.items():
        if val is None:
            out[key] = None
        elif isinstance(val, UUID):
            out[key] = str(val)
        elif hasattr(val, "isoformat") and callable(val.isoformat):
            out[key] = val.isoformat()
        elif isinstance(val, dict | list):
            out[key] = val
        elif hasattr(val, "__float__") and not isinstance(val, bool):
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                out[key] = val
        else:
            out[key] = val
    return out


def _try_embedding(text: str) -> list[float] | None:
    snippet = (text or "").strip()
    if not snippet:
        return None
    try:
        from ollama_client import get_ollama_client

        client = get_ollama_client()
        if not client:
            return None
        return client.generate_embedding(snippet[:8000])
    except Exception as exc:
        logger.debug("thesis embedding skipped: %s", exc)
        return None


class ThesisNotFoundError(LookupError):
    """Raised when a thesis id does not exist."""

    def __init__(self, thesis_id: str) -> None:
        super().__init__(f"thesis not found: {thesis_id}")
        self.thesis_id = thesis_id


class ThesisPermissionError(PermissionError):
    """Raised when the caller cannot perform the action."""


def get_thesis_row(pg: Any, thesis_id: str) -> dict[str, Any]:
    rows = pg.execute_query(
        """
        SELECT t.*,
               (SELECT COUNT(*)::int FROM thesis_entries e WHERE e.thesis_id = t.id) AS entry_count,
               (SELECT COUNT(*)::int FROM thesis_evidence ev WHERE ev.thesis_id = t.id) AS evidence_count
        FROM ticker_theses t
        WHERE t.id = %s::uuid
        """,
        (thesis_id,),
    )
    if not rows:
        raise ThesisNotFoundError(thesis_id)
    return _serialize_row(dict(rows[0]))


def list_theses(
    pg: Any,
    *,
    ticker: str | None = None,
    disposition: str | None = None,
    intent: str | None = None,
    author: str | None = None,
    include_archived: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: list[Any] = []

    if not include_archived:
        clauses.append("t.status = 'active'")
    if ticker:
        clauses.append("t.ticker = %s")
        params.append(_normalize_ticker(ticker))
    if disposition:
        clauses.append("t.disposition = %s")
        params.append(disposition.strip().lower())
    if intent:
        clauses.append("t.intent = %s")
        params.append(intent.strip().lower())
    if author:
        clauses.append("t.created_by = %s")
        params.append(author.strip().lower())

    params.append(max(1, min(limit, 500)))
    where = " AND ".join(clauses)
    rows = pg.execute_query(
        f"""
        SELECT t.*,
               (SELECT COUNT(*)::int FROM thesis_entries e WHERE e.thesis_id = t.id) AS entry_count,
               (SELECT COUNT(*)::int FROM thesis_evidence ev WHERE ev.thesis_id = t.id) AS evidence_count
        FROM ticker_theses t
        WHERE {where}
        ORDER BY t.updated_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return [_serialize_row(dict(r)) for r in rows]


def list_entries(pg: Any, thesis_id: str) -> list[dict[str, Any]]:
    rows = pg.execute_query(
        """
        SELECT * FROM thesis_entries
        WHERE thesis_id = %s::uuid
        ORDER BY created_at ASC
        """,
        (thesis_id,),
    )
    return [_serialize_row(dict(r)) for r in rows]


def list_evidence(pg: Any, thesis_id: str) -> list[dict[str, Any]]:
    rows = pg.execute_query(
        """
        SELECT ev.*,
               ra.title AS article_title,
               ra.url AS article_url
        FROM thesis_evidence ev
        LEFT JOIN research_articles ra
          ON ev.evidence_kind = 'research_article' AND ev.ref_id = ra.id
        WHERE ev.thesis_id = %s::uuid
        ORDER BY ev.created_at ASC
        """,
        (thesis_id,),
    )
    return [_serialize_row(dict(r)) for r in rows]


def get_thesis_detail(pg: Any, thesis_id: str) -> dict[str, Any]:
    thesis = get_thesis_row(pg, thesis_id)
    thesis["entries"] = list_entries(pg, thesis_id)
    thesis["evidence"] = list_evidence(pg, thesis_id)
    return thesis


def create_thesis(
    pg: Any,
    *,
    ticker: str,
    title: str,
    disposition: str,
    intent: str,
    body: str,
    created_by: str,
    source_url: str | None = None,
    source_type: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    ticker_u = _normalize_ticker(ticker)
    disp = disposition.strip().lower()
    intnt = intent.strip().lower()
    if disp not in VALID_DISPOSITIONS:
        raise ValueError(f"invalid disposition: {disposition}")
    if intnt not in VALID_INTENTS:
        raise ValueError(f"invalid intent: {intent}")
    if not body.strip():
        raise ValueError("body is required")

    title_s = (title or "").strip() or f"{ticker_u} thesis"
    meta: dict[str, Any] = {}
    if tags:
        meta["tags"] = [str(t).strip() for t in tags if str(t).strip()]
    if source_type:
        meta["source_type"] = source_type.strip()

    embed_text = f"{title_s}\n{body.strip()}"
    embedding = _try_embedding(embed_text)

    if embedding:
        thesis_rows = pg.execute_query(
            """
            INSERT INTO ticker_theses (
                ticker, title, disposition, intent, status, created_by, embedding
            ) VALUES (%s, %s, %s, %s, 'active', %s, %s)
            RETURNING id
            """,
            (ticker_u, title_s, disp, intnt, created_by, embedding),
        )
    else:
        thesis_rows = pg.execute_query(
            """
            INSERT INTO ticker_theses (
                ticker, title, disposition, intent, status, created_by
            ) VALUES (%s, %s, %s, %s, 'active', %s)
            RETURNING id
            """,
            (ticker_u, title_s, disp, intnt, created_by),
        )
    if not thesis_rows:
        raise RuntimeError("failed to insert thesis")
    thesis_id = str(thesis_rows[0]["id"])

    entry_embed = _try_embedding(body.strip())
    if entry_embed:
        entry_rows = pg.execute_query(
            """
            INSERT INTO thesis_entries (
                thesis_id, entry_kind, author_kind, author_id, body, metadata, embedding
            ) VALUES (%s::uuid, 'opening', 'user', %s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (
                thesis_id,
                created_by,
                body.strip(),
                json.dumps({"disposition": disp, "intent": intnt, **meta}),
                entry_embed,
            ),
        )
    else:
        entry_rows = pg.execute_query(
            """
            INSERT INTO thesis_entries (
                thesis_id, entry_kind, author_kind, author_id, body, metadata
            ) VALUES (%s::uuid, 'opening', 'user', %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                thesis_id,
                created_by,
                body.strip(),
                json.dumps({"disposition": disp, "intent": intnt, **meta}),
            ),
        )
    entry_id = str(entry_rows[0]["id"]) if entry_rows else None

    if source_url and source_url.strip():
        add_evidence(
            pg,
            thesis_id=thesis_id,
            entry_id=entry_id,
            evidence_kind="user_url",
            created_by=created_by,
            url=source_url.strip(),
            title=title_s,
            relation="supports",
        )

    return get_thesis_detail(pg, thesis_id)


def add_entry(
    pg: Any,
    *,
    thesis_id: str,
    entry_kind: str,
    body: str,
    author_id: str,
    disposition: str | None = None,
    intent: str | None = None,
) -> dict[str, Any]:
    kind = entry_kind.strip().lower()
    if kind not in VALID_ENTRY_KINDS - {"opening", "llm_reply"}:
        raise ValueError(f"invalid entry_kind: {entry_kind}")
    if not body.strip():
        raise ValueError("body is required")

    thesis = get_thesis_row(pg, thesis_id)
    meta: dict[str, Any] = {}
    now = datetime.now(UTC)

    if kind == "review":
        prior_disp = thesis.get("disposition")
        prior_intent = thesis.get("intent")
        new_disp = (disposition or prior_disp or "neutral").strip().lower()
        new_intent = (intent or prior_intent or "monitor").strip().lower()
        if new_disp not in VALID_DISPOSITIONS:
            raise ValueError(f"invalid disposition: {disposition}")
        if new_intent not in VALID_INTENTS:
            raise ValueError(f"invalid intent: {intent}")
        meta = {
            "disposition": new_disp,
            "intent": new_intent,
            "prior_disposition": prior_disp,
            "prior_intent": prior_intent,
            "disposition_changed": new_disp != prior_disp,
            "intent_changed": new_intent != prior_intent,
        }
        pg.execute_update(
            """
            UPDATE ticker_theses
            SET disposition = %s, intent = %s, last_reviewed_at = %s, updated_at = %s
            WHERE id = %s::uuid
            """,
            (new_disp, new_intent, now, now, thesis_id),
        )
    else:
        pg.execute_update(
            "UPDATE ticker_theses SET updated_at = %s WHERE id = %s::uuid",
            (now, thesis_id),
        )

    entry_embed = _try_embedding(body.strip())
    if entry_embed:
        rows = pg.execute_query(
            """
            INSERT INTO thesis_entries (
                thesis_id, entry_kind, author_kind, author_id, body, metadata, embedding
            ) VALUES (%s::uuid, %s, 'user', %s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (thesis_id, kind, author_id, body.strip(), json.dumps(meta), entry_embed),
        )
    else:
        rows = pg.execute_query(
            """
            INSERT INTO thesis_entries (
                thesis_id, entry_kind, author_kind, author_id, body, metadata
            ) VALUES (%s::uuid, %s, 'user', %s, %s, %s::jsonb)
            RETURNING id
            """,
            (thesis_id, kind, author_id, body.strip(), json.dumps(meta)),
        )
    entry = _serialize_row(dict(rows[0])) if rows else {}
    return {"entry_id": entry.get("id"), "thesis": get_thesis_detail(pg, thesis_id)}


def update_thesis_title(
    pg: Any,
    *,
    thesis_id: str,
    title: str,
    actor: str,
    is_admin: bool,
) -> dict[str, Any]:
    thesis = get_thesis_row(pg, thesis_id)
    if thesis.get("created_by") != actor and not is_admin:
        raise ThesisPermissionError("only author or admin may edit thesis title")
    title_s = title.strip()
    if not title_s:
        raise ValueError("title is required")
    pg.execute_update(
        "UPDATE ticker_theses SET title = %s, updated_at = %s WHERE id = %s::uuid",
        (title_s, datetime.now(UTC), thesis_id),
    )
    return get_thesis_detail(pg, thesis_id)


def add_evidence(
    pg: Any,
    *,
    thesis_id: str,
    evidence_kind: str,
    created_by: str,
    entry_id: str | None = None,
    ref_id: str | None = None,
    url: str | None = None,
    title: str | None = None,
    snippet: str | None = None,
    relation: str = "context",
) -> dict[str, Any]:
    kind = evidence_kind.strip().lower()
    if kind not in VALID_EVIDENCE_KINDS:
        raise ValueError(f"invalid evidence_kind: {evidence_kind}")
    rel = (relation or "context").strip().lower()
    if rel not in VALID_RELATIONS:
        raise ValueError(f"invalid relation: {relation}")

    get_thesis_row(pg, thesis_id)

    if kind == "research_article" and ref_id:
        art = pg.execute_query(
            "SELECT id, title, url FROM research_articles WHERE id = %s::uuid",
            (ref_id,),
        )
        if not art:
            raise ValueError("research_article not found")
        if not title:
            title = art[0].get("title")
        if not url:
            url = art[0].get("url")

    rows = pg.execute_query(
        """
        INSERT INTO thesis_evidence (
            thesis_id, entry_id, evidence_kind, ref_id, url, title, snippet, relation, created_by
        ) VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            thesis_id,
            entry_id,
            kind,
            ref_id,
            url,
            title,
            snippet,
            rel,
            created_by,
        ),
    )
    pg.execute_update(
        "UPDATE ticker_theses SET updated_at = %s WHERE id = %s::uuid",
        (datetime.now(UTC), thesis_id),
    )
    ev_id = str(rows[0]["id"]) if rows else None
    return {"evidence_id": ev_id, "thesis": get_thesis_detail(pg, thesis_id)}


def delete_evidence(
    pg: Any,
    *,
    thesis_id: str,
    evidence_id: str,
    actor: str,
    is_admin: bool,
) -> dict[str, Any]:
    rows = pg.execute_query(
        "SELECT created_by FROM thesis_evidence WHERE id = %s::uuid AND thesis_id = %s::uuid",
        (evidence_id, thesis_id),
    )
    if not rows:
        raise LookupError("evidence not found")
    if rows[0].get("created_by") != actor and not is_admin:
        raise ThesisPermissionError("only author or admin may remove evidence")
    pg.execute_update(
        "DELETE FROM thesis_evidence WHERE id = %s::uuid",
        (evidence_id,),
    )
    return get_thesis_detail(pg, thesis_id)


def archive_thesis(
    pg: Any,
    *,
    thesis_id: str,
    actor: str,
    is_admin: bool,
) -> dict[str, Any]:
    thesis = get_thesis_row(pg, thesis_id)
    if thesis.get("created_by") != actor and not is_admin:
        raise ThesisPermissionError("only author or admin may archive thesis")
    now = datetime.now(UTC)
    pg.execute_update(
        """
        UPDATE ticker_theses
        SET status = 'archived', archived_at = %s, archived_by = %s, updated_at = %s
        WHERE id = %s::uuid
        """,
        (now, actor, now, thesis_id),
    )
    return get_thesis_detail(pg, thesis_id)


def restore_thesis(
    pg: Any,
    *,
    thesis_id: str,
    actor: str,
    is_admin: bool,
) -> dict[str, Any]:
    thesis = get_thesis_row(pg, thesis_id)
    if thesis.get("created_by") != actor and not is_admin:
        raise ThesisPermissionError("only author or admin may restore thesis")
    now = datetime.now(UTC)
    pg.execute_update(
        """
        UPDATE ticker_theses
        SET status = 'active', archived_at = NULL, archived_by = NULL, updated_at = %s
        WHERE id = %s::uuid
        """,
        (now, thesis_id),
    )
    return get_thesis_detail(pg, thesis_id)


def hard_delete_thesis(
    pg: Any,
    *,
    thesis_id: str,
    actor: str,
    is_admin: bool,
) -> None:
    if not is_admin:
        raise ThesisPermissionError("only admin may hard-delete a thesis")
    get_thesis_row(pg, thesis_id)
    pg.execute_update("DELETE FROM ticker_theses WHERE id = %s::uuid", (thesis_id,))


def fetch_thesis_timeline_events(pg: Any, ticker: str, limit: int = 30) -> list[dict[str, Any]]:
    """Events for dossier evidence timeline."""
    rows = pg.execute_query(
        """
        SELECT 'user_insight' AS event_type,
               COALESCE(t.last_reviewed_at, t.updated_at, t.created_at) AS event_at,
               (t.disposition || ' · ' || t.intent || ' — ' || t.title) AS label,
               t.created_by AS source,
               NULL::numeric AS confidence,
               jsonb_build_object(
                   'thesis_id', t.id,
                   'disposition', t.disposition,
                   'intent', t.intent,
                   'title', t.title,
                   'status', t.status
               ) AS metadata
        FROM ticker_theses t
        WHERE t.ticker = %s AND t.status = 'active'
        ORDER BY t.updated_at DESC
        LIMIT %s
        """,
        (_normalize_ticker(ticker), max(1, min(limit, 50))),
    )
    return [_serialize_row(dict(r)) for r in rows]
