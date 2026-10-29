## 2026-07-23 - Watchlist upsert source overwrite logic bug
**Issue:** `upsert_watchlist_ticker` intended to preserve provenance (`source`) of ideas but unconditionally passed `source` to `supabase.table.upsert()`, which clobbered existing values on conflict.
**Learning:** Supabase `upsert` updates all provided keys on conflict. A comment warning not to do it is insufficient; the function itself must enforce it.
**Prevention:** If an upsert must preserve an existing column, perform a `select` first to fetch the original value and explicitly pass it back in the `upsert` payload.

## 2026-07-25 - AI Assistant session upsert clobbers created_at
**Issue:** `replace_messages` blindly updated `ai_assistant_chats` using `.upsert()`, which clobbers any fields (like `created_at`) not explicitly provided in the payload by resetting them to defaults (`now()`).
**Learning:** Supabase's `upsert` with `on_conflict` will overwrite all fields mapped in the DB if they aren't explicitly passed back to preserve them.
**Prevention:** If an upsert must preserve an existing column (like `created_at` or `source`), fetch the existing row first using a targeted `select().limit(1)` and inject the value back into the upsert payload.

## 2026-09-29 - No findings means no PR
**Issue:** Referee opened 17 empty "no reviewable commits" PRs (and one that only added a `dummy.py`) between Aug 18–30, burying the real ones.
**Prevention:** When there is nothing to fix, end the task without committing or opening a PR. Also search open PRs first — the thesis-sort fix below was filed four times (#573, #575, #588, #592).

## 2026-09-29 - Latest-of-several timestamps: GREATEST, not COALESCE
**Issue:** `list_theses_due` sorted by `COALESCE(latest_llm_reply_at, last_reviewed_at, created_at)`, which returns the first non-null value, so a newer human review was ignored once any AI reply existed.
**Prevention:** Use `GREATEST(...)` for "most recent of" across nullable columns (Postgres `GREATEST` skips NULLs). Use `COALESCE` only for "first available".
## 2026-10-20 - Negative shares cause incorrect net shares calculation on SELL
**Issue:** Short positions stored as negative shares in the database would be added instead of subtracted when calculating net shares (or evaluating if shares went down), resulting in double-negative math errors where selling a short position incorrectly increased net shares.
**Learning:** Raw db values representing shares could be negative (specifically for shorts). Checking `action == 'SELL'` and subtracting the raw value results in `-(-value) = +value`.
**Prevention:** When doing signed math on position sizes based on trade action (e.g. `return -qty if action == 'SELL' else qty`), always apply `abs()` to the raw DB value first.
