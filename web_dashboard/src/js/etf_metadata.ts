export { }; // Ensure file is treated as a module

interface ETFMetadata {
    ticker: string;
    company_name?: string;
    fund_description?: string;
}

interface ETFMetadataResponse {
    success: boolean;
    etfs?: ETFMetadata[];
    error?: string;
}

// DOM Elements
const loadingState = document.getElementById('loading-state');
const errorState = document.getElementById('error-state');
const errorMessage = document.getElementById('error-message');
const etfList = document.getElementById('etf-list');

// Load ETFs on page load
document.addEventListener('DOMContentLoaded', async () => {
    await loadETFs();
});

async function loadETFs(): Promise<void> {
    if (loadingState) loadingState.classList.remove('hidden');
    if (errorState) errorState.classList.add('hidden');
    if (etfList) etfList.classList.add('hidden');

    try {
        const response = await fetch('/api/admin/etf-metadata', {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result: ETFMetadataResponse = await response.json();

        if (result.success && result.etfs) {
            renderETFs(result.etfs);
        } else {
            throw new Error(result.error || 'Failed to load ETFs');
        }
    } catch (error) {
        console.error('Error loading ETFs:', error);
        if (errorState && errorMessage) {
            errorMessage.textContent = error instanceof Error ? error.message : 'Failed to load ETFs';
            errorState.classList.remove('hidden');
        }
    } finally {
        if (loadingState) loadingState.classList.add('hidden');
    }
}

function renderETFs(etfs: ETFMetadata[]): void {
    if (!etfList) return;

    etfList.innerHTML = etfs.map(etf => {
        const ticker = escapeHtml(etf.ticker);
        const companyName = escapeHtml(etf.company_name || '');
        // For textarea, we need to escape quotes and backticks but preserve newlines
        const description = escapeForTextarea(etf.fund_description || '');

        return `
            <div class="bg-dashboard-surface rounded-lg shadow-sm p-6 border border-border">
                <div class="flex items-center justify-between mb-4">
                    <div>
                        <h3 class="text-lg font-bold text-text-primary">${ticker}</h3>
                        ${companyName ? `<p class="text-sm text-text-secondary">${companyName}</p>` : ''}
                    </div>
                    <button onclick="saveETFMetadata('${ticker}')" 
                            class="px-4 py-2 text-sm font-medium text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors">
                        💾 Save
                    </button>
                </div>
                
                <div>
                    <label for="description-${ticker}" class="block mb-2 text-sm font-medium text-text-primary">
                        Fund Description
                    </label>
                    <p class="text-xs text-text-secondary mb-2">
                        Include fund objective, strategy, themes, and sectors. Line breaks are preserved.
                    </p>
                    <textarea id="description-${ticker}" 
                              rows="10"
                              class="w-full px-3 py-2 bg-dashboard-background border border-border rounded-lg text-text-primary font-mono text-sm whitespace-pre-wrap"
                              placeholder="Fund Objective:&#10;ARKQ is an actively managed ETF that seeks...&#10;&#10;Fund Description:&#10;Companies within ARKQ are focused on...">${description}</textarea>
                </div>
            </div>
        `;
    }).join('');

    etfList.classList.remove('hidden');
}

function escapeForTextarea(text: string): string {
    // Escape backticks and backslashes for template literals, but preserve newlines
    return text
        .replace(/\\/g, '\\\\')  // Escape backslashes
        .replace(/`/g, '\\`')    // Escape backticks
        .replace(/\${/g, '\\${'); // Escape template literal expressions
}

async function saveETFMetadata(ticker: string): Promise<void> {
    const descriptionEl = document.getElementById(`description-${ticker}`) as HTMLTextAreaElement;

    if (!descriptionEl) {
        showToast('Error: Could not find form field', 'error');
        return;
    }

    // Preserve line breaks - don't trim, just get the value as-is
    const fund_description = descriptionEl.value;

    try {
        const response = await fetch(`/api/admin/etf-metadata/${encodeURIComponent(ticker)}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({
                fund_description
            })
        });

        if (response.ok) {
            showToast(`Saved metadata for ${ticker}`, 'success');
        } else {
            const result = await response.json();
            showToast(result.error || 'Failed to save', 'error');
        }
    } catch (error) {
        console.error('Error saving ETF metadata:', error);
        showToast('Failed to save metadata', 'error');
    }
}

function escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message: string, type: 'success' | 'error' | 'info' = 'info'): void {
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 px-4 py-2 rounded shadow-lg z-50 ${
        type === 'success' ? 'bg-green-500 text-white' :
        type === 'error' ? 'bg-red-500 text-white' :
        'bg-blue-500 text-white'
    }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

// Make saveETFMetadata available globally
(window as any).saveETFMetadata = saveETFMetadata;
