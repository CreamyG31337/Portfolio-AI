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
    const borderColor = type === 'error' ? 'border-red-500' : 'border-green-500';

    toast.className = `flex items-center w-full max-w-xs p-4 text-gray-500 bg-white rounded-lg shadow dark:text-gray-400 dark:bg-gray-800 border-l-4 ${borderColor} transition-opacity duration-300 opacity-100`;
    toast.innerHTML = `
        <div class="ms-3 text-sm font-normal">${escapeHtmlForContributions(message)}</div>
        <button type="button" class="bg-white text-gray-400 hover:text-gray-900 rounded-lg p-1.5 hover:bg-gray-100 inline-flex items-center justify-center h-8 w-8 dark:text-gray-500 dark:bg-gray-800 dark:hover:text-white dark:hover:bg-gray-700" onclick="this.parentElement.remove()">✕</button>
    `;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
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

    tbody.innerHTML = '<tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700"><td colspan="5" class="px-6 py-4 text-center">Loading...</td></tr>';

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
            tbody.innerHTML = '<tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700"><td colspan="5" class="px-6 py-4 text-center text-gray-500">No records found</td></tr>';
        } else {
            contributions.forEach(row => {
                uniqueNames.add(row.contributor);

                const tr = document.createElement('tr');
                tr.className = 'bg-white border-b dark:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600';

                const isContrib = row.contribution_type === 'CONTRIBUTION';
                const typeBadge = isContrib
                    ? '<span class="bg-green-100 text-green-800 text-xs font-medium px-2.5 py-0.5 rounded dark:bg-green-900 dark:text-green-300">DEPOSIT</span>'
                    : '<span class="bg-red-100 text-red-800 text-xs font-medium px-2.5 py-0.5 rounded dark:bg-red-900 dark:text-red-300">WITHDRAWAL</span>';

                const dateStr = new Date(row.timestamp).toLocaleDateString();

                tr.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap">${escapeHtmlForContributions(dateStr)}</td>
                    <td class="px-6 py-4 font-medium">${escapeHtmlForContributions(row.fund)}</td>
                    <td class="px-6 py-4">${escapeHtmlForContributions(row.contributor)}</td>
                    <td class="px-6 py-4">${typeBadge}</td>
                    <td class="px-6 py-4 text-right font-mono ${isContrib ? 'text-green-600' : 'text-red-600'}">$${row.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
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
        tbody.innerHTML = `<tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700"><td colspan="5" class="px-6 py-4 text-center text-red-500">Error loading history: ${escapeHtmlForContributions(errorMsg)}</td></tr>`;
    }
}

// Fetch summary pivot
async function fetchSummary(): Promise<void> {
    const tbody = document.getElementById('summary-table-body');
    if (!tbody) return;

    tbody.innerHTML = '<tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700"><td colspan="5" class="px-6 py-4 text-center">Loading summary...</td></tr>';

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
            tbody.innerHTML = '<tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700"><td colspan="5" class="px-6 py-4 text-center text-gray-500">No data</td></tr>';
        } else {
            summary.forEach(row => {
                const tr = document.createElement('tr');
                tr.className = 'bg-white border-b dark:bg-gray-800 dark:border-gray-700';

                tr.innerHTML = `
                    <td class="px-6 py-4 font-bold text-gray-900 dark:text-white">${escapeHtmlForContributions(row.contributor)}</td>
                    <td class="px-6 py-4">${escapeHtmlForContributions(row.fund)}</td>
                    <td class="px-6 py-4 text-right text-green-600">$${row.contribution.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td class="px-6 py-4 text-right text-red-600">$${row.withdrawal.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td class="px-6 py-4 text-right font-bold">$${row.net.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                 `;
                tbody.appendChild(tr);
            });
        }
    } catch (error) {
        console.error('[Contributions] Error fetching summary:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        tbody.innerHTML = `<tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700"><td colspan="5" class="px-6 py-4 text-center text-red-500">Error loading summary: ${escapeHtmlForContributions(errorMsg)}</td></tr>`;
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
            const activeClasses = ['text-blue-600', 'border-blue-600', 'dark:text-blue-500', 'dark:border-blue-500'];
            const inactiveClasses = ['hover:text-gray-600', 'hover:border-gray-300', 'dark:hover:text-gray-300', 'border-transparent'];

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
