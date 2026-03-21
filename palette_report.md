## Issue: Hardcoded hex colors and inline styling in TypeScript cell renderers
**Why it matters:** Using inline styles with arbitrary hex values (e.g., `#4ade80`, `#f87171` in `congress_positions.ts`) bypasses Tailwind’s design system, making components unresponsive to dark mode and inconsistent with the rest of the application's semantic color palette.

**Suggestion:** Replace inline styles and arbitrary hex codes with the project's semantic Tailwind utility classes (e.g., `text-theme-success-text`, `text-theme-error-text`, `text-text-tertiary`) and ensure font-weight is applied using `font-bold` or `font-semibold`.

**Scope:** Local (`web_dashboard/src/js/congress_positions.ts`)

## Issue: Inline explicit styles for width and height in grid components
**Why it matters:** Setting `img.style.width = '24px'` and `img.style.height = '24px'` in `.ts` files (`signals.ts`, `congress_trades.ts`, `social_sentiment.ts`, `etf_holdings.ts`) hardcodes dimensions outside the design system and bypasses Tailwind, introducing inconsistency.

**Suggestion:** Remove `style.width` and `style.height` assignments and instead apply equivalent Tailwind classes `w-6 h-6` directly to the element's `className` or `classList`.

**Scope:** Systemic (multiple AgGrid cell renderer implementations in `.ts` files)

## Issue: Re-implemented toast notification system across multiple files
**Why it matters:** Multiple files (`contributions.ts`, `jobs.ts`, `contributors.ts`, `users.ts`, `ai_settings.ts`, `trade_entry.ts`, `research.html`, `newsletters.html`) implement custom toast notifications that manually append `div` elements to the DOM and manage timeouts. This duplicates Flowbite's standard Toast component behavior, leading to inconsistent UX, redundant code, and potential accessibility gaps.

**Suggestion:** Refactor the custom toast implementations to use standard Flowbite Toast components or a centralized utility that leverages Flowbite's built-in alerts and accessibility attributes.

**Scope:** Systemic (multiple `.ts` and `.html` files)

## Issue: Hand-rolled custom modal implementations bypassing Flowbite
**Why it matters:** The `trade_entry.html` file implements modals manually using `<div id="edit-trade-modal" class="hidden fixed inset-0 z-50 ...">`, which lacks Flowbite's built-in focus trapping, keyboard navigation (`Escape` to close), and accessibility features (`aria-modal="true"`, `role="dialog"`). Similarly, `newsletters.html` implements `email-view-modal` with inline JavaScript (`onclick="if(event.target === this) closeEmailModal()"`).

**Suggestion:** Refactor these custom modals to use Flowbite’s standard modal component syntax, utilizing data attributes like `data-modal-target`, `data-modal-toggle`, and `data-modal-hide` to handle behavior and accessibility seamlessly.

**Scope:** Local (`web_dashboard/templates/trade_entry.html`, `web_dashboard/templates/newsletters.html`)
