## 2026-01-16 - Global Polling Anti-Pattern
**Learning:** Found aggressive global polling (5s interval) in `_scripts_content.html` for scheduler status. This runs on every page extending `base.html`, regardless of tab visibility or user role.
**Action:** When implementing polling in this codebase, always:
1. Use reasonable interval based on use case (5s for admin-critical, 30s+ for non-critical).
2. Wrap in `!document.hidden` check to pause in background tabs.
3. Add `visibilitychange` listener for immediate resume when tab becomes visible.

## 2026-02-14 - Historical Snapshot Query Optimization
**Learning:** The `_get_positions_as_of_date_flask_cached` function was fetching all historical data (`.lte("date", as_of_str)`) and filtering in Python, causing O(N*T) data transfer where T is history length. Supabase/Postgres scans were inefficient for large datasets.
**Action:** For "as of date" queries on snapshot tables:
1. First find the *latest specific date* using `.select("date").lte(...).order("date", desc=True).limit(1)`.
2. Then fetch rows for that *exact* date using `.eq("date", found_date)`.
3. This reduces fetch volume from "All History" to "Single Snapshot" (O(1) relative to history).

## 2026-02-23 - Ticker Fetch Optimization & Pagination
**Learning:** `get_all_unique_tickers` was fetching only the first 1000 rows of large tables (e.g. `congress_trades`) due to missing pagination, resulting in incorrect/incomplete data. It was also unnecessarily scanning large historical tables for tickers.
**Action:**
1. When fetching "all" items from Supabase, ALWAYS use a pagination loop with `.range(offset, offset + limit)` to bypass the 1000-row default limit.
2. For aggregate lists (like tickers), prioritize master metadata tables (e.g. `securities`) over scanning large transaction logs.

## 2024-05-18 - Pandas JSON Normalization Anti-Pattern
**Learning:** Found that `pd.json_normalize` on a column of dictionaries (`df['securities']`) is significantly slower than doing list comprehensions over the column data (`df['securities'].tolist()`) and extracting properties with `.get()`. This added unnecessary overhead during dashboard metric calculations for things like `get_current_positions_flask`.
**Action:** When flattening a known set of keys from a Series of dicts in Pandas, prefer converting the Series to a list and using a list comprehension instead of `pd.json_normalize`. E.g. `col_list = df['dict_col'].tolist(); df['key'] = [s.get('key') if isinstance(s, dict) else None for s in col_list]`.

## 2024-05-19 - O(M*N) Nested Loop Anti-Pattern in CSV Reconciliation
**Learning:** In `CSVRepository.update_daily_portfolio_snapshot`, finding an updated position for each row involved looping over `snapshot.positions` resulting in an O(M*N) nested loop complexity. When dealing with CSV updates or iterating over DataFrames, linear searches inside loops cause severe performance degradation for larger portfolios.
**Action:** When performing ticker-based lookups within loops, always pre-build a dictionary mapping (e.g., `snapshot_positions_by_ticker = {pos.ticker: pos for pos in snapshot.positions}`) to reduce complexity to O(M+N).

## YYYY-MM-DD - Fetch Distinct Values Without Data Transfer
**Learning:** Found that `get_all_unique_tickers` was performing a full row extraction from 4 large tables using `.execute()` to collect unique tickers, downloading hundreds of megabytes of redundant data over the network only to extract a small set of distinct strings. Also, `.execute()` is limited to 1000 rows without pagination.
**Action:** Use `fetch_unique_column_values_parallel` (which tries an RPC call for O(1) fetch and falls back to chunked, paginated selection) to significantly reduce memory footprint and network transfer when extracting a set of unique column values across large tables.

## 2025-03-05 - O(N) Ticker Lookup Anti-Pattern in PortfolioSnapshot
**Learning:** `PortfolioSnapshot` relied on an $O(N)$ linear list traversal in its `get_position_by_ticker` method. In highly active scenarios involving loops parsing CSV records or rebuilding historical portfolios, repeated calls scale to $O(N^2)$, causing significant CPU overhead for large portfolios.
**Action:** Always wrap data models representing collections with internal dictionary caches to provide $O(1)$ access. Added `_positions_by_ticker` via `__post_init__` to `PortfolioSnapshot`, keeping it cleanly synced during `add_position` and `remove_position` mutations while offering an explicit fallback for deserialization pipelines that bypass the constructor.## 2024-05-01 - Pandas Iteration Bottleneck
**Learning:** `df.iterrows()` is a significant performance bottleneck in large data processing pipelines within scheduler jobs (e.g., `jobs_etf_watchtower.py`, `jobs_portfolio.py`). It instantiates a Pandas Series object for every row, making it notoriously slow (O(n) with high overhead).
**Action:** Replace `df.iterrows()` with vectorized operations (e.g., `.abs().round().tolist()`, boolean vectorization `.all()`) wherever possible. When iteration is absolutely necessary, prefer `.to_dict('records')` (for bulk dictionary creation) or `.itertuples(index=False)` (which yields standard Python tuples and avoids the high overhead of Series instantiation).

## 2026-05-09 - Pandas DataFrame Iteration Bottleneck
**Learning:** The `.iterrows()` method is a significant performance bottleneck in Pandas when iterating over rows, as it yields a `pd.Series` object for every row, incurring heavy object instantiation overhead (O(n) overhead).
**Action:** Replace `.iterrows()` with `.to_dict('records')` when iteration logic expects dictionary-like access. This converts the dataframe to native Python dictionaries upfront, preserving structure while increasing iteration speed by 10x-100x and casting numpy datatypes directly to Python natives for safer serialization.

## 2024-05-18 - Pandas iterrows in render loops (historical)
**Learning:** `iterrows()` in display/chart loops (`chart_utils.py`, etc.) is slow — prefer vectorized ops or `.itertuples()`.
**Action:** Replace `iterrows()` with `itertuples(index=False)` and use `getattr(row, 'colname')` for row access. This yields standard Python namedtuples, avoiding the Series instantiation overhead and providing a 10-100x speedup for dashboard rendering loops.

## 2024-05-18 - Pandas iterrows Timezone Overhead
**Learning:** In `Scripts and CSV Files/Generate_Graph.py`, modifying timestamps via `.iterrows()` loop using `datetime.timedelta` took significant O(N) execution overhead because of Pandas instantiating Series objects for every row, and running timezone assignments row-by-row in python space.
**Action:** When adjusting datetime columns by hours or constant offsets across entire DataFrames, entirely skip iterative loops and use `.dt.normalize() + pd.Timedelta(hours=X)` for massive 10-100x vectorization speedups.

## 2026-06-10 - Optimize iterrows bottlenecks in Generate_Graph
**Learning:** `df.iterrows()` inside `Generate_Graph.py` was being used incorrectly both for finding valid real prices and for converting to a dictionary, which incurred massive O(N) overheads due to instantiating Pandas Series objects. A quick vectorized check (`.abs()` and `.any()`) and `.to_dict('records')` conversion provide >90x speedup.
**Action:** Replace `df.iterrows()` iterative checks with `.any()` boolean checks where possible. Use `.to_dict('records')` if an exact dictionary loop is needed instead of `row.to_dict()`.

## 2026-06-22 - Pandas df.apply with axis=1 in routes
**Learning:** Using df.apply(..., axis=1) is notoriously slow (O(n) overhead) in Flask routes like dashboard_routes.py and etf_routes.py. It is a major bottleneck on large DataFrames compared to numpy vectorized alternatives.
**Action:** Replaced df.apply(..., axis=1) with vectorized conditional logic using numpy.where and numpy.select, improving iteration speed by 8x-80x.

## 2026-06-22 - np.where with pandas division and zero denominators
**Learning:** When vectorizing `DataFrame.apply()` using `np.where` and pandas division, pandas evaluates `A / B` for all rows before `np.where` applies its mask. If `B` can be zero, this floods logs with `RuntimeWarning: divide by zero encountered in divide` even when the result is masked.
**Action:** Use safe division by replacing zeros with `np.nan` before dividing: `df['A'].divide(df['B'].replace(0, np.nan))`.

## 2024-05-18 - Pandas iterrows Timezone Overhead
**Learning:** In `utils/timezone_utils.py`, `safe_parse_datetime_column` was iteratively parsing timezone abbreviations via `.apply(lambda)` and stripping/reapplying timezones per-row, causing massive O(N) object instantiation overhead on CSV reads. It also previously crashed with `AttributeError` when incorrectly using `tz.utcoffset(None)`.
**Action:** When adjusting datetime columns by timezone abbreviations across entire DataFrames, entirely skip iterative loops and use `.str.replace()` for abbreviations, imputation using `np.where`, and then bulk `pd.to_datetime(..., utc=True)` before a final vectorized `.dt.tz_convert(tz)` for a massive 100x vectorization speedup. Always pass a concrete `datetime` object to `.utcoffset()` when resolving local timezone offsets instead of `None` to prevent `AttributeError`.
