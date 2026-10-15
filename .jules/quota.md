
## 2025-05-18 - Fix silent signal truncation in Confluence Service
**Bug:** `confluence_service.py` was silently dropping signal hits across the portfolio because its `limit(1000)` was a hard ceiling for an entire batch of tickers rather than per-ticker limit, permanently skipping the middle rows.
**Learning:** PostgREST default maximum rows is 1000. An explicit `limit(1000)` behaves exactly like an unbounded query and is vulnerable to silent data loss if the matched rows exceed 1000. It doesn't throw errors.
**Prevention:** Use `fetch_all_rows` from `supabase_pagination` for potentially unbounded filtered queries instead of one-shot limits.

## 2026-08-01 - LLM context caps misidentified as bugs
**Bug:** Agent hallucinated that intentional LLM context limits (`.limit(100)`, `.limit(50)`) and heavily parallelized safe chunks were "silent truncations".
**Learning:** Not every `.limit()` or chunked loop is a truncation bug. AI route builders explicitly use caps to protect context windows. `app.py`'s congress stats uses a parallelized ThreadPoolExecutor specifically tuned to 1000-row chunks for high performance aggregation where `fetch_all_rows` would sequentialize and bottleneck it.
**Prevention:** Verify if a limit is an intentional safety cap (like AI token budgets) or part of a carefully optimized parallel fetch mechanism before attempting to "fix" it by blindly dropping in `fetch_all_rows`. Stop and enforce the Empty-Result rule if no actual correctness bugs exist.

## 2026-10-06 - Replacing manual pagination with fetch_all_rows
**Bug:** Silent data truncation and missing portfolio/dividend history due to manual `.range()` pagination loops in Flask data utilities. The loops were vulnerable to PostgREST's hard 1000-row cap and arbitrary safety breaks (e.g. `offset > 50000`).
**Learning:** Manual `while True:` pagination is extremely fragile and repetitive. When a chunk hits exactly 1000 rows due to the server cap, `len(rows) < batch_size` conditions can incorrectly break early, or ranges can skip data.
**Prevention:** Always use the robust `fetch_all_rows` helper imported from `supabase_pagination` for unbound data reads instead of hand-rolling PostgREST `.range()` loops.
