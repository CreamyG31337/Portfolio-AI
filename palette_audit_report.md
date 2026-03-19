# Palette Design Audit Report

**Issue:** Custom modal implementation duplicates Flowbite modal behavior
**Why it matters:** Manually toggling the `hidden` class and manipulating `document.body.style.overflow` misses Flowbite's built-in accessibility features (like focus trapping and ARIA management) and creates fragile, hard-to-maintain code.
**Suggestion:** Replace the manual Javascript toggling in `viewEmail` and `closeEmailModal` with standard Flowbite data attributes (`data-modal-target`, `data-modal-toggle`) or use the programmatic JavaScript API (`new Modal(element)`).
**Scope:** Local (`web_dashboard/templates/newsletters.html`)

**Issue:** Hardcoded hex colors via inline styles in TypeScript cell renderers
**Why it matters:** Using inline styles like `<span style="color: ${color};">` with hardcoded hex values (`#4ade80`, `#f87171`) circumvents the design system and breaks consistency, especially for dark mode compatibility.
**Suggestion:** Map the conditional logic to semantic Tailwind text color utility classes (e.g., `text-theme-success-text` or `text-theme-error-text`) and apply them via `class="..."` instead of inline styles.
**Scope:** Local (`web_dashboard/src/js/congress_positions.ts`)

**Issue:** Arbitrary pixel values used for sizing
**Why it matters:** Using arbitrary values like `h-[300px]`, `min-h-[400px]`, or `max-h-[420px]` violates the utility-first approach and can lead to inconsistent responsive layouts.
**Suggestion:** Replace these arbitrary pixel values with standard Tailwind spacing scale utilities (e.g., `h-72`, `max-h-screen`, `min-h-full`) to ensure a consistent, predictable layout across the application.
**Scope:** Systemic (Multiple HTML templates including `dashboard.html`, `research.html`, and `newsletters.html`)
