Issue: Hardcoded hex colors and inline styles used for grid cell rendering in `web_dashboard/src/js/congress_positions.ts`.
Why it matters: Using hardcoded hex values (`#4ade80`, `#f87171`, `#9ca3af`) via inline `style` attributes breaks layout consistency, duplicates Tailwind utility functionality, and prevents proper dynamic color support for the application's different themes (e.g. Dark Mode, Midnight Tokyo).
Suggestion: Replace the inline styles and hex strings with semantic Tailwind CSS utility classes (e.g., `text-theme-success-text`, `text-theme-error-text`, `text-text-tertiary`) combined with standard font-weight classes like `font-semibold`.
Scope: Local (component-level within the `positionsGridApi` column definitions).
