# Tailwind and Flowbite Code Audit

## Issue: Inline style used for dynamic width instead of CSS variables and utility classes
**Why it matters:** Using inline styles like `style="width: 0%"` bypasses the Tailwind utility-first approach and makes it harder to override or manage dimensions via standard classes. This directly contradicts the project's CSS best practices.
**Suggestion:** Replace the inline `style="width: X%"` with an inline CSS variable `style="--bar-width: X%"` and use the arbitrary value class `w-[var(--bar-width)]` on the element.
**Scope:** Reusable (Progress Bars in `web_dashboard/templates/ticker_details.html` and updating TS references)

## Issue: Inline style used for image sizing instead of Tailwind classes
**Why it matters:** Using inline styles like `img.style.width = '24px'` in TypeScript bypasses Tailwind's standard sizing scale.
**Suggestion:** Replace the direct style manipulation with adding Tailwind classes like `img.classList.add('w-6')` (since `w-6` equals `24px`).
**Scope:** Reusable (Image cell creation across multiple TypeScript files: `signals.ts`, `congress_trades.ts`, `social_sentiment.ts`, `etf_holdings.ts`)

## Issue: Custom hand-rolled modals bypassing Flowbite component
**Why it matters:** Manually implementing modals with `hidden fixed inset-0 z-50` and custom javascript toggles misses out on Flowbite's built-in features such as focus trapping, keyboard navigation (Escape to close), ARIA attributes, and consistent animation.
**Suggestion:** Refactor `edit-trade-modal` and `delete-trade-modal` in `trade_entry.html` and `email-view-modal` in `newsletters.html` to use standard Flowbite modal markup and `data-modal-target`/`data-modal-toggle` attributes instead of reinventing the pattern.
**Scope:** Local (`web_dashboard/templates/trade_entry.html` and `web_dashboard/templates/newsletters.html`)

## Issue: Verbose custom toggles bypassing standardized Flowbite utilities/classes
**Why it matters:** Multiple templates use complex, hand-rolled Tailwind structures (e.g. `peer-checked:after:translate-x-full after:absolute after:top-[2px] ...`) for toggle switches. This bloats HTML and reduces maintainability.
**Suggestion:** Replace these excessively verbose toggle implementations with standard Flowbite toggle components or abstract the repeating classes into a single `@apply` component class in `input.css` (e.g., `.toggle-switch`).
**Scope:** Systemic (Toggles across `dashboard.html`, `color_test.html`, `contributions.html`, and `system.html`)
