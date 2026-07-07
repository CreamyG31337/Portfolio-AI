## Code Review: Handling Suspect Performance Metrics

**Commit:** `3c1aecf90f39c6afc371a678638c491b959d1921`
**Author:** Lance Colton

### Overview
This commit introduces a feature to detect and replace suspect performance metrics when discrepancies exceed 15% between `performance_metrics` and `portfolio_positions`. The changes are implemented across three files:
- `web_dashboard/flask_data_utils.py`
- `web_dashboard/scheduler/jobs_metrics.py`
- `tests/test_flask_performance_gap_fill.py`

### Changes Analyzed

#### 1. `web_dashboard/flask_data_utils.py`
- Added the `_detect_suspect_metric_dates` nested function. It iterates through the performance metrics data and detects dates where the metric value and the total value calculated from positions diverge by more than 15%.
- Implemented `_fetch_position_daily_totals` to aggregate the total value, cost basis, and PnL for positions, grouped by date. This supports checking metrics against true position totals.
- Added logic around line 896 to try replacing suspect metrics by re-fetching and using values from `portfolio_positions`. This helps address issues like incorrect totals during US-only holidays where parts of the portfolio are stale.

**Feedback:** The logic correctly fetches and compares daily totals. The grouping correctly accommodates CAD conversion where pre-converted columns are available (`total_value_base`). Exception handling is well implemented so suspect data won't crash the entire function.

#### 2. `web_dashboard/scheduler/jobs_metrics.py`
- Updated the select query in `_process_performance_metrics_for_date` to also pull `total_value_base`, `cost_basis_base`, and `pnl_base`.
- Changed the logic to prefer pre-calculated `_base` variables over manually calculating exchange rates. This is an excellent improvement for stability, especially handling partial market days accurately.

**Feedback:** The decision to lean on base variables rather than running conversions inside the metric job minimizes race conditions with live exchange rates and missing rate errors.

#### 3. `tests/test_flask_performance_gap_fill.py`
- Added `test_suspect_performance_metrics_replaced_from_positions` which creates mock data simulating a >15% divergence between the `performance_metrics` table and the `portfolio_positions` table.
- Mocks out the necessary Supabase dependencies.
- Asserts that the calculation correctly updates the `value` in the resulting DataFrame based on the `total_value_base` in `portfolio_positions` rather than the old suspect value in `performance_metrics`.

**Feedback:** The test directly covers the new functionality with clear mocking and assertions.

### Summary
The commit effectively addresses the goal of correcting suspect performance metrics. The approach is sound, prioritizing pre-converted position tables and dynamically replacing skewed metrics data when fetching the portfolio values over time. The associated test passed in the sandbox environment.

Overall, the changes look great and appear safe to deploy.
