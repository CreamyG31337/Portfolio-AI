1. **Optimize Pandas Dataframe Iteration in `jobs_portfolio.py` and `jobs_etf_watchtower.py`**
   - Replace the slow `iterrows()` with the much faster `itertuples(index=False)` pattern for the pandas dataframes in `web_dashboard/scheduler/jobs_portfolio.py` and `web_dashboard/scheduler/jobs_etf_watchtower.py` to boost performance. (This aligns with memory rule: "Optimization Pattern: For iterating over pandas DataFrames, avoid `df.iterrows()`. Use `df.itertuples(index=False)`.")
   - Adjust column access syntax (e.g., from `row['col']` to `getattr(row, 'col', None)` or `row.col`)
   - Handle missing values using safe access.
2. **Review performance metrics in a comment.**
   - Include a comment linking to the optimization reasoning or marking the speed up.
3. **Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.**
   - Call `pre_commit_instructions` and follow the steps before submission.
4. **Submit changes**
   - Open a PR with the expected format `⚡ Bolt: [performance improvement]`.
