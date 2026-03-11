# Palette CSS Audit Report 🎨

The following issues regarding Tailwind CSS and Flowbite usage were identified during the automated audit of the codebase:

**Issue**: Custom modal implementation (`#email-view-modal`) duplicates Flowbite modal behavior in `web_dashboard/templates/newsletters.html`
**Why it matters**: Missing focus trap and standard keyboard handling (e.g., proper Escape key propagation and tabbing isolation) reduces accessibility. Manual JavaScript toggling (`hidden`, `flex`) is error-prone compared to Flowbite's established data attributes (`data-modal-target`, `data-modal-toggle`) or robust JS API (`Modal` class).
**Suggestion**: Replace the custom HTML markup and vanilla JS show/hide toggles with the canonical Flowbite modal component and API to ensure ARIA attributes are managed correctly and state handling is consistent across the application.
**Scope**: Local (`web_dashboard/templates/newsletters.html`)

**Issue**: Custom modals for Trade Entry edit/delete (`#edit-trade-modal`, `#delete-trade-modal`) reinvent UI behavior in `web_dashboard/templates/trade_entry.html`
**Why it matters**: The codebase introduces custom Tailwind configurations (e.g., `hidden fixed inset-0 z-50 flex items-center justify-center bg-black/50`) and complex, manually-managed JavaScript in `trade_entry.ts` (e.g., manual DOM lookups to toggle visibility) for these dialogs. This bypasses the accessibility inheritance and uniform design language provided natively by Flowbite components.
**Suggestion**: Migrate the custom modal markup to utilize standard Flowbite component structures and integrate Flowbite's JS API or data attributes, removing the duplicate dialog logic from `trade_entry.ts`.
**Scope**: Systemic (affects standard dialog patterns across `web_dashboard/templates/trade_entry.html` and `web_dashboard/src/js/trade_entry.ts`)

**Issue**: Custom dropdown implementation for contributor autocomplete in `web_dashboard/src/js/contributions.ts`
**Why it matters**: Implementing custom autocomplete dropdowns frequently leads to missing or incomplete keyboard navigation support (e.g., Arrow Up/Down selection, Enter to confirm, Escape to close). Re-implementing these standard accessibility features from scratch creates a maintenance burden.
**Suggestion**: Transition the custom autocomplete UI to leverage a Flowbite Dropdown component or structurally similar Flowbite interactive element, taking advantage of its pre-built focus management and ARIA roles.
**Scope**: Local (`web_dashboard/src/js/contributions.ts`)
