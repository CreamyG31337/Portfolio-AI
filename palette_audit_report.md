# Tailwind and Flowbite Code Audit Report

## Issue: Custom modal implementation duplicates Flowbite modal behavior
**Why it matters:** The `#email-view-modal` in `newsletters.html`, `#edit-trade-modal` in `trade_entry.html`, and `#delete-trade-modal` in `trade_entry.html` are hand-rolled. Missing Flowbite data attributes (`data-modal-target`, `data-modal-toggle`, `data-modal-hide`) forces custom JS handling and misses built-in accessibility (ARIA roles, focus trapping).
**Suggestion:** Replace these hand-rolled modals and custom JavaScript toggle logic with Flowbite's native Modal component structure and attributes.
**Scope:** Local (template-level)

## Issue: Custom drawer implementation duplicates Flowbite drawer behavior
**Why it matters:** The `#ai-drawer-backdrop` and toggle logic in `ai_assistant.html` are manually implemented. This bypasses standard `data-drawer-target` and accessibility handling for focus trapping and escape key dismissal.
**Suggestion:** Replace the custom JavaScript toggle and backdrop with Flowbite's native Drawer component attributes.
**Scope:** Local (template-level)

## Issue: Custom CSS overriding internal AgGrid styles
**Why it matters:** Hardcoded RGBA colors (`rgba(0, 200, 83, 0.08)`) in the `<style>` block in `insider_trades.html` break semantic theming (light/dark mode) and bypass Tailwind's design token system.
**Suggestion:** Since AgGrid row styling is complex, either move these specific definitions to the global `input.css` using Tailwind `@apply` (e.g., `bg-theme-success-bg/10`), or use AgGrid's JS `getRowStyle` API to apply standard Tailwind classes directly to rows, enabling dynamic theming.
**Scope:** Local (template-level)

## Issue: Hardcoded CSS inside iframe instead of Tailwind utility classes
**Why it matters:** The injected `<style>` block inside the `doc.write` in `newsletters.html` duplicates design tokens and styling logic, reducing consistency.
**Suggestion:** While iframes restrict stylesheet inheritance, consider injecting a minified Tailwind stylesheet or using Tailwind's typography plugin classes directly if the email HTML supports it, to maintain a consistent look-and-feel.
**Scope:** Local (template-level)

## Issue: Inline style `style="width: 0%"` used for dynamic progress bar width
**Why it matters:** In `ticker_details.html`, inline widths are used for progress bars (`#momentum-composite-bar` and `#fund-composite-bar`). While JS manipulates this value, inline styles bypass the utility-first methodology.
**Suggestion:** If the initial state is zero, consider using `w-[0%]` Tailwind utility and have JS toggle dynamic Tailwind `w-[x%]` classes if arbitrary values support it. (Note: Inline style for progress bar width is a common edge-case exception, but should be evaluated against Tailwind).
**Scope:** Local (template-level)
