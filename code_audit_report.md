**Issue:** Scattered use of arbitrary sizing values (e.g., `h-[300px]`, `min-w-[200px]`, `max-h-[420px]`, `w-[85%]`) instead of using standard Tailwind spacing scales.
**Why it matters:** Hardcoded pixel or percentage values bypass Tailwind's unified design system, leading to inconsistent spacing and layout bugs, specifically with responsive design.
**Suggestion:** Replace arbitrary values with standard Tailwind utilities (e.g., replace `h-[300px]` with `h-72` or `h-80`, `max-h-[400px]` with `max-h-96`).
**Scope:** Systemic across `web_dashboard/templates` (e.g., `research.html`, `dashboard.html`, `ai_settings.html`).

**Issue:** Reimplementation of toggle switches using verbose and conflicting custom pseudo-class chains (e.g., `peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px]...`).
**Why it matters:** Custom pseudo-element implementations are brittle, hard to read, and difficult to maintain. Flowbite already provides standard, accessible switch components that handle state and animation out-of-the-box.
**Suggestion:** Replace these manual checkbox toggles with Flowbite's standard toggle switch component to guarantee uniform styling, semantic structure, and built-in accessibility.
**Scope:** Systemic (e.g., `dashboard.html`, `system.html`, `color_test.html`).

**Issue:** The codebase contains manual modal wrappers and custom tooltips missing ARIA bindings and `data-` attributes expected by Flowbite.
**Why it matters:** Manually reinventing UI patterns like modals/tooltips ignores standard keyboard navigation (e.g., `Esc` to close, focus trapping) and ARIA support, making the application less accessible.
**Suggestion:** Refactor custom modal and tooltip elements to strictly utilize standard Flowbite `data-modal-target`, `data-modal-toggle`, and `data-tooltip-target` attributes, along with their associated JS bindings.
**Scope:** Reusable components/templates.

**Issue:** There are instances where JavaScript modifies styles directly (e.g., `element.style.width = '24px'`) instead of adding utility classes.
**Why it matters:** Direct DOM style manipulation bypasses the Tailwind compilation step, creates a disconnect between HTML and JS, and makes dynamic responsive behavior much harder to manage.
**Suggestion:** Use inline CSS variables (`--bar-width`) combined with arbitrary class values (e.g., `w-[var(--bar-width)]`) or add/remove specific Tailwind utility classes via `classList`.
**Scope:** Systemic across `web_dashboard/src/js/` (e.g., `chart_theme_utils.ts`, `ui.ts`).
