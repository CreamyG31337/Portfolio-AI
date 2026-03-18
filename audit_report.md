Issue: Custom modal implementations (`edit-trade-modal` and `delete-trade-modal`) in `web_dashboard/templates/trade_entry.html` manually use Tailwind classes like `hidden fixed inset-0 z-50` and custom JavaScript for toggling instead of standard Flowbite attributes.
Why it matters: Custom modals lack built-in accessibility features (like focus trapping, ARIA roles, and keyboard navigation) and duplicate behavior already provided consistently by Flowbite's `Modal` component, leading to maintainability overhead.
Suggestion: Refactor these modals to use standard Flowbite data attributes (`data-modal-target`, `data-modal-toggle`, `data-modal-hide`) and appropriate classes. Manage their state using Flowbite's JS API.
Scope: Local (`trade_entry.html` and `trade_entry.ts`)
Issue: The AI Assistant drawer implementation in `web_dashboard/templates/ai_assistant.html` relies on a custom backdrop (`id="ai-drawer-backdrop"`) using `hidden fixed inset-0 z-40 bg-black/50` alongside custom toggle logic.
Why it matters: Reimplementing drawer behaviors manually bypasses standard Flowbite transitions, ARIA states, and click-outside handling. It introduces inconsistencies in how overlays work compared to the rest of the app.
Suggestion: Replace the custom drawer setup with a standard Flowbite Drawer implementation using the appropriate data attributes (`data-drawer-target`, `data-drawer-show`, `data-drawer-hide`, `aria-controls`) and Flowbite's JS API.
Scope: Local (`ai_assistant.html` and `ai_assistant.ts`)
