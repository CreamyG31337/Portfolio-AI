/**
 * Contributions Management Dashboard
 * Handles contribution history, summary, and adding new contributions
 */

// Type definitions
interface Fund {
    name: string;
}

interface FundsResponse {
    funds?: Fund[];
}

interface Contribution {
    contributor: string;
    fund: string;
    amount: number;
    contribution_type: 'CONTRIBUTION' | 'WITHDRAWAL';
    timestamp: string;
}

interface ContributionsResponse {
    contributions?: Contribution[];
}

interface SummaryRow {
    contributor: string;
    fund: string;
    contribution: number;
    withdrawal: number;
    net: number;
}

interface SummaryResponse {
    summary: SummaryRow[];
}

interface ApiResponse {
    success?: boolean;
    error?: string;
}

interface TabConfig {
    id: string;
    target: string;
}

// Utility functions (scoped to contributions.ts to avoid conflicts)
function escapeHtmlForContributions(text: string | undefined | null): string {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function debounceForContributions<T extends (...args: any[]) => void>(
    func: T,
    wait: number
): (...args: Parameters<T>) => void {
    let timeout: ReturnType<typeof setTimeout>;
    return function executedFunction(...args: Parameters<T>) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function showToastForContributions(message: string, type: 'success' | 'error' = 'success'): void {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'fixed bottom-5 right-5 z-50 flex flex-col gap-2';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const borderColor = type === 'error' ? 'border-theme-error-text' : 'border-theme-success-text';

    toast.className = `flex items-center w-full max-w-sm p-4 text-text-secondary bg-dashboard-surface rounded-lg shadow-xl border border-border border-l-4 ${borderColor} transition-all duration-500 transform translate-x-full opacity-0`;
    toast.innerHTML = `
        <div class="flex items-center gap-3 text-text-primary">
            <span class="font-medium text-sm">${escapeHtmlForContributions(message)}</span>
        </div>
        <button type="button" onclick="this.parentElement.remove()" class="ms-auto -mx-1.5 -my-1.5 bg-transparent text-text-secondary hover:text-text-primary rounded-lg focus:ring-2 focus:ring-accent p-1.5 hover:bg-dashboard-hover inline-flex items-center justify-center h-8 w-8">
            <i class="fas fa-times"></i>
        </button>
    `;
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

// Load funds dropdown
async function loadFunds(): Promise<void> {
    try {
        const response = await fetch('/api/funds', { credentials: 'include' });

        if (!response.ok) {
            const errorData: ApiResponse = await response.json().catch(() => ({
                error: `HTTP ${response.status}: ${response.statusText}`
            }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: FundsResponse | Fund[] = await response.json();
        // Handle both array and object response formats
        const funds = Array.isArray(data) ? data : (data.funds || []);

        const filterSelect = document.getElementById('contrib-fund-filter') as HTMLSelectElement | null;
        const formSelect = document.getElementById('form-fund') as HTMLSelectElement | null;

        if (!filterSelect || !formSelect) return;

        // Keep "All" in filter (don't clear it)
        formSelect.innerHTML = '';

        funds.forEach(fund => {
            const opt = document.createElement('option');
            // Handle both string and object formats
            const fundName = typeof fund === 'string' ? fund : fund.name;
            opt.value = fundName;
            opt.textContent = fundName;

            // Add to filter
            const filterOpt = opt.cloneNode(true) as HTMLOptionElement;
            filterSelect.appendChild(filterOpt);

            // Add to form
            formSelect.appendChild(opt);
        });
    } catch (error) {
        console.error('[Contributions] Error loading funds:', error);
    }
}

// Fetch contribution history
async function fetchHistory(): Promise<void> {
    const fundSelect = document.getElementById('contrib-fund-filter') as HTMLSelectElement | null;
    const searchInput = document.getElementById('history-search') as HTMLInputElement | null;
    const tbody = document.getElementById('history-table-body');

    if (!tbody) return;

    const fund = fundSelect?.value || '';
    const search = searchInput?.value || '';

    tbody.innerHTML = '<tr class="bg-dashboard-surface border-b border-border"><td colspan="5" class="px-6 py-4 text-center text-text-secondary">Loading...</td></tr>';

    try {
        const url = `/api/admin/contributions?fund=${encodeURIComponent(fund)}&search=${encodeURIComponent(search)}`;
        const response = await fetch(url, { credentials: 'include' });

        if (!response.ok) {
            const errorData: ApiResponse = await response.json().catch(() => ({
                error: `HTTP ${response.status}: ${response.statusText}`
            }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: ContributionsResponse | Contribution[] = await response.json();

        tbody.innerHTML = '';

        // Update datalist for contributor names
        const datalist = document.getElementById('prev-contributors');
        const uniqueNames = new Set<string>();

        // Handle response format - check for contributions array
        const contributions: Contribution[] = Array.isArray(data)
            ? data
            : (data.contributions || []);

        if (!Array.isArray(contributions)) {
            throw new Error('Invalid response format: expected contributions array');
        }

        if (contributions.length === 0) {
            tbody.innerHTML = '<tr class="bg-dashboard-surface border-b border-border"><td colspan="5" class="px-6 py-4 text-center text-text-secondary">No records found</td></tr>';
        } else {
            contributions.forEach(row => {
                uniqueNames.add(row.contributor);

                const tr = document.createElement('tr');
                tr.className = 'bg-dashboard-surface border-b border-border hover:bg-dashboard-hover';

                const isContrib = row.contribution_type === 'CONTRIBUTION';
                const typeBadge = isContrib
                    ? '<span class="bg-theme-success-bg/10 text-theme-success-text text-xs font-medium px-2.5 py-0.5 rounded border border-theme-success-text/30">DEPOSIT</span>'
                    : '<span class="bg-theme-error-bg/10 text-theme-error-text text-xs font-medium px-2.5 py-0.5 rounded border border-theme-error-text/30">WITHDRAWAL</span>';

                const dateStr = new Date(row.timestamp).toLocaleDateString();

                tr.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-text-secondary">${escapeHtmlForContributions(dateStr)}</td>
                    <td class="px-6 py-4 font-medium text-text-primary">${escapeHtmlForContributions(row.fund)}</td>
                    <td class="px-6 py-4 text-text-primary">${escapeHtmlForContributions(row.contributor)}</td>
                    <td class="px-6 py-4">${typeBadge}</td>
                    <td class="px-6 py-4 text-right font-mono ${isContrib ? 'text-theme-success-text' : 'text-theme-error-text'}">$${row.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        // Update Datalist
        if (datalist) {
            datalist.innerHTML = '';
            uniqueNames.forEach(name => {
                const opt = document.createElement('option');
                opt.value = name;
                datalist.appendChild(opt);
            });
        }

    } catch (error) {
        console.error('[Contributions] Error fetching history:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        tbody.innerHTML = `<tr class="bg-dashboard-surface border-b border-border"><td colspan="5" class="px-6 py-4 text-center text-theme-error-text">Error loading history: ${escapeHtmlForContributions(errorMsg)}</td></tr>`;
    }
}

// Fetch summary pivot
async function fetchSummary(): Promise<void> {
    const tbody = document.getElementById('summary-table-body');
    if (!tbody) return;

    tbody.innerHTML = '<tr class="bg-dashboard-surface border-b border-border"><td colspan="5" class="px-6 py-4 text-center text-text-secondary">Loading summary...</td></tr>';

    try {
        const response = await fetch('/api/admin/contributions/summary', { credentials: 'include' });

        if (!response.ok) {
            const errorData: ApiResponse = await response.json().catch(() => ({
                error: `HTTP ${response.status}: ${response.statusText}`
            }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: SummaryResponse = await response.json();
        const summary = data.summary || [];

        tbody.innerHTML = '';

        if (summary.length === 0) {
            tbody.innerHTML = '<tr class="bg-dashboard-surface border-b border-border"><td colspan="5" class="px-6 py-4 text-center text-text-secondary">No data</td></tr>';
        } else {
            summary.forEach(row => {
                const tr = document.createElement('tr');
                tr.className = 'bg-dashboard-surface border-b border-border';

                tr.innerHTML = `
                    <td class="px-6 py-4 font-bold text-text-primary">${escapeHtmlForContributions(row.contributor)}</td>
                    <td class="px-6 py-4 text-text-secondary">${escapeHtmlForContributions(row.fund)}</td>
                    <td class="px-6 py-4 text-right text-theme-success-text">$${row.contribution.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td class="px-6 py-4 text-right text-theme-error-text">$${row.withdrawal.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td class="px-6 py-4 text-right font-bold text-text-primary">$${row.net.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                 `;
                tbody.appendChild(tr);
            });
        }
    } catch (error) {
        console.error('[Contributions] Error fetching summary:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        tbody.innerHTML = `<tr class="bg-dashboard-surface border-b border-border"><td colspan="5" class="px-6 py-4 text-center text-theme-error-text">Error loading summary: ${escapeHtmlForContributions(errorMsg)}</td></tr>`;
    }
}

// Handle add contribution form submission
async function handleAddContribution(e: Event): Promise<void> {
    e.preventDefault();
    const form = e.target as HTMLFormElement;
    const btn = document.getElementById('submit-contrib-btn') as HTMLButtonElement | null;
    if (!btn) return;

    const originalText = btn.innerHTML;
    btn.innerHTML = 'Saving...';
    btn.disabled = true;

    try {
        const formData = new FormData(form);
        const payload: Record<string, string> = {};
        formData.forEach((value, key) => {
            payload[key] = value.toString();
        });

        const response = await fetch('/api/admin/contributions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            credentials: 'include'
        });

        const result: ApiResponse = await response.json();

        if (!response.ok) {
            throw new Error(result.error || 'Failed to save contribution');
        }

        if (result.success) {
            showToastForContributions('✅ Transaction Saved');
            form.reset();
            const dateInput = document.getElementById('date') as HTMLInputElement | null;
            if (dateInput) {
                dateInput.valueAsDate = new Date();
            }
            // Refresh tables
            await fetchHistory();
            const summaryContent = document.getElementById('summary-content');
            if (summaryContent && !summaryContent.classList.contains('hidden')) {
                await fetchSummary();
            }
        } else {
            showToastForContributions('❌ ' + (result.error || 'Failed to save'), 'error');
        }
    } catch (error) {
        console.error('[Contributions] Error saving contribution:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        showToastForContributions('❌ Error saving transaction: ' + errorMsg, 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Tab switching
    const tabs: TabConfig[] = [
        { id: 'history-tab', target: 'history-content' },
        { id: 'summary-tab', target: 'summary-content' }
    ];

    tabs.forEach(tab => {
        const tabElement = document.getElementById(tab.id);
        if (!tabElement) return;

        tabElement.addEventListener('click', () => {
            const activeClasses = ['text-accent', 'border-accent'];
            const inactiveClasses = ['hover:text-text-primary', 'hover:border-border', 'border-transparent'];

            tabs.forEach(t => {
                const b = document.getElementById(t.id);
                const c = document.getElementById(t.target);

                if (t.id === tab.id) {
                    b?.classList.add(...activeClasses);
                    b?.classList.remove(...inactiveClasses);
                    b?.setAttribute('aria-selected', 'true');
                    c?.classList.remove('hidden');
                } else {
                    b?.classList.remove(...activeClasses);
                    b?.classList.add(...inactiveClasses);
                    b?.setAttribute('aria-selected', 'false');
                    c?.classList.add('hidden');
                }
            });

            if (tab.id === 'summary-tab') {
                fetchSummary();
            }
        });
    });

    // Init default date
    const dateInput = document.getElementById('date') as HTMLInputElement | null;
    if (dateInput) {
        dateInput.valueAsDate = new Date();
    }

    // Load funds
    loadFunds();

    // Event listeners
    const contribForm = document.getElementById('contrib-form');
    if (contribForm) {
        contribForm.addEventListener('submit', handleAddContribution);
    }

    const fundFilter = document.getElementById('contrib-fund-filter');
    if (fundFilter) {
        fundFilter.addEventListener('change', fetchHistory);
    }

    const historySearch = document.getElementById('history-search');
    if (historySearch) {
        historySearch.addEventListener('input', debounceForContributions(fetchHistory, 500));
    }

    const refreshBtn = document.getElementById('refresh-history-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', fetchHistory);
    }

    // Initial fetch
    fetchHistory();
});

// Export empty object to make this a module (required for declare global in other files)
export { };
