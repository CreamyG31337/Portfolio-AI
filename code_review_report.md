# Code Review Report

## Commit `0a17874c` (Close UI quick-win TODOs for dashboard and ticker detail styling)
- **Finding**: The commit incorrectly uses a custom CSS class `.ticker-composite-progress` for dynamic width styling instead of the required standard Tailwind arbitrary value class (`w-[var(--bar-width)]`). The project standard prefers applying Tailwind utility classes directly (e.g., `class="w-[var(--bar-width)]"`) rather than creating custom CSS classes.

## Commit `7a69ae18` (Harden social-media LLM ingestion against prompt-style input)
- **Finding**: The `sanitize_for_llm` function fails to explicitly replace angle brackets (`< >`) with square brackets (`[ ]`). This violates the project's prompt safety security standard for handling untrusted free-text fields.

## Commit `fb53faf6` (Simplify redundant company-name type check in table formatter)
- **Finding**: Removing the `isinstance(company_name, str)` check is potentially unsafe. Data originating from Pandas/CSV might contain `float('nan')` for the `company_name` field. This would cause a `TypeError` when calling `len()` on it. The code should handle `nan` values explicitly as per the data handling pattern.
