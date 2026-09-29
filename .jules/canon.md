## 2026-07-22 - Cleanup Orphaned Alter Scripts
 **Learning:** When rolling up table schema updates (like adding columns), ad-hoc `alter_table.sql` scripts should not remain in the `database/schema/research/` modular schema root if the changes are already incorporated into the main `tables/` file. They cause clutter and aren't executed during a fresh boot.
 **Prevention:** Move orphaned ad-hoc migration or alter scripts to `database/archive/` once their changes have been consolidated into the canonical table definitions.

## 2026-09-29 - Check a path exists before "fixing" a doc link (PR #585 rejected)
**Learning:** #585 rewrote `database/migrations/` → `database/schema/supabase/migrations/` and `migrations/008_…` → `database/schema/research/migrations/008_…`. Both originals were correct: dated migrations still land in `database/migrations/`, `migrations/008_create_yt_sources.sql` exists at the repo root, and `database/schema/research/migrations/` does not exist.
**Prevention:** `git ls-files <path>` the new target before changing any doc path, and confirm where recent migrations actually go with `git log --name-only`.
