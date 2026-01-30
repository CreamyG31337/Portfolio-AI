/**
 * UI Utilities Module
 * Handles header auto-hide, sidebar collapse, scheduler badge updates, and fund selector persistence
 */

// ============================================================================
// Sidebar Collapse/Expand (Desktop)
// Mobile uses Flowbite Drawer component
// ============================================================================

interface SidebarElements {
    sidebar: HTMLElement;
}

const MOBILE_BREAKPOINT = 768; // md breakpoint in Tailwind
const NARROW_SCREEN_THRESHOLD = 1024; // Collapse by default on screens narrower than this

function isMobile(): boolean {
    return window.innerWidth < MOBILE_BREAKPOINT;
}

function isNarrowScreen(): boolean {
    return window.innerWidth < NARROW_SCREEN_THRESHOLD;
}

function collapseSidebar(elements: SidebarElements): void {
    const { sidebar } = elements;
    sidebar.setAttribute('data-sidebar-collapsed', 'true');

    // Save state (only on desktop)
    if (!isMobile()) {
        localStorage.setItem('sidebarCollapsed', 'true');
    }
}

function expandSidebar(elements: SidebarElements): void {
    const { sidebar } = elements;
    sidebar.setAttribute('data-sidebar-collapsed', 'false');

    // Save state (only on desktop)
    if (!isMobile()) {
        localStorage.setItem('sidebarCollapsed', 'false');
    }
}

function toggleSidebar(elements: SidebarElements): void {
    const isCollapsed = elements.sidebar.getAttribute('data-sidebar-collapsed') === 'true';

    if (isCollapsed) {
        expandSidebar(elements);
    } else {
        collapseSidebar(elements);
    }
}

function initSidebar(): void {
    const sidebar = document.getElementById('sidebar');
    const toggleButton = document.getElementById('sidebar-collapse-toggle');

    if (!sidebar) return;

    const elements: SidebarElements = { sidebar };

    if (isMobile()) {
        // Mobile: Let Flowbite drawer handle it completely; ensure full width (no collapsed state)
        sidebar.removeAttribute('data-sidebar-collapsed');
    } else {
        // Desktop: Apply collapsible state
        const shouldCollapseByDefault = isNarrowScreen();
        const savedState = localStorage.getItem('sidebarCollapsed');

        if (shouldCollapseByDefault && savedState !== 'false') {
            collapseSidebar(elements);
        } else if (savedState === 'true') {
            collapseSidebar(elements);
        } else {
            expandSidebar(elements);
        }
    }

    // Event listener for toggle button
    if (toggleButton) {
        toggleButton.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            toggleSidebar(elements);
        });
    }

    // Handle window resize
    let resizeTimeout: number;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = window.setTimeout(() => {
            if (isMobile()) {
                // Mobile: always show full-width drawer; clear collapsed state so Flowbite drawer isn't 64px
                sidebar.removeAttribute('data-sidebar-collapsed');
            } else {
                const isCollapsed = sidebar.getAttribute('data-sidebar-collapsed') === 'true';
                if (isCollapsed) {
                    collapseSidebar(elements);
                } else {
                    expandSidebar(elements);
                }
            }
        }, 150);
    });
}

// ============================================================================
// Header Auto-Hide
// ============================================================================

function initHeaderAutoHide(): void {
    const header = document.getElementById('main-header');
    if (!header) return;

    let lastScrollY = window.scrollY;
    let ticking = false;

    function updateHeader(): void {
        if (!header) return; // Additional null check for closure

        const scrollY = window.scrollY;
        const headerHeight = header.offsetHeight;

        // Only activate if we've scrolled past the header height
        if (scrollY > headerHeight) {
            if (scrollY > lastScrollY) {
                // Scrolling down - hide
                header.style.transform = 'translateY(-100%)';
            } else {
                // Scrolling up - show
                header.style.transform = 'translateY(0)';
            }
        } else {
            // At top - show
            header.style.transform = 'translateY(0)';
        }

        lastScrollY = scrollY;
        ticking = false;
    }

    window.addEventListener('scroll', () => {
        if (!ticking) {
            window.requestAnimationFrame(updateHeader);
            ticking = true;
        }
    });
}

// ============================================================================
// Scheduler Status Badge Auto-Update
// ============================================================================

async function updateSchedulerBadge(): Promise<void> {
    try {
        const response = await fetch('/api/admin/scheduler/status');
        if (!response.ok) {
            // If not authorized or endpoint unavailable, silently fail
            return;
        }
        const data = await response.json();

        // Find the badge within the Jobs Scheduler link
        const schedulerLink = Array.from(document.querySelectorAll('a')).find(
            link => link.href.includes('scheduler') || link.textContent?.includes('Jobs Scheduler')
        );

        if (!schedulerLink) return;

        const badge = schedulerLink.querySelector('.sidebar-badge');
        if (!badge) return;

        // Priority-based badge states
        const jobs = data.jobs || [];
        
        // Priority 1: Check if any job is running
        const hasRunningJob = jobs.some((job: any) => job.is_running === true);
        
        // Priority 2: Check if no jobs running but errors exist
        const hasErrors = !hasRunningJob && jobs.some((job: any) => {
            // Check for last_error or recent ERROR logs
            if (job.last_error) return true;
            if (job.recent_logs && Array.isArray(job.recent_logs)) {
                return job.recent_logs.some((log: any) => 
                    log.level === 'ERROR' || log.level === 'error'
                );
            }
            return false;
        });

        if (hasRunningJob) {
            // Priority 1: Job is running - show pulsing amber badge
            badge.textContent = 'Running';
            badge.className = 'inline-flex items-center justify-center px-2 py-1 ms-3 text-xs font-medium text-amber-800 bg-amber-100 rounded-full dark:bg-amber-900 dark:text-amber-300 animate-pulse sidebar-badge';
        } else if (hasErrors) {
            // Priority 2: Errors exist but no jobs running - show solid red badge
            badge.textContent = 'Errors';
            badge.className = 'inline-flex items-center justify-center px-2 py-1 ms-3 text-xs font-medium text-red-800 bg-red-100 rounded-full dark:bg-red-900 dark:text-red-300 sidebar-badge';
        } else if (data.scheduler_running) {
            // Priority 3: Scheduler running, no jobs running, no errors - show solid green badge
            badge.textContent = 'Running';
            badge.className = 'inline-flex items-center justify-center px-2 py-1 ms-3 text-xs font-medium text-green-800 bg-green-100 rounded-full dark:bg-green-900 dark:text-green-300 sidebar-badge';
        } else {
            // Priority 4: Scheduler stopped - show solid red badge
            badge.textContent = 'Stopped';
            badge.className = 'inline-flex items-center justify-center px-2 py-1 ms-3 text-xs font-medium text-red-800 bg-red-100 rounded-full dark:bg-red-900 dark:text-red-300 sidebar-badge';
        }
    } catch (error) {
        // Silently fail - badge will show server-rendered status
        console.debug('Scheduler badge update failed (non-critical):', error);
    }
}

function initSchedulerBadge(): void {
    // Only update if user is admin (badge exists)
    const badge = document.querySelector('a[href*="scheduler"] .sidebar-badge');
    if (!badge) return;

    updateSchedulerBadge();

    // Poll every 15s when visible (performance optimization), pause when hidden
    setInterval(() => {
        if (!document.hidden) {
            updateSchedulerBadge();
        }
    }, 15000);

    // Update immediately when tab becomes visible
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            updateSchedulerBadge();
        }
    });
}

// ============================================================================
// Global Fund Selector URL Persistence
// ============================================================================

function initFundSelector(): void {
    const selector = document.getElementById('global-fund-select') as HTMLSelectElement | null;
    if (!selector) return;

    // Read fund from URL parameter on page load
    const urlParams = new URLSearchParams(window.location.search);
    const urlFund = urlParams.get('fund');

    if (urlFund && selector.querySelector(`option[value="${urlFund}"]`)) {
        selector.value = urlFund;
    }

    // Update URL when fund selector changes (without page reload)
    selector.addEventListener('change', (e) => {
        const selectedFund = (e.target as HTMLSelectElement).value;
        const url = new URL(window.location.href);

        if (selectedFund && selectedFund.toLowerCase() !== 'all') {
            url.searchParams.set('fund', selectedFund);
        } else {
            url.searchParams.delete('fund');
        }

        // Update URL without page reload
        window.history.pushState({ fund: selectedFund }, '', url.toString());

        // Dispatch custom event for pages that need to react to fund changes
        window.dispatchEvent(new CustomEvent('fundChanged', { detail: { fund: selectedFund } }));
    });

    // Handle browser back/forward buttons
    window.addEventListener('popstate', () => {
        const urlParams = new URLSearchParams(window.location.search);
        const urlFund = urlParams.get('fund');

        if (urlFund && selector.querySelector(`option[value="${urlFund}"]`)) {
            selector.value = urlFund;
            window.dispatchEvent(new CustomEvent('fundChanged', { detail: { fund: urlFund } }));
        } else if (!urlFund) {
            // If no fund in URL, set to "all" or first option
            const allOption = selector.querySelector('option[value="all"]');
            if (allOption) {
                selector.value = 'all';
            } else if (selector.options.length > 0) {
                selector.value = selector.options[0].value;
            }
            window.dispatchEvent(new CustomEvent('fundChanged', { detail: { fund: selector.value } }));
        }
    });
}

// ============================================================================
// Initialize All UI Components
// ============================================================================

function initUI(): void {
    // Wait a bit for Flowbite to initialize
    setTimeout(() => {
        initSidebar();
        initHeaderAutoHide();
        initSchedulerBadge();
        initFundSelector();
    }, 100);
}

// Run initialization when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUI);
} else {
    initUI();
}
