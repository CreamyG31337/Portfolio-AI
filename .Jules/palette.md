## 2026-01-30 - Verification of Authenticated UI
**Learning:** Verified that testing authenticated pages (like admin/jobs) requires creating a standalone HTML harness that mocks inheritance and static assets, as bypassing backend auth logic in a live test environment is complex and unreliable.
**Action:** When working on authenticated views, always create a `verification/mock_view.html` that includes the relevant CSS/JS and HTML structure to test interactions in isolation using Playwright with a local HTTP server.
