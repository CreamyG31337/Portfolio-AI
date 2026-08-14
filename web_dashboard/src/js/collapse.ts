/**
 * Collapse binding for dynamically created content.
 *
 * Flowbite auto-initialises collapses once, at DOMContentLoaded, so anything we
 * insert afterwards (job cards, chat panels, research rows) is never bound and
 * the toggle silently does nothing.
 *
 * Re-running Flowbite's `initCollapses()` is not a fix: it walks every
 * `[data-collapse-toggle]` on the page and, for triggers it has already seen,
 * registers a *second* Collapse instance with a second click listener — so each
 * click would toggle twice and every static collapse on the page would appear
 * dead. Bind only the subtree we just created instead.
 *
 * Convention: the target starts with `hidden`; expanded adds `rotate-180` to a
 * `[data-accordion-icon]` inside the trigger.
 */

/** Bind every unbound `[data-collapse-toggle]` inside `root` (idempotent). */
export function initCollapsesIn(root: ParentNode): void {
    root.querySelectorAll<HTMLElement>('[data-collapse-toggle]').forEach((trigger) => {
        if (trigger.dataset.collapseBound === 'true') return;

        const targetId = trigger.getAttribute('data-collapse-toggle');
        if (!targetId) return;
        const target = document.getElementById(targetId);
        if (!target) {
            console.error(`[Collapse] Target "${targetId}" not found for trigger`);
            return;
        }

        trigger.dataset.collapseBound = 'true';
        trigger.addEventListener('click', (event) => {
            // Links inside a collapsible header should not toggle it.
            if ((event.target as HTMLElement)?.closest('a')) return;
            setCollapsed(targetId, target.classList.contains('hidden') === false);
        });
    });
}

/** Force a collapse target open or closed, keeping aria/icon state in sync. */
export function setCollapsed(targetId: string, collapsed: boolean): void {
    const target = document.getElementById(targetId);
    if (!target) return;

    target.classList.toggle('hidden', collapsed);
    // Compare the attribute directly rather than building a selector — job ids
    // and generated ids are not guaranteed to be selector-safe.
    document.querySelectorAll<HTMLElement>('[data-collapse-toggle]').forEach((trigger) => {
        if (trigger.getAttribute('data-collapse-toggle') !== targetId) return;
        trigger.setAttribute('aria-expanded', String(!collapsed));
        trigger
            .querySelector<HTMLElement>('[data-accordion-icon]')
            ?.classList.toggle('rotate-180', !collapsed);
    });
}
