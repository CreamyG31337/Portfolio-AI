# 🎨 Palette Audit Report

This document outlines findings from a design system and CSS audit of the codebase. The goal is to identify opportunities to better leverage Tailwind CSS and Flowbite, improve accessibility, and ensure maintainability.

## 🚨 Critical Findings

### 1. Manual "Alert" Components
**Issue:** Custom alert implementations duplicate Flowbite components. Specifically, `dashboard-error-container` in `web_dashboard/templates/dashboard.html` and the `web_dashboard/templates/components/_alert.html` component use manual classes instead of standard Flowbite Alert components.
**Why it matters:** Missing proper accessibility attributes, standard sizing, and built-in interactive dismissibility behaviors provided out of the box by Flowbite. Reduces consistency across the application.
**Suggestion:** Replace manual implementations with the standardized Flowbite Alert component.
**Scope:** Reusable / Systemic

### 2. Hardcoded Inline Hex Colors
**Issue:** Hardcoded hex colors via inline styles in AG Grid cell renderers. In `web_dashboard/src/js/congress_positions.ts`, inline styles (`style="color: ${color}"`) are used to colorize text.
**Why it matters:** Hardcoded colors bypass the design system's theme capabilities, which can break layout consistency and fail to support dynamic dark/light mode switching.
**Suggestion:** Map the logic to output the project's semantic Tailwind utility classes (like `text-theme-success-text` or `text-theme-error-text`) instead of static color values.
**Scope:** Local (component-level)

### 3. Explicit Inline Styles for Dimensions in JS
**Issue:** Explicit inline styles for dimensions are set in JavaScript. In `web_dashboard/src/js/signals.ts`, `web_dashboard/src/js/congress_trades.ts`, `web_dashboard/src/js/social_sentiment.ts`, and `web_dashboard/src/js/etf_holdings.ts`, `img.style.width = '24px'` is used.
**Why it matters:** Setting explicit pixel values via inline styling ignores the utility-first approach and the standard spacing scale of Tailwind, which can lead to inconsistencies and make responsive design harder to maintain.
**Suggestion:** Avoid setting `style.width`. Instead, apply standard Tailwind utility classes (e.g., by adding `w-6` via `classList`) to ensure sizing consistency.
**Scope:** Reusable
