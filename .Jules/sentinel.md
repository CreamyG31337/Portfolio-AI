## 2025-02-19 - Hardcoded Debug Mode & Information Disclosure
**Vulnerability:** The Flask application had `app.debug = True` hardcoded in `web_dashboard/app.py`. This enables the Werkzeug interactive debugger, which can allow arbitrary code execution if not properly protected. Additionally, the custom error handlers were explicitly configured to return stack traces to the client in both JSON and HTML responses, leading to information disclosure.
**Learning:** Developers often hardcode debug settings for convenience during development but forget to externalize them for production. Explicitly including `traceback.format_exc()` in error responses is a dangerous pattern that bypasses Flask's built-in protections.
**Prevention:** Always use environment variables (e.g., `FLASK_DEBUG`) to control debug mode. In error handlers, conditionally include sensitive information like stack traces only if the application is in debug mode. Use generic error messages for production users.

## 2025-02-26 - SQL Injection via Developer Interface
**Vulnerability:** The `/api/dev/query` endpoint used a blacklist approach to filter SQL queries, checking for substrings like `DROP`. This was bypassable (e.g., `WITH ... DELETE`) and caused false positives (blocking columns like `update_date`).
**Learning:** Blacklist-based sanitization is fragile against the complexity of SQL syntax. It often fails to account for all dangerous commands or their variations and can interfere with legitimate inputs.
**Prevention:** Use whitelist validation where possible (e.g., strictly ensuring the query starts with `SELECT` and contains no modification keywords as whole words). Block query chaining (`;`) to prevent multiple statements.
