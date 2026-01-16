## 2026-01-16 - Global Polling Anti-Pattern
**Learning:** Found aggressive global polling (5s interval) in `_scripts_content.html` for scheduler status. This runs on every page extending `base.html`, regardless of tab visibility or user role.
**Action:** When implementing polling in this codebase, always:
1. Increase interval for non-critical status (30s+).
2. Wrap in `!document.hidden` check to pause in background.
3. Add `visibilitychange` listener for immediate resume.
