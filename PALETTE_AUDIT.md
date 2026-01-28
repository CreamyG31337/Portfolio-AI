# 🎨 Palette Audit Report

This document outlines the findings from a design system and CSS audit of the `web_dashboard` codebase. The goal is to identify opportunities to better leverage Tailwind CSS and Flowbite, improve accessibility, and ensure maintainability.

## 🔍 Executive Summary

The codebase is well-structured but currently suffers from a "conflict of interest" between its custom theming system and Tailwind's utility-first philosophy. Critical overrides in `theme.css` prevent standard Tailwind usage, and several UI patterns (Sidebar, Tabs, Button Groups) are reimplemented with custom logic instead of leveraging the available Flowbite components.

## 🚨 Critical Findings

### 1. `theme.css` Breaks Utility-First Contract
**Location:** `web_dashboard/static/css/theme.css`
**Issue:** Global styles for `input`, `select`, `textarea`, and `button` are defined with `!important` to enforce CSS variable usage.
```css
input, select, textarea {
    background-color: var(--bg-tertiary) !important;
    /* ... */
}
```
**Why it matters:** This makes it impossible to use standard Tailwind utilities like `bg-red-500` or `border-blue-300` on form elements without writing even more specific custom CSS. It defeats the primary purpose of using Tailwind (utility composition).
**Suggestion:**
1.  Map the CSS variables (e.g., `var(--bg-tertiary)`) to Tailwind colors in `tailwind.config.js` (e.g., `colors: { dashboard: { surface: 'var(--bg-tertiary)' } }`).
2.  Use `@layer base` in `input.css` to apply default styles *without* `!important`.
3.  Let Tailwind's cascade handle overrides naturally.
**Scope:** Systemic

### 2. Hybrid Sidebar Implementation
**Location:** `web_dashboard/src/js/ui.ts`
**Issue:** The sidebar collapse logic manually manipulates `style.width`, `style.marginLeft`, and `style.opacity` using pixel values (`256px`, `64px`).
```typescript
sidebar.style.width = `${SIDEBAR_COLLAPSED_WIDTH}px`;
mainContent.style.marginLeft = `${SIDEBAR_COLLAPSED_WIDTH}px`;
```
**Why it matters:** This creates a dependency on hardcoded pixel values that may drift from the Tailwind config (`w-64`, `w-16`). It also mixes imperative DOM manipulation with declarative CSS classes, making the code harder to maintain and test.
**Suggestion:** Refactor `ui.ts` to toggle a state class (e.g., `sidebar-collapsed`) on the parent container. Use Tailwind's arbitrary variants or group modifiers (e.g., `group-[.sidebar-collapsed]:w-16`) to handle the width and visibility changes in CSS/Tailwind, rather than JS.
**Scope:** Component (Sidebar)

## 🛠 Flowbite Underutilization

### 3. Manual Tab Implementations
**Location:** `web_dashboard/templates/logs.html`, `web_dashboard/templates/auth.html`
**Issue:** Tabs are implemented with custom `div`s and inline/custom JS event handlers that manually toggle generic classes (`hidden`, `block`).
**Why it matters:** Flowbite provides a robust [Tabs component](https://flowbite.com/docs/components/tabs/) that handles accessibility (ARIA roles), keyboard navigation, and styling consistency out of the box.
**Suggestion:** Replace custom tab logic with Flowbite's data-attribute API (`data-tabs-target`, `role="tablist"`).
**Scope:** Local

### 4. Custom Button Groups
**Location:** `web_dashboard/templates/dashboard.html` (Time Range Selector)
**Issue:** The time range selector ("1M", "3M", "All") uses a custom implementation of a button group.
**Why it matters:** Flowbite has a standard [Button Group](https://flowbite.com/docs/components/button-group/) pattern that ensures proper border collapsing, focus rings, and semantic structure.
**Suggestion:** Adopt the Flowbite `inline-flex rounded-md shadow-sm` pattern with proper focus state management.
**Scope:** Local

### 5. Manual Password Visibility Toggle
**Location:** `web_dashboard/templates/settings.html`
**Issue:** The "Show Password" functionality is implemented with custom JS event listeners and manually toggles icons.
**Why it matters:** While functional, this is a standard pattern that can be standardized.
**Suggestion:** Ensure `aria-label` is dynamically updated ("Show password" vs "Hide password") for accessibility.
**Scope:** Local

## 🎨 Best Practice Violations

### 6. Iconography Inconsistency
**Location:** Global
**Issue:** The project relies heavily on FontAwesome (`fas fa-...`), whereas Flowbite and Tailwind best practices typically favor SVG icons (like Heroicons) to reduce page load (no large font file) and allow for better Tailwind styling integration (e.g., `w-6 h-6 text-current`).
**Why it matters:** FontAwesome adds a significant render-blocking resource. SVGs are inline and instantly styleable.
**Suggestion:** Gradually migrate to inline SVGs or a lightweight SVG library compatible with Flowbite.
**Scope:** Systemic

## ✅ Immediate Action Items (Safe)

1.  **Refactor Tabs:** Convert `logs.html` tabs to use Flowbite's data attributes.
2.  **Standardize Button Groups:** Update the dashboard time range selector to match Flowbite's button group styling.
3.  **Audit ARIA:** Ensure all custom interactive elements (like the password toggle) have valid and updating `aria-*` attributes.

---
*Generated by Palette 🎨*
