"""Unit tests for scripts/export_clean_schema.py helpers (no live DB required)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_clean_schema.py"


def _load_exporter():
    spec = importlib.util.spec_from_file_location("export_clean_schema", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def exp():
    return _load_exporter()


def test_should_skip_backup_and_deprecated(exp):
    assert exp.should_skip_object("congress_trades_backup_20260717_prescrape") is True
    assert exp.should_skip_object("_deprecated_ui_ai_summary_20260520") is True
    assert exp.should_skip_object("deprecated_old_thing") is True
    assert exp.should_skip_object("ai_task_queue") is False
    assert exp.should_skip_object("congress_trades") is False


def test_should_skip_utility_rpc(exp):
    assert exp.should_skip_object("execute_sql", kind="function") is True
    assert exp.should_skip_object("execute_sql", kind="table") is False
    assert exp.should_skip_object("lease_ai_task", kind="function") is False


def test_write_sql_file_uses_lf(exp, tmp_path: Path):
    path = tmp_path / "sample.sql"
    exp.write_sql_file(path, "CREATE TABLE t (\r\n  id INT\r\n);")
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    assert raw == b"CREATE TABLE t (\n  id INT\n);\n"


def test_normalize_indexdef_strips_public_and_btree(exp):
    raw = (
        "CREATE INDEX ai_task_queue_pending_idx ON public.ai_task_queue "
        "USING btree (status, priority DESC, created_at) WHERE (status = 'pending')"
    )
    cleaned = exp.normalize_indexdef(raw)
    assert "public." not in cleaned
    assert "USING btree" not in cleaned.lower()
    assert "priority DESC" in cleaned
    assert "WHERE" in cleaned
    assert cleaned.endswith(";")


def test_format_check_constraint(exp):
    assert (
        exp.format_check_constraint("ai_task_queue_attempts_nonnegative", "CHECK ((attempts >= 0))")
        == "CONSTRAINT ai_task_queue_attempts_nonnegative CHECK ((attempts >= 0))"
    )
    already = "CONSTRAINT x CHECK (y > 0)"
    assert exp.format_check_constraint("x", already) == already


def test_format_pg_type_preserves_timestamptz(exp):
    assert exp.format_pg_type("timestamp with time zone") == "TIMESTAMP WITH TIME ZONE"
    assert exp.format_pg_type("timestamp without time zone") == "TIMESTAMP"
    assert exp.format_pg_type("character varying(40)") == "VARCHAR(40)"
    assert exp.format_pg_type("character varying(40)[]") == "VARCHAR(40)[]"


def test_is_primary_key_index(exp):
    assert exp.is_primary_key_index("ai_task_queue_pkey", "CREATE UNIQUE INDEX ...") is True
    assert (
        exp.is_primary_key_index(
            "some_constraint",
            "CREATE UNIQUE INDEX some_constraint ON t (id) PRIMARY KEY",
        )
        is True
    )
    assert exp.is_primary_key_index("ai_task_queue_pending_idx", "CREATE INDEX ...") is False


def test_build_table_sql_type_and_constraint_fidelity(exp):
    sql = exp.build_table_sql(
        table_name="ai_task_queue",
        columns=[
            {
                "name": "id",
                "type": "uuid",
                "not_null": True,
                "default": "gen_random_uuid()",
            },
            {
                "name": "status",
                "type": "character varying(20)",
                "not_null": True,
                "default": "'pending'::character varying",
            },
            {
                "name": "leased_until",
                "type": "timestamp with time zone",
                "not_null": False,
                "default": None,
            },
            {
                "name": "attempts",
                "type": "integer",
                "not_null": True,
                "default": "0",
            },
        ],
        primary_key_cols=["id"],
        check_constraints=[
            ("ai_task_queue_attempts_nonnegative", "CHECK ((attempts >= 0))"),
            (
                "ai_task_queue_status_check",
                "CHECK ((status)::text = ANY (ARRAY['pending'::text, 'leased'::text]))",
            ),
        ],
        foreign_keys=[],
        index_defs=[
            "CREATE INDEX ai_task_queue_pending_idx ON public.ai_task_queue "
            "USING btree (status, priority DESC, created_at) WHERE (status = 'pending')",
        ],
        rls_enabled=True,
    )
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "VARCHAR(20)" in sql
    assert "CONSTRAINT ai_task_queue_attempts_nonnegative CHECK" in sql
    assert "CONSTRAINT ai_task_queue_status_check CHECK" in sql
    assert "ALTER TABLE ai_task_queue ENABLE ROW LEVEL SECURITY;" in sql
    assert "priority DESC" in sql
    assert "WHERE (status = 'pending')" in sql
    assert "public." not in sql.split("-- Indexes", 1)[-1]


def test_split_and_merge_init_preserves_curated_footer(exp):
    existing = """-- Master Init Schema
-- Generated: 2026-02-09 18:51:34

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- TABLES
\\i tables/ai_task_queue.sql
\\i tables/congress_trades.sql

-- FUNCTIONS
\\i functions/lease_ai_task.sql

-- RLS tightening (2026-05-20): see docs/RLS_AUDIT_PHASE0.md
\\i policies/ai_analysis_queue_Allow service role full access.sql

-- GRANTS (2026-05-20): close view + SECURITY DEFINER function bypasses.
REVOKE SELECT ON public.congress_trades_enriched FROM anon;
"""
    managed, curated = exp.split_init_schema(existing)
    assert "RLS tightening" not in managed
    assert curated.startswith("-- RLS tightening")
    assert "REVOKE SELECT" in curated

    merged = exp.merge_init_includes(
        existing,
        {
            "tables": ["ai_task_queue.sql", "congress_trades.sql", "job_steps.sql"],
            "functions": ["lease_ai_task.sql", "heartbeat_ai_task.sql"],
            "types": [],
            "sequences": [],
            "views": [],
            "triggers": [],
            "policies": [],
        },
    )
    assert "-- Generated: 2026-02-09 18:51:34" in merged
    assert "\\i tables/job_steps.sql" in merged
    assert "\\i functions/heartbeat_ai_task.sql" in merged
    assert merged.index("\\i tables/ai_task_queue.sql") < merged.index(
        "\\i tables/congress_trades.sql"
    )
    assert merged.index("\\i tables/congress_trades.sql") < merged.index(
        "\\i tables/job_steps.sql"
    )
    assert "-- RLS tightening" in merged
    assert "REVOKE SELECT ON public.congress_trades_enriched FROM anon;" in merged
    assert merged.count("-- RLS tightening") == 1


def test_merge_init_does_not_duplicate_includes(exp):
    existing = """-- TABLES
\\i tables/ai_task_queue.sql

-- CURATED
-- keep me
"""
    merged = exp.merge_init_includes(
        existing,
        {
            "tables": ["ai_task_queue.sql"],
            "functions": [],
            "types": [],
            "sequences": [],
            "views": [],
            "triggers": [],
            "policies": [],
        },
    )
    assert merged.count("\\i tables/ai_task_queue.sql") == 1
    assert "-- CURATED" in merged
    assert "-- keep me" in merged
