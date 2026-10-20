## 2026-10-20 - Fix missing watchlist removals on trade edits/deletes
**Issue:** Modifying a trade (e.g. DELETE a trade or EDIT from BUY to SELL) to close a position failed to remove the ticker from the watchlist.
**Learning:** Only new `POST` trade submissions triggered the watchlist cleanup helper (`remove_closed_position_from_watchlist`), while `PUT` and `DELETE` paths updated the DB but skipped the cleanup contract.
**Prevention:** When adding side-effects to CRUD operations (like watchlist cleanup on position closure), apply them consistently across all endpoints (Create, Update, Delete) that can affect the underlying state.
