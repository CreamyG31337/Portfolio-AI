#!/usr/bin/env python3
"""Rebuild research DB embeddings for the configured embedding model.

This is intended for model/dimension migrations, for example moving from
``nomic-embed-text`` vector(768) to ``bge-m3`` vector(1024). It re-embeds rows
where ``embedding IS NULL`` across the three research DB tables that currently
store pgvector embeddings.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

current_dir = Path(__file__).resolve().parent
web_dashboard_path = current_dir.parent
project_root = web_dashboard_path.parent
for path in (str(project_root), str(web_dashboard_path)):
    if path not in sys.path:
        sys.path.insert(0, path)

load_dotenv(project_root / ".env")
load_dotenv(web_dashboard_path / ".env")

from model_registry import get_embed_dim, get_embed_max_chars, get_embed_model  # noqa: E402
from ollama_client import OllamaClient  # noqa: E402
from postgres_client import PostgresClient  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableSpec:
    name: str
    id_column: str
    title_expr: str
    content_expr: str
    order_expr: str


TABLES: dict[str, TableSpec] = {
    "newsletters": TableSpec(
        name="newsletters",
        id_column="id",
        title_expr="subject",
        content_expr="COALESCE(body_plain, body_html, '')",
        order_expr="received_at ASC",
    ),
    "research_articles": TableSpec(
        name="research_articles",
        id_column="id",
        title_expr="title",
        content_expr="COALESCE(content, summary, '')",
        order_expr="fetched_at DESC",
    ),
    "ticker_analysis": TableSpec(
        name="ticker_analysis",
        id_column="id",
        title_expr="ticker",
        content_expr="COALESCE(analysis_text, summary, '')",
        order_expr="updated_at DESC",
    ),
}


def _embedding_to_vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def _iter_pending_rows(client: PostgresClient, spec: TableSpec, limit: int | None) -> list[dict]:
    limit_sql = "LIMIT %s" if limit is not None else ""
    params: tuple[int, ...] = (limit,) if limit is not None else ()
    query = f"""
        SELECT
            {spec.id_column}::text AS id,
            {spec.title_expr} AS title,
            {spec.content_expr} AS content,
            length({spec.content_expr}) AS content_chars
        FROM {spec.name}
        WHERE embedding IS NULL
          AND length(trim({spec.content_expr})) > 0
        ORDER BY {spec.order_expr}
        {limit_sql}
    """
    return client.execute_query(query, params)


def _selected_tables(names: Iterable[str]) -> list[TableSpec]:
    specs: list[TableSpec] = []
    for name in names:
        if name == "all":
            return list(TABLES.values())
        if name not in TABLES:
            raise ValueError(f"Unknown table {name!r}; choose one of {', '.join(TABLES)}")
        specs.append(TABLES[name])
    return specs


def reembed(
    *,
    table_names: list[str],
    limit: int | None,
    sleep_seconds: float,
    dry_run: bool,
) -> int:
    client = PostgresClient()
    model = get_embed_model()
    expected_dim = get_embed_dim()
    max_chars = get_embed_max_chars()
    # Backfills can issue thousands of embedding calls. Force the configured
    # base URL directly so each call does not spend time checking per-model
    # system_settings overrides.
    ollama = OllamaClient(force_base_url_only=True)
    if not ollama.enabled:
        raise RuntimeError("Ollama client disabled")
    logger.info(
        "Re-embedding research vectors with model=%s expected_dim=%s max_chars=%s dry_run=%s",
        model,
        expected_dim,
        max_chars,
        dry_run,
    )

    total_success = 0
    total_failed = 0
    for spec in _selected_tables(table_names):
        rows = _iter_pending_rows(client, spec, limit)
        logger.info("Table %s: %d rows pending", spec.name, len(rows))
        for idx, row in enumerate(rows, start=1):
            row_id = str(row["id"])
            title = str(row.get("title") or "")[:80]
            content = str(row.get("content") or "")
            started = time.perf_counter()
            try:
                embedding = ollama.generate_embedding(content)
                duration_ms = int((time.perf_counter() - started) * 1000)
                if len(embedding) != expected_dim:
                    raise ValueError(f"embedding dim {len(embedding)} != expected {expected_dim}")
                if not dry_run:
                    update = f"UPDATE {spec.name} SET embedding = %s::vector WHERE {spec.id_column} = %s"
                    client.execute_update(update, (_embedding_to_vector_literal(embedding), row_id))
                total_success += 1
                logger.info(
                    "[%s %d/%d] embedded id=%s chars=%s dim=%s duration_ms=%s title=%r",
                    spec.name,
                    idx,
                    len(rows),
                    row_id,
                    row.get("content_chars"),
                    len(embedding),
                    duration_ms,
                    title,
                )
                if sleep_seconds:
                    time.sleep(sleep_seconds)
            except Exception as exc:
                total_failed += 1
                logger.error("[%s %d/%d] failed id=%s title=%r: %s", spec.name, idx, len(rows), row_id, title, exc)

    logger.info("Re-embed complete: success=%d failed=%d", total_success, total_failed)
    return 1 if total_failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tables",
        nargs="+",
        default=["all"],
        help="Tables to re-embed: all, newsletters, research_articles, ticker_analysis",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional per-table row limit")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between rows")
    parser.add_argument("--dry-run", action="store_true", help="Generate embeddings but do not update DB")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return reembed(
        table_names=args.tables,
        limit=args.limit,
        sleep_seconds=args.sleep,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
