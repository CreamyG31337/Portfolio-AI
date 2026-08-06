
## 2025-05-18 - Fix silent signal truncation in Confluence Service
**Bug:** `confluence_service.py` was silently dropping signal hits across the portfolio because its `limit(1000)` was a hard ceiling for an entire batch of tickers rather than per-ticker limit, permanently skipping the middle rows.
**Learning:** PostgREST default maximum rows is 1000. An explicit `limit(1000)` behaves exactly like an unbounded query and is vulnerable to silent data loss if the matched rows exceed 1000. It doesn't throw errors.
**Prevention:** Use `fetch_all_rows` from `supabase_pagination` for potentially unbounded filtered queries instead of one-shot limits.

## 2026-08-01 - LLM context caps misidentified as bugs
**Bug:** Agent hallucinated that intentional LLM context limits (`.limit(100)`, `.limit(50)`) and heavily parallelized safe chunks were "silent truncations".
**Learning:** Not every `.limit()` or chunked loop is a truncation bug. AI route builders explicitly use caps to protect context windows. `app.py`'s congress stats uses a parallelized ThreadPoolExecutor specifically tuned to 1000-row chunks for high performance aggregation where `fetch_all_rows` would sequentialize and bottleneck it.
**Prevention:** Verify if a limit is an intentional safety cap (like AI token budgets) or part of a carefully optimized parallel fetch mechanism before attempting to "fix" it by blindly dropping in `fetch_all_rows`. Stop and enforce the Empty-Result rule if no actual correctness bugs exist.
