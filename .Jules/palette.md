## 2024-05-23 - Authentication Forms Autocomplete

**Learning:** Missing `autocomplete` attributes on authentication forms are a common but critical oversight. Adding them significantly improves the user experience by enabling browser autofill and password manager integration, which also aids accessibility by reducing cognitive load and typing errors.

**Action:** Always audit form inputs for `autocomplete` attributes, especially for email, password, and username fields. Use specific values like `username`, `current-password`, and `new-password`.
