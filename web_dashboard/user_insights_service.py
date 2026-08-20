"""Thesis / Insights service — org-wide human thesis threads in Research DB."""

from __future__ import annotations

import hashlib
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

DEFAULT_SOFT_DUE_DAYS = 14
DEFAULT_HARD_STALE_DAYS = 30
WEAK_CONTEXT_MARKER = "[WEAK CONTEXT]"
META_THESIS_OPENING_MAX = 500
META_THESIS_ENTRY_MAX = 400
META_THESIS_MAX_PER_TICKER = 3
META_THESIS_RECENT_DAYS = 14
# Auto soft-archive weak/bootstrap drafts after this many consecutive INSUFFICIENT_DATA llm_replies.
WEAK_INSUFFICIENT_ARCHIVE_THRESHOLD = 3
# Correlated subquery: last advisory eval timestamp (does not bump last_reviewed_at).
_LATEST_LLM_REPLY_AT_SQL = """
               (
                   SELECT MAX(e.created_at) FROM thesis_entries e
                   WHERE e.thesis_id = t.id AND e.entry_kind = 'llm_reply'
               ) AS latest_llm_reply_at"""


def _normalize_ticker(ticker: str) -> str:
    return (ticker or "").upper().strip()


def _url_evidence_title(url: str) -> str:
    """Short display label for a pasted URL — never reuse the thesis title."""
    from urllib.parse import urlparse

    raw = (url or "").strip()
    if not raw:
        return "Source link"
    try:
        parsed = urlparse(raw)
        host = (parsed.netloc or "").removeprefix("www.")
        path = parsed.path or ""
        if path in ("", "/"):
            return host or raw[:80]
        # Keep path short so evidence rows stay scannable
        clipped = path if len(path) <= 48 else path[:45] + "…"
        return f"{host}{clipped}" if host else clipped
    except Exception:
        return raw[:80]


def _parse_ts(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=UTC)
        return val
    if isinstance(val, str):
        try:
            parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    return None


def thesis_reviewed_at(row: dict[str, Any]) -> datetime | None:
    """Effective human-review timestamp: last human review, else created_at."""
    return _parse_ts(row.get("last_reviewed_at")) or _parse_ts(row.get("created_at"))


def thesis_checked_at(row: dict[str, Any]) -> datetime | None:
    """Last check-in for due/stale: human review, latest AI llm_reply, or created_at.

    ``last_reviewed_at`` stays human-only (eval must not bump it). Due/stale for
    the Insights queue and Today/Ideas uses this so a successful eval actually
    refreshes the thread instead of leaving it stale forever.
    """
    latest_llm = _parse_ts(row.get("latest_llm_reply_at"))
    if latest_llm is None:
        latest_entry = latest_llm_reply_entry(row)
        if latest_entry:
            latest_llm = _parse_ts(latest_entry.get("created_at"))
    present = [
        ts
        for ts in (
            _parse_ts(row.get("last_reviewed_at")),
            latest_llm,
            _parse_ts(row.get("created_at")),
        )
        if ts is not None
    ]
    return max(present) if present else None


def is_weak_thesis(
    *,
    title: str | None = None,
    opening_body: str | None = None,
    opening_metadata: dict[str, Any] | list[Any] | None = None,
) -> bool:
    """True for moat/bootstrap drafts tagged weak_context or WEAK CONTEXT marker."""
    if title and WEAK_CONTEXT_MARKER in title:
        return True
    if opening_body and (
        opening_body.lstrip().startswith(WEAK_CONTEXT_MARKER)
        or WEAK_CONTEXT_MARKER in opening_body[:80]
    ):
        return True
    meta = opening_metadata if isinstance(opening_metadata, dict) else {}
    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    return any(str(t).strip().lower() == "weak_context" for t in tags)


def classify_due_status(
    reviewed_at: datetime | None,
    *,
    soft_days: int = DEFAULT_SOFT_DUE_DAYS,
    hard_days: int = DEFAULT_HARD_STALE_DAYS,
    now: datetime | None = None,
) -> str | None:
    """Return 'stale', 'due_for_review', or None if still fresh."""
    if reviewed_at is None:
        return "stale"
    now_ts = now or datetime.now(UTC)
    if reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=UTC)
    age_days = (now_ts - reviewed_at).total_seconds() / 86400.0
    if age_days >= hard_days:
        return "stale"
    if age_days >= soft_days:
        return "due_for_review"
    return None


def _apply_due_fields(
    row: dict[str, Any],
    *,
    now: datetime,
    soft_days: int = DEFAULT_SOFT_DUE_DAYS,
    hard_days: int = DEFAULT_HARD_STALE_DAYS,
) -> None:
    """Set review_status / age_days / reviewed_at / checked_at from check-in time."""
    checked = thesis_checked_at(row)
    row["review_status"] = classify_due_status(
        checked, soft_days=soft_days, hard_days=hard_days, now=now
    )
    human = thesis_reviewed_at(row)
    row["reviewed_at"] = human.isoformat() if human else None
    row["checked_at"] = checked.isoformat() if checked else None
    age_days = None
    if checked is not None:
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=UTC)
        age_days = round((now - checked).total_seconds() / 86400.0, 1)
    row["age_days"] = age_days


def _entry_metadata(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not entry:
        return {}
    meta = entry.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return meta if isinstance(meta, dict) else {}


def compute_thesis_eval_digest(
    detail: dict[str, Any],
    research_refs: dict[str, Any],
) -> str:
    """Fingerprint thesis claim + saved research timestamps for eval skip gating.

    Same digest ⇒ no human claim change and no newer ticker_analysis / meta rows.
    """
    entries = detail.get("entries") or []
    human_entries = [
        e
        for e in entries
        if e.get("entry_kind") in ("opening", "comment", "review")
    ]
    latest_human = human_entries[-1] if human_entries else None
    payload = {
        "disposition": detail.get("disposition"),
        "intent": detail.get("intent"),
        "last_reviewed_at": detail.get("last_reviewed_at"),
        "title": detail.get("title"),
        "human_entry_id": (latest_human or {}).get("id"),
        "human_entry_at": (latest_human or {}).get("created_at"),
        "human_entry_kind": (latest_human or {}).get("entry_kind"),
        "ta_id": research_refs.get("ticker_analysis_id") or "",
        "ta_updated_at": research_refs.get("ticker_analysis_updated_at") or "",
        "meta_id": research_refs.get("ticker_meta_analysis_id") or "",
        "meta_updated_at": research_refs.get("ticker_meta_updated_at") or "",
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def latest_llm_reply_entry(detail: dict[str, Any]) -> dict[str, Any] | None:
    entries = detail.get("entries") or []
    for e in reversed(entries):
        if e.get("entry_kind") == "llm_reply":
            return e
    return None


def should_skip_thesis_eval(
    detail: dict[str, Any],
    research_refs: dict[str, Any],
    *,
    now: datetime | None = None,
    max_digest_age_days: int = DEFAULT_SOFT_DUE_DAYS,
) -> tuple[bool, str, str]:
    """Return (skip, digest, reason). Skip when prior llm_reply used the same digest.

    Digest skip expires after ``max_digest_age_days`` so stale threads re-enter the
    LLM batch even when saved research ids/timestamps have not moved.
    """
    digest = compute_thesis_eval_digest(detail, research_refs)
    latest = latest_llm_reply_entry(detail)
    if not latest:
        return False, digest, ""
    prior = _entry_metadata(latest).get("research_digest")
    if not prior or str(prior) != digest:
        return False, digest, ""
    reply_at = _parse_ts(latest.get("created_at"))
    if reply_at is None:
        return False, digest, ""
    now_ts = now or datetime.now(UTC)
    if reply_at.tzinfo is None:
        reply_at = reply_at.replace(tzinfo=UTC)
    age_days = (now_ts - reply_at).total_seconds() / 86400.0
    if age_days >= max(1, max_digest_age_days):
        return False, digest, "research_digest_expired"
    return True, digest, "research_digest_unchanged"


def count_trailing_insufficient_llm_replies(detail: dict[str, Any]) -> int:
    """Count consecutive trailing llm_reply entries with verdict INSUFFICIENT_DATA."""
    entries = detail.get("entries") or []
    n = 0
    for e in reversed(entries):
        if e.get("entry_kind") != "llm_reply":
            # Human activity after the trailing insufficient streak breaks it.
            if e.get("entry_kind") in ("opening", "comment", "review"):
                break
            continue
        verdict = str(_entry_metadata(e).get("verdict") or "").upper()
        if verdict == "INSUFFICIENT_DATA":
            n += 1
        else:
            break
    return n


def thesis_has_human_review(detail: dict[str, Any]) -> bool:
    return any(e.get("entry_kind") == "review" for e in (detail.get("entries") or []))


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
               (SELECT COUNT(*)::int FROM thesis_evidence ev WHERE ev.thesis_id = t.id) AS evidence_count,
               {_LATEST_LLM_REPLY_AT_SQL}
        FROM ticker_theses t
        WHERE {where}
        ORDER BY t.updated_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    now_ts = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = _serialize_row(dict(raw))
        _apply_due_fields(row, now=now_ts)
        out.append(row)
    return out


def list_theses_due(
    pg: Any,
    *,
    soft_days: int = DEFAULT_SOFT_DUE_DAYS,
    hard_days: int = DEFAULT_HARD_STALE_DAYS,
    include_weak_always: bool = True,
    limit: int = 100,
    now: datetime | None = None,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Active theses due for human review (soft/hard age) and/or weak drafts.

    Does not bump last_reviewed_at. Sorted: stale, then due, then weak drafts, then oldest.
    Optional ``ticker`` filters in SQL so callers are not capped by a global top-N pool.
    Due/stale age uses last human review or latest AI ``llm_reply`` (see thesis_checked_at).
    """
    soft = max(1, soft_days)
    hard = max(soft, hard_days)
    now_ts = now or datetime.now(UTC)
    # Fetch a wider pool then classify in Python so weak always-include works.
    fetch_limit = max(1, min(limit * 4, 500))
    clauses = ["t.status = 'active'"]
    params: list[Any] = []
    if ticker:
        clauses.append("t.ticker = %s")
        params.append(_normalize_ticker(ticker))
    params.append(fetch_limit)
    where = " AND ".join(clauses)
    rows = pg.execute_query(
        f"""
        SELECT t.*,
               (SELECT COUNT(*)::int FROM thesis_entries e WHERE e.thesis_id = t.id) AS entry_count,
               (SELECT COUNT(*)::int FROM thesis_evidence ev WHERE ev.thesis_id = t.id) AS evidence_count,
               {_LATEST_LLM_REPLY_AT_SQL},
               (
                   SELECT e.body FROM thesis_entries e
                   WHERE e.thesis_id = t.id AND e.entry_kind = 'opening'
                   ORDER BY e.created_at ASC
                   LIMIT 1
               ) AS opening_body,
               (
                   SELECT e.metadata FROM thesis_entries e
                   WHERE e.thesis_id = t.id AND e.entry_kind = 'opening'
                   ORDER BY e.created_at ASC
                   LIMIT 1
               ) AS opening_metadata
        FROM ticker_theses t
        WHERE {where}
        ORDER BY COALESCE(
            (
                SELECT MAX(e.created_at) FROM thesis_entries e
                WHERE e.thesis_id = t.id AND e.entry_kind = 'llm_reply'
            ),
            t.last_reviewed_at,
            t.created_at
        ) ASC NULLS FIRST
        LIMIT %s
        """,
        tuple(params),
    )

    due: list[dict[str, Any]] = []
    for raw in rows:
        row = _serialize_row(dict(raw))
        opening_meta = row.get("opening_metadata")
        if isinstance(opening_meta, str):
            try:
                opening_meta = json.loads(opening_meta)
            except (TypeError, ValueError, json.JSONDecodeError):
                opening_meta = {}
        weak = is_weak_thesis(
            title=str(row.get("title") or ""),
            opening_body=str(row.get("opening_body") or ""),
            opening_metadata=opening_meta if isinstance(opening_meta, dict) else {},
        )
        _apply_due_fields(row, now=now_ts, soft_days=soft, hard_days=hard)
        row["is_weak"] = weak
        status = row.get("review_status")
        if status is None and not (include_weak_always and weak):
            continue
        if status is None and weak:
            row["review_status"] = "due_for_review"
        due.append(row)

    due.sort(
        key=lambda r: (
            0 if r.get("review_status") == "stale" else 1,
            0 if r.get("review_status") == "due_for_review" and not r.get("is_weak") else 1,
            0 if r.get("is_weak") else 1,
            -(r.get("age_days") or 0),
        )
    )
    return due[: max(1, min(limit, 500))]


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
        # Caption must describe the URL destination — not the thesis title
        # (moat probe used to make "[LLM draft] …" look like an article link to Yahoo).
        src = source_url.strip()
        add_evidence(
            pg,
            thesis_id=thesis_id,
            entry_id=entry_id,
            evidence_kind="user_url",
            created_by=created_by,
            url=src,
            title=_url_evidence_title(src),
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


def add_llm_reply(
    pg: Any,
    *,
    thesis_id: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    author_id: str = "insights_thesis_evaluation",
    model_used: str | None = None,
) -> dict[str, Any]:
    """Insert an advisory llm_reply. Does NOT bump last_reviewed_at or change disposition."""
    if not body.strip():
        raise ValueError("body is required")
    get_thesis_row(pg, thesis_id)
    meta: dict[str, Any] = dict(metadata or {})
    if model_used:
        meta["model_used"] = model_used
    now = datetime.now(UTC)
    # Touch updated_at only — human review is what clears due/stale.
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
            ) VALUES (%s::uuid, 'llm_reply', 'llm', %s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (thesis_id, author_id, body.strip(), json.dumps(meta), entry_embed),
        )
    else:
        rows = pg.execute_query(
            """
            INSERT INTO thesis_entries (
                thesis_id, entry_kind, author_kind, author_id, body, metadata
            ) VALUES (%s::uuid, 'llm_reply', 'llm', %s, %s, %s::jsonb)
            RETURNING id
            """,
            (thesis_id, author_id, body.strip(), json.dumps(meta)),
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
    system: bool = False,
) -> dict[str, Any]:
    """Soft-archive a thesis. ``system=True`` bypasses author/admin checks (jobs)."""
    thesis = get_thesis_row(pg, thesis_id)
    if not system and thesis.get("created_by") != actor and not is_admin:
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


def _clip_meta(text: str | None, max_len: int) -> str:
    if not text:
        return ""
    t = " ".join(str(text).split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 3].rsplit(" ", 1)[0] + "..."


def format_human_theses_for_meta_bundle(
    pg: Any,
    ticker: str,
    *,
    max_theses: int = META_THESIS_MAX_PER_TICKER,
) -> str | None:
    """Compact Insights thesis text for ticker-meta artifact bundles, or None if none.

    Labels weak/bootstrap drafts explicitly so meta does not treat them as ground truth.
    Skips weak drafts that have never had a human ``review`` (cuts meta↔eval chatter).
    Distinct from fund-level ``fund_thesis`` philosophy.
    """
    rows = list_theses(
        pg,
        ticker=_normalize_ticker(ticker),
        include_archived=False,
        limit=max(1, min(max_theses * 3, 15)),
    )
    if not rows:
        return None

    parts: list[str] = [
        "### Human ticker thesis threads (Insights — not fund_thesis)",
        "Treat as human / bootstrap claims to reconcile. "
        "WEAK / bootstrap drafts are noisy — do not elevate them over stronger artifacts.",
    ]
    included = 0
    for row in rows:
        if included >= max(1, min(max_theses, 10)):
            break
        thesis_id = str(row.get("id") or "")
        detail = get_thesis_detail(pg, thesis_id) if thesis_id else row
        entries = detail.get("entries") or []
        opening = next(
            (e for e in entries if e.get("entry_kind") == "opening"),
            entries[0] if entries else None,
        )
        opening_body = str((opening or {}).get("body") or "")
        opening_meta = (opening or {}).get("metadata") or {}
        if isinstance(opening_meta, str):
            try:
                opening_meta = json.loads(opening_meta)
            except (TypeError, ValueError, json.JSONDecodeError):
                opening_meta = {}
        weak = is_weak_thesis(
            title=str(row.get("title") or ""),
            opening_body=opening_body,
            opening_metadata=opening_meta if isinstance(opening_meta, dict) else {},
        )
        # Unreviewed weak/bootstrap drafts are noise for meta until a human review exists
        # (or the thesis is non-weak). Eval may still archive them after repeated INSUFFICIENT_DATA.
        if weak and not thesis_has_human_review(detail):
            continue
        tags = opening_meta.get("tags") if isinstance(opening_meta, dict) else None
        bootstrap = isinstance(tags, list) and any(
            str(t).lower() in ("llm_draft", "moat", "weak_context") for t in tags
        )
        label_bits = []
        if weak:
            label_bits.append("WEAK CONTEXT")
        if bootstrap or weak:
            label_bits.append("bootstrap/llm_draft")
        flag = f" [{', '.join(label_bits)}]" if label_bits else ""

        parts.append(
            f"- {row.get('ticker')} | {row.get('disposition')}/{row.get('intent')} | "
            f"{_clip_meta(str(row.get('title') or ''), 120)}{flag}"
        )
        parts.append(f"  opening: {_clip_meta(opening_body, META_THESIS_OPENING_MAX)}")

        latest_review = next(
            (e for e in reversed(entries) if e.get("entry_kind") == "review"),
            None,
        )
        latest_llm = next(
            (e for e in reversed(entries) if e.get("entry_kind") == "llm_reply"),
            None,
        )
        if latest_review:
            parts.append(
                f"  latest_review: {_clip_meta(str(latest_review.get('body') or ''), META_THESIS_ENTRY_MAX)}"
            )
        if latest_llm:
            meta = _entry_metadata(latest_llm)
            verdict = meta.get("verdict")
            vbit = f" verdict={verdict}" if verdict else ""
            parts.append(
                f"  latest_llm_reply{vbit}: "
                f"{_clip_meta(str(latest_llm.get('body') or ''), META_THESIS_ENTRY_MAX)}"
            )
        included += 1

    if included == 0:
        return None
    return "\n".join(parts)


def ticker_has_recent_active_thesis(
    pg: Any,
    ticker: str,
    *,
    within_days: int = META_THESIS_RECENT_DAYS,
    now: datetime | None = None,
) -> bool:
    """True if an active thesis for ticker was updated within ``within_days``."""
    rows = list_theses(pg, ticker=ticker, include_archived=False, limit=5)
    if not rows:
        return False
    now_ts = now or datetime.now(UTC)
    cutoff_secs = max(1, within_days) * 86400.0
    for row in rows:
        updated = _parse_ts(row.get("updated_at")) or _parse_ts(row.get("created_at"))
        if updated is None:
            continue
        if (now_ts - updated).total_seconds() <= cutoff_secs:
            return True
    return False


ATTENTION_LLM_VERDICTS = frozenset({"TENSION", "STALE_THESIS"})


def list_theses_attention(
    pg: Any,
    *,
    soft_days: int = DEFAULT_SOFT_DUE_DAYS,
    hard_days: int = DEFAULT_HARD_STALE_DAYS,
    limit: int = 40,
    now: datetime | None = None,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Theses that need human attention: due/stale/weak and/or LLM TENSION/STALE_THESIS.

    Used by Today briefing and Ideas badges (ROADMAP §2.6 R2). Deduped by thesis id.
    Optional ``ticker`` filters in SQL (avoids false misses from a global top-N pool).
    """
    by_id: dict[str, dict[str, Any]] = {}
    ticker_norm = _normalize_ticker(ticker) if ticker else None

    for row in list_theses_due(
        pg,
        soft_days=soft_days,
        hard_days=hard_days,
        include_weak_always=True,
        limit=limit,
        now=now,
        ticker=ticker_norm,
    ):
        tid = str(row.get("id") or "")
        if not tid:
            continue
        reasons: list[str] = []
        if row.get("is_weak"):
            reasons.append("weak")
        rs = row.get("review_status")
        if rs:
            reasons.append(str(rs))
        row = dict(row)
        row["attention_reasons"] = reasons or ["due_for_review"]
        row["llm_verdict"] = row.get("llm_verdict")
        by_id[tid] = row

    tension_clauses = [
        "t.status = 'active'",
        "UPPER(COALESCE(ll.metadata->>'verdict', '')) IN ('TENSION', 'STALE_THESIS')",
    ]
    tension_params: list[Any] = []
    if ticker_norm:
        tension_clauses.append("t.ticker = %s")
        tension_params.append(ticker_norm)
    tension_params.append(max(1, min(limit, 100)))
    tension_where = " AND ".join(tension_clauses)
    try:
        tension_rows = pg.execute_query(
            f"""
            WITH latest_llm AS (
                SELECT DISTINCT ON (thesis_id)
                       thesis_id, body, metadata, created_at
                FROM thesis_entries
                WHERE entry_kind = 'llm_reply'
                ORDER BY thesis_id, created_at DESC
            )
            SELECT t.id, t.ticker, t.title, t.disposition, t.intent, t.status,
                   t.created_by, t.created_at, t.updated_at, t.last_reviewed_at,
                   ll.metadata AS llm_metadata,
                   ll.body AS llm_body,
                   UPPER(COALESCE(ll.metadata->>'verdict', '')) AS llm_verdict
            FROM ticker_theses t
            JOIN latest_llm ll ON ll.thesis_id = t.id
            WHERE {tension_where}
            ORDER BY ll.created_at DESC
            LIMIT %s
            """,
            tuple(tension_params),
        )
    except Exception as exc:
        logger.warning("list_theses_attention llm_reply scan failed: %s", exc)
        tension_rows = []

    for raw in tension_rows or []:
        row = _serialize_row(dict(raw))
        tid = str(row.get("id") or "")
        if not tid:
            continue
        verdict = str(row.get("llm_verdict") or "").upper()
        existing = by_id.get(tid)
        if existing:
            reasons = list(existing.get("attention_reasons") or [])
            if verdict and verdict not in reasons:
                reasons.append(verdict.lower())
            existing["attention_reasons"] = reasons
            existing["llm_verdict"] = verdict
            if row.get("llm_body") and not existing.get("llm_body"):
                existing["llm_body"] = row.get("llm_body")
            continue
        reviewed = thesis_checked_at(row)
        now_ts = now or datetime.now(UTC)
        age_days = None
        if reviewed is not None:
            age_days = round((now_ts - reviewed).total_seconds() / 86400.0, 1)
        weak = is_weak_thesis(title=str(row.get("title") or ""))
        reasons = [verdict.lower()] if verdict else ["tension"]
        if weak:
            reasons.insert(0, "weak")
        row["review_status"] = classify_due_status(
            reviewed, soft_days=soft_days, hard_days=hard_days, now=now_ts
        )
        row["is_weak"] = weak
        row["age_days"] = age_days
        row["attention_reasons"] = reasons
        by_id[tid] = row

    out = list(by_id.values())
    # Priority: tension/stale_thesis, then weak, then stale, then due; older first
    def _rank(r: dict[str, Any]) -> tuple[int, int, float]:
        reasons = {str(x).lower() for x in (r.get("attention_reasons") or [])}
        pri = 3
        if "tension" in reasons or "stale_thesis" in reasons:
            pri = 0
        elif "weak" in reasons:
            pri = 1
        elif "stale" in reasons:
            pri = 2
        return (pri, 0 if r.get("is_weak") else 1, -(r.get("age_days") or 0))

    out.sort(key=_rank)
    return out[: max(1, min(limit, 100))]


def thesis_attention_by_ticker(
    pg: Any,
    tickers: list[str],
    *,
    limit: int = 40,
) -> dict[str, list[dict[str, Any]]]:
    """Map UPPER ticker → attention thesis rows (for Ideas badges)."""
    wanted = {_normalize_ticker(t) for t in tickers if t and str(t).strip()}
    if not wanted:
        return {}
    # Per-ticker queries so a global top-N pool cannot hide a watched name.
    out: dict[str, list[dict[str, Any]]] = {}
    per_limit = max(1, min(limit, 20))
    for t in wanted:
        for row in list_theses_attention(pg, limit=per_limit, ticker=t):
            out.setdefault(t, []).append(
                {
                    "thesis_id": str(row.get("id")),
                    "title": row.get("title"),
                    "disposition": row.get("disposition"),
                    "intent": row.get("intent"),
                    "review_status": row.get("review_status"),
                    "llm_verdict": row.get("llm_verdict"),
                    "is_weak": bool(row.get("is_weak")),
                    "attention_reasons": row.get("attention_reasons") or [],
                }
            )
    return out
