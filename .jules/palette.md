## 2026-01-30 - Verification of Authenticated UI
**Learning:** Verified that testing authenticated pages (like admin/jobs) requires creating a standalone HTML harness that mocks inheritance and static assets, as bypassing backend auth logic in a live test environment is complex and unreliable.
**Action:** When working on authenticated views, always create a `verification/mock_view.html` that includes the relevant CSS/JS and HTML structure to test interactions in isolation using Playwright with a local HTTP server.
**Critical:** Do NOT delete the `verification/` folder or its contents (e.g. `verify_password_toggle.py`, `password_toggle.png`) when making PRs. Only add or update verification files; never remove existing verification scripts or assets.## 2026-02-03 - Verify Async UI with Mock Fetch
**Learning:** When verifying async UI states (like loading spinners) in a static mock harness, overriding `window.fetch` to return a delayed promise allows capturing transient states (loading) that are otherwise too fast or fail immediately in a file:// environment.
**Action:** Use `window.fetch = async () => { await new Promise(r => setTimeout(r, 1000)); ... }` in verification scripts to reliably test loading states.
## 2025-02-15 - [Avoid hard-coded accent classes for page actions]
 **Issue:** [Hard-coded bg-accent text-white utilities were used for buttons instead of established standards.]
 **Learning:** [Hard-coded classes look harsh in light+dark themes.]
 **Prevention:** [Use standardized btn-outline or btn-outline-sm utilities instead.]
