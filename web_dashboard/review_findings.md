## Tailwind & Flowbite Improvements Found

### 1. Hardcoded Inline Styles in JS Components (Tailwind Anti-Pattern)
- `web_dashboard/src/js/ticker_details.ts`: Found extensive use of `style.display = 'block'` and `style.display = 'none'` rather than using Tailwind's `hidden` utility class via `classList.add('hidden')`. Addressed.
- `web_dashboard/src/js/ai_settings.ts`: Also had instances of `style.display` logic for component visibility (e.g., `verboseOutput`). Addressed.
- `web_dashboard/templates/research.html`: Inline JS setting `style.display = 'none'` instead of class list modification. Addressed.
- These violate Tailwind's utility-first principles by injecting hardcoded styles rather than changing state via utility classes.

### 2. Leftover TODOs Flagging Anti-Patterns
- `web_dashboard/src/js/ai_assistant.ts` and `web_dashboard/src/js/jobs.ts`: Contained temporary textarea elements explicitly using `style.position = 'fixed'` and `style.opacity = '0'`. Replaced with Tailwind's `sr-only` class.
- `web_dashboard/src/js/congress_positions.ts`: Column renderer used hardcoded hex colors (`#4ade80`, `#f87171`) within inline style tags instead of utilizing the configured theme variables (e.g., `text-theme-success-text`). Replaced the inline string concatenation with standard Tailwind semantic utility classes.

### 3. Redundant style.removeProperty Usage
- `web_dashboard/src/js/ticker_details.ts`: Leftover call to `style.removeProperty('display')` right after a `classList.remove('hidden')`, which is redundant and can break the cascade. Cleaned up.

These changes directly align with the Palette Audit goals to eliminate custom CSS strings from JavaScript logic, increase reliance on Tailwind utilities, and replace arbitrary hex color bindings with semantic tokens that properly react to dark mode/themes.

### 4. Remove custom Research tab logic replacing Flowbite
- `web_dashboard/templates/research.html`: Found custom JS for a tab switching component. As the TODO correctly flagged, this replicates standard Flowbite tab functionality, increasing JS bundle size and diverging from the site's standardized Flowbite components setup. Removed the custom code.

### 5. Remove Duplicate Ghost Button Class
- `web_dashboard/static/css/input.css`: Found two identical classes: `.btn-outline` and `.btn-outline-accent`. Removed `.btn-outline-accent` and replaced its usages in `web_dashboard/templates/auth.html` with `.btn-outline`.

### 6. Remove Redundant `.card` Utility Class
- `web_dashboard/static/css/input.css`: The `.card` CSS class was just a thin wrapper for `@apply bg-dashboard-surface rounded-lg border border-border;`. As flagged by the TODO, this violates utility-first principles by abstracting too early. Replaced all usages of `.card` with `bg-dashboard-surface rounded-lg border border-border` in the templates and removed the class from `input.css`.
