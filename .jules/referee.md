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

## 2026-10-29 - Short position shares bug in watchlist cleanup
**Issue:** `_net_shares_from_trades` and `_tickers_with_fewer_shares` assumed `shares` from `trade_log` was always positive and used `act == 'SELL'` to deduct shares. However, short position SELL trades might have negative shares in the DB. This double-negative effectively increased net shares when it should have decreased them.
**Learning:** For signed math operations tracking net shares with explicit action fields, apply `abs()` to raw DB shares before evaluating the sign.
**Prevention:** Wrap `float(t.get('shares') or 0)` with `abs()` when checking position logic to correctly handle both positive and negative recorded shares.

## 2026-10-29 - Oversell epsilon and CRUD rebuild_reason parity
**Issue:** `abs(net_shares) > epsilon` treated oversold/negative nets as still held, so watchlist cleanup skipped. PUT/DELETE trade APIs also omitted `rebuild_reason` that POST already returned.
**Prevention:** Compare signed net shares to epsilon (no abs). Keep rebuild_reason on create/update/delete responses.

## 2026-10-29 - Short position support does not exist
**Issue:** I attempted to restore `abs()` around negative net shares because I assumed short positions were supported and should remain active on the watchlist. However, the app has no short-position support (no entry path or handling). Negative net shares only occur from an oversell or a deleted BUY, meaning the long is closed.
**Learning:** Do not blindly assume short position support. If an inline comment explicitly states that negative net means a closed long (oversell/deleted BUY), respect that domain knowledge. Restoring `abs()` incorrectly keeps these closed positions on the watchlist.
**Prevention:** Do not restore `abs()` on net share checks. Read inline comments carefully before reversing domain-specific logic.
