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
    mainContent: HTMLElement;
    toggleButton: HTMLElement | null;
    toggleIcon: HTMLElement | null;
    sidebarTexts: NodeListOf<HTMLElement>;
    sidebarContents: NodeListOf<HTMLElement>;
    sidebarSelect: HTMLSelectElement | null;
    sidebarBadges: NodeListOf<HTMLElement>;
}

const SIDEBAR_EXPANDED_WIDTH = 256; // w-64 = 16rem = 256px
const SIDEBAR_COLLAPSED_WIDTH = 64;  // w-16 = 4rem = 64px
const MOBILE_BREAKPOINT = 768; // md breakpoint in Tailwind
const NARROW_SCREEN_THRESHOLD = 1024; // Collapse by default on screens narrower than this

function isMobile(): boolean {
    return window.innerWidth < MOBILE_BREAKPOINT;
}

function isNarrowScreen(): boolean {
    return window.innerWidth < NARROW_SCREEN_THRESHOLD;
}

function collapseSidebar(elements: SidebarElements): void {
    const { sidebar, mainContent, sidebarTexts, sidebarContents, sidebarSelect, sidebarBadges, toggleIcon } = elements;

    sidebar.style.width = `${SIDEBAR_COLLAPSED_WIDTH}px`;
    sidebar.setAttribute('data-sidebar-collapsed', 'true');

    if (!isMobile()) {
        mainContent.style.marginLeft = `${SIDEBAR_COLLAPSED_WIDTH}px`;
    }

    // Hide text and content with smooth transition
    sidebarTexts.forEach(el => {
        el.style.opacity = '0';
        el.style.maxWidth = '0';
        el.style.overflow = 'hidden';
    });

    sidebarContents.forEach(el => {
        el.style.opacity = '0';
        el.style.maxHeight = '0';
        el.style.overflow = 'hidden';
    });

    if (sidebarSelect) {
        sidebarSelect.style.opacity = '0';
        sidebarSelect.style.pointerEvents = 'none';
    }

    sidebarBadges.forEach(el => {
        el.style.opacity = '0';
    });

    // Rotate icon
    if (toggleIcon) {
        toggleIcon.classList.remove('fa-chevron-left');
        toggleIcon.classList.add('fa-chevron-right');
    }

    // Save state (only on desktop)
    if (!isMobile()) {
        localStorage.setItem('sidebarCollapsed', 'true');
    }
}

function expandSidebar(elements: SidebarElements): void {
    const { sidebar, mainContent, sidebarTexts, sidebarContents, sidebarSelect, sidebarBadges, toggleIcon } = elements;

    sidebar.style.width = `${SIDEBAR_EXPANDED_WIDTH}px`;
    sidebar.setAttribute('data-sidebar-collapsed', 'false');

    if (!isMobile()) {
        mainContent.style.marginLeft = `${SIDEBAR_EXPANDED_WIDTH}px`;
    }

    // Show text and content with smooth transition
    sidebarTexts.forEach(el => {
        el.style.opacity = '1';
        el.style.maxWidth = 'none';
        el.style.overflow = 'visible';
    });

    sidebarContents.forEach(el => {
        el.style.opacity = '1';
        el.style.maxHeight = 'none';
        el.style.overflow = 'visible';
    });

    if (sidebarSelect) {
        sidebarSelect.style.opacity = '1';
        sidebarSelect.style.pointerEvents = 'auto';
    }

    sidebarBadges.forEach(el => {
        el.style.opacity = '1';
    });

    // Rotate icon
    if (toggleIcon) {
        toggleIcon.classList.remove('fa-chevron-right');
        toggleIcon.classList.add('fa-chevron-left');
    }

    // Save state (only on desktop)
    if (!isMobile()) {
        localStorage.setItem('sidebarCollapsed', 'false');
    }
}

function toggleSidebar(elements: SidebarElements): void {
    const currentWidth = elements.sidebar.offsetWidth;
    const isCurrentlyCollapsed = currentWidth <= SIDEBAR_COLLAPSED_WIDTH + 10; // 10px tolerance

    if (isCurrentlyCollapsed) {
        expandSidebar(elements);
    } else {
        collapseSidebar(elements);
    }
}

function initSidebar(): void {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('main-content');
    const toggleButton = document.getElementById('sidebar-collapse-toggle');
    const toggleIcon = document.getElementById('sidebar-toggle-icon');

    if (!sidebar || !mainContent) return;

    const elements: SidebarElements = {
        sidebar,
        mainContent,
        toggleButton,
        toggleIcon,
        sidebarTexts: document.querySelectorAll('.sidebar-text'),
        sidebarContents: document.querySelectorAll('.sidebar-content'),
        sidebarSelect: document.getElementById('global-fund-select') as HTMLSelectElement | null,
        sidebarBadges: document.querySelectorAll('.sidebar-badge'),
    };

    if (isMobile()) {
        // Mobile: Let Flowbite drawer handle it completely
        sidebar.style.width = '';
        sidebar.style.marginLeft = '';
        mainContent.style.marginLeft = '0';
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
                sidebar.style.width = '';
                sidebar.style.marginLeft = '';
                mainContent.style.marginLeft = '0';
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

    // Handle orientation change on mobile
    window.addEventListener('orientationchange', () => {
        setTimeout(() => {
            if (isMobile()) {
                sidebar.style.width = '';
                sidebar.style.marginLeft = '';
                mainContent.style.marginLeft = '0';
            }
        }, 200);
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

        if (data.scheduler_running) {
            badge.textContent = 'Running';
            badge.className = 'inline-flex items-center justify-center px-2 py-1 ms-3 text-xs font-medium text-green-800 bg-green-100 rounded-full dark:bg-green-900 dark:text-green-300 sidebar-badge';
        } else {
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

    // Poll every 30s when visible (performance optimization), pause when hidden
    setInterval(() => {
        if (!document.hidden) {
            updateSchedulerBadge();
        }
    }, 30000);

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
