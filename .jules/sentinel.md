## 2026-01-20 - Exposed Debug Endpoint Information Disclosure
**Vulnerability:** The `/logs/debug` endpoint in `web_dashboard/app.py` was accessible to any authenticated user (via `@require_auth`) instead of restricted to admins (`@require_admin`). It returned sensitive internal state including user roles, DB RPC results, and potential error messages.
**Learning:** Debug endpoints added for convenience often bypass strict access controls or use laxer defaults. The explicit comment "Debug endpoint to check admin status without requiring admin" indicated intentional exposure for debugging, but failed to account for the risk of leaking internal implementation details to non-privileged users.
**Prevention:**
1. Audit all routes starting with `/debug` or containing "debug" in the name.
2. Use restrictive defaults (deny all) and explicitly grant access only when necessary.
3. If a debug endpoint is needed for non-admins, ensure it returns sanitized data and no internal stack traces or DB errors.
