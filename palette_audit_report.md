## Tailwind CSS and Flowbite Audit Report

**Issue**: Custom modal implementation duplicates Flowbite modal behavior in `web_dashboard/templates/trade_entry.html` (`#edit-trade-modal`, `#delete-trade-modal`).
**Why it matters**: Hand-rolled modals utilizing `hidden fixed inset-0 z-50` are missing proper focus trapping and keyboard handling, which reduces accessibility and breaks project consistency.
**Suggestion**: Replace with standard Flowbite modal components utilizing `data-modal-target` and `data-modal-toggle` data attributes to ensure ARIA compliance, proper focus management, and visual consistency.
**Scope**: Local

**Issue**: Hand-rolled modal in `web_dashboard/templates/newsletters.html` (`#email-view-modal`).
**Why it matters**: The code manually handles backdrop clicks (`onclick="if(event.target === this) closeEmailModal()"`) and bypasses standard accessible modal features that Flowbite provides out-of-the-box.
**Suggestion**: Refactor to use the standard Flowbite modal implementation to ensure consistency.
**Scope**: Local

**Issue**: Direct inline style usage for dynamic progress bar widths in `web_dashboard/templates/ticker_details.html` (`style="width: 0%"`) and manipulated via `style.width` in `web_dashboard/src/js/ticker_details.ts` and `web_dashboard/src/js/dashboard.ts`.
**Why it matters**: It violates Tailwind's utility-first approach and project CSS best practices. Direct inline styles override utilities and are harder to maintain in a utility-driven design system.
**Suggestion**: Use inline CSS variables combined with Tailwind's arbitrary value classes. Example: `style.setProperty('--bar-width', value)` in JS and `w-[var(--bar-width)]` in HTML templates instead of `style="width: ...%"`.
**Scope**: Reusable

**Issue**: Inline style usage for image widths in JavaScript files (e.g., `img.style.width = '24px'` in `web_dashboard/src/js/signals.ts`, `congress_trades.ts`, `social_sentiment.ts`, `etf_holdings.ts`).
**Why it matters**: Bypasses Tailwind CSS classes entirely. Hardcoding dimensions via inline styles makes it difficult to maintain consistent standard sizing globally or adapt layouts responsively.
**Suggestion**: Use standard Tailwind sizing utility classes (e.g., `img.classList.add('w-6')`) instead of directly manipulating inline `style.width`.
**Scope**: Reusable

**Issue**: Dynamic inline color assignments in `web_dashboard/src/js/congress_trades.ts` (e.g., `tickerSpan.style.color`, `this.eGui.style.color`, `this.eGui.style.backgroundColor`).
**Why it matters**: Hardcoding colors or accessing CSS variables directly in JS inline styles circumvents Tailwind's semantic utility classes (`text-theme-success-text`, `bg-theme-success-bg`). This breaks layout consistency and native support for dark mode.
**Suggestion**: Map values to semantic Tailwind utility classes (e.g., `text-theme-success-text`) in JS string interpolations or class toggling, instead of direct inline styling.
**Scope**: Reusable

**Issue**: Inline style usage returning from cell renderers in `web_dashboard/src/js/congress_positions.ts` (`<span style="color: ${color}; font-weight: 600;">`).
**Why it matters**: Bypasses Tailwind CSS utilities (`text-theme-success-text font-semibold`). Hardcoded colors prevent dynamic theming and are harder to maintain in string interpolations.
**Suggestion**: Use Flowbite and Tailwind semantic color utility classes mapped dynamically based on conditions, and replace `font-weight: 600` with the corresponding Tailwind class (`font-semibold`).
**Scope**: Reusable

**Issue**: Widespread use of arbitrary values for sizing (e.g., `h-[300px]`, `min-h-[500px]`, `max-h-[420px]`) in multiple templates (e.g., `dashboard.html`, `research.html`, `ticker_details.html`).
**Why it matters**: Arbitrary values circumvent Tailwind's standard sizing scale, leading to inconsistent heights, widths, and spacing across the application, which makes responsive design harder to maintain.
**Suggestion**: Replace arbitrary pixel values with the closest standard Tailwind size utilities (e.g., `h-72` for `288px`, `h-96` for `384px`, `max-h-screen`, `max-h-min`).
**Scope**: Systemic

**Issue**: Custom toggle switch implementations using excessively verbose Tailwind classes (e.g., `peer-checked:after:translate-x-full`) in `web_dashboard/templates/dashboard.html` and `web_dashboard/templates/system.html`.
**Why it matters**: Duplicates standard Flowbite toggle component behavior with difficult-to-maintain custom CSS classes. It introduces verbosity in the templates and is inconsistent with project's standard component usage.
**Suggestion**: Replace with standard Flowbite toggle components or extract the custom toggle classes into an `@apply` directive within `web_dashboard/static/css/input.css` as `.toggle-switch` to encapsulate the behavior.
**Scope**: Reusable
