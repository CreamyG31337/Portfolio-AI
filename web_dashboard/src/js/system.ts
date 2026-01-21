/**
 * System Monitoring Dashboard
 * Handles system status and cache management
 */

import { clearCache, bumpCacheVersion, resetSystemCache } from './system_cache_functions.js';

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

document.addEventListener('DOMContentLoaded', () => {
    fetchSystemStatus();
    fetchDeploymentInfo();
});

async function fetchDeploymentInfo(): Promise<void> {
    try {
        const response = await fetch('/api/admin/system/deployment-info');
        const data = await response.json();
        const deployInfo = document.getElementById('deployment-info');

        if (deployInfo) {
            if (data.build_info && (data.build_info.commit || data.build_info.timestamp)) {
                deployInfo.innerHTML = `
                    <span class="text-xs text-text-secondary">
                        🚀 Deployed: ${data.build_info.build_date || data.build_info.timestamp || 'Unknown'} 
                        | Commit: <code class="bg-dashboard-background px-1 rounded text-accent">${(data.build_info.commit || 'unknown').substring(0, 8)}</code>
                        | Branch: ${data.build_info.branch || 'Unknown'}
                    </span>
                `;
            } else {
                // Handle case where build info is missing but API worked
                deployInfo.innerHTML = `
                    <span class="text-xs text-text-secondary">
                        Deployment info unavailable
                    </span>
                `;
            }
        }
    } catch (error) {
        console.error("Error fetching deployment info:", error);
        const deployInfo = document.getElementById('deployment-info');
        if (deployInfo) {
            deployInfo.innerHTML = `
                <span class="text-xs text-theme-error-text" title="${error}">
                    Failed to load deployment info
                </span>
            `;
        }
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
                dbEl.innerHTML = `<span class="bg-theme-success-bg text-theme-success-text text-sm font-medium mr-2 px-2.5 py-0.5 rounded border border-theme-success-text">Connected</span>`;
            } else {
                dbEl.innerHTML = `<span class="bg-theme-error-bg text-theme-error-text text-sm font-medium mr-2 px-2.5 py-0.5 rounded border border-theme-error-text">Disconnected</span>`;
            }
        }

        // Update Postgres
        const pgEl = document.getElementById('status-postgres');
        const pgStats = document.getElementById('stats-postgres');
        if (pgEl) {
            if (status.postgres_connected) {
                pgEl.innerHTML = `<span class="bg-theme-success-bg text-theme-success-text text-sm font-medium mr-2 px-2.5 py-0.5 rounded border border-theme-success-text">Connected</span>`;
                if (pgStats && status.postgres_stats) {
                    pgStats.innerHTML = `<div>Total Articles: ${status.postgres_stats.total}</div>`;
                }
            } else {
                pgEl.innerHTML = `<span class="bg-theme-error-bg text-theme-error-text text-sm font-medium mr-2 px-2.5 py-0.5 rounded border border-theme-error-text">Disconnected</span>`;
            }
        }

        // Rates
        const ratesEl = document.getElementById('status-rates');
        if (ratesEl) {
            if (status.exchange_rates) {
                ratesEl.innerHTML = `<span class="text-xl font-bold text-text-primary">${status.exchange_rates}</span>`;
            } else {
                ratesEl.innerHTML = `<span class="text-text-secondary">N/A</span>`;
            }
        }

        // Jobs
        const tbody = document.getElementById('jobs-table-body');
        if (tbody && data.jobs && data.jobs.length > 0) {
            tbody.innerHTML = data.jobs.map(job => `
                <tr class="bg-dashboard-surface border-b border-border hover:bg-dashboard-hover">
                    <td class="px-6 py-4 font-medium text-text-primary">${job.job_id}</td>
                    <td class="px-6 py-4">
                        ${job.success
                    ? '<span class="text-theme-success-text"><i class="fas fa-check-circle"></i> Success</span>'
                    : '<span class="text-theme-error-text"><i class="fas fa-times-circle"></i> Failed</span>'}
                    </td>
                    <td class="px-6 py-4 text-text-secondary">${job.timestamp}</td>
                    <td class="px-6 py-4 truncate max-w-xs text-text-secondary" title="${job.message}">${job.message}</td>
                </tr>
            `).join('');
        } else if (tbody) {
            tbody.innerHTML = `<tr><td colspan="4" class="px-6 py-4 text-center text-text-secondary">No recent job logs found</td></tr>`;
        }

    } catch (error) {
        console.error("Error fetching status:", error);
    }
}

// Make functions available globally for onclick handlers
(window as any).clearCache = clearCache;
(window as any).bumpCacheVersion = bumpCacheVersion;
(window as any).resetSystemCache = resetSystemCache;
