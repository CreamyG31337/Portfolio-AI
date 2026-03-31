# Tailwind & Flowbite Design System Audit 🎨

This audit identifies places where Tailwind CSS and Flowbite are underutilized, misused, or bypassed in favor of custom styles, arbitrary values, or reinvented patterns.

## 1. Missed Tailwind Opportunities & Best Practice Violations

**Issue**: Arbitrary pixel values for sizing (e.g., `h-[300px]`, `max-h-[420px]`, `min-w-[200px]`, `w-[60px]`) are heavily used across templates (`research.html`, `dashboard.html`, `ticker_details.ts`, `jobs.ts`).
**Why it matters**: Bypassing Tailwind's standard spacing scale (`h-72`, `max-h-screen`, `w-16`) leads to inconsistent visual rhythm, makes responsive design harder to maintain, and breaks the utility-first constraint system.
**Suggestion**: Replace arbitrary pixel values with the closest standard Tailwind spacing utility. If dynamic dimensions are strictly necessary (e.g., progress bars), use inline CSS variables (`style="--bar-width: X%"`) combined with arbitrary value classes (`w-[var(--bar-width)]`).
**Scope**: Systemic

---

**Issue**: Hardcoded inline styles (e.g., `style="display: none;"`) are used for toggling visibility in static HTML files (`login.html`, `set_cookie.html`).
**Why it matters**: Inline styles bypass Tailwind's utility system entirely, increasing CSS specificity unnecessarily and making the layout harder to control via responsive breakpoints or dark mode variants.
**Suggestion**: Convert inline styles to standard Tailwind utility classes (use `hidden` instead of `display: none;`). Manage visibility toggling in JavaScript by adding/removing the `hidden` class via `classList`.
**Scope**: Local / Reusable

---

**Issue**: Custom inline color and font-weight styles (e.g., `<span style="color: ${color}; font-weight: 600;">`) are dynamically generated in TypeScript files (`congress_positions.ts`).
**Why it matters**: Hardcoding hex colors directly in JS string interpolation breaks dark mode compatibility and deviates from the project's semantic color system (e.g., `--color-success-text`).
**Suggestion**: Map text colors to the project's semantic Tailwind utility classes (e.g., `text-theme-success-text`, `text-theme-error-text`) and use `font-semibold` instead of inline styles to ensure design consistency across themes.
**Scope**: Reusable

---

**Issue**: Direct manipulation of element styles via JavaScript DOM API (e.g., `element.style.width = '24px'`).
**Why it matters**: Modifying inline styles directly via JS creates disconnected styling logic that is hard to debug and overrides Tailwind utilities.
**Suggestion**: Apply standard Tailwind utility classes dynamically (e.g., `element.classList.add('w-6')`) instead of modifying inline styles directly.
**Scope**: Local

## 2. Flowbite Underutilization & Reinvented Patterns

**Issue**: Repeated custom toast notification logic is duplicated across multiple TypeScript files and HTML templates (`jobs.ts`, `users.ts`, `newsletters.html`), rather than relying on a unified component.
**Why it matters**: Reinventing standard UI interactive components leads to visual inconsistency and reduces maintainability, while potentially missing accessibility features like ARIA roles that Flowbite handles automatically.
**Suggestion**: Standardize on Flowbite's built-in toast notification components and data attributes (`data-dismiss-target`) to ensure a unified user experience and proper accessibility out-of-the-box.
**Scope**: Systemic

---

**Issue**: Custom switch toggles implemented using verbose manual Tailwind pseudo-classes (e.g., `peer-checked:after:translate-x-full`).
**Why it matters**: Flowbite provides a standardized toggle component. Re-implementing this manually clutters the markup and increases the risk of accessibility regressions (missing focus rings, states).
**Suggestion**: Use Flowbite's standard toggle component markup. If custom styling is strictly necessary, encapsulate the Flowbite base into an `@apply` directive rather than writing raw complex utility chains inline.
**Scope**: Reusable
