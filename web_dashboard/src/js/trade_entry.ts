/**
 * Trade Entry Dashboard
 * Handles manual trade entry, email parsing, and trade history
 */

// Type definitions
interface Trade {
    date: string;
    ticker: string;
    shares: number;
    price: number;
    reason?: string;
}

interface TradesResponse {
    trades: Trade[];
    total: number;
    pages: number;
}

interface ParsedTrade {
    ticker: string;
    action?: string;
    shares: number;
    price: number;
    currency?: string;
    reason?: string;
    timestamp: string;
}

interface TradeSubmitResponse {
    success?: boolean;
    error?: string;
    rebuild_job_id?: string;
}

interface EmailParseResponse {
    success?: boolean;
    error?: string;
    trade?: ParsedTrade;
}

interface ApiResponse {
    success?: boolean;
    error?: string;
}

// Utility functions (scoped to trade_entry.ts to avoid conflicts)
function escapeHtmlForTradeEntry(text: string | undefined | null): string {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToastForTradeEntry(message: string, type: 'success' | 'error' | 'info' = 'success'): void {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'fixed bottom-5 right-5 z-50 flex flex-col gap-2';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const borderColor = type === 'error' ? 'border-theme-error-text' : (type === 'info' ? 'border-theme-info-text' : 'border-theme-success-text');

    toast.className = `flex items-center w-full max-w-sm p-4 text-text-secondary bg-dashboard-surface rounded-lg shadow-xl border border-border border-l-4 ${borderColor} transition-all duration-500 transform translate-x-full opacity-0`;
    toast.innerHTML = `
        <div class="flex items-center gap-3 text-text-primary">
            <span class="font-medium text-sm">${escapeHtmlForTradeEntry(message)}</span>
        </div>
        <button type="button" onclick="this.parentElement.remove()" class="ms-auto -mx-1.5 -my-1.5 bg-transparent text-text-secondary hover:text-text-primary rounded-lg focus:ring-2 focus:ring-accent p-1.5 hover:bg-dashboard-hover inline-flex items-center justify-center h-8 w-8">
            <i class="fas fa-times"></i>
        </button>
    `;

    const closeBtn = toast.querySelector('button');
    if (closeBtn) {
        closeBtn.onclick = () => toast.remove();
    }
    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        toast.classList.remove('translate-x-full', 'opacity-0');
    });

    setTimeout(() => {
        if (toast.parentElement) {
            toast.classList.add('translate-x-full', 'opacity-0');
            setTimeout(() => {
                if (toast.parentElement) toast.remove();
            }, 500);
        }
    }, 4000);
}

// Get selected fund from global selector
function getSelectedFund(): string {
    const globalSelector = document.getElementById('global-fund-select') as HTMLSelectElement | null;
    if (!globalSelector) {
        console.warn('[Trade Entry] Global fund selector not found');
        return '';
    }
    const fund = globalSelector.value;
    // Don't allow "all" for trade entry - need a specific fund
    if (!fund || fund === 'all') {
        return '';
    }
    return fund;
}

// State
let parsedTradeData: ParsedTrade | null = null;
let currentPage = 0;
const limit = 20;

// Tab configuration
interface TabConfig {
    id: string;
    target: string;
}

const tabs: TabConfig[] = [
    { id: 'manual-tab', target: 'manual-content' },
    { id: 'email-tab', target: 'email-content' },
    { id: 'history-tab', target: 'history-content' }
];

// Initialize tabs
function initTabs(): void {
    const tabsElement = document.getElementById('trade-tabs');
    if (!tabsElement) {
        console.warn('[Trade Entry] Tabs container not found');
        return;
    }

    tabs.forEach(tab => {
        const btn = document.getElementById(tab.id);
        if (!btn) {
            console.warn(`[Trade Entry] Tab button ${tab.id} not found`);
            return;
        }

        btn.addEventListener('click', () => {
            const activeClasses = ['text-accent', 'border-accent'];
            const inactiveClasses = ['text-text-secondary', 'border-transparent', 'hover:text-text-primary', 'hover:border-border-hover'];

            tabs.forEach(t => {
                const b = document.getElementById(t.id);
                const c = document.getElementById(t.target);

                if (t.id === tab.id) {
                    // Activate this tab
                    b?.classList.remove(...inactiveClasses);
                    b?.classList.add(...activeClasses);
                    b?.setAttribute('aria-selected', 'true');
                    c?.classList.remove('hidden');
                } else {
                    // Deactivate other tabs
                    b?.classList.remove(...activeClasses);
                    b?.classList.add(...inactiveClasses);
                    b?.setAttribute('aria-selected', 'false');
                    c?.classList.add('hidden');
                }
            });

            // Refresh data if history tab selected
            if (tab.id === 'history-tab') {
                fetchRecentTrades();
            }
        });
    });

    // Ensure first tab is active (it should already be visible from template)
    const firstTab = document.getElementById('manual-tab');
    const firstContent = document.getElementById('manual-content');
    if (firstTab && firstContent) {
        // Make sure it's visible and styled correctly
        firstContent.classList.remove('hidden');
        firstTab.setAttribute('aria-selected', 'true');
    }
}

// Update manual total preview
function updateManualTotal(): void {
    const sharesInput = document.getElementById('shares') as HTMLInputElement | null;
    const priceInput = document.getElementById('price') as HTMLInputElement | null;
    const display = document.getElementById('total-value-display');
    const previewBox = document.getElementById('manual-total-preview');

    if (!sharesInput || !priceInput || !display || !previewBox) return;

    const shares = parseFloat(sharesInput.value) || 0;
    const price = parseFloat(priceInput.value) || 0;
    const total = shares * price;

    display.textContent = '$' + total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    if (total > 0) {
        previewBox.classList.remove('hidden');
    } else {
        previewBox.classList.add('hidden');
    }
}

// Handle manual trade submission
async function handleManualSubmit(e: Event): Promise<void> {
    e.preventDefault();
    const fund = getSelectedFund();
    if (!fund) {
        showToastForTradeEntry('Please select a fund from the sidebar menu first', 'error');
        return;
    }

    const submitBtn = document.getElementById('submit-manual-btn') as HTMLButtonElement | null;
    if (!submitBtn) return;

    const originalText = submitBtn.innerHTML;
    submitBtn.innerHTML = '<span class="animate-spin text-xl">↻</span> Submitting...';
    submitBtn.disabled = true;

    try {
        const form = e.target as HTMLFormElement;
        const formData = new FormData(form);
        const date = formData.get('date') as string;
        const time = formData.get('time') as string;
        const timestamp = new Date(`${date}T${time}`).toISOString();

        const payload = {
            fund: fund,
            action: formData.get('action') as string,
            ticker: formData.get('ticker') as string,
            shares: formData.get('shares') as string,
            price: formData.get('price') as string,
            currency: formData.get('currency') as string,
            reason: formData.get('reason') as string,
            timestamp: timestamp
        };

        const response = await fetch('/api/admin/trades/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            credentials: 'include'
        });

        const result: TradeSubmitResponse = await response.json();

        if (!response.ok || !result.success) {
            throw new Error(result.error || 'Submission failed');
        }

        showToastForTradeEntry('✅ Trade Submitted Successfully');
        form.reset();

        // Reset date/time
        const now = new Date();
        const dateInput = document.getElementById('trade-date') as HTMLInputElement | null;
        const timeInput = document.getElementById('trade-time') as HTMLInputElement | null;
        if (dateInput) dateInput.valueAsDate = now;
        if (timeInput) timeInput.value = now.toTimeString().slice(0, 5);

        updateManualTotal();

        if (result.rebuild_job_id) {
            showToastForTradeEntry('⏳ Background rebuild started (backdated trade)', 'info');
        }
    } catch (error) {
        console.error('[Trade Entry] Error submitting trade:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        showToastForTradeEntry('❌ ' + errorMsg, 'error');
    } finally {
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
}

// Handle email parsing
async function handleEmailParse(): Promise<void> {
    const textArea = document.getElementById('email-text') as HTMLTextAreaElement | null;
    if (!textArea || !textArea.value.trim()) {
        showToastForTradeEntry('Please paste email text', 'error');
        return;
    }

    const btn = document.getElementById('parse-email-btn') as HTMLButtonElement | null;
    if (!btn) return;

    btn.disabled = true;
    btn.textContent = 'Parsing...';

    try {
        const response = await fetch('/api/admin/trades/preview-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: textArea.value }),
            credentials: 'include'
        });

        const result: EmailParseResponse = await response.json();

        if (!response.ok || !result.success) {
            throw new Error(result.error || 'Parse failed');
        }

        if (!result.trade) {
            throw new Error('No trade data returned');
        }

        parsedTradeData = result.trade;

        // Fill preview
        const previewTicker = document.getElementById('preview-ticker');
        const previewAction = document.getElementById('preview-action');
        const previewShares = document.getElementById('preview-shares');
        const previewPrice = document.getElementById('preview-price');
        const previewTotal = document.getElementById('preview-total');
        const previewDate = document.getElementById('preview-date');
        const parsedResult = document.getElementById('parsed-result');

        if (previewTicker) previewTicker.textContent = result.trade.ticker;

        if (previewAction) {
            const action = result.trade.action || (result.trade.reason && result.trade.reason.toLowerCase().includes('sell') ? 'SELL' : 'BUY');
            previewAction.textContent = action;

            // Color action
            if (action === 'SELL') {
                previewAction.className = 'font-bold text-lg text-theme-error-text';
            } else {
                previewAction.className = 'font-bold text-lg text-theme-success-text';
            }
        }

        if (previewShares) previewShares.textContent = result.trade.shares.toString();
        if (previewPrice) previewPrice.textContent = '$' + result.trade.price.toFixed(2);
        if (previewTotal) previewTotal.textContent = '$' + (result.trade.shares * result.trade.price).toFixed(2);
        if (previewDate) previewDate.textContent = new Date(result.trade.timestamp).toLocaleString();
        if (parsedResult) parsedResult.classList.remove('hidden');

    } catch (error) {
        console.error('[Trade Entry] Error parsing email:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        showToastForTradeEntry('❌ ' + errorMsg, 'error');
        parsedTradeData = null;
    } finally {
        btn.disabled = false;
        btn.textContent = '🔍 Parse Email';
    }
}

// Handle email trade confirmation
async function handleEmailConfirm(): Promise<void> {
    if (!parsedTradeData) return;

    const fund = getSelectedFund();
    if (!fund) {
        showToastForTradeEntry('Please select a fund from the sidebar menu first', 'error');
        return;
    }

    // Determine action if missing
    let action = parsedTradeData.action;
    if (!action) {
        const reason = (parsedTradeData.reason || '').toLowerCase();
        if (reason.includes('sell') || reason.includes('sold')) {
            action = 'SELL';
        } else {
            action = 'BUY';
        }
    }

    const payload = {
        fund: fund,
        action: action,
        ticker: parsedTradeData.ticker,
        shares: parsedTradeData.shares,
        price: parsedTradeData.price,
        currency: parsedTradeData.currency,
        reason: parsedTradeData.reason,
        timestamp: parsedTradeData.timestamp
    };

    try {
        const response = await fetch('/api/admin/trades/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            credentials: 'include'
        });

        const result: TradeSubmitResponse = await response.json();

        if (!response.ok || !result.success) {
            throw new Error(result.error || 'Failed to save trade');
        }

        showToastForTradeEntry('✅ Trade Saved');
        const parsedResult = document.getElementById('parsed-result');
        const emailText = document.getElementById('email-text') as HTMLTextAreaElement | null;

        if (parsedResult) parsedResult.classList.add('hidden');
        if (emailText) emailText.value = '';
        parsedTradeData = null;
    } catch (error) {
        console.error('[Trade Entry] Error saving trade:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        showToastForTradeEntry('❌ ' + errorMsg, 'error');
    }
}

// Fetch recent trades
async function fetchRecentTrades(page: number = 0): Promise<void> {
    const fund = getSelectedFund();
    if (!fund) {
        const tbody = document.getElementById('trades-table-body');
        if (tbody) {
            tbody.innerHTML = '<tr class="bg-dashboard-surface border-b border-border"><td colspan="6" class="px-6 py-4 text-center text-text-secondary">Please select a fund from the sidebar menu</td></tr>';
        }
        return;
    }

    currentPage = page;
    const offset = page * limit;

    const tbody = document.getElementById('trades-table-body');
    if (!tbody) return;

    tbody.innerHTML = '<tr class="bg-dashboard-surface border-b border-border"><td colspan="6" class="px-6 py-4 text-center">Loading...</td></tr>';

    try {
        const response = await fetch(`/api/admin/trades/recent?fund=${encodeURIComponent(fund)}&page=${page}&limit=${limit}`, {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data: TradesResponse = await response.json();

        tbody.innerHTML = '';

        if (data.trades.length === 0) {
            tbody.innerHTML = '<tr class="bg-dashboard-surface border-b border-border"><td colspan="6" class="px-6 py-4 text-center text-text-secondary">No trades found</td></tr>';
        } else {
            data.trades.forEach(trade => {
                const tr = document.createElement('tr');
                tr.className = 'bg-dashboard-surface border-b border-border hover:bg-dashboard-surface-alt';

                // Determine Action
                const reason = (trade.reason || '').toLowerCase();
                const isSell = reason.includes('sell') || reason.includes('sold');
                const actionBadge = isSell
                    ? '<span class="bg-theme-error-bg text-theme-error-text text-xs font-medium px-2.5 py-0.5 rounded border border-theme-error-text">SELL</span>'
                    : '<span class="bg-theme-success-bg text-theme-success-text text-xs font-medium px-2.5 py-0.5 rounded border border-theme-success-text">BUY</span>';

                const dateStr = new Date(trade.date).toLocaleString([], {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                });
                const total = trade.shares * trade.price;

                tr.innerHTML = `
                    <td class="px-6 py-4">${escapeHtmlForTradeEntry(dateStr)}</td>
                    <td class="px-6 py-4">${actionBadge}</td>
                    <td class="px-6 py-4 font-bold text-text-primary">${escapeHtmlForTradeEntry(trade.ticker)}</td>
                    <td class="px-6 py-4 text-right">${trade.shares}</td>
                    <td class="px-6 py-4 text-right">$${trade.price.toFixed(2)}</td>
                    <td class="px-6 py-4 text-right">$${total.toFixed(2)}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        // Update Pagination
        const pageStart = document.getElementById('page-start');
        const pageEnd = document.getElementById('page-end');
        const totalCount = document.getElementById('total-count');

        if (pageStart) pageStart.textContent = ((page * limit) + 1).toString();
        if (pageEnd) pageEnd.textContent = Math.min((page + 1) * limit, data.total).toString();
        if (totalCount) totalCount.textContent = data.total.toString();

        renderPagination(data.pages, page);

    } catch (error) {
        console.error('[Trade Entry] Error fetching trades:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        tbody.innerHTML = `<tr class="bg-dashboard-surface border-b border-border"><td colspan="6" class="px-6 py-4 text-center text-theme-error-text">Error loading trades: ${escapeHtmlForTradeEntry(errorMsg)}</td></tr>`;
    }
}

// Render pagination
function renderPagination(totalPages: number, currPage: number): void {
    const container = document.getElementById('pagination');
    if (!container) return;

    container.innerHTML = '';

    // Prev
    const prevLi = document.createElement('li');
    prevLi.innerHTML = `
        <a href="#" class="flex items-center justify-center px-3 h-8 ms-0 leading-tight text-text-secondary bg-dashboard-surface border border-border rounded-s-lg hover:bg-dashboard-surface-alt hover:text-text-primary ${currPage === 0 ? 'pointer-events-none opacity-50' : ''}">
            <span class="sr-only">Previous</span>
            <svg class="w-2.5 h-2.5 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 6 10">
              <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 1 1 5l4 4"/>
            </svg>
        </a>
    `;
    prevLi.onclick = (e) => {
        e.preventDefault();
        if (currPage > 0) {
            fetchRecentTrades(currPage - 1);
        }
    };
    container.appendChild(prevLi);

    // Next
    const nextLi = document.createElement('li');
    nextLi.innerHTML = `
        <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border rounded-e-lg hover:bg-dashboard-surface-alt hover:text-text-primary ${currPage >= totalPages - 1 ? 'pointer-events-none opacity-50' : ''}">
            <span class="sr-only">Next</span>
            <svg class="w-2.5 h-2.5 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 6 10">
              <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 9 4-4-4-4"/>
            </svg>
        </a>
    `;
    nextLi.onclick = (e) => {
        e.preventDefault();
        if (currPage < totalPages - 1) {
            fetchRecentTrades(currPage + 1);
        }
    };
    container.appendChild(nextLi);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Initialize tabs
    initTabs();

    // Live calc for manual form
    const sharesInput = document.getElementById('shares');
    const priceInput = document.getElementById('price');

    if (sharesInput) {
        sharesInput.addEventListener('input', updateManualTotal);
    }
    if (priceInput) {
        priceInput.addEventListener('input', updateManualTotal);
    }

    // Ticker auto-uppercase with visual feedback
    const tickerInput = document.getElementById('ticker') as HTMLInputElement | null;
    if (tickerInput) {
        tickerInput.addEventListener('change', () => {
            const originalValue = tickerInput.value;
            tickerInput.value = tickerInput.value.toUpperCase();

            // Visual feedback if value changed
            if (originalValue !== tickerInput.value) {
                tickerInput.classList.add('border-theme-success-text');
                setTimeout(() => {
                    tickerInput.classList.remove('border-theme-success-text');
                }, 300);
            }
        });
    }

    // Event Listeners
    const manualForm = document.getElementById('manual-trade-form');
    if (manualForm) {
        manualForm.addEventListener('submit', handleManualSubmit);
    }

    const parseEmailBtn = document.getElementById('parse-email-btn');
    if (parseEmailBtn) {
        parseEmailBtn.addEventListener('click', handleEmailParse);
    }

    const clearEmailBtn = document.getElementById('clear-email-btn');
    if (clearEmailBtn) {
        clearEmailBtn.addEventListener('click', () => {
            const emailText = document.getElementById('email-text') as HTMLTextAreaElement | null;
            const parsedResult = document.getElementById('parsed-result');
            if (emailText) emailText.value = '';
            if (parsedResult) parsedResult.classList.add('hidden');
        });
    }

    const confirmEmailBtn = document.getElementById('confirm-email-trade-btn');
    if (confirmEmailBtn) {
        confirmEmailBtn.addEventListener('click', handleEmailConfirm);
    }

    // Listen to global fund selector changes
    const globalFundSelect = document.getElementById('global-fund-select');
    if (globalFundSelect) {
        globalFundSelect.addEventListener('change', () => {
            // Refresh recent trades if that tab is open
            const historyContent = document.getElementById('history-content');
            if (historyContent && !historyContent.classList.contains('hidden')) {
                fetchRecentTrades();
            }
        });
    }

    // Set default date/time
    const now = new Date();
    const dateInput = document.getElementById('trade-date') as HTMLInputElement | null;
    const timeInput = document.getElementById('trade-time') as HTMLInputElement | null;

    if (dateInput) dateInput.valueAsDate = now;
    if (timeInput) timeInput.value = now.toTimeString().slice(0, 5);
});

// Export empty object to make this a module
export { };
