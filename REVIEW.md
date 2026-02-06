# Code Review: Newsletter Subsystem

**Date:** 2026-02-06
**Scope:** Newsletter feature (`dc96061`)

## Findings

### 1. 🚨 Critical Security Vulnerability (XSS)
*   **File:** `web_dashboard/templates/newsletters.html`
*   **Issue:** The frontend uses `innerHTML` to inject email content (subject, body, sender) directly into the DOM without sanitization.
    ```javascript
    // Vulnerable code
    return `... <h3>${newsletter.subject}</h3> ...`;
    ```
*   **Risk:** stored XSS via malicious email content.
*   **Recommendation:** Implement `escapeHtml` or use `textContent`.

### 2. 🐛 Logic & UX Defect
*   **File:** `web_dashboard/templates/newsletters.html`
*   **Issue:** `loadTickers` fetches from paginated `/api/newsletters` (default limit 20), missing older tickers.
*   **Recommendation:** Add `/api/newsletters/tickers` endpoint.

### 3. ✅ Strengths
*   Strong HMAC webhook verification in `NewsletterService`.
*   Correct SQL parameterization in `NewsletterRepository`.
*   Efficient `pgvector` schema.
