## 2025-02-19 - Hardcoded Debug Mode & Information Disclosure
**Vulnerability:** The Flask application had `app.debug = True` hardcoded in `web_dashboard/app.py`. This enables the Werkzeug interactive debugger, which can allow arbitrary code execution if not properly protected. Additionally, the custom error handlers were explicitly configured to return stack traces to the client in both JSON and HTML responses, leading to information disclosure.
**Learning:** Developers often hardcode debug settings for convenience during development but forget to externalize them for production. Explicitly including `traceback.format_exc()` in error responses is a dangerous pattern that bypasses Flask's built-in protections.
**Prevention:** Always use environment variables (e.g., `FLASK_DEBUG`) to control debug mode. In error handlers, conditionally include sensitive information like stack traces only if the application is in debug mode. Use generic error messages for production users.

## 2026-01-17 - SQL Injection PR Rejected (Admin Tool Context)
**Sentinel PR:** `sentinel/fix-sql-injection-dev-query-3566238923453452445` - REJECTED
**Reason for Rejection:** The `/api/dev/query` endpoint is an admin-only SQL interface protected by both `@require_auth` and `is_admin()` checks. The Sentinel PR would have blocked all INSERT/UPDATE/DELETE queries, defeating the purpose of having an admin SQL tool.
**Learning:** Security fixes must consider the context and intended use of an endpoint. Admin tools require full SQL access for legitimate operations like data fixes, testing, and maintenance. Overly restrictive validation can break necessary functionality.
**Alternative Approach Taken:** Instead of blocking modification queries, we implemented:
- Comprehensive audit logging with user email, IP address, and full query text
- Whole-word keyword validation (prevents false positives like 'update_date')
- WARNING-level logging for all modification queries (INSERT/UPDATE/DELETE/DROP)
- Detailed security documentation in the endpoint docstring
- Best practices guidance for admins using the tool
This provides defense-in-depth through visibility and accountability rather than restriction.
