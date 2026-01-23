# Palette's Journal

## 2024-05-23 - Initial Setup
**Learning:** The project uses a mix of server-side rendered templates (Flask) and client-side TypeScript. Accessibility issues are present in the templates (missing ARIA labels, interactive elements without keyboard support).
**Action:** Focus on adding ARIA attributes and improving keyboard navigation in HTML templates, while checking TypeScript for dynamic behavior.

## 2024-05-23 - Authentication Forms Autocomplete

**Learning:** Missing `autocomplete` attributes on authentication forms are a common but critical oversight. Adding them significantly improves the user experience by enabling browser autofill and password manager integration, which also aids accessibility by reducing cognitive load and typing errors.

**Action:** Always audit form inputs for `autocomplete` attributes, especially for email, password, and username fields. Use specific values like `username`, `current-password`, and `new-password`.

## 2025-02-12 - Auth Forms and Button Semantics
**Learning:** Users often scan authentication forms quickly. Adding placeholders (e.g., `name@example.com`, `••••••••`) significantly improves usability by providing a visual hint of the expected input format. Also, explicitly setting `type="button"` on buttons that are not intended to submit forms is crucial to prevent unexpected behavior and adhere to HTML standards.
**Action:** Always check for placeholders in form inputs and verify button types in future UI enhancements.
