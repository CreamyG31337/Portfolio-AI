# 🎨 Palette Audit Report

This document outlines the findings from a design system and CSS audit of the `web_dashboard` codebase. The goal is to identify opportunities to better leverage Tailwind CSS and Flowbite, improve accessibility, and ensure maintainability.

## 🔍 Executive Summary

The codebase generally adheres to Tailwind CSS conventions but suffers from a few key issues:
1.  **Rigid Global Overrides:** `theme.css` uses `!important` too aggressively, breaking the "utility-first" promise of Tailwind.
2.  **Hybrid UI Patterns:** Components like the Sidebar mix custom logic with Flowbite attributes, creating complexity.
3.  **Inline Styles:** Some templates (e.g., `auth.html`) use inline styles that should be Tailwind utilities.
4.  **Flowbite Underutilization:** Standard UI elements (Forms, Alerts) are often hand-rolled instead of using Flowbite components.

## 🚨 Critical Findings

### 1. Excessive `!important` in `theme.css`
**Location:** `web_dashboard/static/css/theme.css`
**Issue:** Global styles for `input`, `select`, `textarea`, and `button` are defined with `!important`.
```css
input, select, textarea {
    background-color: var(--bg-tertiary) !important;
    /* ... */
}
```
**Why it matters:** This makes it impossible to override these styles with Tailwind utilities (e.g., `bg-red-500`) without writing more specific custom CSS or using inline styles. It defeats the purpose of a utility-first framework.
**Suggestion:** Move these base styles to Tailwind's `@layer base` directive in `input.css` and remove `!important`.

### 2. Hybrid Sidebar Implementation
**Location:** `web_dashboard/templates/components/_sidebar_content.html`
**Issue:** The sidebar uses a mix of Flowbite data attributes (in header) and custom CSS classes/JS for collapsing/expanding.
**Why it matters:** This duplication logic increases maintenance burden and can lead to visual bugs (e.g., conflicting transforms).
**Suggestion:** Standardize on Flowbite's `Drawer` and `Sidebar` components completely, removing custom collapse logic if possible.

### 3. Inline Styles in Authentication Template
**Location:** `web_dashboard/templates/auth.html`
**Issue:** Uses `style="display: none;"` for visibility toggling.
**Why it matters:** Inconsistent with the class-based state management of Tailwind.
**Suggestion:** Replace with the `hidden` utility class.

### 4. Custom Form Implementations
**Location:** `web_dashboard/templates/auth.html`
**Issue:** Login/Register forms are built with generic Tailwind classes rather than standard Flowbite Form components.
**Why it matters:** Misses out on built-in accessibility features and consistent focus states provided by Flowbite.
**Suggestion:** Refactor forms to use Flowbite's input and label classes.

## 🛠 Best Practice Violations

-   **Accessibility:** Email inputs in `auth.html` lack `inputmode="email"`.
-   **Iconography:** The project mixes FontAwesome with SVG icons. Consolidating to one set (preferably Heroicons/Flowbite SVGs) would reduce bundle size.
-   **Focus Management:** Manual form switching in `auth.html` does not manage focus, which is a barrier for screen reader users.

## ✅ Action Plan

1.  **Immediate Fix:** Refactor `auth.html` to remove inline styles and add `inputmode`. (In Progress)
2.  **Short Term:** Remove `!important` from `theme.css` and test for regressions.
3.  **Long Term:** Refactor Sidebar to strictly use Flowbite logic.
