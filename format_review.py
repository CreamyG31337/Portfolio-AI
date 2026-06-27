import json

review_notes = """
Code Review for commits in the last 12 hours:

*   **feat: enhance insider and congress trades formatting and retrieval (20578839)**:
    *   Cleaned up string formatting for insider/congress trades.
    *   `format_insider_trades` and `format_congress_trades` now correctly return empty strings when trades are missing instead of a hardcoded string.
    *   Congress lookback parameter added and defaulting to 30 days.

*   **feat(etf): enhance ETF context handling and reporting (356b7fc5)**:
    *   `aggregate_etf_changes` successfully implements data aggregation for ETF contexts.
    *   A set of python tests introduced for ETF context and pass correctly.

*   **perf: land Bolt vectorization from Jules PRs; palette audit TODOs (99fd59b5)**:
    *   Performance optimizations successfully converted looping mechanisms over dataframes to vectorized operations via `numpy` (`np.where`).
    *   Flask data util handles security dictionaries safely via list comprehensions, dropping inefficient `.apply()` loops.
    *   TODO(palette) added for flowbite Modals and Collapse elements in TS files (`trade_entry.ts`, `funds.ts`, `jobs.ts`, `ticker_details.ts`, `ai_assistant.ts`). These outline a goal to migrate away from inline `hidden` classes towards the Flowbite API.

*   **refactor(glm): update GLM model management and deprecate older versions (bfa11af0)**:
    *   GLM models correctly updated via `model_registry` and configuration.
    *   `glm-4.7` and `glm-4.5` retired in `model_config.json` with `hidden: true`.
    *   Frontend models now correctly fallback onto preferred ids using `model_registry.resolve_ai_model_preference`.

*   **fix(data-quality): enhance OHLCV validation and signal integrity (d156395c)**:
    *   Commit message says "Refined the OHLCV data validation process...".
    *   *Issue:* The diff for this commit (`d156395c`) only contains the creation of `web_dashboard/chat_context.py` containing a `ContextItemType(Enum)` class. There are no OHLCV or SignalEngine modifications in this commit diff.

**Test Results:**
* All backend pytest testing (for `test_ai_congress_context.py`, `test_ai_etf_context.py`, and `test_model_registry.py`) pass successfully.
* Frontend `pnpm run test:ts` passes successfully without emitting errors.
"""

print(review_notes)
