/**
 * Cache Management Functions for System Monitor
 * These functions are imported into system.ts
 */

interface CacheResponse {
    success: boolean;
    message: string;
    cache_version?: string;
}

export async function clearCache(): Promise<void> {
    const btn = document.getElementById('clear-cache-btn') as HTMLButtonElement;
    const statusDiv = document.getElementById('cache-status');
    
    if (!btn || !statusDiv) return;
    
    // Disable button and show loading
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> Clearing...';
    statusDiv.textContent = '';
    
    try {
        const response = await fetch('/api/admin/system/cache/clear', {
            method: 'POST',
            credentials: 'include'
        });
        
        const data: CacheResponse = await response.json();
        
        if (data.success) {
            statusDiv.textContent = '✓ Cache cleared successfully';
            statusDiv.className = 'text-sm text-green-600';
            
            // Refresh system status to show fresh data
            setTimeout(() => {
                if (typeof (window as any).fetchSystemStatus === 'function') {
                    (window as any).fetchSystemStatus();
                }
            }, 1000);
        } else {
            statusDiv.textContent = `✗ Error: ${data.message}`;
            statusDiv.className = 'text-sm text-red-600';
        }
    } catch (error) {
        statusDiv.textContent = `✗ Error: ${error instanceof Error ? error.message : 'Unknown error'}`;
        statusDiv.className = 'text-sm text-red-600';
    } finally {
        // Re-enable button
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-trash-alt mr-2"></i> Clear All Cache';
        
        // Clear status message after 5 seconds
        setTimeout(() => {
            statusDiv.textContent = '';
        }, 5000);
    }
}

export async function bumpCacheVersion(): Promise<void> {
    const btn = document.getElementById('bump-cache-version-btn') as HTMLButtonElement;
    const statusDiv = document.getElementById('cache-status');
    
    if (!btn || !statusDiv) return;
    
    // Disable button and show loading
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> Bumping...';
    statusDiv.textContent = '';
    
    try {
        const response = await fetch('/api/admin/system/cache/bump-version', {
            method: 'POST',
            credentials: 'include'
        });
        
        const data: CacheResponse = await response.json();
        
        if (data.success) {
            const versionText = data.cache_version ? ` (version: ${data.cache_version})` : '';
            statusDiv.textContent = `✓ Cache version bumped${versionText}`;
            statusDiv.className = 'text-sm text-green-600';
        } else {
            statusDiv.textContent = `✗ Error: ${data.message}`;
            statusDiv.className = 'text-sm text-red-600';
        }
    } catch (error) {
        statusDiv.textContent = `✗ Error: ${error instanceof Error ? error.message : 'Unknown error'}`;
        statusDiv.className = 'text-sm text-red-600';
    } finally {
        // Re-enable button
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-sync-alt mr-2"></i> Bump Cache Version';
        
        // Clear status message after 5 seconds
        setTimeout(() => {
            statusDiv.textContent = '';
        }, 5000);
    }
}

export async function resetSystemCache(): Promise<void> {
    const btn = document.getElementById('reset-cache-btn') as HTMLButtonElement;
    const statusDiv = document.getElementById('cache-status');
    
    if (!btn || !statusDiv) return;
    
    // Disable button and show loading
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> Resetting...';
    statusDiv.textContent = '';
    
    try {
        const response = await fetch('/api/admin/system/cache/reset', {
            method: 'POST',
            credentials: 'include'
        });
        
        const data: CacheResponse = await response.json();
        
        if (data.success) {
            const versionText = data.cache_version ? ` (version: ${data.cache_version})` : '';
            statusDiv.textContent = `✓ System cache reset successfully${versionText}`;
            statusDiv.className = 'text-sm text-green-600';
            
            // Refresh system status to show fresh data
            setTimeout(() => {
                if (typeof (window as any).fetchSystemStatus === 'function') {
                    (window as any).fetchSystemStatus();
                }
            }, 1000);
        } else {
            statusDiv.textContent = `✗ Error: ${data.message}`;
            statusDiv.className = 'text-sm text-red-600';
        }
    } catch (error) {
        statusDiv.textContent = `✗ Error: ${error instanceof Error ? error.message : 'Unknown error'}`;
        statusDiv.className = 'text-sm text-red-600';
    } finally {
        // Re-enable button
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-trash-alt mr-2"></i> Reset System Cache';
        
        // Clear status message after 5 seconds
        setTimeout(() => {
            statusDiv.textContent = '';
        }, 5000);
    }
}
