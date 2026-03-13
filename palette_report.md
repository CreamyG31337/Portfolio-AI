# Tailwind & Flowbite Code Audit Report

**Issue:** Custom modal implementation duplicates Flowbite modal behavior in `web_dashboard/templates/trade_entry.html` (`#edit-trade-modal`, `#delete-trade-modal`) and `web_dashboard/templates/ai_assistant.html` (`#ai-drawer-backdrop`).
**Why it matters:** Missing focus trap, ARIA attributes (`aria-hidden="true"`, `tabindex="-1"`), and keyboard handling (Esc to close) reduces accessibility. Hand-rolled implementations duplicate existing Flowbite functionality.
**Suggestion:** Replace custom Tailwind classes (`hidden fixed inset-0 z-50 flex items-center justify-center bg-black/50`) with standard Flowbite modal/drawer components and data attributes (`data-modal-target`, `data-modal-toggle`) to ensure ARIA compliance, focus management, and consistency.
**Scope:** Local (`trade_entry.html`, `ai_assistant.html`)

---

**Issue:** Inline styles used for width on composite bars in `web_dashboard/templates/ticker_details.html` (`style="width: 0%"`).
**Why it matters:** Violates Tailwind's utility-first approach and makes it harder to manage dynamic dimensions predictably within the design system.
**Suggestion:** Use inline CSS variables combined with arbitrary value classes (e.g., `style="--bar-width: 0%"` and `w-[var(--bar-width)]`) rather than direct inline styles for `width`.
**Scope:** Local (`ticker_details.html`)

---

**Issue:** Inline styles used for colors in `web_dashboard/src/js/congress_positions.ts` (`style="color: ${color}; font-weight: 600;"`).
**Why it matters:** Bypasses the project's Tailwind design system and semantic theme colors, reducing consistency and potentially breaking dark mode or dynamic theming.
**Suggestion:** Replace hardcoded hex colors and inline styles with corresponding semantic Tailwind classes (e.g., `text-theme-success-text`, `text-theme-error-text`, `font-semibold`).
**Scope:** Local (`congress_positions.ts`)