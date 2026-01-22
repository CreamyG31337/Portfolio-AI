# Palette 🎨 Design System Audit

This audit identifies opportunities to better leverage Tailwind CSS and Flowbite, improve accessibility, and standardize UI patterns across the `web_dashboard` codebase.

## 1. Tailwind CSS Best Practices

### Global CSS Overrides in `theme.css`
**Issue**: Aggressive global overrides with `!important` on base elements (`input`, `select`, `textarea`).
**Why**: This violates Tailwind's utility-first philosophy, making it impossible to override styles with utility classes (e.g., `bg-red-500` won't work). It breaks component composability.
**Suggestion**: Remove `!important`. Move base styles to `input.css` using the `@layer base` directive or use the `@tailwindcss/forms` plugin to handle form defaults gracefully.
**Scope**: Systemic (`web_dashboard/static/css/theme.css`)

### Duplicate Dark Mode Logic
**Issue**: `theme.css` manually implements dark mode logic using `[data-theme="dark"]` selectors, duplicating Tailwind's built-in `dark:` modifier.
**Why**: Increases CSS bundle size and maintenance burden. Tailwind's `dark:` variant is tree-shakeable and standard.
**Suggestion**: Refactor `theme.css` to map CSS variables to Tailwind's `dark:` class strategy. Use Tailwind's `darkMode: 'class'` config (already likely present) and rely on the `dark` class on the `<html>` tag, which `theme.ts` already toggles.
**Scope**: Systemic (`web_dashboard/static/css/theme.css`)

### Repeated Utility Patterns
**Issue**: Long, repeated class strings for form elements in `auth.html` and `dashboard.html`.
Example: `w-full px-3 py-2 border rounded-md` appears multiple times.
**Why**: Hard to maintain consistency. If we change the border radius, we have to find/replace all instances.
**Suggestion**: Use `@apply` in `input.css` to create semantic component classes (e.g., `.input-primary`, `.btn-primary`) or encapsulate these in Jinja2 macros.
**Scope**: Local / Reusable (`web_dashboard/templates/auth.html`)

## 2. Flowbite Underutilization

### Manual Sidebar Implementation
**Issue**: The sidebar in `_sidebar_content.html` and `ui.ts` uses custom JavaScript and CSS transitions for collapsing/expanding.
**Why**: Reinvents the wheel. Flowbite provides a robust [Drawer/Sidebar component](https://flowbite.com/docs/components/sidebar/) that handles accessibility, focus trapping, and responsive behavior out of the box.
**Suggestion**: Replace the manual `collapseSidebar` logic in `ui.ts` with Flowbite's data attributes (`data-drawer-target`, `data-drawer-toggle`) or the `Drawer` object from the Flowbite JS API.
**Scope**: Systemic (`web_dashboard/src/js/ui.ts`, `web_dashboard/templates/components/_sidebar_content.html`)

### Custom Spinners
**Issue**: `dashboard.html` implements custom spinners using `animate-spin rounded-full h-8 w-8 border-b-2...`.
**Why**: Inconsistent visual language. Flowbite has a standard [Spinner component](https://flowbite.com/docs/components/spinner/) with defined sizes and colors.
**Suggestion**: Replace custom spinner `div`s with Flowbite's spinner pattern for consistency.
**Scope**: Local (`web_dashboard/templates/dashboard.html`)

## 3. Best Practice Violations

### Accessibility: Missing Focus States
**Issue**: Interactive elements (e.g., error retry buttons, dividend toggle) in `dashboard.html` lack consistent `focus-visible` states.
**Why**: Keyboard users cannot easily tell which element is focused, a major accessibility failure.
**Suggestion**: Add `focus:ring-2 focus:ring-accent` (or similar) to all interactive elements, matching the "Good" examples found in `auth.html`.
**Scope**: Local (`web_dashboard/templates/dashboard.html`)

### Hardcoded Colors in TypeScript
**Issue**: `ui.ts` hardcodes Tailwind class strings for badges (e.g., `text-green-800 bg-green-100`).
**Why**: If the theme colors change in `tailwind.config.js`, these hardcoded values will drift.
**Suggestion**: Use the semantic colors defined in `tailwind.config.js` (e.g., `text-theme-success-text`) instead of raw color palette values.
**Scope**: Local (`web_dashboard/src/js/ui.ts`)

### Non-Semantic Elements
**Issue**: Theme toggle button in `auth.html` uses inline SVG icons.
**Why**: While not strictly wrong, it clutters the template.
**Suggestion**: Use an icon library (FontAwesome is already included) or extract SVGs to a partial to keep the template clean.
**Scope**: Local (`web_dashboard/templates/auth.html`)

## Summary of Recommendations

1.  **Refactor `theme.css`**: Remove `!important` and lean on Tailwind utilities.
2.  **Adopt Flowbite Drawer**: Delete custom sidebar JS code.
3.  **Standardize Form Components**: Extract common form styles.
4.  **Fix Accessibility**: Audit and add focus rings to all buttons in the dashboard.
