## 2024-05-22 - Missing Skip Links
**Learning:** The application lacks "Skip to main content" links, forcing keyboard users to tab through the entire navigation menu on every page load. This is a critical accessibility barrier for power users and those relying on assistive technology.
**Action:** Implement a global skip link in `base.html` using `sr-only` and `focus:not-sr-only` utility classes to ensure it's available when needed but invisible otherwise.

## 2026-01-17 - Input Auto-formatting UX
**Learning:** Using the `input` event to force text transformation (like uppercase) causes cursor position resets to the end of the input, degrading UX for users editing text in the middle.
**Action:** Use the `change` event (triggers on blur) for non-critical formatting to preserve editing flow, or manage cursor selection range explicitly if using `input`.

## 2026-02-15 - Icon-Only Button Accessibility
**Learning:** Icon-only buttons (like hamburger menus) rely solely on visual cues, leaving screen reader users without context. Even when using UI libraries, explicit labels are often missing.
**Action:** Always add `aria-label` to icon-only buttons and hide the icon itself with `aria-hidden="true"` to prevent redundant or confusing announcements.
