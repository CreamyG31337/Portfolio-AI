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
    success?: boolean;
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

// Helper function to escape HTML content
function escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Toast notification system for AI settings
function showToastForAI(message: string, type: 'success' | 'error' | 'info' = 'success'): void {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'fixed bottom-5 right-5 z-50 flex flex-col gap-2';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const borderColor = type === 'error' ? 'border-red-500' : (type === 'info' ? 'border-blue-500' : 'border-green-500');

    toast.className = `flex items-center w-full max-w-xs p-4 text-gray-500 bg-white rounded-lg shadow dark:text-gray-400 dark:bg-gray-800 border-l-4 ${borderColor} transition-opacity duration-300 opacity-100`;

    toast.innerHTML = `
        <div class="ms-3 text-sm font-normal">${escapeHtml(message)}</div>
        <button type="button" class="ms-auto -mx-1.5 -my-1.5 bg-white text-gray-400 hover:text-gray-900 rounded-lg focus:ring-2 focus:ring-gray-300 p-1.5 hover:bg-gray-100 inline-flex items-center justify-center h-8 w-8 dark:text-gray-500 dark:hover:text-white dark:bg-gray-800 dark:hover:bg-gray-700">
            <span class="sr-only">Close</span>
            <svg class="w-3 h-3" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 14">
                <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/>
            </svg>
        </button>
    `;

    container.appendChild(toast);

    // Add close button functionality
    const closeBtn = toast.querySelector('button');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            toast.style.opacity = '0';
            setTimeout(() => {
                toast.remove();
                const allToasts = container.querySelectorAll('div');
                if (allToasts.length === 0) {
                    container.remove();
                }
            }, 300);
        });
    }

    toast.style.opacity = '0';
    setTimeout(() => {
        toast.style.opacity = '1';
    }, 10);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => {
            toast.remove();
            // Remove container if empty
            const allToasts = container.querySelectorAll('div');
            if (allToasts.length === 0) {
                container.remove();
            }
        }, 300);
    }, 4000);
}

// Confirmation toast with action buttons
function showConfirmationToast(message: string, onConfirm: () => void, onCancel?: () => void): void {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'fixed bottom-5 right-5 z-50 flex flex-col gap-2';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = 'flex flex-col w-full max-w-xs p-4 text-gray-500 bg-white rounded-lg shadow dark:text-gray-400 dark:bg-gray-800 border-l-4 border-yellow-500 transition-opacity duration-300 opacity-100';

    const toastId = `toast-${Date.now()}`;
    toast.id = toastId;

    toast.innerHTML = `
        <div class="mb-3 text-sm font-normal">${escapeHtml(message)}</div>
        <div class="flex gap-2 justify-end">
            <button type="button" class="confirm-btn px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 focus:ring-2 focus:ring-red-300 dark:bg-red-500 dark:hover:bg-red-600">
                Confirm
            </button>
            <button type="button" class="cancel-btn px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-200 rounded-lg hover:bg-gray-300 focus:ring-2 focus:ring-gray-300 dark:text-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600">
                Cancel
            </button>
        </div>
    `;

    container.appendChild(toast);

    // Add event listeners
    const confirmBtn = toast.querySelector('.confirm-btn');
    const cancelBtn = toast.querySelector('.cancel-btn');

    const removeToast = () => {
        toast.style.opacity = '0';
        setTimeout(() => {
            toast.remove();
            const allToasts = container.querySelectorAll('div');
            if (allToasts.length === 0) {
                container.remove();
            }
        }, 300);
    };

    if (confirmBtn) {
        confirmBtn.addEventListener('click', () => {
            removeToast();
            onConfirm();
        });
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            removeToast();
            if (onCancel) {
                onCancel();
            }
        });
    }

    toast.style.opacity = '0';
    setTimeout(() => {
        toast.style.opacity = '1';
    }, 10);
}

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

// Toggle Cookie Method
function toggleCookieMethod() {
    const selectedMethod = (document.querySelector('input[name="cookie-method"]:checked') as HTMLInputElement)?.value || 'json';
    
    const cookieJsonContainer = document.getElementById('cookie-json-method');
    const cookieIndividualContainer = document.getElementById('cookie-individual-method');
    
    if (cookieJsonContainer && cookieIndividualContainer) {
        if (selectedMethod === 'json') {
            cookieJsonContainer.classList.remove('hidden');
            cookieIndividualContainer.classList.add('hidden');
        } else {
            cookieJsonContainer.classList.add('hidden');
            cookieIndividualContainer.classList.remove('hidden');
        }
    }
}

// Test WebAI Cookies Function
async function testWebaiCookies() {
    if (!testWebaiBtn) return;

    console.log('[DEBUG] Testing WebAI cookies...');

    const originalText = testWebaiBtn.textContent;
    testWebaiBtn.textContent = 'Testing...';
    (testWebaiBtn as HTMLButtonElement).disabled = true;

    // Create or get verbose output container
    let verboseOutput = document.getElementById('cookie-test-verbose-output');
    if (!verboseOutput) {
        // Create container if it doesn't exist
        const webaiStatusCard = document.querySelector('[data-status-card="webai"]');
        if (webaiStatusCard) {
            verboseOutput = document.createElement('div');
            verboseOutput.id = 'cookie-test-verbose-output';
            verboseOutput.className = 'mt-4 p-4 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm';
            verboseOutput.style.display = 'none';
            webaiStatusCard.appendChild(verboseOutput);
        }
    }

    // Show verbose output container
    if (verboseOutput) {
        verboseOutput.style.display = 'block';
        verboseOutput.innerHTML = '<div class="text-gray-600 dark:text-gray-400">🔄 Running cookie connection test...</div>';
    }

    try {
        console.log('[DEBUG] Sending POST request to /api/admin/ai/cookies/test');
        const response = await fetch('/api/admin/ai/cookies/test', {
            method: 'POST'
        });

        console.log('[DEBUG] Received response:', response.status, response.statusText);

        const result: ApiResponse & { 
            message?: string;
            details?: {
                has_1psid?: boolean;
                has_1psidts?: boolean;
                client_init?: string;
                response_received?: boolean;
                response_length?: number;
                error?: string;
                error_type?: string;
                cookie_file?: string;
            };
        } = await response.json();

        console.log('[DEBUG] Test result:', result);

        // Build verbose output
        let verboseHtml = '<div class="space-y-2">';
        
        if (result.success) {
            verboseHtml += '<div class="text-green-600 dark:text-green-400 font-semibold">✅ Connection Test Successful</div>';
            verboseHtml += '<div class="text-gray-700 dark:text-gray-300">' + (result.message || 'Connection established successfully') + '</div>';
        } else {
            verboseHtml += '<div class="text-red-600 dark:text-red-400 font-semibold">❌ Connection Test Failed</div>';
            verboseHtml += '<div class="text-gray-700 dark:text-gray-300">' + (result.message || result.error || 'Unknown error') + '</div>';
        }

        // Add detailed information
        if (result.details) {
            verboseHtml += '<div class="mt-3 pt-3 border-t border-gray-300 dark:border-gray-600">';
            verboseHtml += '<div class="font-semibold text-gray-900 dark:text-white mb-2">Test Details:</div>';
            verboseHtml += '<div class="space-y-1 text-gray-700 dark:text-gray-300">';

            // Cookie presence
            if (result.details.has_1psid !== undefined) {
                verboseHtml += `<div>${result.details.has_1psid ? '✅' : '❌'} __Secure-1PSID: ${result.details.has_1psid ? 'Present' : 'Missing'}</div>`;
            }
            if (result.details.has_1psidts !== undefined) {
                verboseHtml += `<div>${result.details.has_1psidts ? '✅' : '⚠️'} __Secure-1PSIDTS: ${result.details.has_1psidts ? 'Present' : 'Missing (optional)'}</div>`;
            }

            // Client initialization
            if (result.details.client_init) {
                verboseHtml += `<div>${result.details.client_init === 'success' ? '✅' : '❌'} Client Initialization: ${result.details.client_init}</div>`;
            }

            // Response status
            if (result.details.response_received !== undefined) {
                verboseHtml += `<div>${result.details.response_received ? '✅' : '❌'} Response Received: ${result.details.response_received ? 'Yes' : 'No'}</div>`;
            }
            if (result.details.response_length !== undefined) {
                verboseHtml += `<div>📏 Response Length: ${result.details.response_length} characters</div>`;
            }

            // Error details
            if (result.details.error) {
                verboseHtml += `<div class="text-red-600 dark:text-red-400">❌ Error: ${escapeHtml(result.details.error)}</div>`;
            }
            if (result.details.error_type) {
                verboseHtml += `<div class="text-red-600 dark:text-red-400">🔍 Error Type: ${escapeHtml(result.details.error_type)}</div>`;
            }

            // Cookie file location
            if (result.details.cookie_file) {
                verboseHtml += `<div class="text-gray-600 dark:text-gray-400">📁 Cookie File: ${escapeHtml(result.details.cookie_file)}</div>`;
            }

            verboseHtml += '</div></div>';
        }

        verboseHtml += '</div>';

        // Update verbose output
        if (verboseOutput) {
            verboseOutput.innerHTML = verboseHtml;
        }

        // Show toast notification
        if (result.success) {
            showToastForAI('Cookie test successful!', 'success');
        } else {
            showToastForAI('Cookie test failed: ' + (result.message || result.error || 'Unknown error'), 'error');
        }

    } catch (error) {
        console.error('[DEBUG] Error testing cookies:', error);
        
        // Show error in verbose output
        if (verboseOutput) {
            verboseOutput.innerHTML = `
                <div class="space-y-2">
                    <div class="text-red-600 dark:text-red-400 font-semibold">❌ Test Error</div>
                    <div class="text-gray-700 dark:text-gray-300">Failed to execute test: ${escapeHtml(String(error))}</div>
                    <div class="text-gray-600 dark:text-gray-400 text-xs mt-2">Check browser console for more details.</div>
                </div>
            `;
        }
        
        showToastForAI('Error testing cookies: ' + String(error), 'error');
    } finally {
        testWebaiBtn.textContent = originalText;
        (testWebaiBtn as HTMLButtonElement).disabled = false;
        console.log('[DEBUG] Test button reset');
    }
}

// Save Cookies Function
async function saveCookies() {
    if (!saveCookiesBtn) return;

    console.log('[DEBUG] Saving cookies...');

    const originalText = saveCookiesBtn.textContent;
    saveCookiesBtn.textContent = 'Saving...';
    (saveCookiesBtn as HTMLButtonElement).disabled = true;

    try {
        // Get selected method
        const selectedMethod = (document.querySelector('input[name="cookie-method"]:checked') as HTMLInputElement)?.value || 'json';
        console.log('[DEBUG] Selected method:', selectedMethod);

        let cookies: { [key: string]: string } = {};

        if (selectedMethod === 'json') {
            if (!cookieJsonInput || !cookieJsonInput.value.trim()) {
                console.log('[DEBUG] No JSON input provided');
                showToastForAI('Please enter cookie JSON', 'error');
                return;
            }

            try {
                console.log('[DEBUG] Parsing JSON input...');
                cookies = JSON.parse(cookieJsonInput.value);
                console.log('[DEBUG] Parsed cookies:', Object.keys(cookies));

                if (!cookies['__Secure-1PSID']) {
                    console.log('[DEBUG] Missing __Secure-1PSID in parsed data');
                    showToastForAI('Missing required cookie: __Secure-1PSID', 'error');
                    return;
                }

                console.log('[DEBUG] __Secure-1PSID length:', cookies['__Secure-1PSID'].length);
                if (cookies['__Secure-1PSIDTS']) {
                    console.log('[DEBUG] __Secure-1PSIDTS length:', cookies['__Secure-1PSIDTS'].length);
                }
            } catch (e) {
                console.error('[DEBUG] JSON parse error:', e);
                showToastForAI('Invalid JSON: ' + (e as Error).message, 'error');
                return;
            }
        } else {
            if (!cookie1psidInput || !cookie1psidInput.value.trim()) {
                console.log('[DEBUG] No __Secure-1PSID input provided');
                showToastForAI('__Secure-1PSID is required', 'error');
                return;
            }

            cookies['__Secure-1PSID'] = cookie1psidInput.value.trim();
            console.log('[DEBUG] __Secure-1PSID length:', cookies['__Secure-1PSID'].length);

            if (cookie1psidtsInput && cookie1psidtsInput.value.trim()) {
                cookies['__Secure-1PSIDTS'] = cookie1psidtsInput.value.trim();
                console.log('[DEBUG] __Secure-1PSIDTS length:', cookies['__Secure-1PSIDTS'].length);
            }
        }

        console.log('[DEBUG] Sending POST request to /api/admin/ai/cookies');
        console.log('[DEBUG] Request body:', JSON.stringify({ cookies: { ...cookies, '__Secure-1PSID': '[REDACTED]', '__Secure-1PSIDTS': '[REDACTED]' } }));

        const response = await fetch('/api/admin/ai/cookies', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ cookies })
        });

        console.log('[DEBUG] Received response:', response.status, response.statusText);

        const result: ApiResponse = await response.json();

        console.log('[DEBUG] Save result:', result);

        if (result.success) {
            console.log('[DEBUG] Cookies saved successfully');
            showToastForAI('Cookies saved successfully!', 'success');
            // Reload current cookies display after save
            console.log('[DEBUG] Reloading current cookies display...');
            await loadCurrentCookies();
            // Reload refresher status
            console.log('[DEBUG] Reloading refresher status...');
            await loadCookieRefresherStatus();
        } else {
            console.log('[DEBUG] Save failed:', result.error);
            showToastForAI('Error saving cookies: ' + (result.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('[DEBUG] Error saving cookies:', error);
        showToastForAI('Error saving cookies', 'error');
    } finally {
        saveCookiesBtn.textContent = originalText;
        (saveCookiesBtn as HTMLButtonElement).disabled = false;
        console.log('[DEBUG] Save button reset');
    }
}

// Load Current Cookies
async function loadCurrentCookies() {
    console.log('[DEBUG] Loading current cookies...');

    // Update current cookies display (above input fields)
    const currentDisplay = document.getElementById('cookie-current-display');
    if (!currentDisplay) {
        console.error('[DEBUG] cookie-current-display element not found');
        return;
    }

    try {
        const response = await fetch('/api/admin/ai/cookies');
        console.log('[DEBUG] Received response:', response.status, response.statusText);

        const result: ApiResponse & { cookies?: { [key: string]: string }, has_cookies?: boolean } = await response.json();

        console.log('[DEBUG] Current cookies result:', result);

        if (result.success) {
            const cookies = result.cookies || {};
            const hasCookies = result.has_cookies === true;

            console.log('[DEBUG] Loaded cookies:', Object.keys(cookies));
            console.log('[DEBUG] has_cookies:', hasCookies);

            // Don't auto-populate input fields - user wants to paste new cookies to compare
            // Just display current cookies above for comparison

            let html = '<div class="space-y-2">';
            html += '<div class="grid grid-cols-1 md:grid-cols-2 gap-4">';
            html += '<div class="bg-white p-3 rounded border border-gray-200 dark:bg-gray-800 dark:border-gray-700">';
            html += '<h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">Current Cookies</h6>';

            // Display cookie status
            html += '<div class="space-y-1 text-sm text-gray-700 dark:text-gray-400">';
            if (hasCookies) {
                const psid = cookies['__Secure-1PSID'] || '';
                const psidts = cookies['__Secure-1PSIDTS'] || '';

                console.log('[DEBUG] __Secure-1PSID length:', psid.length);
                console.log('[DEBUG] __Secure-1PSIDTS length:', psidts.length);

                if (psid) {
                    html += '<div class="flex items-center gap-2">';
                    html += '<div class="w-2 h-2 bg-green-500 rounded-full"></div>';
                    html += '<div>';
                    html += '<div class="text-xs font-mono text-gray-600 dark:text-gray-400">__Secure-1PSID:</div>';
                    html += '<div class="text-xs font-mono text-gray-900 dark:text-white truncate max-w-xs">' + psid.substring(0, 50) + (psid.length > 50 ? '...' : '') + '</div>';
                    html += '</div>';
                    html += '</div>';
                } else {
                    html += '<div class="text-xs text-gray-500 dark:text-gray-400">__Secure-1PSID: Not set</div>';
                }

                if (psidts) {
                    html += '<div class="flex items-center gap-2">';
                    html += '<div class="w-2 h-2 bg-green-500 rounded-full"></div>';
                    html += '<div>';
                    html += '<div class="text-xs font-mono text-gray-600 dark:text-gray-400">__Secure-1PSIDTS:</div>';
                    html += '<div class="text-xs font-mono text-gray-900 dark:text-white truncate max-w-xs">' + psidts.substring(0, 50) + (psidts.length > 50 ? '...' : '') + '</div>';
                    html += '</div>';
                    html += '</div>';
                } else {
                    html += '<div class="text-xs text-gray-500 dark:text-gray-400">__Secure-1PSIDTS: Not set</div>';
                }
            } else {
                html += '<div class="text-xs text-gray-500 dark:text-gray-400">No cookies configured</div>';
            }

            html += '</div>';
            html += '</div>';
            html += '</div>';

            currentDisplay.innerHTML = html;
            console.log('[DEBUG] Current cookies display updated');
        }
    } catch (error) {
        console.error('[DEBUG] Error loading current cookies:', error);
        if (currentDisplay) {
            currentDisplay.innerHTML = '<div class="text-sm text-red-600 dark:text-red-400">Error loading cookies</div>';
        }
    }
}

// Cookie Refresher Logs
async function loadCookieRefresherLogs() {
    console.log('[DEBUG] Loading cookie refresher logs...');

    if (!cookieLogLinesInput) {
        console.log('[DEBUG] cookieLogLinesInput not found');
        return;
    }

    const lines = parseInt(cookieLogLinesInput.value) || 100;
    console.log('[DEBUG] Requesting', lines, 'log lines');

    const valueText = document.getElementById('cookie-log-lines-value');

    try {
        const response = await fetch(`/api/admin/ai/cookies/refresher/logs?lines=${lines}`);
        console.log('[DEBUG] Logs response:', response.status, response.statusText);

        const result: ApiResponse & {
            logs?: string[],
            error?: string,
            total_lines?: number,
            showing_lines?: number,
            message?: string
        } = await response.json();

        console.log('[DEBUG] Logs result:', {
            success: result.success,
            total_lines: result.total_lines,
            showing_lines: result.showing_lines,
            has_logs: !!result.logs,
            logs_count: result.logs?.length,
            error: result.error,
            message: result.message
        });

        if (result.success && result.logs) {
            if (valueText) {
                valueText.textContent = `${result.logs.length} lines`;
            }

            console.log('[DEBUG] Rendering', result.logs.length, 'log lines');

            // Display logs
            const logsHtml = result.logs.map(line =>
                `<div class="text-xs font-mono text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-all">${escapeHtml(line)}</div>`
            ).join('');

            if (cookieRefresherLogs) {
                cookieRefresherLogs.innerHTML = logsHtml;
                console.log('[DEBUG] Logs display updated');
            }
        } else if (result.error) {
            console.log('[DEBUG] Error loading logs:', result.error);
            const errorMsg = result.message || result.error || 'Unknown error';
            if (cookieRefresherLogs) {
                cookieRefresherLogs.innerHTML = `<div class="text-sm text-red-600 dark:text-red-400">${escapeHtml(errorMsg)}</div>`;
            }
        }
    } catch (error) {
        console.error('[DEBUG] Error loading logs:', error);
        if (cookieRefresherLogs) {
            cookieRefresherLogs.innerHTML = `<div class="text-sm text-red-600 dark:text-red-400">Error loading logs</div>`;
        }
    }
}

// Cookie Refresher Status
async function loadCookieRefresherStatus() {
    console.log('[DEBUG] Loading cookie refresher status...');

    try {
        const response = await fetch('/api/admin/ai/cookies/refresher/status');
        console.log('[DEBUG] Received response:', response.status, response.statusText);

        const result: ApiResponse & {
            status?: string,
            message?: string,
            last_refreshed_at?: string,
            refresh_count?: number,
            container_name?: string,
            error?: string,
            has_1psid?: boolean,
            has_1psidts?: boolean,
            metadata?: {
                updated_by?: string,
                updated_at?: string,
                refreshed_at?: string,
                refresh_count?: number
            },
            age_info?: {
                age_hours?: number,
                refresh_age_hours?: number,
                age_formatted?: string
            },
            is_in_grace_period?: boolean
        } = await response.json();

        console.log('[DEBUG] Status result:', result);

        if (result.success) {
            // Determine status based on cookie presence
            const hasCookies = result.has_1psid && result.has_1psidts;
            const partialCookies = result.has_1psid && !result.has_1psidts;

            console.log('[DEBUG] Cookie status:', {
                hasCookies,
                partialCookies,
                has_1psid: result.has_1psid,
                has_1psidts: result.has_1psidts
            });

            if (statusDot) {
                if (hasCookies) {
                    statusDot.className = 'bg-green-500';
                } else if (partialCookies) {
                    statusDot.className = 'bg-yellow-500';
                } else {
                    statusDot.className = 'bg-red-500';
                }
            }

            // Build status text
            let statusTextContent = '';
            if (result.status === 'full') {
                statusTextContent = 'Configured';
            } else if (result.status === 'configured') {
                statusTextContent = 'Partial';
            } else {
                statusTextContent = 'Missing';
            }

            // Add grace period info
            if (result.is_in_grace_period) {
                console.log('[DEBUG] Cookie refresher is in grace period');
                if (result.age_info?.age_hours !== undefined) {
                    const remaining = Math.max(0, 2 - result.age_info.age_hours);
                    statusTextContent += ` (Grace: ${remaining.toFixed(1)}h remaining)`;
                }
            }

            // Add refresh info
            if (result.metadata?.refresh_count !== undefined) {
                statusTextContent += ` | Refreshes: ${result.metadata.refresh_count}`;
            }

            if (statusText) {
                statusText.textContent = statusTextContent;
            }

            // Log additional details
            if (result.metadata) {
                console.log('[DEBUG] Metadata:', result.metadata);
            }
            if (result.age_info) {
                console.log('[DEBUG] Age info:', result.age_info);
            }

        } else if (result.error) {
            console.log('[DEBUG] Error loading status:', result.error);
            if (statusDot) {
                statusDot.className = 'bg-red-500';
            }
            if (statusText) {
                statusText.textContent = 'Error: ' + (result.message || result.error || 'Unknown');
            }
        } else {
            console.log('[DEBUG] No cookies configured');
            if (statusDot) {
                statusDot.className = 'bg-red-500';
            }
            if (statusText) {
                statusText.textContent = 'No cookies';
            }
        }
    } catch (error) {
        console.error('[DEBUG] Error loading refresher status:', error);
        if (statusDot) {
            statusDot.className = 'bg-red-500';
        }
        if (statusText) {
            statusText.textContent = 'Error loading status';
        }
    }
}

// Blacklist Functions
async function addDomain() {
    if (!addDomainInput || !addDomainBtn) return;

    const domain = addDomainInput.value.trim();
    if (!domain) {
        showToastForAI('Please enter a domain', 'error');
        return;
    }

    const originalText = addDomainBtn.textContent;
    addDomainBtn.textContent = 'Adding...';
    (addDomainBtn as HTMLButtonElement).disabled = true;

    try {
        const response = await fetch('/api/admin/ai/blacklist/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain })
        });

        const result: ApiResponse = await response.json();

        if (result.success) {
            // Reload blacklist table
            await loadBlacklist();
            addDomainInput.value = '';
            showToastForAI('Domain added to blacklist', 'success');
        } else {
            showToastForAI('Error adding domain: ' + (result.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error adding domain:', error);
        showToastForAI('Error adding domain', 'error');
    } finally {
        addDomainBtn.textContent = originalText;
        (addDomainBtn as HTMLButtonElement).disabled = false;
    }
}

async function removeDomain(domain: string) {
    showConfirmationToast(
        `Are you sure you want to remove "${domain}" from the blacklist?`,
        async () => {
            try {
                const response = await fetch('/api/admin/ai/blacklist/remove', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ domain })
                });

                const result: ApiResponse = await response.json();

                if (result.success) {
                    await loadBlacklist();
                    showToastForAI('Domain removed from blacklist', 'success');
                } else {
                    showToastForAI('Error removing domain: ' + (result.error || 'Unknown error'), 'error');
                }
            } catch (error) {
                console.error('Error removing domain:', error);
                showToastForAI('Error removing domain', 'error');
            }
        }
    );
}

async function toggleAutoBlacklist(domain: string, currentEntry: BlacklistEntry) {
    try {
        const isAuto = !currentEntry.auto_blacklisted;
        const response = await fetch('/api/admin/ai/blacklist/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain, auto_blacklisted: isAuto })
        });

        const result: ApiResponse = await response.json();

        if (result.success) {
            await loadBlacklist();
            showToastForAI(`Domain ${isAuto ? 'added to' : 'removed from'} auto-blacklist`, 'success');
        } else {
            showToastForAI(`Error toggling auto-blacklist: ${result.error || 'Unknown error'}`, 'error');
        }
    } catch (error) {
        console.error('Error toggling auto-blacklist:', error);
        showToastForAI('Error toggling auto-blacklist', 'error');
    }
}

async function loadBlacklist() {
    try {
        const response = await fetch('/api/admin/ai/blacklist');
        const result: BlacklistResponse = await response.json();

        if ((result.success || result.blacklist) && result.blacklist && blacklistTableBody) {
            blacklistTableBody.innerHTML = result.blacklist.map(entry => {
                const lastFailure = entry.last_failure_reason ? `(${entry.last_failure_reason})` : '';
                const consecutive = entry.consecutive_failures !== undefined ? `[${entry.consecutive_failures}]` : '';
                const autoLabel = entry.auto_blacklisted ? `<span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-full ${entry.auto_blacklisted ? 'bg-red-500' : 'bg-gray-400'}"></span> ${entry.auto_blacklisted ? 'Auto' : 'Manual'}</span>` : `<span class="text-gray-400">Manual</span>`;

                return `
                    <tr>
                        <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-300">${escapeHtml(entry.domain)}</td>
                        <td class="px-4 py-2 text-sm text-center">
                            ${autoLabel}
                        </td>
                        <td class="px-4 py-2 text-sm text-center">
                            <div class="inline-flex items-center justify-center gap-1">
                                <button onclick="removeDomain('${escapeHtml(entry.domain)}')" class="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300 px-2 py-1 rounded text-sm">
                                    Remove
                                </button>
                            </div>
                            <td class="px-4 py-2 text-sm text-center">
                                <button onclick="toggleAutoBlacklist('${escapeHtml(entry.domain)}', ${JSON.stringify(entry)})" class="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300 px-2 py-1 rounded text-sm">
                                    ${entry.auto_blacklisted ? 'Unban' : 'Ban'}
                                </button>
                            </td>
                        </td>
                        <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-300">${lastFailure}</td>
                        <td class="px-4 py-2 text-sm text-gray-700 dark:text-gray-300">${consecutive}</td>
                    </tr>
                `;
            }).join('');
        } else if (result.error && blacklistTableBody) {
            blacklistTableBody.innerHTML = `<tr><td colspan="5" class="px-4 py-4 text-red-600 dark:text-red-400">Error: ${escapeHtml(result.error)}</td></tr>`;
        }
    } catch (error) {
        console.error('Error loading blacklist:', error);
        if (blacklistTableBody) {
            blacklistTableBody.innerHTML = `<tr><td colspan="5" class="px-4 py-4 text-red-600 dark:text-red-400">Error loading blacklist</td></tr>`;
        }
    }
}

// Settings Functions
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

async function saveSettings() {
    if (!settingsForm || !saveSettingsBtn) return;

    const originalText = saveSettingsBtn.textContent;
    saveSettingsBtn.textContent = 'Saving...';
    (saveSettingsBtn as HTMLButtonElement).disabled = true;

    try {
        const autoBlacklistThreshold = autoBlacklistInput?.value || '10';
        const maxResearchBatchSize = maxBatchSizeInput?.value || '100';

        const response = await fetch('/api/admin/ai/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                auto_blacklist_threshold: autoBlacklistThreshold,
                max_research_batch_size: maxResearchBatchSize
            })
        });

        const result: ApiResponse = await response.json();

        if (result.success) {
            showToastForAI('Settings saved successfully!', 'success');
        } else {
            showToastForAI('Error saving settings: ' + (result.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error saving settings:', error);
        showToastForAI('Error saving settings', 'error');
    } finally {
        if (saveSettingsBtn) {
            saveSettingsBtn.textContent = originalText;
            (saveSettingsBtn as HTMLButtonElement).disabled = false;
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    console.log('[DEBUG] Page loaded, initializing AI Settings...');
    console.log('[DEBUG] DOM Elements found:', {
        ollamaIndicator: !!ollamaIndicator,
        ollamaMessage: !!ollamaMessage,
        testOllamaBtn: !!testOllamaBtn,
        postgresIndicator: !!postgresIndicator,
        postgresMessage: !!postgresMessage,
        webaiIndicator: !!webaiIndicator,
        webaiMessage: !!webaiMessage,
        webaiSource: !!webaiSource,
        testWebaiBtn: !!testWebaiBtn,
        cookieJsonInput: !!cookieJsonInput,
        cookie1psidInput: !!cookie1psidInput,
        cookie1psidtsInput: !!cookie1psidtsInput,
        saveCookiesBtn: !!saveCookiesBtn,
        cookieRefresherLogs: !!cookieRefresherLogs,
        refreshCookieLogsBtn: !!refreshCookieLogsBtn,
        cookieLogLinesInput: !!cookieLogLinesInput,
        cookieLogLinesValue: !!cookieLogLinesValue,
        cookieRefresherStatus: !!cookieRefresherStatus,
        statusDot: !!statusDot,
        statusText: !!statusText,
        addDomainBtn: !!addDomainBtn,
        addDomainInput: !!addDomainInput,
        saveSettingsBtn: !!saveSettingsBtn,
        settingsForm: !!settingsForm
    });

    // Check initial status
    console.log('[DEBUG] Checking initial status...');
    await checkStatus();

    // Load settings
    console.log('[DEBUG] Loading settings...');
    await loadSettings();

    // Load current cookies
    console.log('[DEBUG] Loading current cookies...');
    await loadCurrentCookies();

    // Load cookie refresher logs
    if (cookieLogLinesInput) {
        console.log('[DEBUG] Loading cookie refresher logs...');
        loadCookieRefresherLogs();
    }

    // Load cookie refresher status
    console.log('[DEBUG] Loading cookie refresher status...');
    loadCookieRefresherStatus();

    // Load blacklist
    console.log('[DEBUG] Loading blacklist...');
    await loadBlacklist();

    console.log('[DEBUG] Setting up event listeners...');

    // Event listeners
    if (testOllamaBtn) {
        testOllamaBtn.addEventListener('click', checkStatus);
        console.log('[DEBUG] testOllamaBtn listener added');
    }

    if (testWebaiBtn) {
        testWebaiBtn.addEventListener('click', testWebaiCookies);
        console.log('[DEBUG] testWebaiBtn listener added');
    }

    if (saveCookiesBtn) {
        saveCookiesBtn.addEventListener('click', saveCookies);
        console.log('[DEBUG] saveCookiesBtn listener added');
    }

    if (cookieLogLinesInput) {
        cookieLogLinesInput.addEventListener('input', (e) => {
            const value = (e.target as HTMLInputElement).value;
            if (cookieLogLinesValue) {
                cookieLogLinesValue.textContent = value;
            }
            loadCookieRefresherLogs();
        });
        console.log('[DEBUG] cookieLogLinesInput listener added');
    }

    if (refreshCookieLogsBtn) {
        refreshCookieLogsBtn.addEventListener('click', loadCookieRefresherLogs);
        console.log('[DEBUG] refreshCookieLogsBtn listener added');
    }

    if (addDomainBtn) {
        addDomainBtn.addEventListener('click', addDomain);
        console.log('[DEBUG] addDomainBtn listener added');
    }

    // Allow adding domain with Enter key
    if (addDomainInput) {
        addDomainInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addDomain();
            }
        });
        console.log('[DEBUG] addDomainInput Enter listener added');
    }

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', saveSettings);
        console.log('[DEBUG] saveSettingsBtn listener added');
    }

    // Cookie method toggle
    document.querySelectorAll('input[name="cookie-method"]').forEach(radio => {
        radio.addEventListener('change', toggleCookieMethod);
    });

    console.log('[DEBUG] AI Settings initialization complete');
});
