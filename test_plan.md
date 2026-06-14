```markdown
1. **Extract and replace `.form-input-theme` utility class**
   - The `.form-input-theme` utility class is already defined in `web_dashboard/static/css/input.css` as `@apply bg-dashboard-surface-alt border border-border text-text-primary text-sm rounded-lg focus:ring-accent focus:border-accent block w-full p-2.5;`.
   - Ensure `web_dashboard/templates/dashboard.html` and other form inputs are using this utility instead of the long class string where missed. Actually, `auth.html` and `settings.html` already use it. Wait, I should double check `dashboard.html`.

2. **Replace manual Alerts with `components/_alert.html`**
   - Refactor `id="dashboard-error-container"` in `web_dashboard/templates/dashboard.html` to use `{% include "components/_alert.html" %}` or just Flowbite alert classes without hardcoded `bg-theme-error-bg` where `components/_alert.html` already does this. Wait, the `dashboard.html` one is meant to be shown/hidden by JS. `components/_alert.html` has an `id` prop so we can just use `{% with id='dashboard-error-container', type='error', message='<div id="dashboard-error-message"></div><button onclick="refreshDashboard()" class="mt-3 font-semibold underline hover:text-text-primary">Try Again</button>', hidden=True %}{% include "components/_alert.html" %}{% endwith %}` or something similar.

3. **Standardize `.card` classes**
   - The `web_dashboard/static/css/input.css` contains `.card { @apply bg-dashboard-surface rounded-lg border border-border; }`.
   - Update `web_dashboard/templates/settings.html`, `web_dashboard/templates/index.html`, `web_dashboard/templates/auth.html`, and `web_dashboard/templates/system.html` to use `.card shadow-lg p-6 mb-6 hover:-translate-y-0.5 transition-transform duration-200` to avoid repeating `bg-dashboard-surface rounded-lg border border-border`. Wait, the V2 audit mentions:
     `Repeated Card Styling... Issue: Section containers repeatedly use: bg-dashboard-surface rounded-lg shadow-lg p-6 mb-6 hover:-translate-y-0.5 transition-transform duration-200 ... Suggestion: Create a .card or .panel component class.`
   - So I will update `.card` in `input.css` to:
     `@apply bg-dashboard-surface rounded-lg border border-border shadow-lg p-6 mb-6 hover:-translate-y-0.5 transition-transform duration-200;`
   - Then replace the matching classes in those HTML files with just `card`.

4. **"Ghost" Button Inconsistencies**
   - Replace occurrences of `text-accent bg-transparent border border-accent hover:bg-accent/10 focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-4 py-2 focus:outline-hidden transition-colors duration-200` with `.btn-outline` or `.btn-outline-accent` across templates.

5. **Arbitrary Theme Variable Usage**
   - The audit said: `from-[var(--gradient-from)]` is used instead of the mapped Tailwind utility. `web_dashboard/templates/base.html`, `web_dashboard/templates/auth.html`
   - I didn't see `[var(--` when I grep'd. Wait, the audit says `from-[var(--gradient-from)]`. Let me check if it's there. Actually, I didn't find it. Maybe it was already fixed? Wait, `PALETTE_AUDIT_V2.md` was just generated. Wait no, it's static text. Let me check `auth.html` again.

6. **Fix `congress_positions.ts` and `ticker_details.ts` inline styles**
   - Replace hardcoded hex colors and inline styles with `text-theme-success-text`, `text-theme-error-text`, `text-text-secondary` in `congress_positions.ts`.
   - Remove inline styles like `style="width: ${actionabilityPct}%"` in `ticker_details.ts`? Wait, the audit says "dynamic inline styles that depend on variables (e.g., a progress bar's `style.width = '${confidencePct}%'`) are valid and should not be flagged." Oh, right! So `ticker_details.ts` `style="width:..."` is perfectly fine. `congress_positions.ts` has hardcoded hex colors `#4ade80`, `#f87171`, `#9ca3af` inside JS templates. These should be replaced by classes like `text-theme-success-text`, `text-theme-error-text`, `text-text-tertiary` or `text-text-secondary`.

7. **Complete pre-commit steps**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.

8. **Submit**
   - Run tests and submit using `submit`.
```
