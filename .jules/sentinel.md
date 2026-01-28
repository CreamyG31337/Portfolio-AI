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

## 2026-01-20 - Exposed Debug Endpoint Information Disclosure
**Vulnerability:** The `/logs/debug` endpoint in `web_dashboard/app.py` was accessible to any authenticated user (via `@require_auth`) instead of restricted to admins (`@require_admin`). It returned sensitive internal state including user roles, DB RPC results, and potential error messages.
**Learning:** Debug endpoints added for convenience often bypass strict access controls or use laxer defaults. The explicit comment "Debug endpoint to check admin status without requiring admin" indicated intentional exposure for debugging, but failed to account for the risk of leaking internal implementation details to non-privileged users.
**Prevention:**
1. Audit all routes starting with `/debug` or containing "debug" in the name.
2. Use restrictive defaults (deny all) and explicitly grant access only when necessary.
3. If a debug endpoint is needed for non-admins, ensure it returns sanitized data and no internal stack traces or DB errors.

## 2026-01-25 - Hardcoded Secret Key Fallbacks
**Sentinel PR:** `sentinel/fix-hardcoded-secrets-fallback-641220019199152828` - MERGED
**Vulnerability:** The application had hardcoded fallback values for critical secrets (`FLASK_SECRET_KEY` and `JWT_SECRET`) with predictable values like `"your-secret-key-change-this"`. These defaults were used whenever environment variables were not set, allowing attackers who could see the source code to forge session tokens and JWT tokens.
**Learning:** Hardcoded fallback secrets are a common security anti-pattern. Even if intended only for development, they create a vulnerability if environment variables are not properly configured in production. Predictable secrets visible in source code can be exploited by attackers.
**Solution Implemented:**
- Removed all hardcoded fallback secrets
- Generate cryptographically secure random secrets using `secrets.token_hex(32)` (256 bits of entropy) if environment variables are not set
- Added warning logs when secrets are auto-generated to alert developers
- Sessions are invalidated on restart if secrets aren't configured (documented in warnings)
**Prevention:**
1. Never use hardcoded fallback secrets - always generate random secrets if env vars aren't set
2. Use cryptographically secure random generation (Python's `secrets` module)
3. Log warnings when secrets are auto-generated to ensure proper configuration in production
4. Document the requirement for environment variables in deployment guides

## 2026-01-28 - HttpOnly Cookie Leak via Debug Endpoint (FALSE POSITIVE - REJECTED)
**Sentinel PR:** `sentinel/fix-httponly-cookie-leak-17698819992073297743` - REJECTED
**Reported Vulnerability:** The `/api/debug/cookies` endpoint reflected all request cookies (including HttpOnly cookies like `auth_token`) in the JSON response body. Sentinel claimed this allowed an attacker with XSS to bypass HttpOnly protection.
**Reason for Rejection:** This is a false positive with minimal actual risk:
1. **Admin-only access**: Endpoint is protected by `@require_admin` decorator - only authenticated admins can access it
2. **Returns user's own cookies**: The endpoint only echoes back cookies that the authenticated admin user themselves sent in the request
3. **XSS context is moot**: If an attacker already has XSS on the dashboard, they can make authenticated requests directly - reading cookies via this endpoint doesn't provide additional attack surface beyond what XSS already enables
4. **Debugging utility**: Full cookie visibility is necessary for troubleshooting authentication issues, which is the primary purpose of this admin debug endpoint
**Learning:** Security scanners may flag debug endpoints that reflect cookies, but context matters:
- Admin-only endpoints with proper authentication are lower risk
- Endpoints that only return the user's own data don't provide additional attack surface
- Debugging functionality has legitimate operational value that must be balanced against theoretical risks
**Decision:** Keep endpoint functional with full cookie visibility. Added security documentation in endpoint docstring explaining why this is safe.
