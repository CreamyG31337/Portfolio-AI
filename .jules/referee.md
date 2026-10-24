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
## 2026-10-20 - [Fix Watchlist Epsilon Math Bug]
 **Issue:** When checking if a financial position is completely closed to remove it from the watchlist, the net shares were being checked as `abs(net_shares) > _CLOSED_POSITION_EPSILON`. This incorrectly treated negative net shares (e.g., from overselling, shorting, or deleting a BUY) as active holdings instead of closed positions.
 **Learning:** In financial math, a net negative share balance logically means the original long position is closed. Wrapping the balance in `abs()` prevents these conditions from triggering cleanup logic.
 **Prevention:** Never use `abs()` when checking if net shares exceed a zero-bound epsilon threshold for long position closure.
## 2026-10-20 - [Short Positions are Open Positions]
**Issue:** Attempted to remove `abs()` from the closed-position epsilon check in `remove_closed_position_from_watchlist` because a memory file suggested negative shares logically mean the original long position is closed.
**Learning:** The memory was flawed. Short positions have negative shares, but they are *open* positions and must remain on the active watchlist. `abs(net_shares) > _CLOSED_POSITION_EPSILON` is the correct mathematical check for determining if *any* position (long or short) is active. The original code was correct; removing `abs()` introduces a bug where active short positions are erroneously removed.
**Prevention:** Always use `abs()` when checking net shares against a zero-bound epsilon to correctly handle short positions.
## 2026-10-20 - [API Contract Consistency (CRUD)]
**Issue:** `api_submit_trade` (POST) returned a `rebuild_reason` field so the UI could show a helpful toast ("backdated trade" vs "sell recorded"). However, `api_update_trade` (PUT) and `api_delete_trade` (DELETE) missed this field when they triggered the identical background rebuild logic, violating the CRUD contract consistency rule.
**Learning:** When one CRUD endpoint is enriched with UI-driving fields, related state-mutating endpoints must also carry those fields to ensure consistent frontend state and feedback.
**Prevention:** If adding UI-driving response fields (e.g. `rebuild_reason`, `watchlist_removed`) to a POST endpoint, consistently apply them to PUT/DELETE endpoints.
## 2026-10-20 - [API Contract Consistency (CRUD)]
**Issue:** `api_submit_trade` (POST) returned a `rebuild_reason` field so the UI could show a helpful toast ("backdated trade" vs "sell recorded"). However, `api_update_trade` (PUT) and `api_delete_trade` (DELETE) missed this field when they triggered the identical background rebuild logic, violating the CRUD contract consistency rule.
**Learning:** When one CRUD endpoint is enriched with UI-driving fields, related state-mutating endpoints must also carry those fields to ensure consistent frontend state and feedback.
**Prevention:** If adding UI-driving response fields (e.g. `rebuild_reason`, `watchlist_removed`) to a POST endpoint, consistently apply them to PUT/DELETE endpoints.
