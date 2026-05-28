"""Schema regression tests for scheduler step logging."""

from pathlib import Path


def test_job_steps_migration_creates_rls_protected_table() -> None:
    """log_job_step depends on this table existing in Supabase."""

    root = Path(__file__).resolve().parents[1]
    migration = root / "database" / "schema" / "supabase" / "migrations" / "create_job_steps.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.job_steps" in sql
    assert "ALTER TABLE public.job_steps ENABLE ROW LEVEL SECURITY" in sql
    assert "job_steps_service_role_full_access" in sql
