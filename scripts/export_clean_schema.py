"""
Export modular SQL schema snapshots from live databases.

Writes one file per object under database/schema/{supabase,research}/.

Safety / fidelity (why the previous exporter was noisy)
-------------------------------------------------------
- LF-only line endings via write_bytes (Path.write_text on Windows uses CRLF).
- Table DDL uses pg_catalog: format_type, CHECK via pg_get_constraintdef,
  full indexdef (partial predicates + DESC), and relrowsecurity for RLS.
- Skips ephemeral objects: names containing ``_backup_``, ``_deprecated_*``.
- Skips extension-owned functions/types (e.g. pgvector) to avoid churn.
- Skips known utility RPCs (``execute_sql``) that are not app schema.
- ``_init_schema.sql`` is left untouched by default so curated GRANTS / RLS
  notes are never wiped. Pass ``--update-init`` to append-only merge new
  ``\\i`` includes while preserving any curated footer (lines from the first
  ``-- RLS tightening``, ``-- GRANTS``, or ``-- CURATED`` marker onward).

Usage
-----
    .\\venv\\Scripts\\Activate.ps1
    python scripts/export_clean_schema.py
    python scripts/export_clean_schema.py --dry-run
    python scripts/export_clean_schema.py --update-init
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Utility RPCs / one-offs that exist in prod but are not part of the app schema.
SKIP_FUNCTION_NAMES = frozenset(
    {
        "execute_sql",
    }
)

# Curated footer markers in _init_schema.sql (do not regenerate past these).
CURATED_SECTION_RE = re.compile(
    r"^--\s+(RLS tightening|GRANTS|CURATED)\b",
    re.MULTILINE | re.IGNORECASE,
)

SECTION_HEADER_RE = re.compile(r"^--\s+(TYPES|SEQUENCES|TABLES|FUNCTIONS|VIEWS|TRIGGERS|POLICIES)\s*$")
INCLUDE_RE = re.compile(r"^\\i\s+(\w+)/(.+\.sql)\s*$")

SUBDIRS = ("types", "sequences", "tables", "functions", "views", "triggers", "policies")


def should_skip_object(name: str, kind: str = "table") -> bool:
    """Return True for ephemeral, deprecated, or explicitly excluded objects."""
    if not name:
        return True
    lower = name.lower()
    if "_backup_" in lower:
        return True
    if lower.startswith("_deprecated_") or lower.startswith("deprecated_"):
        return True
    if kind == "function" and lower in SKIP_FUNCTION_NAMES:
        return True
    return False


def normalize_sql_text(content: str) -> str:
    """Normalize to LF endings and ensure a trailing newline."""
    text_out = content.replace("\r\n", "\n").replace("\r", "\n")
    if not text_out.endswith("\n"):
        text_out += "\n"
    return text_out


def write_sql_file(path: Path, content: str, *, dry_run: bool = False) -> None:
    """Write SQL with LF line endings (no Windows CRLF translation)."""
    payload = normalize_sql_text(content).encode("utf-8")
    if dry_run:
        print(f"    [dry-run] would write {path} ({len(payload)} bytes)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def split_init_schema(content: str) -> tuple[str, str]:
    """Split _init_schema into (managed_prefix, curated_suffix)."""
    match = CURATED_SECTION_RE.search(content)
    if not match:
        return content, ""
    return content[: match.start()], content[match.start() :]


def normalize_indexdef(indexdef: str) -> str:
    """Clean pg_indexes.indexdef toward hand-curated style (no schema, no USING btree)."""
    cleaned = indexdef.strip()
    if not cleaned.endswith(";"):
        cleaned += ";"
    cleaned = re.sub(r"\bON\s+public\.", "ON ", cleaned, count=1, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+USING\s+btree\b", "", cleaned, count=1, flags=re.IGNORECASE)
    # Drop noisy casts often injected by pg_get_expr in WHERE clauses when safe-ish:
    # leave WHERE as-is from Postgres — predicates matter more than cast cosmetics.
    return cleaned


def is_primary_key_index(index_name: str, indexdef: str) -> bool:
    if index_name.endswith("_pkey"):
        return True
    return bool(re.search(r"\bPRIMARY\s+KEY\b", indexdef, re.IGNORECASE))


def format_check_constraint(conname: str, constraintdef: str) -> str:
    """Build ``CONSTRAINT name CHECK (...)`` from pg_get_constraintdef output."""
    definition = constraintdef.strip()
    if definition.upper().startswith("CONSTRAINT "):
        return definition
    return f"CONSTRAINT {conname} {definition}"


def format_pg_type(data_type: str) -> str:
    """Normalize format_type output toward existing schema file spelling."""
    type_sql = data_type.strip()
    # Keep timezone fidelity (old exporter collapsed these to TIMESTAMP).
    type_sql = re.sub(
        r"\btimestamp\s+with\s+time\s+zone\b",
        "TIMESTAMP WITH TIME ZONE",
        type_sql,
        flags=re.IGNORECASE,
    )
    type_sql = re.sub(
        r"\btimestamp\s+without\s+time\s+zone\b",
        "TIMESTAMP",
        type_sql,
        flags=re.IGNORECASE,
    )
    type_sql = re.sub(r"\bdouble precision\b", "DOUBLE PRECISION", type_sql, flags=re.IGNORECASE)
    type_sql = re.sub(r"\bcharacter varying\b", "VARCHAR", type_sql, flags=re.IGNORECASE)
    # VARCHAR(n) from character varying(n) already handled; bare "character varying" -> VARCHAR
    type_sql = re.sub(r"\bboolean\b", "BOOLEAN", type_sql, flags=re.IGNORECASE)
    type_sql = re.sub(r"\buuid\b", "UUID", type_sql, flags=re.IGNORECASE)
    type_sql = re.sub(r"\bjsonb\b", "JSONB", type_sql, flags=re.IGNORECASE)
    type_sql = re.sub(r"\btext\b", "TEXT", type_sql, flags=re.IGNORECASE)
    type_sql = re.sub(r"\binteger\b", "INTEGER", type_sql, flags=re.IGNORECASE)
    type_sql = re.sub(r"\bbigint\b", "BIGINT", type_sql, flags=re.IGNORECASE)
    # Arrays: character varying(40)[] already becomes VARCHAR(40)[] via the varying sub.
    return type_sql


def format_column_line(
    col_name: str,
    data_type: str,
    not_null: bool,
    default: Optional[str],
) -> str:
    """Format one column DDL line with PG format_type output preserved."""
    type_sql = format_pg_type(data_type)
    nullable = " NOT NULL" if not_null else ""
    default_sql = f" DEFAULT {default}" if default else ""
    return f"    {col_name} {type_sql}{nullable}{default_sql}"


def build_table_sql(
    table_name: str,
    columns: list[dict[str, Any]],
    primary_key_cols: list[str],
    check_constraints: list[tuple[str, str]],
    foreign_keys: list[dict[str, Any]],
    index_defs: list[str],
    rls_enabled: bool,
) -> str:
    """Assemble modular table SQL matching existing hand-curated structure."""
    lines: list[str] = [
        f"-- Table: {table_name}",
        f"DROP TABLE IF EXISTS {table_name} CASCADE;",
        "",
        f"CREATE TABLE {table_name} (",
    ]

    col_lines = [
        format_column_line(
            c["name"],
            c["type"],
            bool(c.get("not_null")),
            c.get("default"),
        )
        for c in columns
    ]

    table_constraints: list[str] = []
    if primary_key_cols:
        table_constraints.append(f"    PRIMARY KEY ({', '.join(primary_key_cols)})")
    for conname, condef in check_constraints:
        table_constraints.append(f"    {format_check_constraint(conname, condef)}")

    body_parts = col_lines + table_constraints
    # Join with commas between all body parts
    for i, part in enumerate(body_parts):
        suffix = "," if i < len(body_parts) - 1 else ""
        lines.append(f"{part}{suffix}")

    lines.append(");")
    lines.append("")

    if rls_enabled:
        lines.append(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
        lines.append("")

    if foreign_keys:
        lines.append("-- Foreign Keys")
        for fk in foreign_keys:
            fk_name = fk.get("name") or (
                f"fk_{table_name}_{'_'.join(fk['constrained_columns'])}"
            )
            on_delete = f" ON DELETE {fk['ondelete']}" if fk.get("ondelete") else ""
            on_update = f" ON UPDATE {fk['onupdate']}" if fk.get("onupdate") else ""
            lines.append(
                f"ALTER TABLE {table_name} ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY ({', '.join(fk['constrained_columns'])}) "
                f"REFERENCES {fk['referred_table']}({', '.join(fk['referred_columns'])})"
                f"{on_delete}{on_update};"
            )
        lines.append("")

    if index_defs:
        lines.append("-- Indexes")
        for indexdef in index_defs:
            lines.append(normalize_indexdef(indexdef))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_init_includes(managed_prefix: str) -> dict[str, list[str]]:
    """Parse existing \\i includes from the managed portion of _init_schema.sql."""
    includes: dict[str, list[str]] = {subdir: [] for subdir in SUBDIRS}
    for line in managed_prefix.splitlines():
        match = INCLUDE_RE.match(line.strip())
        if not match:
            continue
        subdir, filename = match.group(1), match.group(2)
        if subdir in includes and filename not in includes[subdir]:
            includes[subdir].append(filename)
    return includes


def merge_init_includes(
    existing_content: str,
    discovered: dict[str, list[str]],
) -> str:
    """
    Append-only merge of new object includes into _init_schema.sql.

    - Preserves existing \\i order within each section.
    - Appends newly discovered filenames at the end of each section.
    - Preserves curated footer (RLS tightening / GRANTS / CURATED).
    - Does not refresh the Generated timestamp (avoids needless churn).
    """
    managed, curated = split_init_schema(existing_content)
    existing = parse_init_includes(managed)

    merged: dict[str, list[str]] = {}
    for subdir in SUBDIRS:
        prior = list(existing.get(subdir, []))
        for name in discovered.get(subdir, []):
            if name not in prior:
                prior.append(name)
        merged[subdir] = prior

    # Rebuild managed section from existing text structure when possible:
    # replace each -- SECTION block's includes while keeping surrounding comments.
    lines = managed.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        header = SECTION_HEADER_RE.match(line.strip())
        if not header:
            out.append(line)
            i += 1
            continue

        section = header.group(1).lower()
        out.append(line)
        i += 1
        # Skip old include lines for this section
        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped:
                break
            if SECTION_HEADER_RE.match(stripped) or CURATED_SECTION_RE.match(stripped):
                break
            if INCLUDE_RE.match(stripped):
                i += 1
                continue
            # Non-include content inside a section (rare) — keep it
            break

        for filename in merged.get(section, []):
            out.append(f"\\i {section}/{filename}")
        # Ensure a blank line after the section if the next kept line isn't blank
        if i < len(lines) and lines[i].strip() != "":
            out.append("")
        elif i >= len(lines):
            out.append("")

    managed_out = "\n".join(out).rstrip() + "\n"
    if curated:
        if not managed_out.endswith("\n\n"):
            managed_out = managed_out.rstrip("\n") + "\n\n"
        return managed_out + curated.lstrip("\n")
    return managed_out


def list_sql_filenames(folder: Path) -> list[str]:
    if not folder.exists():
        return []
    return sorted(p.name for p in folder.glob("*.sql"))


def get_pg_definition(
    engine: Engine,
    query: str,
    folder: Path,
    filename_formatter: Callable[[str], str],
    *,
    kind: str = "object",
    dry_run: bool = False,
    name_filter: Optional[Callable[[str], bool]] = None,
) -> int:
    """Fetch definitions from pg_catalog and save to files."""
    try:
        with engine.connect() as conn:
            results = conn.execute(text(query)).fetchall()
            written = 0
            if results:
                folder.mkdir(parents=True, exist_ok=True)
                for row in results:
                    name = row[0]
                    definition = row[1]
                    if should_skip_object(str(name), kind=kind):
                        continue
                    if name_filter is not None and not name_filter(str(name)):
                        continue
                    if not definition.strip().endswith(";"):
                        definition = definition.strip() + ";"
                    file_path = folder / filename_formatter(str(name))
                    write_sql_file(file_path, definition, dry_run=dry_run)
                    written += 1
            return written
    except Exception as exc:  # noqa: BLE001 - surface export errors, continue other DBs
        print(f"    [ERROR] Failed to fetch definitions for {folder.name}: {exc}")
        return 0


def _fetch_table_columns(conn: Any, table_name: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT a.attname AS name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                   a.attnotnull AS not_null,
                   pg_get_expr(ad.adbin, ad.adrelid) AS col_default
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attrdef ad
              ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
            WHERE n.nspname = 'public'
              AND c.relname = :table_name
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    return [
        {
            "name": r.name,
            "type": r.data_type,
            "not_null": bool(r.not_null),
            "default": r.col_default,
        }
        for r in rows
    ]


def _fetch_primary_key(conn: Any, table_name: str) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
            WHERE n.nspname = 'public'
              AND c.relname = :table_name
              AND i.indisprimary
            ORDER BY k.ord
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    return [r[0] for r in rows]


def _fetch_check_constraints(conn: Any, table_name: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        text(
            """
            SELECT con.conname, pg_get_constraintdef(con.oid) AS constraintdef
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = :table_name
              AND con.contype = 'c'
            ORDER BY con.conname
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    return [(r.conname, r.constraintdef) for r in rows]


def _fetch_foreign_keys(conn: Any, table_name: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT con.conname,
                   pg_get_constraintdef(con.oid) AS constraintdef
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = :table_name
              AND con.contype = 'f'
            ORDER BY con.conname
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    # Keep ALTER TABLE style via full constraintdef for fidelity.
    return [
        {"_raw_name": r.conname, "_raw_def": r.constraintdef}
        for r in rows
    ]


def _fetch_index_defs(conn: Any, table_name: str) -> list[str]:
    rows = conn.execute(
        text(
            """
            SELECT i.relname AS index_name,
                   pg_get_indexdef(i.oid) AS indexdef
            FROM pg_index ix
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public'
              AND t.relname = :table_name
              AND NOT ix.indisprimary
            ORDER BY i.relname
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    out: list[str] = []
    for r in rows:
        if is_primary_key_index(r.index_name, r.indexdef):
            continue
        out.append(r.indexdef)
    return out


def _fetch_rls_enabled(conn: Any, table_name: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT c.relrowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = :table_name
            """
        ),
        {"table_name": table_name},
    ).fetchone()
    return bool(row and row[0])


def export_table(conn: Any, table_dir: Path, table_name: str, *, dry_run: bool) -> None:
    columns = _fetch_table_columns(conn, table_name)
    pk_cols = _fetch_primary_key(conn, table_name)
    checks = _fetch_check_constraints(conn, table_name)
    raw_fks = _fetch_foreign_keys(conn, table_name)
    index_defs = _fetch_index_defs(conn, table_name)
    rls_enabled = _fetch_rls_enabled(conn, table_name)

    # Emit FKs as ALTER TABLE ... ADD CONSTRAINT <pg_get_constraintdef>
    # pg_get_constraintdef for FK returns: FOREIGN KEY (...) REFERENCES ...
    foreign_keys: list[dict[str, Any]] = []
    fk_alter_lines: list[str] = []
    for fk in raw_fks:
        fk_alter_lines.append(
            f"ALTER TABLE {table_name} ADD CONSTRAINT {fk['_raw_name']} {fk['_raw_def']};"
        )

    sql = build_table_sql(
        table_name=table_name,
        columns=columns,
        primary_key_cols=pk_cols,
        check_constraints=checks,
        foreign_keys=foreign_keys,  # handled below for raw fidelity
        index_defs=index_defs,
        rls_enabled=rls_enabled,
    )

    if fk_alter_lines:
        # Insert FK block before indexes (or at end if no indexes)
        parts = sql.rstrip().split("\n")
        insert_at = len(parts)
        for idx, line in enumerate(parts):
            if line.strip() == "-- Indexes":
                insert_at = idx
                break
        fk_block = ["-- Foreign Keys", *fk_alter_lines, ""]
        parts = parts[:insert_at] + fk_block + parts[insert_at:]
        sql = "\n".join(parts).rstrip() + "\n"

    write_sql_file(table_dir / f"{table_name}.sql", sql, dry_run=dry_run)


def export_complete_schema(
    db_url: str,
    schema_dir: Path,
    db_name: str,
    *,
    dry_run: bool = False,
    update_init: bool = False,
) -> bool:
    """Export all database objects into a modular structure."""
    print(f"[*] Generating complete schema for {db_name}...")

    try:
        engine = create_engine(db_url)

        # 1. TYPES (Enums only; skip extension-owned)
        print("    Exporting custom types...")
        type_query = """
            SELECT t.typname,
                   'CREATE TYPE ' || t.typname || ' AS ENUM (' ||
                   string_agg('''' || e.enumlabel || '''', ', ' ORDER BY e.enumsortorder) || ')'
            FROM pg_type t
            JOIN pg_enum e ON t.oid = e.enumtypid
            JOIN pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = 'public'
              AND NOT EXISTS (
                  SELECT 1 FROM pg_depend d
                  JOIN pg_extension ext ON d.refobjid = ext.oid
                  WHERE d.objid = t.oid AND d.deptype = 'e'
              )
            GROUP BY t.typname
            ORDER BY t.typname;
        """
        type_count = get_pg_definition(
            engine,
            type_query,
            schema_dir / "types",
            lambda name: f"{name}.sql",
            kind="type",
            dry_run=dry_run,
        )
        print(f"    Exported {type_count} custom types")

        # 2. SEQUENCES
        print("    Exporting sequences...")
        seq_query = """
            SELECT c.relname, 'CREATE SEQUENCE ' || c.relname || ';'
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public' AND c.relkind = 'S'
            ORDER BY c.relname;
        """
        seq_count = get_pg_definition(
            engine,
            seq_query,
            schema_dir / "sequences",
            lambda name: f"{name}.sql",
            kind="sequence",
            dry_run=dry_run,
        )
        print(f"    Exported {seq_count} sequences")

        # 3. TABLES
        table_dir = schema_dir / "tables"
        table_dir.mkdir(parents=True, exist_ok=True)
        with engine.connect() as conn:
            table_names = [
                r[0]
                for r in conn.execute(
                    text(
                        """
                        SELECT c.relname
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public'
                          AND c.relkind = 'r'
                        ORDER BY c.relname
                        """
                    )
                ).fetchall()
            ]
            table_names = [t for t in table_names if not should_skip_object(t, kind="table")]
            print(f"    Found {len(table_names)} tables (after filters)")
            for table_name in table_names:
                export_table(conn, table_dir, table_name, dry_run=dry_run)

        # 4. VIEWS
        print("    Exporting views...")
        view_query = """
            SELECT viewname,
                   'CREATE OR REPLACE VIEW ' || viewname || ' AS ' || definition
            FROM pg_views
            WHERE schemaname = 'public'
            ORDER BY viewname;
        """
        view_count = get_pg_definition(
            engine,
            view_query,
            schema_dir / "views",
            lambda name: f"{name}.sql",
            kind="view",
            dry_run=dry_run,
        )
        print(f"    Exported {view_count} views")

        # 5. FUNCTIONS (exclude aggregates + extension-owned + utility RPCs)
        print("    Exporting functions...")
        func_query = """
            SELECT p.proname, pg_get_functiondef(p.oid)
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = 'public'
              AND p.prokind != 'a'
              AND NOT EXISTS (
                  SELECT 1 FROM pg_depend d
                  JOIN pg_extension ext ON d.refobjid = ext.oid
                  WHERE d.objid = p.oid AND d.deptype = 'e'
              )
            ORDER BY p.proname;
        """
        func_count = get_pg_definition(
            engine,
            func_query,
            schema_dir / "functions",
            lambda name: f"{name}.sql",
            kind="function",
            dry_run=dry_run,
        )
        print(f"    Exported {func_count} functions")

        # 6. TRIGGERS
        print("    Exporting triggers...")
        trigger_query = """
            SELECT t.tgname, pg_get_triggerdef(t.oid)
            FROM pg_trigger t
            JOIN pg_class c ON t.tgrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public' AND NOT t.tgisinternal
            ORDER BY t.tgname;
        """
        trigger_count = get_pg_definition(
            engine,
            trigger_query,
            schema_dir / "triggers",
            lambda name: f"{name}.sql",
            kind="trigger",
            dry_run=dry_run,
        )
        print(f"    Exported {trigger_count} triggers")

        # 7. RLS POLICIES
        print("    Exporting RLS policies...")
        policy_query = """
            SELECT tablename, policyname,
                   'CREATE POLICY "' || policyname || '" ON "' || tablename || '" FOR ' || cmd ||
                   ' TO ' || array_to_string(roles, ', ') ||
                   CASE WHEN qual IS NOT NULL THEN ' USING (' || qual || ')' ELSE '' END ||
                   CASE WHEN with_check IS NOT NULL THEN ' WITH CHECK (' || with_check || ')' ELSE '' END
                   AS definition
            FROM pg_policies
            WHERE schemaname = 'public'
            ORDER BY tablename, policyname;
        """
        policy_count = 0
        with engine.connect() as conn:
            policies = conn.execute(text(policy_query)).fetchall()
            if policies:
                pol_dir = schema_dir / "policies"
                pol_dir.mkdir(parents=True, exist_ok=True)
                for row in policies:
                    table_name, pol_name, definition = row
                    if should_skip_object(str(table_name), kind="table"):
                        continue
                    write_sql_file(
                        pol_dir / f"{table_name}_{pol_name}.sql",
                        definition + ";",
                        dry_run=dry_run,
                    )
                    policy_count += 1
        print(f"    Exported {policy_count} policies")

        # 8. MASTER INIT — preserve by default
        init_path = schema_dir / "_init_schema.sql"
        kind_by_subdir = {
            "types": "type",
            "sequences": "sequence",
            "tables": "table",
            "functions": "function",
            "views": "view",
            "triggers": "trigger",
            "policies": "policy",
        }
        discovered = {
            subdir: [
                name
                for name in list_sql_filenames(schema_dir / subdir)
                if not should_skip_object(Path(name).stem, kind=kind_by_subdir[subdir])
            ]
            for subdir in SUBDIRS
        }

        if update_init:
            if init_path.exists():
                existing = init_path.read_text(encoding="utf-8")
                merged = merge_init_includes(existing, discovered)
                write_sql_file(init_path, merged, dry_run=dry_run)
                print("    Updated _init_schema.sql (append-only merge, curated footer preserved)")
            else:
                print("    [WARN] _init_schema.sql missing; not creating wholesale (use manual seed)")
        else:
            if init_path.exists():
                existing = init_path.read_text(encoding="utf-8")
                managed, _curated = split_init_schema(existing)
                current = parse_init_includes(managed)
                new_objects: list[str] = []
                for subdir, names in discovered.items():
                    for name in names:
                        if name not in current.get(subdir, []):
                            new_objects.append(f"{subdir}/{name}")
                if new_objects:
                    print("    [NOTE] _init_schema.sql left unchanged. New objects not listed:")
                    for obj in new_objects[:30]:
                        print(f"           - {obj}")
                    if len(new_objects) > 30:
                        print(f"           ... and {len(new_objects) - 30} more")
                    print("           Re-run with --update-init to append them.")
                else:
                    print("    _init_schema.sql left unchanged (no new includes detected)")
            else:
                print("    [NOTE] _init_schema.sql missing and --update-init not set; skipped")

        engine.dispose()
        return True

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Export failed: {exc}")
        import traceback

        traceback.print_exc()
        return False


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export clean modular SQL schema from live DBs.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print files that would be written without modifying the tree.",
    )
    parser.add_argument(
        "--update-init",
        action="store_true",
        help=(
            "Append new \\i includes into _init_schema.sql while preserving curated "
            "footer sections (-- RLS tightening / -- GRANTS / -- CURATED). "
            "Default leaves _init_schema.sql untouched."
        ),
    )
    parser.add_argument(
        "--db",
        choices=("supabase", "research", "all"),
        default="all",
        help="Which database schema tree to export (default: all).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    from dotenv import load_dotenv

    env_file = Path(__file__).parent.parent / "web_dashboard" / ".env"
    load_dotenv(env_file)
    schema_base = Path(__file__).parent.parent / "database" / "schema"

    targets = [
        {"name": "Supabase Production", "env": "SUPABASE_DATABASE_URL", "folder": "supabase"},
        {"name": "Research Database", "env": "RESEARCH_DATABASE_URL", "folder": "research"},
    ]
    if args.db != "all":
        targets = [t for t in targets if t["folder"] == args.db]

    ok = True
    for db in targets:
        url = os.getenv(db["env"])
        if not url:
            print(f"[WARN] {db['env']} not set; skipping {db['name']}")
            continue
        if not export_complete_schema(
            url,
            schema_base / db["folder"],
            db["name"],
            dry_run=args.dry_run,
            update_init=args.update_init,
        ):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
