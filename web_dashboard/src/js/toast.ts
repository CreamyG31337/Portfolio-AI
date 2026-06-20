/**
 * Shared toast notifications.
 *
 * Single source of truth for the per-page `showToast*` helpers that were
 * previously duplicated across ai_settings, contributions, etf_metadata,
 * funds, ticker_details, trade_entry and users. Theme-aware, accessible
 * (role + close button), bottom-right stacked container.
 *
 * Pure module: NO top-level side effects, so it is safe to import from any
 * page module without triggering unintended initialization. (This is why the
 * helper lives here rather than in ui.ts, which auto-runs initUI() on load and
 * is also script-tag loaded with a cache-busting query string — importing it
 * would load that module a second time.)
 */

export type ToastType = 'success' | 'error' | 'warning' | 'info';

const CONTAINER_ID = 'toast-container';
const AUTO_DISMISS_MS = 4000;
const FADE_MS = 300;

const BORDER_BY_TYPE: Record<ToastType, string> = {
    success: 'border-theme-success-text',
    error: 'border-theme-error-text',
    warning: 'border-theme-warning-text',
    info: 'border-theme-info-text',
};

const ICON_BY_TYPE: Record<ToastType, string> = {
    success: '✅',
    error: '❌',
    warning: '⚠️',
    info: 'ℹ️',
};

function escapeHtml(value: string): string {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
}

function getContainer(): HTMLElement {
    let container = document.getElementById(CONTAINER_ID);
    if (!container) {
        container = document.createElement('div');
        container.id = CONTAINER_ID;
        container.className = 'fixed bottom-5 right-5 z-50 flex flex-col gap-2';
        document.body.appendChild(container);
    }
    return container;
}

/**
 * Show a transient toast notification. Auto-dismisses after 4s; can be
 * dismissed early via the close button.
 */
export function showToast(message: string, type: ToastType = 'success'): void {
    const container = getContainer();

    const toast = document.createElement('div');
    toast.className = `flex items-center w-full max-w-xs p-4 text-text-secondary bg-dashboard-surface rounded-lg shadow-lg border border-border border-l-4 ${BORDER_BY_TYPE[type]} transition-opacity duration-300 opacity-0`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.innerHTML = `
        <div class="ms-3 text-sm font-normal flex items-center gap-2">
            <span class="text-lg" aria-hidden="true">${ICON_BY_TYPE[type]}</span>
            <span>${escapeHtml(message)}</span>
        </div>
        <button type="button" class="ms-auto -mx-1.5 -my-1.5 bg-transparent text-text-secondary hover:text-text-primary rounded-lg focus:ring-2 focus:ring-accent p-1.5 hover:bg-dashboard-hover inline-flex items-center justify-center h-8 w-8" aria-label="Close">
            <span class="sr-only">Close</span>
            <svg class="w-3 h-3" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 14">
                <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/>
            </svg>
        </button>
    `;

    const dismiss = (): void => {
        toast.classList.remove('opacity-100');
        toast.classList.add('opacity-0');
        setTimeout(() => {
            toast.remove();
            if (container.childElementCount === 0) {
                container.remove();
            }
        }, FADE_MS);
    };

    const closeBtn = toast.querySelector('button');
    if (closeBtn) {
        closeBtn.addEventListener('click', dismiss);
    }

    container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.classList.remove('opacity-0');
        toast.classList.add('opacity-100');
    });

    setTimeout(dismiss, AUTO_DISMISS_MS);
}
