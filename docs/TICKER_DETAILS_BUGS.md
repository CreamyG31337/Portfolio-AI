# Ticker Details Page — Bug Report (Refined)

**Date:** 2026-03-01  
**Last Verified:** 2026-03-02  
**Status:** Refined after code re-validation  
**Files:** `web_dashboard/src/js/ticker_details.ts`, `web_dashboard/app.py`, `web_dashboard/templates/ticker_details.html`

---

## 🔴 Critical

### 1. Research Articles Chevron Double-Toggle (TS ~L1497 + L1520)
The inline `onclick` on the row div toggles the `hidden` class on the detail panel. Then the `addEventListener('click')` on the same element fires *after* and checks the state — but the state has already flipped, so the chevron rotation is **inverted** (points right when expanded, rotated when collapsed).

**Fix:** Remove the inline `onclick` attribute from the generated HTML and handle everything in the `addEventListener`, OR remove the `addEventListener` and handle chevron rotation inline.
**Confidence:** Confirmed in current code.

### 2. Chart Theme Mismatch (app.py L4029)
Frontend sends `midnight-tokyo` and `abyss` as theme values (TS L1053-1054), but backend only accepts `dark`|`light` (app.py L4029: `theme=client_theme if client_theme in ['dark', 'light'] else None`). Custom themes silently fall back to user preference or `light`, causing wrong chart colors.

**Fix:** Either map `midnight-tokyo`/`abyss` → `dark` on the frontend before sending, or accept them on the backend and treat as dark variants.
**Confidence:** Confirmed in current code.

### 3. Stale Global State on Ticker Switch (TS L284-294)
`hideAllSections()` only hides DOM; it does not clear global arrays/pages.  
Main confirmed issue: `renderCongressTickerTrades()` and `renderInsiderTrades()` return early on empty input and do not clear prior state arrays/pages. If a previous ticker had data and next ticker has empty/missing data, stale state can persist in memory and leak into later renders.

**Fix:** At minimum, clear state in empty branches of congress/insider renderers. Safer option: also reset all trade arrays/page indices at the top of `loadTickerData()`.
**Confidence:** Confirmed (congress/insider). ETF already clears `allEtfTrades` on empty, but should also reset page index for consistency.

### 4. Race Condition on Rapid Ticker Switching (TS L725)
No `AbortController` or load sequence counter. If user searches ticker A then quickly ticker B, ticker A's slower API responses can overwrite ticker B's rendered UI.

**Fix:** Add a monotonic `loadSeq` counter incremented at the start of `loadTickerData()`. Each async callback checks `if (seq !== loadSeq) return;` before rendering.
**Confidence:** Confirmed in current async flow.

---

## 🟡 Medium

### 5. Hardcoded `dark:` Classes Break Custom Themes
These functions use hardcoded Tailwind `dark:` classes instead of CSS variable theme classes (`bg-dashboard-surface`, `text-text-primary`, etc.), so they render incorrectly on `midnight-tokyo` and `abyss` themes:

- `renderSignals()` — TS L2096-2106 (signal badges), L2162-2198 (fear/risk colors)
- `renderDebugPanel()` / `renderDebugPanelMessage()` — TS L2831-2853
- `showToast()` — TS L2913
- `colorScoreEl()` — TS L2224 (`text-green-500` etc.)
- `barColorClass()` — TS L2236
- Momentum/fundamental badge rendering — TS L2257-2268, L2363-2378

**Fix:** Replace with theme-aware classes: `bg-theme-success-bg`, `text-theme-success-text`, `bg-theme-error-bg`, etc. — matching the pattern used in congress trades rendering.
**Confidence:** Confirmed for listed blocks.

### 6. Research Article Rendering XSS Surface (TS ~L1498-1515)
`previewSummary` is interpolated directly into `innerHTML` without `escapeHtml()`, and several other article fields are also injected unsafely (`title`, `source`, `articleType`, `url`):
```ts
<p class="...">${previewSummary}</p>
```
If article metadata contains malicious HTML or `javascript:` URLs, this creates an XSS vector.

**Fix:** Build row content with DOM APIs (`textContent`, `setAttribute`) where possible. If template strings are retained, escape all user/content fields and enforce URL protocol allowlist (`http:`/`https:`).
**Confidence:** Confirmed.

### 7. `jsonify(None)` API Response (app.py L3606)
`get_ticker_analysis` returns `jsonify(None)` (JSON literal `null`) when no analysis exists. Frontend does handle this with `if (analysis)` check at TS L2641, but it's an inconsistent API pattern — every other endpoint returns an object or 404.

**Fix:** Return `jsonify({})` with 404 status, or return `jsonify({"analysis": null})`.
**Confidence:** Confirmed.

---

## 🟢 Low Priority

### 8. Event Listener Buildup on Re-renders
Research article rows attach new `addEventListener` on each render. Current implementation clears `list.innerHTML` first, so old nodes/listeners are dropped with removed DOM. This is mostly a maintainability concern, not a clear runtime bug.

**Fix:** Use event delegation on `research-articles-list` container instead.
**Confidence:** Low (optimization/refactor, not urgent bug).

### 9. Model Sync Race (`modelSyncInProgress` flag)
The guard is synchronous and likely sufficient for current event flow. No clear repro found for a real race in normal browser event ordering.
**Confidence:** Low (likely false alarm unless repro is found).

### 10. `_save_analysis` SQL Query Termination (ticker_analysis_service.py L1054-1097)
Re-checked: query string and Python call are syntactically complete. Missing trailing semicolon is not required by psycopg execution.
**Status:** Not a bug (remove from active fix list unless runtime error is observed).

---

## Suggested Fix Order
1. **Bug #6** (XSS surface) — security fix first
2. **Bug #3** (stale state reset) — prevents stale trade state
3. **Bug #1** (chevron double-toggle) — visible UI glitch
4. **Bug #2** (chart theme mismatch) — wrong theme rendering
5. **Bug #4** (rapid-switch race) — prevents out-of-order render overwrite
6. **Bug #5** (hardcoded `dark:` classes) — broader theme consistency pass
7. **Bug #7** API consistency cleanup
8. Leave #8/#9 as optional cleanup; drop #10 unless new evidence appears
