/**
 * Fund Management Dashboard
 * Handles fund CRUD operations, production toggles, and portfolio rebuilds
 */

import { getCsrfHeaders } from './csrf.js';

// Type definitions
interface Fund {
    name: string;
    description?: string;
    type?: string;
    currency?: string;
    is_production?: boolean;
    positions?: number;
    trades?: number;
}

interface FundsResponse {
    funds: Fund[];
}

interface FundResponse {
    success?: boolean;
    error?: string;
    data?: {
        company_name?: string;
        sector?: string;
    };
    pid?: number;
}

interface ApiResponse {
    success?: boolean;
    error?: string;
    message?: string;
}

// State
let allFunds: Fund[] = [];

// DOM Elements
const getElements = () => ({
    tableBody: document.getElementById('funds-table-body'),
    rebuildSelect: document.getElementById('rebuild-fund-select') as HTMLSelectElement | null,
    statsCards: document.getElementById('fund-stats-cards'),
    deleteArea: document.getElementById('delete-confirm-area'),
    editOriginalName: document.getElementById('edit-fund-original-name') as HTMLInputElement | null,
    editName: document.getElementById('edit-fund-name') as HTMLInputElement | null,
    editDesc: document.getElementById('edit-fund-desc') as HTMLInputElement | null,
    editType: document.getElementById('edit-fund-type') as HTMLSelectElement | null,
    editCurrency: document.getElementById('edit-fund-currency') as HTMLSelectElement | null,
    deleteConfirmInput: document.getElementById('delete-confirm-input') as HTMLInputElement | null,
    refreshTicker: document.getElementById('refresh-ticker') as HTMLInputElement | null,
    refreshCurrency: document.getElementById('refresh-currency') as HTMLSelectElement | null,
    refreshResult: document.getElementById('refresh-result'),
});

// Utility functions (scoped to funds.ts to avoid conflicts with other files)
function escapeHtmlForFunds(text: string | undefined | null): string {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToastForFunds(message: string, type: 'success' | 'error' = 'success'): void {
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 z-50 p-4 rounded-lg shadow-lg ${type === 'success' ? 'bg-theme-success-bg text-theme-success-text border border-theme-success-text' : 'bg-theme-error-bg text-theme-error-text border border-theme-error-text'
        }`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('opacity-0', 'transition-opacity', 'duration-300');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Close edit modal by clicking Flowbite's hide trigger (modal must be initialized via data-modal-target)
function closeEditModal(): void {
    document.querySelector<HTMLElement>('[data-modal-hide="edit-fund-modal"]')?.click();
}

// Close create modal by clicking Flowbite's hide trigger
function closeCreateModal(): void {
    document.querySelector<HTMLElement>('[data-modal-hide="create-fund-modal"]')?.click();
}

// Load funds from API
async function loadFunds(): Promise<void> {
    const elements = getElements();
    const tableBody = elements.tableBody;
    const rebuildSelect = elements.rebuildSelect;
    const statsCards = elements.statsCards;

    try {
        const response = await fetch('/api/v2/funds', { credentials: 'include' });

        if (!response.ok) {
            const errorData: ApiResponse = await response.json().catch(() => ({
                error: `HTTP ${response.status}: ${response.statusText}`
            }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: FundsResponse = await response.json();
        allFunds = data.funds || [];

        // Populate Table
        if (allFunds.length === 0) {
            if (tableBody) {
                tableBody.innerHTML = '<tr><td colspan="6" class="px-6 py-4 text-center">No funds found</td></tr>';
            }
        } else {
            if (tableBody) {
                tableBody.innerHTML = allFunds.map(fund => `
                    <tr class="bg-dashboard-surface border-b border-border hover:bg-dashboard-background">
                        <td class="px-6 py-4 font-medium text-text-primary whitespace-nowrap">${escapeHtmlForFunds(fund.name)}</td>
                        <td class="px-6 py-4 text-text-secondary">${escapeHtmlForFunds(fund.type || 'investment')}</td>
                        <td class="px-6 py-4 text-text-secondary">${escapeHtmlForFunds(fund.currency || 'CAD')}</td>
                        <td class="px-6 py-4">
                            <label class="relative inline-flex items-center cursor-pointer">
                                <input type="checkbox" value="" class="sr-only peer" ${fund.is_production ? 'checked' : ''} onchange="window.toggleProduction('${escapeHtmlForFunds(fund.name)}', this.checked)">
                                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-accent/30 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-accent dark:bg-gray-700 dark:border-gray-600"></div>
                            </label>
                        </td>
                        <td class="px-6 py-4 text-text-secondary">
                            <div class="text-xs">
                                <div>Pos: ${fund.positions || 0}</div>
                                <div>Trades: ${fund.trades || 0}</div>
                            </div>
                        </td>
                        <td class="px-6 py-4 text-right">
                            <button onclick="window.openEditModal('${escapeHtmlForFunds(fund.name)}')" class="text-accent hover:text-accent-hover font-medium">Edit</button>
                        </td>
                    </tr>
                `).join('');
            }
        }

        // Populate rebuild select
        if (rebuildSelect) {
            rebuildSelect.innerHTML = '<option value="">Select fund...</option>';
            allFunds.forEach(fund => {
                const opt = document.createElement('option');
                opt.value = fund.name;
                opt.textContent = fund.name;
                rebuildSelect.appendChild(opt);
            });
        }

        // Populate stats cards
        if (statsCards) {
            const totalFunds = allFunds.length;
            const productionFunds = allFunds.filter(f => f.is_production).length;
            const totalPositions = allFunds.reduce((sum, f) => sum + (f.positions || 0), 0);

            statsCards.innerHTML = `
                <div class="bg-dashboard-surface rounded-lg shadow-sm border border-border p-6">
                    <div class="flex items-center">
                        <div class="p-3 bg-theme-info-bg rounded-lg">
                            <i class="fas fa-building text-theme-info-text text-2xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-text-secondary">Total Funds</p>
                            <p class="text-2xl font-bold text-text-primary">${totalFunds}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-dashboard-surface rounded-lg shadow-sm border border-border p-6">
                    <div class="flex items-center">
                        <div class="p-3 bg-theme-success-bg rounded-lg">
                            <i class="fas fa-check-circle text-theme-success-text text-2xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-text-secondary">Production</p>
                            <p class="text-2xl font-bold text-text-primary">${productionFunds}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-dashboard-surface rounded-lg shadow-sm border border-border p-6">
                    <div class="flex items-center">
                        <div class="p-3 bg-purple-100 rounded-lg dark:bg-purple-900/30">
                            <i class="fas fa-chart-line text-purple-600 text-2xl dark:text-purple-400"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-text-secondary">Total Positions</p>
                            <p class="text-2xl font-bold text-text-primary">${totalPositions}</p>
                        </div>
                    </div>
                </div>
            `;
        }

    } catch (error) {
        console.error('[Funds] Error loading funds:', error);
        if (tableBody) {
            const errorMessage = error instanceof Error ? error.message : 'Unknown error';
            tableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-center text-theme-error-text">Error loading funds: ${escapeHtmlForFunds(errorMessage)}</td></tr>`;
        }
    }
}

// Toggle production status
async function toggleProduction(fundName: string, isProduction: boolean): Promise<void> {
    try {
        const response = await fetch(`/api/v2/funds/${encodeURIComponent(fundName)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({ is_production: isProduction }),
            credentials: 'include'
        });

        if (!response.ok) {
            const errorData: ApiResponse = await response.json().catch(() => ({
                error: `HTTP ${response.status}`
            }));
            throw new Error(errorData.error || 'Failed to update production status');
        }

        showToastForFunds(isProduction ? '✅ Fund set to production' : '✅ Fund set to test', 'success');
        await loadFunds(); // Refresh
    } catch (error) {
        console.error('[Funds] Error toggling production:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
        await loadFunds(); // Refresh to reset toggle
    }
}

// Open edit modal
function openEditModal(fundName: string): void {
    const fund = allFunds.find(f => f.name === fundName);
    if (!fund) return;

    const elements = getElements();
    if (elements.editOriginalName) elements.editOriginalName.value = fund.name;
    if (elements.editName) elements.editName.value = fund.name;
    if (elements.editDesc) elements.editDesc.value = fund.description || '';
    if (elements.editType) elements.editType.value = fund.type || 'investment';
    if (elements.editCurrency) elements.editCurrency.value = fund.currency || 'CAD';

    // Reset delete confirmation area
    if (elements.deleteArea) {
        elements.deleteArea.classList.add('hidden');
    }
    if (elements.deleteConfirmInput) {
        elements.deleteConfirmInput.value = '';
    }

    // Open via Flowbite's trigger so the modal is in Flowbite's registry (required for data-modal-hide)
    const trigger = document.getElementById('edit-fund-modal-trigger');
    if (trigger) {
        trigger.click();
    } else {
        console.error('[Funds] Edit fund modal trigger not found');
    }
}

// Create fund
async function createFund(event: Event): Promise<void> {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    const btn = form.querySelector('button[type="submit"]') as HTMLButtonElement;
    if (!btn) return;

    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
    btn.disabled = true;

    try {
        const formData = new FormData(form);
        const data = {
            name: formData.get('name') as string,
            description: (formData.get('description') as string) || '',
            fund_type: (formData.get('fund_type') as string) || 'investment',
            currency: (formData.get('currency') as string) || 'CAD'
        };

        const response = await fetch('/api/v2/funds', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify(data),
            credentials: 'include'
        });

        const result: FundResponse = await response.json();

        if (!response.ok) {
            throw new Error(result.error || 'Failed to create fund');
        }

        showToastForFunds('✅ Fund created successfully', 'success');
        form.reset();

        closeCreateModal();

        await loadFunds();
    } catch (error) {
        console.error('[Funds] Error creating fund:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// Update fund
async function updateFund(event: Event): Promise<void> {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    const btn = form.querySelector('button[type="submit"]') as HTMLButtonElement;
    if (!btn) return;

    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    btn.disabled = true;

    try {
        const elements = getElements();
        const originalName = elements.editOriginalName?.value || '';
        const newName = elements.editName?.value || '';
        const description = elements.editDesc?.value || '';
        const fundType = elements.editType?.value || 'investment';
        const currency = elements.editCurrency?.value || 'CAD';

        // If name changed, use rename endpoint
        if (newName !== originalName) {
            const renameResponse = await fetch('/api/v2/funds/rename', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({ old_name: originalName, new_name: newName }),
                credentials: 'include'
            });

            if (!renameResponse.ok) {
                const errorData: ApiResponse = await renameResponse.json().catch(() => ({
                    error: 'Rename failed'
                }));
                throw new Error(errorData.error || 'Failed to rename fund');
            }
        }

        // Update other fields
        const updateData = {
            description: description,
            fund_type: fundType,
            currency: currency
        };

        const response = await fetch(`/ api / v2 / funds / ${encodeURIComponent(newName)} `, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify(updateData),
            credentials: 'include'
        });

        if (!response.ok) {
            const errorData: ApiResponse = await response.json().catch(() => ({
                error: 'Update failed'
            }));
            throw new Error(errorData.error || 'Failed to update fund');
        }

        showToastForFunds('✅ Fund updated successfully', 'success');

        closeEditModal();

        await loadFunds();
    } catch (error) {
        console.error('[Funds] Error updating fund:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// Show delete confirmation
function showDeleteConfirm(): void {
    const elements = getElements();
    if (elements.deleteArea) {
        elements.deleteArea.classList.remove('hidden');
    }
}

// Confirm delete fund
async function confirmDeleteFund(): Promise<void> {
    const elements = getElements();
    const originalName = elements.editOriginalName?.value || '';
    const confirmInput = elements.deleteConfirmInput?.value || '';

    if (confirmInput !== originalName) {
        showToastForFunds('❌ Fund name does not match', 'error');
        return;
    }

    try {
        const response = await fetch(`/ api / v2 / funds / ${encodeURIComponent(originalName)} `, {
            method: 'DELETE',
            headers: { ...getCsrfHeaders() },
            credentials: 'include'
        });

        if (!response.ok) {
            const errorData: ApiResponse = await response.json().catch(() => ({
                error: 'Delete failed'
            }));
            throw new Error(errorData.error || 'Failed to delete fund');
        }

        showToastForFunds('✅ Fund deleted successfully', 'success');

        closeEditModal();

        await loadFunds();
    } catch (error) {
        console.error('[Funds] Error deleting fund:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
    }
}

// Refresh ticker metadata
async function refreshTickerMetadata(): Promise<void> {
    const elements = getElements();
    const ticker = elements.refreshTicker?.value.trim().toUpperCase() || '';
    const currency = elements.refreshCurrency?.value || '';
    const resultDiv = elements.refreshResult;

    if (!ticker) {
        showToastForFunds('❌ Please enter a ticker symbol', 'error');
        return;
    }

    if (!resultDiv) return;

    resultDiv.classList.remove('hidden', 'bg-theme-success-bg', 'text-theme-success-text', 'bg-theme-error-bg', 'text-theme-error-text');
    resultDiv.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refreshing...';
    resultDiv.classList.add('bg-theme-info-bg', 'text-theme-info-text');

    try {
        const response = await fetch('/api/v2/ticker/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({ ticker, currency }),
            credentials: 'include'
        });

        const result: FundResponse = await response.json();

        if (!response.ok) {
            throw new Error(result.error || 'Failed to refresh ticker');
        }

        const companyName = result.data?.company_name || ticker;
        const sector = result.data?.sector || 'N/A';
        resultDiv.innerHTML = `✅ Updated: ${companyName} (${sector})`;
        resultDiv.classList.remove('bg-theme-info-bg', 'text-theme-info-text');
        resultDiv.classList.add('bg-theme-success-bg', 'text-theme-success-text');

        if (elements.refreshTicker) {
            elements.refreshTicker.value = '';
        }
    } catch (error) {
        console.error('[Funds] Error refreshing ticker:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        resultDiv.innerHTML = '❌ ' + errorMessage;
        resultDiv.classList.remove('bg-theme-info-bg', 'text-theme-info-text');
        resultDiv.classList.add('bg-theme-error-bg', 'text-theme-error-text');
    }
}

// Rebuild portfolio
async function rebuildPortfolio(): Promise<void> {
    const elements = getElements();
    const fundSelect = elements.rebuildSelect;
    const fundName = fundSelect?.value || '';

    if (!fundName) {
        showToastForFunds('❌ Please select a fund', 'error');
        return;
    }

    (window as any).showConfirmModal({
        title: 'Rebuild portfolio',
        message: `Rebuild portfolio for "${fundName}"? This may take several minutes.`,
        confirmLabel: 'Start rebuild',
        onConfirm: async () => {
            try {
                const response = await fetch('/api/v2/funds/rebuild', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                    body: JSON.stringify({ fund_name: fundName }),
                    credentials: 'include'
                });
                const result: FundResponse = await response.json();
                if (!response.ok) {
                    throw new Error(result.error || 'Failed to start rebuild');
                }
                const pid = result.pid || 'N/A';
                showToastForFunds(`✅ Rebuild started for ${fundName}(PID: ${pid})`, 'success');
            } catch (error) {
                console.error('[Funds] Error starting rebuild:', error);
                const errorMessage = error instanceof Error ? error.message : 'Unknown error';
                showToastForFunds('❌ ' + errorMessage, 'error');
            }
        }
    });
}

// Initialize on page load (Flowbite modals are initialized via data-modal-target in template)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadFunds);
} else {
    loadFunds();
}

// Make functions globally available for onclick handlers
window.toggleProduction = toggleProduction;
window.openEditModal = openEditModal;
window.createFund = createFund;
window.updateFund = updateFund;
window.showDeleteConfirm = showDeleteConfirm;
window.confirmDeleteFund = confirmDeleteFund;
window.refreshTickerMetadata = refreshTickerMetadata;
window.rebuildPortfolio = rebuildPortfolio;
