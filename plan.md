1. **Remove hardcoded hex colors and inline styles in `congress_positions.ts`**
   - Replace `#4ade80`, `#f87171`, `#9ca3af` with `text-theme-success-text`, `text-theme-error-text`, `text-text-tertiary` or `text-text-secondary`.
   - Instead of `<span style="color: ${color}; font-weight: 600;">`, use `<span class="font-semibold ${colorClass}">`.

2. **Replace manual Alerts in `dashboard.html` and `settings.html`**
   - In `dashboard.html`: refactor `<div id="dashboard-error-container" class="hidden p-4 mb-6 text-sm text-theme-error-text rounded-lg bg-theme-error-bg border border-theme-error-text" role="alert">...</div>` to use `{% include "components/_alert.html" %}` with the appropriate message inside (the error message UI + "Try Again" button).
   - `settings.html` already uses `{% include "components/_alert.html" %}` extensively for its alerts. If there are manual alerts in it, replace them.

3. **Standardize `.card` / panel classes**
   - Since `.card` is `@apply bg-dashboard-surface rounded-lg border border-border;`, update instances of `class="card shadow-lg p-6 mb-6 hover:-translate-y-0.5 transition-transform duration-200"` in `settings.html` to be cleaner or simply create `.panel` class in `input.css`:
     `@apply bg-dashboard-surface rounded-lg border border-border shadow-lg p-6 mb-6 hover:-translate-y-0.5 transition-transform duration-200;`
     and apply it to sections in `settings.html` and `auth.html`.
     Wait, in `settings.html`, it's currently using `class="card shadow-lg p-6 mb-6 hover:-translate-y-0.5 transition-transform duration-200"`.
     We can introduce `.panel { @apply card shadow-lg p-6 mb-6 hover:-translate-y-0.5 transition-transform duration-200; }` or just simplify it as requested in V2 audit. Let's add `.panel` to `input.css`.

4. **"Ghost" Button Inconsistencies**
   - Replace occurrences of `text-accent bg-transparent border border-accent hover:bg-accent/10 focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-4 py-2 focus:outline-hidden transition-colors duration-200` with `.btn-outline` or `.btn-outline-accent` across templates.

5. **Arbitrary Theme Variable Usage**
   - Check `base.html` and `auth.html` for arbitrary variables. Based on V2 audit: `from-[var(--gradient-from)]` is used instead of the mapped Tailwind utility. However, grep didn't find `from-[var(--gradient-from)]`. It found `from-accent-from` in `base.html` and `auth.html`. This might have already been addressed or I need to check `auth.html` directly.

6. **Complete Pre-Commit Steps**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.

7. **Submit Changes**
   - Submit the PR with the title and description dynamically populated based on tests and changes.
