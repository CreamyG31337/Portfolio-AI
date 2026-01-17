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

interface ContainerStatus {
    success: boolean;
    container_found?: boolean;
    status?: string;
    name?: string;
    id?: string;
    image?: string;
    is_running?: boolean;
    error?: string;
    message?: string;
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
const cookieRefresherLogs = document.getElementById('cookie-refresher-logs');
const refreshCookieLogsBtn = document.getElementById('refresh-cookie-logs-btn');
const cookieLogLinesInput = document.getElementById('cookie-log-lines') as HTMLInputElement | null;
const cookieLogLinesValue = document.getElementById('cookie-log-lines-value');
const cookieRefresherStatus = document.getElementById('cookie-refresher-status');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');

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

// Load Current Cookies
async function loadCurrentCookies() {
    try {
        const response = await fetch('/api/admin/ai/cookies');
        const result: ApiResponse & { cookies?: { [key: string]: string }, has_cookies?: boolean } = await response.json();
        
        // Update current cookies display (above input fields)
        const currentDisplay = document.getElementById('cookie-current-display');
        
        if (!currentDisplay) {
            console.error('cookie-current-display element not found');
            return;
        }
        
        if (result.success) {
            const cookies = result.cookies || {};
            const hasCookies = result.has_cookies === true;
            
            // Don't auto-populate input fields - user wants to paste new cookies to compare
            // Just display current cookies above for comparison
            
            // Display current cookies in the comparison section
            if (hasCookies && cookies['__Secure-1PSID']) {
                const psid = cookies['__Secure-1PSID'] || 'Not set';
                const psidts = cookies['__Secure-1PSIDTS'] || 'Not set';
                
                // Truncate long values for display (show first 50 chars)
                const psidDisplay = psid.length > 50 ? psid.substring(0, 50) + '...' : psid;
                const psidtsDisplay = psidts.length > 50 ? psidts.substring(0, 50) + '...' : psidts;
                
                currentDisplay.innerHTML = `
                    <div class="space-y-2">
                        <div>
                            <span class="font-mono text-xs font-semibold text-gray-700 dark:text-gray-300">__Secure-1PSID:</span>
                            <div class="mt-1 p-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded font-mono text-xs text-gray-900 dark:text-gray-100 break-all">
                                ${psidDisplay}
                            </div>
                            ${psid.length > 50 ? `<span class="text-xs text-gray-500 dark:text-gray-400">(Full length: ${psid.length} chars)</span>` : ''}
                        </div>
                        <div>
                            <span class="font-mono text-xs font-semibold text-gray-700 dark:text-gray-300">__Secure-1PSIDTS:</span>
                            <div class="mt-1 p-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded font-mono text-xs text-gray-900 dark:text-gray-100 break-all">
                                ${psidtsDisplay}
                            </div>
                            ${psidts.length > 50 ? `<span class="text-xs text-gray-500 dark:text-gray-400">(Full length: ${psidts.length} chars)</span>` : ''}
                        </div>
                    </div>
                `;
            } else {
                // No cookies found
                currentDisplay.innerHTML = '<p class="text-gray-600 dark:text-gray-400">ℹ️ No current cookies found. Enter new cookies below.</p>';
            }
        } else {
            // API error
            currentDisplay.innerHTML = `<p class="text-red-600 dark:text-red-400">❌ Error loading cookies: ${result.error || 'Unknown error'}</p>`;
        }
    } catch (error) {
        console.error('Error loading current cookies:', error);
        const currentDisplay = document.getElementById('cookie-current-display');
        if (currentDisplay) {
            const errorMessage = error instanceof Error ? error.message : String(error);
            currentDisplay.innerHTML = `<p class="text-red-600 dark:text-red-400">❌ Error loading cookies: ${errorMessage}</p>`;
        }
    }
}

// Load Cookie Refresher Container Status
async function loadCookieRefresherContainerStatus() {
    if (!statusDot || !statusText) return;
    
    try {
        const response = await fetch('/api/admin/ai/cookies/container-status');
        const result: ContainerStatus = await response.json();
        
        if (result.success && result.container_found) {
            const isRunning = result.is_running === true;
            const status = result.status || 'unknown';
            
            // Update status dot
            statusDot.className = `w-2 h-2 rounded-full mr-1.5 ${
                isRunning ? 'bg-green-500' : 
                status === 'exited' ? 'bg-yellow-500' : 
                'bg-red-500'
            }`;
            
            // Update status text
            if (isRunning) {
                statusText.textContent = `Running (${result.id || 'N/A'})`;
                statusText.className = 'text-green-600 dark:text-green-400';
            } else if (status === 'exited') {
                statusText.textContent = `Stopped (${status})`;
                statusText.className = 'text-yellow-600 dark:text-yellow-400';
            } else {
                statusText.textContent = `${status.charAt(0).toUpperCase() + status.slice(1)}`;
                statusText.className = 'text-red-600 dark:text-red-400';
            }
        } else if (result.success && !result.container_found) {
            // Container not found
            statusDot.className = 'w-2 h-2 rounded-full mr-1.5 bg-gray-400';
            statusText.textContent = 'Not Found';
            statusText.className = 'text-gray-600 dark:text-gray-400';
        } else {
            // Error or Docker not available
            statusDot.className = 'w-2 h-2 rounded-full mr-1.5 bg-gray-400';
            statusText.textContent = result.error || 'Unknown';
            statusText.className = 'text-gray-600 dark:text-gray-400';
        }
    } catch (error) {
        console.error('Error loading container status:', error);
        if (statusDot && statusText) {
            statusDot.className = 'w-2 h-2 rounded-full mr-1.5 bg-gray-400';
            statusText.textContent = 'Error';
            statusText.className = 'text-red-600 dark:text-red-400';
        }
    }
}

// Load Cookie Refresher Logs
async function loadCookieRefresherLogs() {
    if (!cookieRefresherLogs) return;
    
    // Load container status first
    await loadCookieRefresherContainerStatus();
    
    const lines = cookieLogLinesInput ? parseInt(cookieLogLinesInput.value) : 100;
    
    try {
        const response = await fetch(`/api/admin/ai/cookies/logs?lines=${lines}`);
        const result: ApiResponse & { logs?: string[], total_lines?: number, showing_lines?: number, message?: string } = await response.json();
        
        if (result.success && result.logs) {
            cookieRefresherLogs.textContent = result.logs.join('');
            if (result.total_lines !== undefined && result.showing_lines !== undefined) {
                const info = `\n\n--- Showing last ${result.showing_lines} of ${result.total_lines} total log lines ---`;
                cookieRefresherLogs.textContent += info;
            }
        } else {
            cookieRefresherLogs.textContent = result.message || 'No logs available';
            cookieRefresherLogs.classList.add('text-yellow-400');
        }
    } catch (error) {
        console.error('Error loading cookie refresher logs:', error);
        cookieRefresherLogs.textContent = 'Error loading logs: ' + (error as Error).message;
        cookieRefresherLogs.classList.add('text-red-400');
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
    loadCurrentCookies();

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

    // Cookie refresher logs
    if (cookieLogLinesInput) {
        cookieLogLinesInput.addEventListener('input', (e) => {
            const value = (e.target as HTMLInputElement).value;
            if (cookieLogLinesValue) {
                cookieLogLinesValue.textContent = value;
            }
            loadCookieRefresherLogs();
        });
    }

    if (refreshCookieLogsBtn) {
        refreshCookieLogsBtn.addEventListener('click', loadCookieRefresherLogs);
    }

    // Load logs on page load
    loadCookieRefresherLogs();

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
