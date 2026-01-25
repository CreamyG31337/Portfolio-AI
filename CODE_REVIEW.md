# Code Review Report
**Date:** 2024-05-22
**Review Scope:** Commits from the last 12 hours (focusing on `webai` tools, `webull` import, and DB script).

## Summary
The review covers the addition of legacy WebAI cookie-based client tools, a Webull data importer, and a fix to database creation scripts.

## Critical Findings

### 1. Security & Credentials
*   **File:** `deployment/mandrel/create-database.sql`
*   **Severity:** **High**
*   **Issue:** The string `x7k9pQzW3vT2` appears in the comments. This looks like a specific password or username from a test or production environment.
    ```sql
    --   docker exec -i postgres-17.5 psql -U x7k9pQzW3vT2 -f - < create-database.sql
    ```
*   **Recommendation:** Remove this string and replace it with a generic placeholder (e.g., `your_postgres_user`) to prevent potential credential leakage.

### 2. Robustness & Maintenance
*   **File:** `web_dashboard/webai_cookie_client_legacy.py`
*   **Severity:** Medium
*   **Issue:** The `_discover_api_endpoint` method uses regular expressions to parse HTML and find API URLs.
    ```python
    patterns = [r'["\']([^"\']*api[^"\']*chat[^"\']*)["\']', ...]
    ```
    This approach is extremely brittle. Any change to the external service's frontend will break this client.
*   **Recommendation:** Acknowledge this as a "legacy" or "experimental" tool. Add robust error handling that explicitly informs the user if the layout seems to have changed.

### 3. Logic & Data Integrity
*   **File:** `utils/webull_importer.py`
*   **Severity:** Low/Info
*   **Issue:** The importer calculates PnL and updates the portfolio based on the *execution price* of the imported trade.
    ```python
    position["PnL"] = float((new_shares * price) - new_cost_basis)
    ```
    This creates a snapshot of the portfolio's performance *at the moment of the trade*, rather than a current live view.
*   **Issue:** Timezone handling is manual and potentially incomplete (`if "EDT" in ...`).

### 4. Code Quality
*   **File:** `webai_helper_legacy.py`, `webull_import.py`
*   **Severity:** Low
*   **Issue:** Manual modification of `sys.path`.
    ```python
    sys.path.insert(0, str(Path(__file__).parent))
    ```
    This makes the scripts sensitive to the directory they are invoked from.
*   **Recommendation:** Use relative imports within a proper package structure or set `PYTHONPATH` in the execution environment.

## Conclusion
The new tools provide useful functionality but rely on some fragile mechanisms (screen scraping/regex for auth) and manual path management. The database script comment should be sanitized immediately.
