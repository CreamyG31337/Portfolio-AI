## 2026-07-23 - Watchlist upsert source overwrite logic bug
**Issue:** `upsert_watchlist_ticker` intended to preserve provenance (`source`) of ideas but unconditionally passed `source` to `supabase.table.upsert()`, which clobbered existing values on conflict.
**Learning:** Supabase `upsert` updates all provided keys on conflict. A comment warning not to do it is insufficient; the function itself must enforce it.
**Prevention:** If an upsert must preserve an existing column, perform a `select` first to fetch the original value and explicitly pass it back in the `upsert` payload.

## 2026-07-25 - AI Assistant session upsert clobbers created_at
**Issue:** `replace_messages` blindly updated `ai_assistant_chats` using `.upsert()`, which clobbers any fields (like `created_at`) not explicitly provided in the payload by resetting them to defaults (`now()`).
**Learning:** Supabase's `upsert` with `on_conflict` will overwrite all fields mapped in the DB if they aren't explicitly passed back to preserve them.
**Prevention:** If an upsert must preserve an existing column (like `created_at` or `source`), fetch the existing row first using a targeted `select().limit(1)` and inject the value back into the upsert payload.
## 2026-08-22 - Referee: fix stale thesis sort to use GREATEST instead of COALESCE
**Issue:** The stale thesis queue incorrectly bubbled up theses with recent human reviews if they had an older AI evaluation, because the SQL query used `COALESCE` instead of `GREATEST`.
**Learning:** `COALESCE` returns the first non-null value, so `COALESCE(latest_llm_reply, last_reviewed, created)` ignores a newer `last_reviewed` if `latest_llm_reply` exists.
**Prevention:** When querying for the most recent timestamp across multiple nullable columns in PostgreSQL, do not use `COALESCE`. Instead, use `GREATEST(...)` to accurately find the maximum value.
