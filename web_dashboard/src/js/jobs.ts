/**
 * Jobs Scheduler Dashboard
 * Handles status updates, job list rendering, and job actions
 * 
 * ⚠️ IMPORTANT: This is a TypeScript SOURCE file.
 * - Edit this file: web_dashboard/src/js/jobs.ts
 * - Compiled output: web_dashboard/static/js/jobs.js (auto-generated)
 * - DO NOT edit the compiled .js file - it will be overwritten on build
 * - Run `npm run build:ts` to compile changes
 */

console.log('[Jobs] jobs.ts file loaded and executing...');

// Export empty object to make this a module
export { };

// Type definitions
interface Job {
    id: string;
    actual_job_id?: string;
    name?: string;
    next_run?: string | null;
    trigger?: string;
    status?: 'running' | 'error' | 'idle' | 'paused';
    parameters?: Record<string, JobParameter>;
    scheduler_stopped?: boolean;
    has_schedule?: boolean;
    recent_logs?: JobLogEntry[];
    is_running?: boolean;
    is_paused?: boolean;
    last_error?: string;
    running_since?: string;
}

interface JobLogEntry {
    timestamp: string;
    level?: string;
    message: string;
    success?: boolean;
    duration_ms?: number;
}

interface JobParameter {
    type: 'text' | 'number' | 'date' | 'boolean';
    default?: any;
    description?: string;
    optional?: boolean;
}

interface JobsStatusResponse {
    scheduler_running: boolean;
    jobs: Job[];
    error?: string;
}

interface JobsApiResponse {
    success?: boolean;
    error?: string;
    message?: string;
}

interface JobActionRequest {
    job_id: string;
    parameters?: Record<string, any>;
}

interface JobsDOMElements {
    statusContainer: HTMLElement | null;
    errorContainer: HTMLElement | null;
    runningContainer: HTMLElement | null;
    infoText: HTMLElement | null;
    statusText: HTMLElement | null;
    statusIndicator: HTMLElement | null;
    startBtn: HTMLElement | null;
    refreshBtn: HTMLElement | null;
    jobsList: HTMLElement | null;
    jobsLoading: HTMLElement | null;
    noJobs: HTMLElement | null;
    errorMsg: HTMLElement | null;
    errorText: HTMLElement | null;
    autoRefreshCheckbox: HTMLInputElement | null;
}

// State
let isSchedulerRunning = false;
let jobs: Job[] = [];
let refreshInterval: ReturnType<typeof setInterval> | null = null;
let autoRefresh = true;
let consecutiveErrors = 0;
let maxBackoffDelay = 10000; // Max 10 seconds between retries
let currentBackoffDelay = 5000; // Start with 5 seconds
let isRecovering = false;

// DOM Elements - Note: These may be null if called before DOM is ready
const elements: JobsDOMElements = {
    statusContainer: null, // Will be set in DOMContentLoaded
    errorContainer: null,
    runningContainer: null,
    infoText: null,
    statusText: null,
    statusIndicator: null,
    startBtn: null,
    refreshBtn: null,
    jobsList: null,
    jobsLoading: null,
    noJobs: null,
    errorMsg: null,
    errorText: null,
    autoRefreshCheckbox: null
};

// Initialize DOM elements when DOM is ready
function initializeDOMElements(): void {
    elements.statusContainer = document.getElementById('scheduler-status-container');
    elements.errorContainer = document.getElementById('scheduler-error');
    elements.runningContainer = document.getElementById('scheduler-running');
    elements.infoText = document.getElementById('scheduler-info');
    elements.statusText = document.getElementById('status-text');
    elements.statusIndicator = document.getElementById('status-indicator');
    elements.startBtn = document.getElementById('start-scheduler-btn');
    elements.refreshBtn = document.getElementById('refresh-status-btn');
    elements.jobsList = document.getElementById('jobs-container'); // Template uses 'jobs-container'
    elements.jobsLoading = document.getElementById('jobs-loading'); // Will add this to template
    elements.noJobs = document.getElementById('jobs-empty'); // Will add this to template
    elements.errorMsg = document.getElementById('error-message');
    elements.errorText = document.getElementById('error-text');
    elements.autoRefreshCheckbox = document.getElementById('auto-refresh') as HTMLInputElement | null;

    console.log('[Jobs] DOM elements initialized:', {
        statusContainer: !!elements.statusContainer,
        errorContainer: !!elements.errorContainer,
        runningContainer: !!elements.runningContainer,
        startBtn: !!elements.startBtn,
        refreshBtn: !!elements.refreshBtn,
        jobsList: !!elements.jobsList,
        autoRefreshCheckbox: !!elements.autoRefreshCheckbox
    });
}

// Initialize
document.addEventListener('DOMContentLoaded', (): void => {
    console.log('[Jobs] DOMContentLoaded event fired, initializing jobs page...');

    // Initialize DOM elements
    initializeDOMElements();

    fetchStatus();
    startAutoRefresh();

    // Event Listeners
    if (elements.startBtn) {
        elements.startBtn.addEventListener('click', startScheduler);
        console.log('[Jobs] Start scheduler button listener attached');
    }
    if (elements.refreshBtn) {
        elements.refreshBtn.addEventListener('click', (): void => {
            // Manual refresh - reset error counter to get immediate retry
            consecutiveErrors = 0;
            currentBackoffDelay = 5000;
            isRecovering = false;
            fetchStatus();
        });
        console.log('[Jobs] Refresh button listener attached');
    }
    if (elements.autoRefreshCheckbox) {
        elements.autoRefreshCheckbox.addEventListener('change', (e: Event): void => {
            const target = e.target as HTMLInputElement;
            autoRefresh = target.checked;
            console.log('[Jobs] Auto-refresh toggled:', autoRefresh);
            if (autoRefresh) {
                startAutoRefresh();
            } else {
                stopAutoRefresh();
            }
        });
        console.log('[Jobs] Auto-refresh checkbox listener attached');
    }

    // Expose refreshJobs globally for onclick handlers
    if (typeof window !== 'undefined') {
        (window as any).refreshJobs = fetchStatus;
        console.log('[Jobs] refreshJobs function exposed globally for onclick handlers');
    }
});

function startAutoRefresh(): void {
    console.log('[Jobs] Starting auto-refresh with adaptive backoff');
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }

    // Use a function that adjusts delay based on errors
    const scheduleNextRefresh = () => {
        if (refreshInterval) {
            clearInterval(refreshInterval);
        }

        if (!autoRefresh) {
            return;
        }

        const delay = consecutiveErrors > 0 ? currentBackoffDelay : 5000;
        console.log(`[Jobs] Scheduling next refresh in ${delay}ms (errors: ${consecutiveErrors})`);

        refreshInterval = setTimeout(() => {
            if (autoRefresh) {
                console.log('[Jobs] Auto-refresh triggered');
                fetchStatus().finally(() => {
                    // Schedule next refresh after this one completes
                    scheduleNextRefresh();
                });
            }
        }, delay);
    };

    // Start the first refresh
    scheduleNextRefresh();
}

function stopAutoRefresh(): void {
    console.log('[Jobs] Stopping auto-refresh');
    if (refreshInterval) {
        clearTimeout(refreshInterval);
        refreshInterval = null;
    }
}

// Fetch Status
async function fetchStatus(): Promise<void> {
    const startTime = performance.now();
    console.log('[Jobs] fetchStatus() called, fetching scheduler status...');

    try {
        const url = '/api/admin/scheduler/status';
        console.log('[Jobs] Making API request to:', url);

        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Jobs] API response received:', {
            status: response.status,
            statusText: response.statusText,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`,
            url: url
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            console.error('[Jobs] API error response:', {
                status: response.status,
                statusText: response.statusText,
                errorData: errorData,
                url: url,
                duration: `${duration.toFixed(2)}ms`
            });
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: JobsStatusResponse = await response.json();
        console.log('[Jobs] Status data received:', {
            scheduler_running: data.scheduler_running,
            jobs_count: data.jobs ? data.jobs.length : 0,
            has_error: !!data.error,
            error: data.error,
            duration: `${duration.toFixed(2)}ms`,
            raw_data_keys: Object.keys(data),
            jobs_sample: data.jobs && data.jobs.length > 0 ? data.jobs[0] : null
        });

        // Log full response for debugging (truncated)
        if (data.jobs && data.jobs.length > 0) {
            console.log('[Jobs] First job sample:', JSON.stringify(data.jobs[0], null, 2));
        } else {
            console.warn('[Jobs] No jobs in response. Full response:', JSON.stringify(data, null, 2).substring(0, 1000));
        }

        updateStatusUI(data.scheduler_running);
        renderJobs(data.jobs);

        // Success - reset error tracking
        if (consecutiveErrors > 0) {
            console.log('[Jobs] Connection recovered after', consecutiveErrors, 'errors');
            consecutiveErrors = 0;
            currentBackoffDelay = 5000; // Reset to initial delay
            isRecovering = false;
            // Hide any recovery message
            if (elements.infoText) {
                elements.infoText.classList.remove('text-theme-warning-text');
            }
        }

        console.log('[Jobs] fetchStatus() completed successfully');
    } catch (error) {
        const duration = performance.now() - startTime;
        consecutiveErrors++;

        // Simple backoff: 5s on first error, then 10s max
        currentBackoffDelay = consecutiveErrors === 1 ? 5000 : maxBackoffDelay;

        console.error('[Jobs] Error fetching status:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : undefined,
            duration: `${duration.toFixed(2)}ms`,
            consecutiveErrors: consecutiveErrors,
            nextRetryIn: `${currentBackoffDelay}ms`
        });

        // Show error with retry information
        const errorMsg = consecutiveErrors === 1
            ? 'Failed to fetch scheduler status. Retrying...'
            : `Connection lost (${consecutiveErrors} attempts). Retrying in ${Math.round(currentBackoffDelay / 1000)}s...`;

        showJobsError(errorMsg);

        // Show recovery indicator
        if (!isRecovering) {
            isRecovering = true;
            if (elements.infoText) {
                elements.infoText.textContent = `⚠️ Reconnecting... (attempt ${consecutiveErrors})`;
                elements.infoText.classList.add('text-theme-warning-text');
            }
        } else if (elements.infoText) {
            elements.infoText.textContent = `⚠️ Reconnecting... (attempt ${consecutiveErrors}, retry in ${Math.round(currentBackoffDelay / 1000)}s)`;
        }

        // Restart auto-refresh with new backoff delay
        if (autoRefresh) {
            startAutoRefresh();
        }
    }
}

// Update Status UI
function updateStatusUI(running: boolean): void {
    console.log('[Jobs] updateStatusUI called:', { running, isSchedulerRunning });
    isSchedulerRunning = running;
    if (running) {
        // Update status text and indicator
        if (elements.statusText) {
            elements.statusText.textContent = 'Running';
        }
        if (elements.statusIndicator) {
            elements.statusIndicator.className = 'w-3 h-3 rounded-full bg-theme-success-text';
        }
        // Hide/show containers
        if (elements.errorContainer) {
            elements.errorContainer.classList.add('hidden');
        }
        if (elements.runningContainer) {
            elements.runningContainer.classList.remove('hidden');
        }
        if (elements.infoText) {
            const recoveryMsg = isRecovering ? ' • Connection recovered!' : '';
            elements.infoText.textContent = `Running normally • Last updated: ${new Date().toLocaleString()}${recoveryMsg}`;
            elements.infoText.classList.remove('text-yellow-600');
        }
        // Hide start button when running
        if (elements.startBtn) {
            elements.startBtn.classList.add('hidden');
        }
        console.log('[Jobs] Status UI updated: scheduler is running');
    } else {
        // Update status text and indicator
        if (elements.statusText) {
            elements.statusText.textContent = 'Stopped';
        }
        if (elements.statusIndicator) {
            elements.statusIndicator.className = 'w-3 h-3 rounded-full bg-theme-error-text';
        }
        // Hide/show containers
        if (elements.runningContainer) {
            elements.runningContainer.classList.add('hidden');
        }
        if (elements.errorContainer) {
            elements.errorContainer.classList.remove('hidden');
        }
        // Show start button when stopped
        if (elements.startBtn) {
            elements.startBtn.classList.remove('hidden');
        }
        console.log('[Jobs] Status UI updated: scheduler is stopped');
    }
}

// Render Jobs
function renderJobs(jobsData: Job[]): void {
    console.log('[Jobs] renderJobs called:', {
        jobs_count: jobsData ? jobsData.length : 0,
        has_jobsList: !!elements.jobsList,
        jobsList_id: elements.jobsList?.id,
        jobsList_element: elements.jobsList
    });
    jobs = jobsData || [];

    if (elements.jobsLoading) {
        elements.jobsLoading.classList.add('hidden');
        console.log('[Jobs] Hidden loading indicator');
    }

    if (jobs.length === 0) {
        console.log('[Jobs] No jobs to render');
        if (elements.jobsList) {
            elements.jobsList.innerHTML = '<div class="text-center py-8 text-text-secondary">No jobs available</div>';
        }
        if (elements.noJobs) {
            elements.noJobs.classList.remove('hidden');
        }
        return;
    }

    // Before re-rendering, save which parameter forms are currently open
    const openParamForms: string[] = [];
    if (elements.jobsList) {
        const paramForms = elements.jobsList.querySelectorAll('.parameter-form');
        paramForms.forEach((form) => {
            if (!form.classList.contains('hidden')) {
                // Extract job ID from the form ID (format: params-{jobId})
                const formId = form.id;
                if (formId.startsWith('params-')) {
                    const jobId = formId.substring(7); // Remove 'params-' prefix
                    openParamForms.push(jobId);
                }
            }
        });
    }

    if (elements.noJobs) {
        elements.noJobs.classList.add('hidden');
    }
    if (elements.jobsList) {
        const jobCards = jobs.map(job => createJobCard(job));
        elements.jobsList.innerHTML = jobCards.join('');
        console.log('[Jobs] Rendered', jobs.length, 'job cards to element:', elements.jobsList.id);

        // Restore open parameter forms after re-rendering
        openParamForms.forEach(jobId => {
            const paramForm = document.getElementById(`params-${jobId}`);
            if (paramForm) {
                paramForm.classList.remove('hidden');
                console.log('[Jobs] Restored open parameter form for job:', jobId);
            }
        });
    } else {
        console.error('[Jobs] jobsList element not found! Cannot render jobs.', {
            available_ids: Array.from(document.querySelectorAll('[id*="job"]')).map(el => el.id),
            jobs_container: document.getElementById('jobs-container'),
            all_elements: Object.keys(elements).map(key => ({ key, found: !!elements[key as keyof JobsDOMElements] }))
        });
    }

    // Attach event listeners to new buttons
    const actionButtons = document.querySelectorAll('.job-action-btn');
    console.log('[Jobs] Attaching event listeners to', actionButtons.length, 'action buttons');
    actionButtons.forEach(btn => {
        btn.addEventListener('click', handleJobAction);
    });
}

function createJobCard(job: Job): string {
    const statusClass = getStatusClass(job);
    // Show schedule info if scheduler is stopped and job has a schedule, otherwise show next_run or "Not scheduled"
    let nextRun: string;
    if (job.next_run) {
        nextRun = new Date(job.next_run).toLocaleString();
    } else if (job.scheduler_stopped && job.has_schedule && job.trigger && job.trigger !== 'Manual') {
        // Scheduler is stopped but job has a schedule - show the schedule instead of "Not scheduled"
        nextRun = `Scheduled: ${job.trigger}`;
    } else {
        nextRun = 'Not scheduled';
    }

    // Recent logs HTML
    let logsHtml = '';
    if (job.recent_logs && job.recent_logs.length > 0) {
        logsHtml = `
            <div class="mt-4 bg-dashboard-background rounded border border-border overflow-hidden">
                <div class="px-3 py-1 bg-dashboard-surface text-xs font-semibold text-text-secondary border-b border-border">
                    Recent Logs
                </div>
                <div class="max-h-32 overflow-y-auto">
                    ${job.recent_logs.map(log => `
                        <div class="log-entry ${getLogClass(log.level || '')}">
                            <span class="text-text-secondary/70 font-mono text-xs mr-2">[${new Date(log.timestamp).toLocaleString()}]</span>
                            <span class="${getLogLevelColor(log.level || '')} font-bold mr-1">${log.level || 'INFO'}</span>: 
                            <span class="text-text-primary text-sm">${escapeHtmlForJobs(log.message)}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // Parameters HTML
    let paramsHtml = '';
    if (job.parameters && Object.keys(job.parameters).length > 0) {
        const params = job.parameters;

        // Define helpers within closure to generate HTML
        const renderInput = (key: string, p: JobParameter) => {
            const label = p.description || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            const defaultValue = p.default !== undefined ? p.default : '';

            if (p.type === 'boolean') {
                const isChecked = defaultValue === true ? 'checked' : '';
                return `
                    <div class="flex items-center mt-4 mb-2">
                        <input type="checkbox" id="param-${job.id}-${key}" data-param="${key}" 
                               class="h-4 w-4 text-accent focus:ring-accent border-border rounded" ${isChecked}>
                        <label for="param-${job.id}-${key}" class="ml-2 block text-sm text-text-primary leading-none">
                            ${label}
                        </label>
                    </div>
                `;
            } else if (p.type === 'date') {
                // Default to today if no default provided for date inputs
                let val = defaultValue;
                if (!val && !p.optional) {
                    val = new Date().toISOString().split('T')[0];
                }
                return `
                    <div>
                        <label class="block text-xs font-medium text-text-primary mb-1">${label}</label>
                        <input type="date" data-param="${key}" value="${val}" 
                            class="w-full text-sm bg-dashboard-surface border-border rounded-md focus:ring-accent focus:border-accent text-text-primary p-1">
                    </div>
                `;
            } else if (p.type === 'number') {
                return `
                    <div>
                        <label class="block text-xs font-medium text-text-primary mb-1">${label}</label>
                        <input type="number" data-param="${key}" value="${defaultValue}" 
                            class="w-full text-sm bg-dashboard-surface border-border rounded-md focus:ring-accent focus:border-accent text-text-primary p-1">
                    </div>
                `;
            } else {
                return `
                    <div>
                        <label class="block text-xs font-medium text-text-primary mb-1">${label}</label>
                        <input type="text" data-param="${key}" placeholder="${defaultValue}" value="${defaultValue}"
                            class="w-full text-sm bg-dashboard-surface border-border rounded-md focus:ring-accent focus:border-accent text-text-primary p-1">
                    </div>
                `;
            }
        };

        // Special handling for use_date_range logic
        const hasDateRange = 'use_date_range' in params;
        let fieldsHtml = '';

        if (hasDateRange) {
            // Render use_date_range checkbox
            fieldsHtml += `
                <div class="col-span-full mb-2">
                    <div class="flex items-center">
                        <input type="checkbox" id="param-${job.id}-use_date_range" data-param="use_date_range" 
                               onchange="toggleDateRange('${job.id}', this)"
                               class="h-4 w-4 text-accent focus:ring-accent border-border rounded">
                        <label for="param-${job.id}-use_date_range" class="ml-2 block text-sm font-medium text-text-primary">
                            Use Date Range
                        </label>
                    </div>
                    <p class="text-xs text-text-secondary ml-6 mt-0.5">Process data for a range of dates instead of a single day</p>
                </div>
            `;

            // Render Single Date Group (Target Date)
            fieldsHtml += '<div class="col-span-full param-group-single-date">';
            if (params['target_date']) {
                fieldsHtml += renderInput('target_date', params['target_date']);
            }
            fieldsHtml += '</div>';

            // Render Date Range Group (From/To) - Hidden by default
            fieldsHtml += '<div class="col-span-full grid grid-cols-2 gap-3 param-group-date-range hidden">';
            if (params['from_date']) {
                fieldsHtml += renderInput('from_date', params['from_date']);
            }
            if (params['to_date']) {
                fieldsHtml += renderInput('to_date', params['to_date']);
            }
            fieldsHtml += '</div>';

            // Render other params
            Object.entries(params).forEach(([key, p]) => {
                if (key !== 'use_date_range' && key !== 'target_date' && key !== 'from_date' && key !== 'to_date') {
                    fieldsHtml += renderInput(key, p as JobParameter);
                }
            });

        } else {
            // standard rendering
            Object.entries(params).forEach(([key, p]) => {
                fieldsHtml += renderInput(key, p as JobParameter);
            });
        }

        paramsHtml = `
            <div class="mt-4 parameter-form hidden bg-dashboard-background p-4 rounded-md border border-border" id="params-${job.id}">
                <div class="flex justify-between items-center mb-3">
                    <h4 class="text-sm font-bold text-text-primary">⚙️ Job Parameters</h4>
                    <button class="text-xs text-text-secondary hover:text-text-primary" onclick="toggleParams('${job.id}')">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    ${fieldsHtml}
                </div>
                
                <div class="mt-4 flex justify-end border-t border-border pt-3">
                     <button class="text-sm text-text-secondary mr-3 hover:text-text-primary px-3 py-1.5" onclick="toggleParams('${job.id}')">Cancel</button>
                     <button class="bg-accent text-white px-4 py-1.5 rounded-lg hover:bg-accent-hover shadow-md hover:shadow-lg active:scale-95 transition-all duration-200 font-semibold text-sm flex items-center run-btn" 
                        onclick="runJobWithParams('${job.id}', '${job.actual_job_id || job.id}')">
                        <i class="fas fa-play mr-1.5 text-xs"></i> Run Now
                     </button>
                </div>
            </div>
        `;
    }

    return `
        <div class="job-card bg-dashboard-surface rounded-lg shadow-sm p-6 border-l-4 ${getStatusBorderColor(job)} relative border border-border hover:shadow-md transition-shadow duration-200">
            <div class="flex justify-between items-start">
                <div>
                    <div class="flex items-center space-x-3">
                        <h3 class="text-lg font-bold text-text-primary">${job.name || job.id}</h3>
                        <span class="status-badge ${statusClass}">${getJobStatusLabel(job)}</span>
                    </div>
                    <p class="text-xs text-text-secondary mt-1 font-mono">${job.id}</p>
                    
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-3 text-sm">
                        <div>
                            <span class="text-text-secondary">Next Run:</span>
                            <span class="font-medium ${!job.next_run ? 'text-theme-warning-text' : 'text-text-primary'}">${nextRun}</span>
                        </div>
                        <div>
                            <span class="text-text-secondary">Schedule:</span>
                            <span class="font-medium text-text-primary">${getScheduleText(job.trigger || '')}</span>
                        </div>
                    </div>
                </div>
                
                <div class="flex space-x-2">
                    ${job.next_run
            ? `<button class="job-action-btn text-theme-warning-text hover:text-theme-warning-text/80 p-2" 
                                data-action="pause" data-id="${job.actual_job_id || job.id}" title="Pause Job">
                                <i class="fas fa-pause"></i>
                           </button>`
            : `<button class="job-action-btn text-theme-success-text hover:text-theme-success-text/80 p-2" 
                                data-action="resume" data-id="${job.actual_job_id || job.id}" title="Resume Job">
                                <i class="fas fa-play"></i>
                           </button>`
        }
                    
                    ${Object.keys(job.parameters || {}).length > 0
            ? `<button class="text-accent hover:text-accent-hover p-2" 
                                onclick="toggleParams('${job.id}')" title="Run with Parameters">
                                <i class="fas fa-cog"></i>
                           </button>`
            : `<button class="job-action-btn text-accent hover:text-accent-hover p-2" 
                                data-action="run" data-id="${job.actual_job_id || job.id}" title="Run Now">
                                <i class="fas fa-bolt"></i>
                           </button>`
        }
                </div>
            </div>
            
            ${paramsHtml}
            ${logsHtml}
        </div>
    `;
}

// Helper Functions
function getStatusClass(job: Job): string {
    if (job.is_paused || !job.next_run) {
        return 'bg-theme-warning-bg/10 text-theme-warning-text border border-theme-warning-text/20';
    }
    if (job.is_running) {
        return 'bg-theme-info-bg/10 text-theme-info-text border border-theme-info-text/20';
    }
    if (job.last_error) {
        return 'bg-theme-error-bg/10 text-theme-error-text border border-theme-error-text/20';
    }
    return 'bg-theme-success-bg/10 text-theme-success-text border border-theme-success-text/20';
}

function getJobStatusLabel(job: Job): string {
    if (job.is_paused || !job.next_run) {
        return 'Paused';
    }
    if (job.is_running) {
        return 'Running';
    }
    if (job.last_error) {
        return 'Failed';
    }
    return 'Scheduled';
}

function getStatusBorderColor(job: Job): string {
    if (job.is_paused || !job.next_run) {
        return 'border-theme-warning-text';
    }
    if (job.last_error) {
        return 'border-theme-error-text';
    }
    if (job.is_running) {
        return 'border-theme-info-text';
    }
    return 'border-theme-success-text';
}

function getScheduleText(trigger: string): string {
    if (!trigger || trigger === 'unknown') {
        return 'Manual';
    }
    // Backend now formats triggers as readable strings, so just return as-is
    // Keep old format handling for backward compatibility
    return trigger.replace('cron[', '').replace(']', '').replace('interval[', 'Every ');
}

function getLogClass(level: string): string {
    return level === 'ERROR' ? 'bg-theme-error-bg text-theme-error-text' : 'text-text-primary';
}

function getLogLevelColor(level: string): string {
    if (level === 'ERROR') {
        return 'text-theme-error-text';
    }
    if (level === 'WARNING') {
        return 'text-theme-warning-text';
    }
    return 'text-theme-info-text';
}

function escapeHtmlForJobs(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showJobsError(msg: string): void {
    if (elements.errorMsg) {
        elements.errorMsg.classList.remove('hidden');
    }
    if (elements.errorText) {
        elements.errorText.textContent = msg;
    }
    setTimeout(() => {
        if (elements.errorMsg) {
            elements.errorMsg.classList.add('hidden');
        }
    }, 5000);
}

// Job Actions
async function handleJobAction(e: Event): Promise<void> {
    const btn = e.currentTarget as HTMLElement;
    const action = btn.getAttribute('data-action');
    const jobId = btn.getAttribute('data-id');

    if (!action || !jobId) {
        return;
    }

    // Visual feedback
    const originalIcon = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    btn.setAttribute('disabled', 'true');

    try {
        const response = await fetch(`/api/admin/scheduler/jobs/${jobId}/${action}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include'
        });

        // Check if response is JSON before parsing
        const contentType = response.headers.get('content-type');
        const isJson = contentType && contentType.includes('application/json');

        let data: JobsApiResponse;
        if (isJson) {
            data = await response.json();
        } else {
            // If not JSON, try to get text for error message
            const text = await response.text();
            throw new Error(`Server error (${response.status}): ${text.substring(0, 200)}`);
        }

        if (!response.ok) {
            throw new Error(data.error || `Action failed (${response.status})`);
        }

        // Refresh immediately
        fetchStatus();

    } catch (error) {
        console.error('Job action error:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showJobsError(errorMessage);
    } finally {
        btn.innerHTML = originalIcon;
        btn.removeAttribute('disabled');
    }
}

async function startScheduler(): Promise<void> {
    try {
        const response = await fetch('/api/admin/scheduler/start', {
            method: 'POST',
            credentials: 'include'
        });

        // Check if response is JSON before parsing
        const contentType = response.headers.get('content-type');
        const isJson = contentType && contentType.includes('application/json');

        let data: JobsApiResponse;
        if (isJson) {
            data = await response.json();
        } else {
            // If not JSON, try to get text for error message
            const text = await response.text();
            throw new Error(`Server error (${response.status}): ${text.substring(0, 200)}`);
        }

        if (!response.ok) {
            throw new Error(data.error || `Failed to start scheduler (${response.status})`);
        }
        fetchStatus();
    } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showJobsError(errorMessage);
    }
}


// Global functions for inline onclick handlers
function toggleParams(id: string): void {
    const el = document.getElementById(`params-${id}`);
    if (el) {
        el.classList.toggle('hidden');
    }
}

function toggleDateRange(jobId: string, checkbox: HTMLInputElement): void {
    const container = document.getElementById(`params-${jobId}`);
    if (!container) return;

    const singleDateGroup = container.querySelector('.param-group-single-date');
    const dateRangeGroup = container.querySelector('.param-group-date-range');

    if (checkbox.checked) {
        singleDateGroup?.classList.add('hidden');
        dateRangeGroup?.classList.remove('hidden');
    } else {
        singleDateGroup?.classList.remove('hidden');
        dateRangeGroup?.classList.add('hidden');
    }
}

async function runJobWithParams(id: string, actualJobId: string): Promise<void> {
    const container = document.getElementById(`params-${id}`);
    if (!container) {
        return;
    }

    const inputs = container.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select');
    const params: Record<string, any> = {};

    // Check for date range mode
    const useDateRangeInfo = container.querySelector('input[data-param="use_date_range"]') as HTMLInputElement;
    const isDateRangeMode = useDateRangeInfo && useDateRangeInfo.checked;

    inputs.forEach(input => {
        const paramKey = input.getAttribute('data-param');
        if (!paramKey) return;

        // Skip fields that are hidden due to date range logic
        if (paramKey === 'target_date' && isDateRangeMode) return;
        if ((paramKey === 'from_date' || paramKey === 'to_date') && !isDateRangeMode) return;

        if (input.type === 'checkbox') {
            params[paramKey] = (input as HTMLInputElement).checked;
        } else if (input.type === 'number') {
            const val = parseFloat(input.value);
            if (!isNaN(val)) {
                params[paramKey] = val;
            }
        } else if (input.value.trim() !== '') {
            params[paramKey] = input.value.trim();
        }
    });

    try {
        const btn = container.querySelector('button.run-btn') as HTMLButtonElement;
        const originalContent = btn ? btn.innerHTML : '';
        if (btn) {
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Running...';
            btn.disabled = true;
        }

        const response = await fetch(`/api/admin/scheduler/jobs/${actualJobId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
            credentials: 'include'
        });

        // Check if response is JSON before parsing
        const contentType = response.headers.get('content-type');
        const isJson = contentType && contentType.includes('application/json');

        let data: JobsApiResponse;
        if (isJson) {
            data = await response.json();
        } else {
            // If not JSON, try to get text for error message
            const text = await response.text();
            throw new Error(`Server error (${response.status}): ${text.substring(0, 200)}`);
        }

        if (!response.ok) {
            throw new Error(data.error || `Failed to run job (${response.status})`);
        }

        // Hide params and refresh
        toggleParams(id);
        fetchStatus();

        // Show success toast/message
        // You might want to implement a toast notification here

    } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showJobsError(errorMessage);
    } finally {
        const btn = container.querySelector('button.run-btn') as HTMLButtonElement;
        if (btn) {
            btn.innerHTML = 'Run Now';
            btn.disabled = false;
        }
    }
}

// Make functions available globally for inline onclick handlers
// Assign to window for inline handlers - must be done immediately, not in DOMContentLoaded
if (typeof window !== 'undefined') {
    (window as any).refreshJobs = fetchStatus;
    (window as any).toggleParams = toggleParams;
    (window as any).toggleDateRange = toggleDateRange;
    (window as any).runJobWithParams = runJobWithParams;
    console.log('[Jobs] Global functions exposed: refreshJobs, toggleParams, toggleDateRange, runJobWithParams');
}
