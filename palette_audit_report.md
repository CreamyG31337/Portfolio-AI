# Palette CSS Audit Report

## Finding 1: Excessively Verbose Custom Toggle Switches

**Issue:** Several templates (`dashboard.html`, `color_test.html`, `system.html`) implement custom toggle switches using highly verbose inline Tailwind utilities (e.g., `peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-accent rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all`).
**Why it matters:** Repeating these long class strings across multiple templates makes the code difficult to read and maintain. Furthermore, manual custom implementation increases the likelihood of subtle inconsistencies across the application (e.g., varying focus rings or dark mode states) and misses out on standard Flowbite conventions.
**Suggestion:** Replace these hand-rolled toggle implementations with standard Flowbite toggle components. If custom styling is strictly necessary to match the design system, encapsulate the long class strings into a reusable semantic component class (e.g., `.toggle-switch-theme`) via `@apply` directives in `web_dashboard/static/css/input.css` instead of writing them inline in the HTML.
**Scope:** Systemic (`web_dashboard/templates/dashboard.html`, `web_dashboard/templates/color_test.html`, `web_dashboard/templates/system.html`).

## Finding 2: Hand-rolled Trade Entry Modals Missing Flowbite Integration

**Issue:** The "Edit Trade" (`edit-trade-modal`) and "Delete Trade" (`delete-trade-modal`) dialogs in `trade_entry.html` are implemented using custom HTML classes (`hidden fixed inset-0 z-50 ...`) and custom JavaScript toggles.
**Why it matters:** Hand-rolled modals often lack critical accessibility features such as automatic focus trapping, ARIA roles, and standard keyboard navigation (like closing on Escape). Duplicating modal logic also bloats the codebase and strays from the project's dependency on Flowbite for standard interactive UI elements.
**Suggestion:** Refactor the markup of these modals to use standard Flowbite attributes (`data-modal-target`, `data-modal-toggle`, `data-modal-hide`) and Flowbite's standard modal CSS class structures (`overflow-y-auto overflow-x-hidden fixed top-0 right-0 left-0 z-50 justify-center items-center ...`). Remove the custom JavaScript visibility toggling and let Flowbite handle the modal lifecycle and accessibility.
**Scope:** Local (`web_dashboard/templates/trade_entry.html`).

## Finding 3: Direct Inline Styles for Dimensions and Progress Bars

**Issue:** Direct inline styling is being used to manipulate widths and dimensions. In TypeScript files (`signals.ts`, `etf_holdings.ts`, `congress_trades.ts`, `social_sentiment.ts`), table cell images are explicitly sized using inline CSS (e.g., `img.style.width = '24px'`). Additionally, in `ticker_details.html` and `dashboard.ts`, dynamic progress bar widths use direct inline styles (e.g., `style="width: 0%"` and `progressInner.style.width = ...`).
**Why it matters:** Hardcoding styling dimensions via `element.style` or inline HTML attributes bypasses Tailwind's consistent spacing/sizing scale and makes it harder to support responsive design or standard layout changes consistently. It breaks the "utility-first" pattern of Tailwind.
**Suggestion:**
- For static elements like the icons in the TS files, assign standard Tailwind sizing utilities directly instead of inline styles (e.g., use `img.className = 'w-6 h-6 object-contain rounded flex-shrink-0'`).
- To manage dynamic dimensions (like progress bar widths), use inline CSS variables combined with arbitrary utility classes instead of direct inline styles. Set the value via `style="--bar-width: X%"` or `style.setProperty('--bar-width', ...)` and add a class like `w-[var(--bar-width)]` to seamlessly integrate the dynamic value with Tailwind's utility pipeline.
**Scope:** Systemic (`web_dashboard/src/js/signals.ts`, `web_dashboard/src/js/etf_holdings.ts`, `web_dashboard/src/js/congress_trades.ts`, `web_dashboard/src/js/social_sentiment.ts`, `web_dashboard/templates/ticker_details.html`, `web_dashboard/src/js/dashboard.ts`).
