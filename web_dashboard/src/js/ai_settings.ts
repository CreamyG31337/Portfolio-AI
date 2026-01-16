import { ApiResponse } from './types';

// Types for AI Settings
interface StatusResponse {
    ollama: {
        status: boolean;
        message: string;
    };
    postgres: {
        status: string;
        message?: string;
    };
    webai?: {
        status: boolean;
        message: string;
        source?: string;
        has_1psid?: boolean;
        has_1psidts?: boolean;
    };
}

interface SettingsResponse {
    auto_blacklist_threshold: string;
    max_research_batch_size: string;
    [key: string]: string;
}

interface BlacklistEntry {
    domain: string;
    auto_blacklisted?: boolean;
    auto_blacklisted_at?: string;
    last_failure_reason?: string;
    consecutive_failures?: number;
    updated_at?: string;
    // Legacy fields for compatibility
    reason?: string;
    added_at?: string;
    added_by?: string;
}

interface BlacklistResponse {
    blacklist?: BlacklistEntry[];
    error?: string;
}

// DOM Elements
const ollamaIndicator = document.getElementById('ollama-indicator');
const ollamaMessage = document.getElementById('ollama-message');
const testOllamaBtn = document.getElementById('test-ollama-btn');

const postgresIndicator = document.getElementById('postgres-indicator');
const postgresMessage = document.getElementById('postgres-message');

const settingsForm = document.getElementById('settings-form') as HTMLFormElement | null;
const autoBlacklistInput = document.getElementById('auto_blacklist_threshold') as HTMLInputElement | null;
const maxBatchSizeInput = document.getElementById('max_research_batch_size') as HTMLInputElement | null;
const saveSettingsBtn = document.getElementById('save-settings-btn');

const addDomainInput = document.getElementById('add-domain-input') as HTMLInputElement | null;
const addDomainBtn = document.getElementById('add-domain-btn');
const blacklistTableBody = document.getElementById('blacklist-table-body');

const webaiIndicator = document.getElementById('webai-indicator');
const webaiMessage = document.getElementById('webai-message');
const webaiSource = document.getElementById('webai-source');
const testWebaiBtn = document.getElementById('test-webai-btn');

const cookieJsonMethod = document.getElementById('cookie-json-method');
const cookieIndividualMethod = document.getElementById('cookie-individual-method');
const cookieJsonInput = document.getElementById('cookie-json-input') as HTMLTextAreaElement | null;
const cookie1psidInput = document.getElementById('cookie-1psid-input') as HTMLInputElement | null;
const cookie1psidtsInput = document.getElementById('cookie-1psidts-input') as HTMLInputElement | null;
const saveCookiesBtn = document.getElementById('save-cookies-btn');

// Status Check Function
async function checkStatus() {
    if (ollamaMessage) ollamaMessage.textContent = 'Checking...';
    if (postgresMessage) postgresMessage.textContent = 'Checking...';
    if (webaiMessage) webaiMessage.textContent = 'Checking...';

    try {
        const response = await fetch('/api/admin/ai/status');
        const data: StatusResponse = await response.json();

        // Update Ollama Status
        if (ollamaIndicator && ollamaMessage) {
            if (data.ollama.status) {
                ollamaIndicator.classList.remove('bg-gray-200', 'bg-red-500');
                ollamaIndicator.classList.add('bg-green-500');
                ollamaMessage.textContent = 'Online';
                ollamaMessage.classList.remove('text-red-500');
                ollamaMessage.classList.add('text-green-500');
            } else {
                ollamaIndicator.classList.remove('bg-gray-200', 'bg-green-500');
                ollamaIndicator.classList.add('bg-red-500');
                ollamaMessage.textContent = data.ollama.message || 'Offline';
                ollamaMessage.classList.remove('text-green-500');
                ollamaMessage.classList.add('text-red-500');
            }
        }

        // Update Postgres Status
        if (postgresIndicator && postgresMessage) {
            if (data.postgres.status === 'healthy') {
                postgresIndicator.classList.remove('bg-gray-200', 'bg-red-500');
                postgresIndicator.classList.add('bg-green-500');
                postgresMessage.textContent = 'Connected';
                postgresMessage.classList.remove('text-red-500');
                postgresMessage.classList.add('text-green-500');
            } else {
                postgresIndicator.classList.remove('bg-gray-200', 'bg-green-500');
                postgresIndicator.classList.add('bg-red-500');
                postgresMessage.textContent = data.postgres.message || 'Error';
                postgresMessage.classList.remove('text-green-500');
                postgresMessage.classList.add('text-red-500');
            }
        }

        // Update WebAI Cookie Status
        if (webaiIndicator && webaiMessage && data.webai) {
            if (data.webai.status) {
                webaiIndicator.classList.remove('bg-gray-200', 'bg-red-500');
                webaiIndicator.classList.add('bg-green-500');
                webaiMessage.textContent = 'Configured';
                webaiMessage.classList.remove('text-red-500');
                webaiMessage.classList.add('text-green-500');
                if (webaiSource && data.webai.source) {
                    webaiSource.textContent = `Source: ${data.webai.source}`;
                }
            } else {
                webaiIndicator.classList.remove('bg-gray-200', 'bg-green-500');
                webaiIndicator.classList.add('bg-red-500');
                webaiMessage.textContent = data.webai.message || 'Not configured';
                webaiMessage.classList.remove('text-green-500');
                webaiMessage.classList.add('text-red-500');
                if (webaiSource) {
                    webaiSource.textContent = '';
                }
            }
        }

    } catch (error) {
        console.error('Error checking status:', error);
        if (ollamaMessage) ollamaMessage.textContent = 'Error checking status';
        if (postgresMessage) postgresMessage.textContent = 'Error checking status';
        if (webaiMessage) webaiMessage.textContent = 'Error checking status';
    }
}

// Load Settings Function
async function loadSettings() {
    try {
        const response = await fetch('/api/admin/ai/settings');
        const data: SettingsResponse = await response.json();

        if (data.auto_blacklist_threshold && autoBlacklistInput) {
            autoBlacklistInput.value = data.auto_blacklist_threshold;
        }

        if (data.max_research_batch_size && maxBatchSizeInput) {
            maxBatchSizeInput.value = data.max_research_batch_size;
        }

    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

// Save Settings Function
async function saveSettings(e: Event) {
    e.preventDefault();
    if (!saveSettingsBtn) return;

    // Safety check for inputs
    if (!autoBlacklistInput || !maxBatchSizeInput) {
        console.error('Settings inputs not found');
        return;
    }

    const originalText = saveSettingsBtn.textContent;
    saveSettingsBtn.textContent = 'Saving...';
    (saveSettingsBtn as HTMLButtonElement).disabled = true;

    try {
        const payload = {
            auto_blacklist_threshold: autoBlacklistInput.value,
            max_research_batch_size: maxBatchSizeInput.value
        };

        const response = await fetch('/api/admin/ai/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const result: ApiResponse = await response.json();

        if (result.success) {
            alert('Settings saved successfully');
        } else {
            alert('Error saving settings: ' + (result.error || 'Unknown error'));
        }

    } catch (error) {
        console.error('Error saving settings:', error);
        alert('Error saving settings');
    } finally {
        saveSettingsBtn.textContent = originalText;
        (saveSettingsBtn as HTMLButtonElement).disabled = false;
    }
}

// Load Blacklist Function
async function loadBlacklist() {
    if (!blacklistTableBody) return;

    try {
        const response = await fetch('/api/admin/ai/blacklist');
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data: BlacklistResponse = await response.json();

        blacklistTableBody.innerHTML = '';

        // Handle error response
        if (data.error) {
            const row = document.createElement('tr');
            row.className = 'bg-white border-b dark:bg-gray-800 dark:border-gray-700';
            const cell = document.createElement('td');
            cell.colSpan = 3;
            cell.className = 'px-6 py-4 text-center text-red-600';
            cell.textContent = `Error: ${data.error}`;
            row.appendChild(cell);
            blacklistTableBody.appendChild(row);
            return;
        }

        // Handle missing blacklist array
        if (!data.blacklist || data.blacklist.length === 0) {
            const row = document.createElement('tr');
            row.className = 'bg-white border-b dark:bg-gray-800 dark:border-gray-700';
            const cell = document.createElement('td');
            cell.colSpan = 3;
            cell.className = 'px-6 py-4 text-center';
            cell.textContent = 'No domains in blacklist';
            row.appendChild(cell);
            blacklistTableBody.appendChild(row);
            return;
        }

        data.blacklist!.forEach(entry => {
            const row = document.createElement('tr');
            row.className = 'bg-white border-b dark:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600';
            
            // Use reason or last_failure_reason
            const reason = entry.reason || entry.last_failure_reason || 'Manual addition';
            // Use added_at or auto_blacklisted_at
            const addedAt = entry.added_at || entry.auto_blacklisted_at || entry.updated_at || 'Unknown';

            // Domain Cell
            const domainCell = document.createElement('td');
            domainCell.className = 'px-6 py-4 font-medium text-gray-900 whitespace-nowrap dark:text-white';
            domainCell.textContent = entry.domain;
            row.appendChild(domainCell);

            // Reason Cell
            const reasonCell = document.createElement('td');
            reasonCell.className = 'px-6 py-4';
            reasonCell.textContent = reason;
            row.appendChild(reasonCell);

            // Action Cell
            const actionCell = document.createElement('td');
            actionCell.className = 'px-6 py-4 text-right';
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'delete-domain-btn font-medium text-red-600 dark:text-red-500 hover:underline';
            deleteBtn.textContent = 'Remove';
            deleteBtn.setAttribute('data-domain', entry.domain);
            actionCell.appendChild(deleteBtn);
            row.appendChild(actionCell);

            blacklistTableBody.appendChild(row);
        });

        // Add event listeners to delete buttons scoped to table body
        blacklistTableBody.querySelectorAll('.delete-domain-btn').forEach(btn => {
            btn.addEventListener('click', function(this: HTMLButtonElement) {
                const domain = this.getAttribute('data-domain');
                if (domain) removeDomain(domain);
            });
        });

    } catch (error) {
        console.error('Error loading blacklist:', error);
        blacklistTableBody.innerHTML = '';
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 3;
        cell.className = 'px-6 py-4 text-center text-red-500';
        cell.textContent = 'Error loading blacklist';
        row.appendChild(cell);
        blacklistTableBody.appendChild(row);
    }
}

// Add Domain Function
async function addDomain() {
    if (!addDomainInput || !addDomainInput.value.trim()) return;

    const domain = addDomainInput.value.trim();
    if (!addDomainBtn) return;

    const originalText = addDomainBtn.textContent;
    addDomainBtn.textContent = 'Adding...';
    (addDomainBtn as HTMLButtonElement).disabled = true;

    try {
        const response = await fetch('/api/admin/ai/blacklist', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                domain: domain,
                reason: 'Manual addition via Admin Dashboard'
            })
        });

        const result: ApiResponse = await response.json();

        if (result.success) {
            addDomainInput.value = '';
            loadBlacklist();
        } else {
            alert('Error adding domain: ' + (result.error || 'Unknown error'));
        }

    } catch (error) {
        console.error('Error adding domain:', error);
        alert('Error adding domain');
    } finally {
        addDomainBtn.textContent = originalText;
        (addDomainBtn as HTMLButtonElement).disabled = false;
    }
}

// Remove Domain Function
async function removeDomain(domain: string) {
    if (!confirm(`Are you sure you want to remove ${domain} from the blacklist?`)) return;

    try {
        const response = await fetch(`/api/admin/ai/blacklist?domain=${encodeURIComponent(domain)}`, {
            method: 'DELETE'
        });

        const result: ApiResponse = await response.json();

        if (result.success) {
            loadBlacklist();
        } else {
            alert('Error removing domain: ' + (result.error || 'Unknown error'));
        }

    } catch (error) {
        console.error('Error removing domain:', error);
        alert('Error removing domain');
    }
}

// Test WebAI Cookies Function
async function testWebaiCookies() {
    if (!testWebaiBtn) return;

    const originalText = testWebaiBtn.textContent;
    testWebaiBtn.textContent = 'Testing...';
    (testWebaiBtn as HTMLButtonElement).disabled = true;

    try {
        const response = await fetch('/api/admin/ai/cookies/test', {
            method: 'POST'
        });

        const result: ApiResponse & { message?: string } = await response.json();

        if (result.success) {
            alert('✅ Cookie test successful!');
        } else {
            alert('❌ Cookie test failed: ' + (result.message || result.error || 'Unknown error'));
        }

    } catch (error) {
        console.error('Error testing cookies:', error);
        alert('Error testing cookies');
    } finally {
        testWebaiBtn.textContent = originalText;
        (testWebaiBtn as HTMLButtonElement).disabled = false;
    }
}

// Save Cookies Function
async function saveCookies() {
    if (!saveCookiesBtn) return;

    const originalText = saveCookiesBtn.textContent;
    saveCookiesBtn.textContent = 'Saving...';
    (saveCookiesBtn as HTMLButtonElement).disabled = true;

    try {
        // Get selected method
        const selectedMethod = (document.querySelector('input[name="cookie-method"]:checked') as HTMLInputElement)?.value || 'json';
        let cookies: { [key: string]: string } = {};

        if (selectedMethod === 'json') {
            if (!cookieJsonInput || !cookieJsonInput.value.trim()) {
                alert('Please enter cookie JSON');
                return;
            }

            try {
                cookies = JSON.parse(cookieJsonInput.value);
                if (!cookies['__Secure-1PSID']) {
                    alert('❌ Missing required cookie: __Secure-1PSID');
                    return;
                }
            } catch (e) {
                alert('❌ Invalid JSON: ' + (e as Error).message);
                return;
            }
        } else {
            if (!cookie1psidInput || !cookie1psidInput.value.trim()) {
                alert('❌ __Secure-1PSID is required');
                return;
            }

            cookies = {
                '__Secure-1PSID': cookie1psidInput.value.trim()
            };

            if (cookie1psidtsInput && cookie1psidtsInput.value.trim()) {
                cookies['__Secure-1PSIDTS'] = cookie1psidtsInput.value.trim();
            }
        }

        const response = await fetch('/api/admin/ai/cookies', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ cookies })
        });

        const result: ApiResponse & { message?: string } = await response.json();

        if (result.success) {
            alert('✅ Cookies saved successfully!');
            // Clear inputs
            if (cookieJsonInput) cookieJsonInput.value = '';
            if (cookie1psidInput) cookie1psidInput.value = '';
            if (cookie1psidtsInput) cookie1psidtsInput.value = '';
            // Refresh status
            checkStatus();
        } else {
            alert('❌ Error saving cookies: ' + (result.error || 'Unknown error'));
        }

    } catch (error) {
        console.error('Error saving cookies:', error);
        alert('Error saving cookies');
    } finally {
        saveCookiesBtn.textContent = originalText;
        (saveCookiesBtn as HTMLButtonElement).disabled = false;
    }
}

// Cookie Method Toggle
function toggleCookieMethod() {
    const selectedMethod = (document.querySelector('input[name="cookie-method"]:checked') as HTMLInputElement)?.value || 'json';

    if (cookieJsonMethod && cookieIndividualMethod) {
        if (selectedMethod === 'json') {
            cookieJsonMethod.classList.remove('hidden');
            cookieIndividualMethod.classList.add('hidden');
        } else {
            cookieJsonMethod.classList.add('hidden');
            cookieIndividualMethod.classList.remove('hidden');
        }
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    // Initial Load
    checkStatus();
    loadSettings();
    loadBlacklist();

    // Event Listeners
    if (testOllamaBtn) {
        testOllamaBtn.addEventListener('click', checkStatus);
    }

    if (testWebaiBtn) {
        testWebaiBtn.addEventListener('click', testWebaiCookies);
    }

    if (settingsForm) {
        settingsForm.addEventListener('submit', saveSettings);
    }

    if (addDomainBtn) {
        addDomainBtn.addEventListener('click', addDomain);
    }

    if (saveCookiesBtn) {
        saveCookiesBtn.addEventListener('click', saveCookies);
    }

    // Cookie method toggle
    document.querySelectorAll('input[name="cookie-method"]').forEach(radio => {
        radio.addEventListener('change', toggleCookieMethod);
    });

    // Allow adding domain with Enter key
    if (addDomainInput) {
        addDomainInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addDomain();
            }
        });
    }
});
