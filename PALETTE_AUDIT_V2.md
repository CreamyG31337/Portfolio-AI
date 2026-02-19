# Palette Audit V2

This report identifies critical dependency mismatches, CSS overrides, and opportunities for component standardization within the `web_dashboard` codebase.

## 1. Critical Dependency Mismatch

**Issue**: Version conflict between root `package.json` and `web_dashboard/package.json`.
- **Root**: `tailwindcss: ^4.1.0`, `flowbite: ^4.0.1` (used by build process).
- **Subdirectory**: `tailwindcss: ^3.4.1`, `flowbite: ^2.5.2` (used for TypeScript/Dev).

**Why it matters**: The build process (driven by root `package.json`) compiles CSS using Tailwind v4 and Flowbite v4, while local development or TypeScript checking (driven by `web_dashboard/package.json`) expects v3/v2. This discrepancy can lead to:
- Missing types for new v4 features.
- Unexpected CSS behavior due to v4's breaking changes (e.g., variable-based theming).
- "Works on my machine" issues where dev environment differs from build environment.

**Suggestion**: Update `web_dashboard/package.json` to match the root versions:
```json
"tailwindcss": "^4.1.0",
"flowbite": "^4.0.1"
```

## 2. CSS Refactoring

**Issue**: `web_dashboard/static/css/input.css` contains `!important` overrides and bundled utility classes.
- **Overrides**: `input[type="text"].bg-dashboard-surface-alt ... !important` forces theme colors, bypassing Flowbite v4's native CSS variable theming.
- **Bundling**: `.form-input-theme` and `.btn-outline` use `@apply` to bundle utilities, which is an anti-pattern when overused and fights against atomic CSS benefits.

**Why it matters**:
- **Maintainability**: `!important` makes it difficult to override styles contextually without escalating specificity wars.
- **Compatibility**: Flowbite v4 uses CSS variables for theming. Hardcoded overrides break this system and require manual updates for every theme change.

**Suggestion**:
- Remove `!important` overrides.
- Adopt Flowbite v4's CSS variable system for theming inputs globally.
- Replace `.form-input-theme` with standard Flowbite input classes or configured theme defaults.

## 3. Component Standardization

### Button Groups
**Issue**: `dashboard.html` uses manual HTML/CSS (custom classes, border manipulation) for the "Time Range" selector.
**Why**: Reimplementing this pattern is error-prone and often misses accessibility details.
**Suggestion**: Use Flowbite's `Button Group` component:
```html
<div class="inline-flex rounded-md shadow-sm" role="group">
  <button type="button" class="px-4 py-2 text-sm font-medium ... rounded-s-lg ...">1M</button>
  <button type="button" class="px-4 py-2 text-sm font-medium ... border-t border-b ...">3M</button>
  <button type="button" class="px-4 py-2 text-sm font-medium ... rounded-e-lg ...">All</button>
</div>
```

### Alerts
**Issue**: `dashboard.html` uses a custom `#dashboard-error-container` div instead of a standard Alert component.
**Why**: Inconsistent styling and behavior compared to the rest of the UI.
**Suggestion**: Replace with Flowbite's `Alert` component for consistent dismissal behavior and accessibility.

### Modals
**Issue**: `_confirm_modal.html` uses custom DOM manipulation (`window.showConfirmModal`).
**Why**: Bypasses Flowbite's accessible Modal API (focus trapping, backdrop management, lifecycle events).
**Suggestion**: Refactor to use the Flowbite `Modal` JavaScript API:
```javascript
import { Modal } from 'flowbite';
const modal = new Modal($targetEl, options);
modal.show();
```

### Loading Spinners
**Issue**: `_loading_spinner.html` uses a custom `div` with `border-b-2`.
**Why**: Inconsistent with the design system's potential use of SVG spinners.
**Suggestion**: Standardize on Flowbite's SVG spinner for better scaling and visual consistency.

## 4. Auth Form Simplification
**Issue**: `auth.html` uses verbose manual JavaScript for toggling between Login, Register, and Forgot Password forms.
**Why**: Adds unnecessary complexity to the codebase.
**Suggestion**: Simplify using Flowbite's `Tabs` component or utility classes for state management, or refactor to use a cleaner state-driven approach.
