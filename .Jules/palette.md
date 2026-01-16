## 2024-05-22 - Missing Skip Links
**Learning:** The application lacks "Skip to main content" links, forcing keyboard users to tab through the entire navigation menu on every page load. This is a critical accessibility barrier for power users and those relying on assistive technology.
**Action:** Implement a global skip link in `base.html` using `sr-only` and `focus:not-sr-only` utility classes to ensure it's available when needed but invisible otherwise.
