/**
 * System Monitoring Dashboard
 * Handles system status, logs viewing (app, docker, files)
 */

import { clearCache, bumpCacheVersion } from './system_cache_functions';

// Type definitions
interface SystemStatus {
    supabase_connected: boolean;
    postgres_connected: boolean;
    postgres_stats?: {
        total: number;
    };
    exchange_rates?: string;
}

interface SystemStatusResponse {
    status: SystemStatus;
    jobs?: JobLog[];
}

interface JobLog {
    job_id: string;
    success: boolean;
    timestamp: string;
    message: string;
}

interface LogEntry {
    timestamp: string;
    level: string;
    module: string;
    message: string;
}

interface LogsResponse {
    logs: LogEntry[];
    total?: number;
    page?: number;
    pages?: number;
}

interface DockerContainer {
    id: string;
    name: string;
    status: string;
    image: string;
}

interface DockerContainersResponse {
    containers: DockerContainer[];
}

interface DockerLogsResponse {
    logs?: string;
    name?: string;
    error?: string;
}

interface FilesResponse {
    files: string[];
    error?: string;
}

interface FileContentResponse {
    content?: string;
    error?: string;
}

type LogMode = 'app' | 'docker' | 'files';

interface CacheResponse {
    success: boolean;
    message: string;
    cache_version?: string;
}

let currentLogMode: LogMode = 'app';

document.addEventListener('DOMContentLoaded', () => {
    fetchSystemStatus();
    fetchDeploymentInfo();
    switchLogMode('app');

    // Auto-refresh timer
    setInterval(() => {
        const checkbox = document.getElementById('auto-refresh') as HTMLInputElement | null;
        if (checkbox && checkbox.checked && currentLogMode === 'app') {
            refreshLogs();
        }
    }, 5000);
});

async function fetchDeploymentInfo(): Promise<void> {
    try {
        const response = await fetch('/api/admin/system/deployment-info');
        const data = await response.json();
        
        if (data.build_info && data.build_info.commit) {
            const deployInfo = document.getElementById('deployment-info');
            if (deployInfo) {
                deployInfo.innerHTML = `
                    <span class="text-xs text-gray-500">
                        🚀 Deployed: ${data.build_info.build_date || 'Unknown'} 
                        | Commit: <code class="bg-gray-100 px-1 rounded">${data.build_info.commit.substring(0, 8)}</code>
                        | Branch: ${data.build_info.branch || 'Unknown'}
                    </span>
                `;
            }
        }
    } catch (error) {
        console.error("Error fetching deployment info:", error);
    }
}

async function fetchSystemStatus(): Promise<void> {
    try {
        const response = await fetch('/api/admin/system/status');
        const data: SystemStatusResponse = await response.json();
        const status = data.status;

        // Update DB
        const dbEl = document.getElementById('status-db');
        if (dbEl) {
            if (status.supabase_connected) {
                dbEl.innerHTML = `<span class="bg-green-100 text-green-800 text-sm font-medium mr-2 px-2.5 py-0.5 rounded">Connected</span>`;
            } else {
                dbEl.innerHTML = `<span class="bg-red-100 text-red-800 text-sm font-medium mr-2 px-2.5 py-0.5 rounded">Disconnected</span>`;
            }
        }

        // Update Postgres
        const pgEl = document.getElementById('status-postgres');
        const pgStats = document.getElementById('stats-postgres');
        if (pgEl) {
            if (status.postgres_connected) {
                pgEl.innerHTML = `<span class="bg-green-100 text-green-800 text-sm font-medium mr-2 px-2.5 py-0.5 rounded">Connected</span>`;
                if (pgStats && status.postgres_stats) {
                    pgStats.innerHTML = `<div>Total Articles: ${status.postgres_stats.total}</div>`;
                }
            } else {
                pgEl.innerHTML = `<span class="bg-red-100 text-red-800 text-sm font-medium mr-2 px-2.5 py-0.5 rounded">Disconnected</span>`;
            }
        }

        // Rates
        const ratesEl = document.getElementById('status-rates');
        if (ratesEl) {
            if (status.exchange_rates) {
                ratesEl.innerHTML = `<span class="text-xl font-bold text-gray-900">${status.exchange_rates}</span>`;
            } else {
                ratesEl.innerHTML = `<span class="text-gray-400">N/A</span>`;
            }
        }

        // Jobs
        const tbody = document.getElementById('jobs-table-body');
        if (tbody && data.jobs && data.jobs.length > 0) {
            tbody.innerHTML = data.jobs.map(job => `
                <tr class="bg-white border-b hover:bg-gray-50">
                    <td class="px-6 py-4 font-medium">${job.job_id}</td>
                    <td class="px-6 py-4">
                        ${job.success
                    ? '<span class="text-green-600"><i class="fas fa-check-circle"></i> Success</span>'
                    : '<span class="text-red-600"><i class="fas fa-times-circle"></i> Failed</span>'}
                    </td>
                    <td class="px-6 py-4">${job.timestamp}</td>
                    <td class="px-6 py-4 truncate max-w-xs" title="${job.message}">${job.message}</td>
                </tr>
            `).join('');
        } else if (tbody) {
            tbody.innerHTML = `<tr><td colspan="4" class="px-6 py-4 text-center text-gray-500">No recent job logs found</td></tr>`;
        }

    } catch (error) {
        console.error("Error fetching status:", error);
    }
}

function switchTab(tab: string): void {
    // Buttons
    document.querySelectorAll('.tab-button').forEach(b => {
        b.classList.remove('active', 'border-blue-500', 'text-blue-600');
        b.classList.add('border-transparent', 'text-gray-500');
    });
    const tabButton = document.getElementById(`tab-${tab}`);
    if (tabButton) {
        tabButton.classList.add('active', 'border-blue-500', 'text-blue-600');
        tabButton.classList.remove('border-transparent', 'text-gray-500');
    }

    // Content
    document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
    const tabContent = document.getElementById(`content-${tab}`);
    if (tabContent) {
        tabContent.classList.remove('hidden');
    }
}

function switchLogMode(mode: LogMode): void {
    currentLogMode = mode;

    // Toggle active button state
    (['app', 'docker', 'files'] as LogMode[]).forEach(m => {
        const btn = document.getElementById(`mode-${m}`);
        if (m === mode) {
            btn?.classList.add('text-blue-700', 'bg-blue-50', 'ring-2', 'ring-blue-700');
        } else {
            btn?.classList.remove('text-blue-700', 'bg-blue-50', 'ring-2', 'ring-blue-700');
        }
    });

    // Toggle controls
    const appControls = document.querySelector('.app-controls');
    const dockerControls = document.querySelector('.docker-controls');
    
    if (mode === 'app') {
        appControls?.classList.remove('hidden');
        dockerControls?.classList.add('hidden');
        refreshLogs();
    } else {
        appControls?.classList.add('hidden');
        dockerControls?.classList.remove('hidden');

        // Load list
        if (mode === 'docker') loadDockerContainers();
        if (mode === 'files') loadFiles();
    }
}

async function refreshLogs(): Promise<void> {
    if (currentLogMode === 'app') {
        fetchAppLogs();
    } else {
        loadSourceLogs();
    }
}

// --- APP LOGS ---
async function fetchAppLogs(): Promise<void> {
    const viewer = document.getElementById('log-viewer');
    if (!viewer) return;

    const levelSelect = document.getElementById('log-level') as HTMLSelectElement | null;
    const searchInput = document.getElementById('log-search') as HTMLInputElement | null;
    const sinceDeploymentCheckbox = document.getElementById('since-deployment') as HTMLInputElement | null;
    
    const level = levelSelect?.value || 'All';
    const search = searchInput?.value || '';
    const sinceDeployment = sinceDeploymentCheckbox?.checked ? 'true' : 'false';

    try {
        const response = await fetch(`/api/admin/system/logs/application?level=${encodeURIComponent(level)}&search=${encodeURIComponent(search)}&limit=200&since_deployment=${sinceDeployment}`);
        const data: LogsResponse = await response.json();

        if (data.logs) {
            viewer.innerHTML = data.logs.map(log => {
                let colorClass = 'text-gray-300';
                if (log.level === 'ERROR') colorClass = 'text-red-400';
                if (log.level === 'WARNING') colorClass = 'text-yellow-400';
                if (log.level === 'INFO') colorClass = 'text-blue-300';

                return `<div class="log-line hover:bg-gray-800">
                    <span class="text-gray-500">[${log.timestamp}]</span>
                    <span class="${colorClass} w-16 inline-block font-bold">${log.level}</span>
                    <span class="text-gray-400 inline-block w-48 truncate mr-2" title="${log.module}">${log.module}</span>
                    <span class="text-white">${log.message}</span>
                </div>`;
            }).join('');
        }
    } catch (e) {
        viewer.innerHTML = `<div class="text-red-500 p-4">Error fetching logs: ${e}</div>`;
    }
}

// --- DOCKER / FILES ---
async function loadDockerContainers(): Promise<void> {
    const select = document.getElementById('docker-source') as HTMLSelectElement | null;
    if (!select) return;

    select.innerHTML = '<option>Loading containers...</option>';

    try {
        const res = await fetch('/api/admin/system/docker/containers');
        const data: DockerContainersResponse = await res.json();

        if (data.containers) {
            select.innerHTML = data.containers.map(c =>
                `<option value="${c.id}">${c.name} (${c.image})</option>`
            ).join('');
            loadSourceLogs(); // Load first
        } else {
            select.innerHTML = '<option>No containers found or Docker unavailable</option>';
        }
    } catch (e) {
        select.innerHTML = `<option>Error: ${e}</option>`;
    }
}

async function loadFiles(): Promise<void> {
    const select = document.getElementById('docker-source') as HTMLSelectElement | null;
    if (!select) return;

    select.innerHTML = '<option>Loading files...</option>';

    try {
        const res = await fetch('/api/admin/system/files');
        const data: FilesResponse = await res.json();

        if (data.files) {
            select.innerHTML = data.files.map(f => `<option value="${f}">${f}</option>`).join('');
            loadSourceLogs();
        } else {
            select.innerHTML = '<option>No logs found</option>';
        }
    } catch (e) {
        select.innerHTML = `<option>Error: ${e}</option>`;
    }
}

async function loadSourceLogs(): Promise<void> {
    const select = document.getElementById('docker-source') as HTMLSelectElement | null;
    const viewer = document.getElementById('log-viewer');
    
    if (!select || !viewer) return;

    const id = select.value;

    if (!id || id.startsWith('Loading') || id.startsWith('Error')) return;

    viewer.innerHTML = '<div class="text-gray-500 p-4">Fetching content...</div>';

    try {
        let url = '';
        if (currentLogMode === 'docker') {
            url = `/api/admin/system/docker/logs/${id}`;
        } else {
            url = `/api/admin/system/files/content?filename=${encodeURIComponent(id)}`;
        }

        const res = await fetch(url);
        
        if (currentLogMode === 'docker') {
            const data: DockerLogsResponse = await res.json();
            if (data.error) {
                viewer.innerHTML = `<div class="text-red-400 p-4">Error: ${data.error}</div>`;
            } else if (data.logs) {
                viewer.innerHTML = `<pre class="whitespace-pre-wrap font-mono text-xs">${data.logs}</pre>`;
            } else {
                viewer.innerHTML = `<div class="text-red-400 p-4">No logs available</div>`;
            }
        } else {
            const data: FileContentResponse = await res.json();
            if (data.error) {
                viewer.innerHTML = `<div class="text-red-400 p-4">Error: ${data.error}</div>`;
            } else if (data.content) {
                viewer.innerHTML = `<pre class="whitespace-pre-wrap font-mono text-xs">${data.content}</pre>`;
            } else {
                viewer.innerHTML = `<div class="text-red-400 p-4">No content available</div>`;
            }
        }

    } catch (e) {
        viewer.innerHTML = `<div class="text-red-400 p-4">Request failed: ${e}</div>`;
    }
}

// Make functions available globally for onclick handlers
(window as any).switchTab = switchTab;
(window as any).switchLogMode = switchLogMode;
(window as any).refreshLogs = refreshLogs;
(window as any).loadSourceLogs = loadSourceLogs;
(window as any).clearCache = clearCache;
(window as any).bumpCacheVersion = bumpCacheVersion;