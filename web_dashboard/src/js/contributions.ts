/**
 * Contributions Management Dashboard
 * Handles contribution history, summary, and adding new contributions
 */

import { getCsrfHeaders } from './csrf.js';

// Type definitions
interface Fund {
    name: string;
}

interface FundsResponse {
    funds?: Fund[];
}

interface Contributor {
    id: string;
    name: string;
    email: string | null;
}

interface ContributorsResponse {
    contributors?: Contributor[];
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

// Module-level state for contributor selection
let contributorsList: Contributor[] = [];
let selectedContributorId: string | null = null;

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

    toast.className = `flex items-center w-full max-w-xs p-4 text-text-secondary bg-dashboard-surface rounded-lg shadow border-l-4 ${borderColor} transition-opacity duration-300 opacity-0`;
    toast.innerHTML = `
        <div class="ms-3 text-sm font-normal text-text-primary">${escapeHtmlForContributions(message)}</div>
        <button type="button" class="bg-dashboard-surface text-text-secondary hover:text-text-primary rounded-lg p-1.5 hover:bg-dashboard-hover inline-flex items-center justify-center h-8 w-8" onclick="this.parentElement.remove()">✕</button>
    `;
    container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.classList.remove('opacity-0');
        toast.classList.add('opacity-100');
    });

    setTimeout(() => {
        toast.classList.remove('opacity-100');
        toast.classList.add('opacity-0');
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

// Load contributors from the contributors table (not from contribution history)
async function loadContributors(): Promise<void> {
    try {
        const response = await fetch('/api/admin/contributors', { credentials: 'include' });
        
        if (!response.ok) {
            console.error('[Contributions] Failed to load contributors');
            return;
        }
        
        const data: ContributorsResponse = await response.json();
        contributorsList = data.contributors || [];
    } catch (error) {
        console.error('[Contributions] Error loading contributors:', error);
    }
}

// Render contributor dropdown items based on filter
function renderContributorDropdown(filter: string): void {
    const dropdown = document.getElementById('contributor-dropdown');
    if (!dropdown) return;
    
    const filterLower = filter.toLowerCase();
    const filtered = filter 
        ? contributorsList.filter(c => 
            c.name.toLowerCase().includes(filterLower) ||
            (c.email && c.email.toLowerCase().includes(filterLower))
          )
        : contributorsList;
    
    if (filtered.length === 0) {
        dropdown.innerHTML = `
            <div class="p-3 text-sm text-text-secondary">
                ${filter ? 'No matching contributors. A new one will be created.' : 'No contributors found.'}
            </div>
        `;
        return;
    }
    
    dropdown.innerHTML = filtered.map(c => `
        <div class="contributor-option p-3 hover:bg-dashboard-hover cursor-pointer border-b border-border last:border-b-0"
             data-id="${escapeHtmlForContributions(c.id)}"
             data-name="${escapeHtmlForContributions(c.name)}"
             data-email="${escapeHtmlForContributions(c.email || '')}">
            <div class="font-medium text-text-primary">${escapeHtmlForContributions(c.name)}</div>
            ${c.email ? `<div class="text-xs text-text-secondary">${escapeHtmlForContributions(c.email)}</div>` : ''}
        </div>
    `).join('');
    
    // Add click handlers to dropdown items
    dropdown.querySelectorAll('.contributor-option').forEach(option => {
        option.addEventListener('click', () => {
            selectContributor(
                option.getAttribute('data-id') || '',
                option.getAttribute('data-name') || '',
                option.getAttribute('data-email') || ''
            );
        });
    });
}

// Select a contributor from dropdown
function selectContributor(id: string, name: string, email: string): void {
    const contributorInput = document.getElementById('contributor') as HTMLInputElement | null;
    const contributorIdInput = document.getElementById('contributor-id') as HTMLInputElement | null;
    const emailInput = document.getElementById('email') as HTMLInputElement | null;
    const dropdown = document.getElementById('contributor-dropdown');
    
    if (contributorInput) {
        contributorInput.value = name;
    }
    if (contributorIdInput) {
        contributorIdInput.value = id;
    }
    // Auto-fill email only if email field is empty
    if (emailInput && !emailInput.value && email) {
        emailInput.value = email;
    }
    
    selectedContributorId = id;
    
    // Hide dropdown
    if (dropdown) {
        dropdown.classList.add('hidden');
    }
}

// Setup contributor autocomplete with custom dropdown
function setupContributorAutoFill(): void {
    const contributorInput = document.getElementById('contributor') as HTMLInputElement | null;
    const contributorIdInput = document.getElementById('contributor-id') as HTMLInputElement | null;
    const dropdown = document.getElementById('contributor-dropdown');
    
    if (!contributorInput || !dropdown) return;
    
    // Show dropdown and filter on input
    contributorInput.addEventListener('input', () => {
        const value = contributorInput.value;
        
        // Clear contributor_id when user types (they're no longer selecting existing)
        if (contributorIdInput) {
            contributorIdInput.value = '';
        }
        selectedContributorId = null;
        
        // Show dropdown with filtered results
        renderContributorDropdown(value);
        dropdown.classList.remove('hidden');
    });
    
    // Show dropdown on focus
    contributorInput.addEventListener('focus', () => {
        renderContributorDropdown(contributorInput.value);
        dropdown.classList.remove('hidden');
    });
    
    // Hide dropdown when clicking outside
    document.addEventListener('click', (e) => {
        const target = e.target as Node;
        if (!contributorInput.contains(target) && !dropdown.contains(target)) {
            dropdown.classList.add('hidden');
        }
    });
    
    // Keyboard navigation
    contributorInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            dropdown.classList.add('hidden');
        } else if (e.key === 'ArrowDown') {
            const firstOption = dropdown.querySelector('.contributor-option') as HTMLElement | null;
            if (firstOption) {
                e.preventDefault();
                firstOption.focus();
            }
        }
    });
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
                const tr = document.createElement('tr');
                tr.className = 'bg-dashboard-surface border-b border-border hover:bg-dashboard-hover';

                const isContrib = row.contribution_type === 'CONTRIBUTION';
                const typeBadge = isContrib
                    ? '<span class="bg-theme-success-bg/20 text-theme-success-text text-xs font-medium px-2.5 py-0.5 rounded">DEPOSIT</span>'
                    : '<span class="bg-theme-error-bg/20 text-theme-error-text text-xs font-medium px-2.5 py-0.5 rounded">WITHDRAWAL</span>';

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

        // Note: Datalist is now populated from loadContributors(), not from history

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
        const payload: Record<string, string | null> = {};
        formData.forEach((value, key) => {
            payload[key] = value.toString();
        });
        
        // Include contributor_id if we have a selected contributor
        if (selectedContributorId) {
            payload['contributor_id'] = selectedContributorId;
        }

        const response = await fetch('/api/admin/contributions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
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
            selectedContributorId = null; // Clear contributor selection
            // Also clear the hidden contributor_id input
            const contributorIdInput = document.getElementById('contributor-id') as HTMLInputElement | null;
            if (contributorIdInput) {
                contributorIdInput.value = '';
            }
            const dateInput = document.getElementById('date') as HTMLInputElement | null;
            if (dateInput) {
                dateInput.valueAsDate = new Date();
            }
            // Refresh tables and reload contributors (in case a new one was created)
            await Promise.all([fetchHistory(), loadContributors()]);
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

    // Load funds and contributors
    loadFunds();
    loadContributors();
    
    // Set up contributor auto-fill (email auto-populates when selecting from dropdown)
    setupContributorAutoFill();

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
