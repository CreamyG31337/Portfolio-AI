## 2026-01-30 - Verification of Authenticated UI
**Learning:** Verified that testing authenticated pages (like admin/jobs) requires creating a standalone HTML harness that mocks inheritance and static assets, as bypassing backend auth logic in a live test environment is complex and unreliable.
**Action:** When working on authenticated views, always create a `verification/mock_view.html` that includes the relevant CSS/JS and HTML structure to test interactions in isolation using Playwright with a local HTTP server.
**Critical:** Do NOT delete the `verification/` folder or its contents (e.g. `verify_password_toggle.py`, `password_toggle.png`) when making PRs. Only add or update verification files; never remove existing verification scripts or assets.

## 2026-02-03 - Verify Async UI with Mock Fetch
**Learning:** When verifying async UI states (like loading spinners) in a static mock harness, overriding `window.fetch` to return a delayed promise allows capturing transient states (loading) that are otherwise too fast or fail immediately in a file:// environment.
**Action:** Use `window.fetch = async () => { await new Promise(r => setTimeout(r, 1000)); ... }` in verification scripts to reliably test loading states.

## 2026-09-29 - Don't commit compiled JS; write real dates
**Learning:** PR #580 force-added `web_dashboard/static/js/social_sentiment.js` (+741 lines), which is gitignored because `tsc` builds it; PR #596 wrote a journal heading with a literal `$(date +%Y-%m-%d)`.
**Action:** Only change `web_dashboard/src/js/*.ts`; never `git add -f` under `static/js/`. Write journal dates as literal `YYYY-MM-DD`.

## 2026-09-29 - Ideas accept modal stays hand-rolled (PR #568 not merged)
**Learning:** `ideas.html`'s accept modal handles Cancel and backdrop clicks in `ideas.ts`; the only real gap was ESC, fixed with a plain keydown listener. Converting it to a hidden Flowbite toggle button plus a MutationObserver added indirection for that one key.
**Action:** Fix the specific missing behavior in place; only move a modal to Flowbite when that is the smaller change, and verify it in a browser.
