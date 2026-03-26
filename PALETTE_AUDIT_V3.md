# 🎨 Palette Audit Report (V3)

This document outlines the findings from a design system and CSS audit of the `web_dashboard` codebase. The goal is to identify opportunities to better leverage Tailwind CSS and Flowbite, improve accessibility, and ensure maintainability.

## 🚨 Critical Findings

### 1. Reimplementing Flowbite Markup Incorrectly (Modals without focus trapping)
**Location:** `web_dashboard/templates/trade_entry.html`
**Issue:** The "Edit Trade" and "Delete Trade" dialogs are implemented using custom HTML classes (`hidden fixed inset-0 z-50 flex items-center justify-center bg-black/50`) and custom JS for showing/hiding rather than using Flowbite's standard interactive components.
**Why it matters:** Missing focus trap and keyboard handling reduces accessibility. Hand-rolled modals without keyboard navigation (`ESC` key to close) and ARIA attributes degrade user experience.
**Suggestion:** Replace custom modal markup/JS with Flowbite modal components (`data-modal-target`, `data-modal-toggle`, `data-modal-hide`) to ensure ARIA, focus management, and consistency.
**Scope:** Local (Component-level)


### 2. Custom UI Implementations Replacing Flowbite
**Location:** `web_dashboard/templates/newsletters.html`
**Issue:** The "Email View" modal uses a custom implementation (`id="email-view-modal"`) relying on manual inline Javascript like `onclick="if(event.target === this) closeEmailModal()"` and custom CSS variables like `hidden fixed top-0 right-0 left-0`.
**Why it matters:** Missing proper keyboard navigation, ARIA handling, and standardized state transitions. Manual event listeners lead to bugs and inconsistent behavior across the application.
**Suggestion:** Replace custom modal show/hide logic with the Flowbite Modal API to ensure consistent behavior, focus trapping, and accessibility across all page models.
**Scope:** Local (Component-level)

### 3. Inline JavaScript Styles Bypassing Tailwind
**Location:** `web_dashboard/src/js/` (`signals.ts`, `congress_trades.ts`, `social_sentiment.ts`, `etf_holdings.ts`)
**Issue:** Cell renderers create DOM nodes dynamically using JavaScript properties for layout and size styling. e.g. `img.style.width = '24px'`, `img.style.flexShrink = '0'`, and `this.eGui.style.display = 'flex'`.
**Why it matters:** Sizing elements via JavaScript using arbitrary pixel values violates the utility-first CSS contract, breaking consistency with the project’s layout (e.g. `w-6`). These inline values often do not support native state handling or dark mode efficiently.
**Suggestion:** Replace direct style assignments with Tailwind CSS utility classes by appending them using the classList API (e.g., `classList.add('flex', 'items-center', 'gap-1.5')` for containers and `classList.add('w-6', 'h-6', 'shrink-0')` for images).
**Scope:** Reusable (Grid Component Level)
