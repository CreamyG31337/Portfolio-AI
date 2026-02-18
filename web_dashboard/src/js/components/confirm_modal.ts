export interface ConfirmModalOptions {
    title?: string;
    message?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    onConfirm?: () => Promise<void> | void;
}

export function showConfirmModal(opts?: ConfirmModalOptions): void {
    const modalId = 'confirm-modal';
    const triggerId = 'confirm-modal-trigger';
    const titleId = 'confirm-modal-title';
    const messageId = 'confirm-modal-message';
    const cancelBtnId = 'confirm-modal-cancel';
    const iconWrapId = 'confirm-modal-icon';
    const primaryBtnId = 'confirm-modal-submit-primary';
    const dangerBtnId = 'confirm-modal-submit-danger';

    const title = opts?.title || 'Confirm';
    const message = opts?.message ?? '';
    const confirmLabel = opts?.confirmLabel || 'Confirm';
    const cancelLabel = opts?.cancelLabel || 'Cancel';
    const danger = !!opts?.danger;
    const onConfirm = opts?.onConfirm;

    const titleEl = document.getElementById(titleId);
    const messageEl = document.getElementById(messageId);
    const cancelEl = document.getElementById(cancelBtnId);
    const iconWrap = document.getElementById(iconWrapId);
    const primaryBtn = document.getElementById(primaryBtnId) as HTMLButtonElement | null;
    const dangerBtn = document.getElementById(dangerBtnId) as HTMLButtonElement | null;

    const activeBtn = danger ? dangerBtn : primaryBtn;
    const inactiveBtn = danger ? primaryBtn : dangerBtn;

    if (titleEl) titleEl.textContent = title;
    if (messageEl) messageEl.textContent = message;
    if (cancelEl) cancelEl.textContent = cancelLabel;

    if (activeBtn) {
        activeBtn.classList.remove('hidden');
        activeBtn.classList.add('inline-flex');
        activeBtn.innerHTML = '<span>' + confirmLabel + '</span>';
        activeBtn.disabled = false;
    }
    if (inactiveBtn) {
        inactiveBtn.classList.add('hidden');
        inactiveBtn.classList.remove('inline-flex');
    }

    if (iconWrap) {
        iconWrap.className = 'mx-auto flex items-center justify-center h-14 w-14 rounded-full border mb-4 ' + (danger ? 'bg-theme-error-bg border-theme-error-text/30' : 'bg-dashboard-background border-border');
        iconWrap.innerHTML = '<i class="fas ' + (danger ? 'fa-trash-alt text-theme-error-text' : 'fa-question text-text-secondary') + ' text-xl"></i>';
    }

    function closeModal() {
        const hideBtn = document.querySelector('[data-modal-hide="' + modalId + '"]') as HTMLElement | null;
        if (hideBtn) hideBtn.click();
    }

    if (activeBtn) {
        if (onConfirm) {
            activeBtn.onclick = function() {
                if (activeBtn.disabled) return;
                activeBtn.disabled = true;
                activeBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span class="ml-2">Please wait…</span>';

                try {
                    const result = onConfirm();
                    // Check if result is a Promise
                    const p = result && typeof (result as any).then === 'function' ? result as Promise<void> : Promise.resolve();
                    p.then(function() {
                        closeModal();
                        activeBtn.disabled = false;
                        activeBtn.innerHTML = '<span>' + confirmLabel + '</span>';
                    }).catch(function() {
                        activeBtn.disabled = false;
                        activeBtn.innerHTML = '<span>' + confirmLabel + '</span>';
                    });
                } catch (e) {
                     activeBtn.disabled = false;
                     activeBtn.innerHTML = '<span>' + confirmLabel + '</span>';
                }
            };
        } else {
            // If no onConfirm provided, just close the modal
            activeBtn.onclick = function() {
                closeModal();
            };
        }
    }

    const trigger = document.getElementById(triggerId);
    if (trigger) trigger.click();
}

// Attach to window for global access
(window as any).showConfirmModal = showConfirmModal;
