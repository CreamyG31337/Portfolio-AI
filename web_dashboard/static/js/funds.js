/**
 * Fund Management Dashboard
 * Handles fund CRUD operations, production toggles, and portfolio rebuilds
 */
import { getCsrfHeaders } from './csrf.js';
import { showToast as showToastBase } from './toast.js';
// State
let allFunds = [];
// DOM Elements
const getElements = () => ({
    tableBody: document.getElementById('funds-table-body'),
    statsCards: document.getElementById('fund-stats-cards'),
    deleteArea: document.getElementById('delete-confirm-area'),
    editOriginalName: document.getElementById('edit-fund-original-name'),
    editName: document.getElementById('edit-fund-name'),
    editDesc: document.getElementById('edit-fund-desc'),
    editType: document.getElementById('edit-fund-type'),
    editDividendMode: document.getElementById('edit-fund-dividend-mode'),
    editCurrency: document.getElementById('edit-fund-currency'),
    deleteConfirmInput: document.getElementById('delete-confirm-input'),
    refreshTicker: document.getElementById('refresh-ticker'),
    refreshCurrency: document.getElementById('refresh-currency'),
    refreshResult: document.getElementById('refresh-result'),
    cashCadInput: document.getElementById('cash-cad-input'),
    cashUsdInput: document.getElementById('cash-usd-input'),
    cashSaveBtn: document.getElementById('cash-save-btn'),
    rebuildIndicator: document.getElementById('rebuild-fund-indicator'),
    cashIndicator: document.getElementById('cash-fund-indicator'),
});
// Utility functions (scoped to funds.ts to avoid conflicts with other files)
function escapeHtmlForFunds(text) {
    if (!text)
        return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
function showToastForFunds(message, type = 'success') {
    showToastBase(message, type);
}
function getSelectedFund() {
    const sel = document.getElementById('global-fund-select');
    return (sel?.value || '').trim();
}
function isSingleFundSelected() {
    const v = getSelectedFund();
    return v !== '' && v !== 'all';
}
function updateFundIndicators() {
    const v = getSelectedFund();
    const label = !v
        ? '(no fund selected)'
        : v === 'all'
            ? 'All Funds (select a specific fund to use these actions)'
            : v;
    const elements = getElements();
    if (elements.rebuildIndicator)
        elements.rebuildIndicator.textContent = label;
    if (elements.cashIndicator)
        elements.cashIndicator.textContent = label;
}
function closeEditModal() {
    // tsc does not bundle bare "flowbite" imports; click the data-modal-hide
    // trigger so Flowbite (loaded globally) closes the modal and backdrop.
    document.querySelector('[data-modal-hide="edit-fund-modal"]')?.click();
}
function closeCreateModal() {
    document.querySelector('[data-modal-hide="create-fund-modal"]')?.click();
}
// Load funds from API
async function loadFunds() {
    const elements = getElements();
    const tableBody = elements.tableBody;
    const statsCards = elements.statsCards;
    try {
        const response = await fetch('/api/v2/funds', { credentials: 'include' });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({
                error: `HTTP ${response.status}: ${response.statusText}`
            }));
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        allFunds = data.funds || [];
        // Populate Table
        if (allFunds.length === 0) {
            if (tableBody) {
                tableBody.innerHTML = '<tr><td colspan="7" class="px-6 py-4 text-center">No funds found</td></tr>';
            }
        }
        else {
            if (tableBody) {
                tableBody.innerHTML = allFunds.map(fund => `
                    <tr class="bg-dashboard-surface border-b border-border hover:bg-dashboard-background">
                        <td class="px-6 py-4 font-medium text-text-primary whitespace-nowrap">${escapeHtmlForFunds(fund.name)}</td>
                        <td class="px-6 py-4 text-text-secondary">${escapeHtmlForFunds(fund.type || 'investment')}</td>
                        <td class="px-6 py-4 text-text-secondary">${escapeHtmlForFunds(fund.dividend_mode || 'reinvest')}</td>
                        <td class="px-6 py-4 text-text-secondary">${escapeHtmlForFunds(fund.currency || 'CAD')}</td>
                        <td class="px-6 py-4">
                            <label class="relative inline-flex items-center cursor-pointer">
                                <input type="checkbox" value="" class="sr-only peer" ${fund.is_production ? 'checked' : ''} onchange="window.toggleProduction('${escapeHtmlForFunds(fund.name)}', this.checked)">
                                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-hidden peer-focus:ring-4 peer-focus:ring-accent/30 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-accent dark:bg-gray-700 dark:border-gray-600"></div>
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
        // Populate stats cards
        if (statsCards) {
            const totalFunds = allFunds.length;
            const productionFunds = allFunds.filter(f => f.is_production).length;
            const totalPositions = allFunds.reduce((sum, f) => sum + (f.positions || 0), 0);
            statsCards.innerHTML = `
                <div class="bg-dashboard-surface rounded-lg shadow-xs border border-border p-6">
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
                <div class="bg-dashboard-surface rounded-lg shadow-xs border border-border p-6">
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
                <div class="bg-dashboard-surface rounded-lg shadow-xs border border-border p-6">
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
    }
    catch (error) {
        console.error('[Funds] Error loading funds:', error);
        if (tableBody) {
            const errorMessage = error instanceof Error ? error.message : 'Unknown error';
            tableBody.innerHTML = `<tr><td colspan="7" class="px-6 py-4 text-center text-theme-error-text">Error loading funds: ${escapeHtmlForFunds(errorMessage)}</td></tr>`;
        }
    }
}
// Toggle production status
async function toggleProduction(fundName, isProduction) {
    try {
        const response = await fetch(`/api/v2/funds/${encodeURIComponent(fundName)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({ is_production: isProduction }),
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({
                error: `HTTP ${response.status}`
            }));
            throw new Error(errorData.error || 'Failed to update production status');
        }
        showToastForFunds(isProduction ? '✅ Fund set to production' : '✅ Fund set to test', 'success');
        await loadFunds(); // Refresh
    }
    catch (error) {
        console.error('[Funds] Error toggling production:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
        await loadFunds(); // Refresh to reset toggle
    }
}
// Open edit modal
function openEditModal(fundName) {
    const fund = allFunds.find(f => f.name === fundName);
    if (!fund)
        return;
    const elements = getElements();
    if (elements.editOriginalName)
        elements.editOriginalName.value = fund.name;
    if (elements.editName)
        elements.editName.value = fund.name;
    if (elements.editDesc)
        elements.editDesc.value = fund.description || '';
    if (elements.editType)
        elements.editType.value = fund.type || 'investment';
    if (elements.editDividendMode)
        elements.editDividendMode.value = fund.dividend_mode || 'reinvest';
    if (elements.editCurrency)
        elements.editCurrency.value = fund.currency || 'CAD';
    // Reset delete confirmation area
    if (elements.deleteArea) {
        elements.deleteArea.classList.add('hidden');
    }
    if (elements.deleteConfirmInput) {
        elements.deleteConfirmInput.value = '';
    }
    // Open via Flowbite's trigger so the modal is in Flowbite's registry
    // (required for data-modal-hide). Do not `import { Modal } from "flowbite"` —
    // tsc emits a bare specifier and the browser never runs this module.
    const trigger = document.getElementById('edit-fund-modal-trigger');
    if (trigger) {
        trigger.click();
    }
    else {
        console.error('[Funds] Edit fund modal trigger not found');
    }
}
// Create fund
async function createFund(event) {
    event.preventDefault();
    const form = event.target;
    const btn = form.querySelector('button[type="submit"]');
    if (!btn)
        return;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
    btn.disabled = true;
    try {
        const formData = new FormData(form);
        const data = {
            name: formData.get('name'),
            description: formData.get('description') || '',
            fund_type: formData.get('fund_type') || 'investment',
            dividend_mode: formData.get('dividend_mode') || 'reinvest',
            currency: formData.get('currency') || 'CAD'
        };
        const response = await fetch('/api/v2/funds', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify(data),
            credentials: 'include'
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'Failed to create fund');
        }
        showToastForFunds('✅ Fund created successfully', 'success');
        form.reset();
        closeCreateModal();
        await loadFunds();
    }
    catch (error) {
        console.error('[Funds] Error creating fund:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
    }
    finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}
// Update fund
async function updateFund(event) {
    event.preventDefault();
    const form = event.target;
    const btn = form.querySelector('button[type="submit"]');
    if (!btn)
        return;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
    btn.disabled = true;
    try {
        const elements = getElements();
        const originalName = elements.editOriginalName?.value || '';
        const newName = elements.editName?.value || '';
        const description = elements.editDesc?.value || '';
        const fundType = elements.editType?.value || 'investment';
        const dividendMode = elements.editDividendMode?.value || 'reinvest';
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
                const errorData = await renameResponse.json().catch(() => ({
                    error: 'Rename failed'
                }));
                throw new Error(errorData.error || 'Failed to rename fund');
            }
        }
        // Update other fields
        const updateData = {
            description: description,
            fund_type: fundType,
            dividend_mode: dividendMode,
            currency: currency
        };
        const response = await fetch(`/api/v2/funds/${encodeURIComponent(newName)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify(updateData),
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({
                error: 'Update failed'
            }));
            throw new Error(errorData.error || 'Failed to update fund');
        }
        showToastForFunds('✅ Fund updated successfully', 'success');
        closeEditModal();
        await loadFunds();
    }
    catch (error) {
        console.error('[Funds] Error updating fund:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
    }
    finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}
// Show delete confirmation
function showDeleteConfirm() {
    const elements = getElements();
    if (elements.deleteArea) {
        elements.deleteArea.classList.remove('hidden');
    }
}
// Confirm delete fund
async function confirmDeleteFund() {
    const elements = getElements();
    const originalName = elements.editOriginalName?.value || '';
    const confirmInput = elements.deleteConfirmInput?.value || '';
    if (confirmInput !== originalName) {
        showToastForFunds('❌ Fund name does not match', 'error');
        return;
    }
    try {
        const response = await fetch(`/api/v2/funds/${encodeURIComponent(originalName)}`, {
            method: 'DELETE',
            headers: { ...getCsrfHeaders() },
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({
                error: 'Delete failed'
            }));
            throw new Error(errorData.error || 'Failed to delete fund');
        }
        showToastForFunds('✅ Fund deleted successfully', 'success');
        closeEditModal();
        await loadFunds();
    }
    catch (error) {
        console.error('[Funds] Error deleting fund:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
    }
}
// Refresh ticker metadata
async function refreshTickerMetadata() {
    const elements = getElements();
    const ticker = elements.refreshTicker?.value.trim().toUpperCase() || '';
    const currency = elements.refreshCurrency?.value || '';
    const resultDiv = elements.refreshResult;
    if (!ticker) {
        showToastForFunds('❌ Please enter a ticker symbol', 'error');
        return;
    }
    if (!resultDiv)
        return;
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
        const result = await response.json();
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
    }
    catch (error) {
        console.error('[Funds] Error refreshing ticker:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        resultDiv.innerHTML = '❌ ' + errorMessage;
        resultDiv.classList.remove('bg-theme-info-bg', 'text-theme-info-text');
        resultDiv.classList.add('bg-theme-error-bg', 'text-theme-error-text');
    }
}
async function loadCashBalancesForFund(fundName) {
    const elements = getElements();
    const cadEl = elements.cashCadInput;
    const usdEl = elements.cashUsdInput;
    if (!fundName) {
        showToastForFunds('❌ Please select a fund', 'error');
        return;
    }
    try {
        const response = await fetch(`/api/v2/funds/${encodeURIComponent(fundName)}/cash-balances`, { credentials: 'include' });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        if (cadEl)
            cadEl.value = String(data.CAD ?? 0);
        if (usdEl)
            usdEl.value = String(data.USD ?? 0);
    }
    catch (error) {
        console.error('[Funds] Error loading cash balances:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
    }
}
async function saveCashBalances() {
    const elements = getElements();
    const cadEl = elements.cashCadInput;
    const usdEl = elements.cashUsdInput;
    const saveBtn = elements.cashSaveBtn;
    if (saveBtn?.disabled) {
        return;
    }
    if (!isSingleFundSelected()) {
        showToastForFunds('Select a specific fund from the navigation menu', 'error');
        return;
    }
    const fundName = getSelectedFund();
    const cad = parseFloat((cadEl?.value ?? '').trim());
    const usd = parseFloat((usdEl?.value ?? '').trim());
    if (!Number.isFinite(cad) || !Number.isFinite(usd)) {
        showToastForFunds('❌ Enter valid CAD and USD numbers', 'error');
        return;
    }
    if (saveBtn)
        saveBtn.disabled = true;
    try {
        const response = await fetch(`/api/v2/funds/${encodeURIComponent(fundName)}/cash-balances`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({ CAD: cad, USD: usd }),
            credentials: 'include',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        if (cadEl && data.balances)
            cadEl.value = String(data.balances.CAD ?? cad);
        if (usdEl && data.balances)
            usdEl.value = String(data.balances.USD ?? usd);
        showToastForFunds(data.message || '✅ Cash balances saved', 'success');
    }
    catch (error) {
        console.error('[Funds] Error saving cash balances:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showToastForFunds('❌ ' + errorMessage, 'error');
    }
    finally {
        if (saveBtn)
            saveBtn.disabled = false;
    }
}
// Rebuild portfolio
async function rebuildPortfolio() {
    if (!isSingleFundSelected()) {
        showToastForFunds('Select a specific fund from the navigation menu', 'error');
        return;
    }
    const fundName = getSelectedFund();
    window.showConfirmModal({
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
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.error || 'Failed to start rebuild');
                }
                const pid = result.pid || 'N/A';
                showToastForFunds(`✅ Rebuild started for ${fundName}(PID: ${pid})`, 'success');
            }
            catch (error) {
                console.error('[Funds] Error starting rebuild:', error);
                const errorMessage = error instanceof Error ? error.message : 'Unknown error';
                showToastForFunds('❌ ' + errorMessage, 'error');
            }
        }
    });
}
// Initialize on page load (Flowbite modals are initialized via data-modal-target in template)
async function init() {
    await loadFunds();
    updateFundIndicators();
    if (isSingleFundSelected()) {
        void loadCashBalancesForFund(getSelectedFund());
    }
}
window.addEventListener('fundChanged', (e) => {
    updateFundIndicators();
    const detail = e.detail;
    const fund = detail?.fund || '';
    const elements = getElements();
    if (fund && fund !== 'all') {
        void loadCashBalancesForFund(fund);
    }
    else {
        if (elements.cashCadInput)
            elements.cashCadInput.value = '';
        if (elements.cashUsdInput)
            elements.cashUsdInput.value = '';
    }
});
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { void init(); });
}
else {
    void init();
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
window.saveCashBalances = saveCashBalances;
//# sourceMappingURL=funds.js.map