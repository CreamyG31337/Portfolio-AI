/**
 * Dashboard V2 - Matches dashboard.html template
 * Uses /api/dashboard/* endpoints
 * 
 * ⚠️ IMPORTANT: This is a TypeScript SOURCE file.
 * - Edit this file: web_dashboard/src/js/dashboard.ts
 * - Compiled output: web_dashboard/static/js/dashboard.js (auto-generated)
 * - DO NOT edit the compiled .js file - it will be overwritten on build
 * - Run `npm run build:ts` to compile changes
 * 
 * See web_dashboard/src/js/README.md for development guidelines.
 */

// Make this a module
export { };

// Global types are declared in globals.d.ts

console.log('[Dashboard] dashboard.ts file loaded and executing...');

// Type definitions
interface DashboardSummary {
    total_value: number;
    cash_balance: number;
    day_change: number;
    day_change_pct: number;
    unrealized_pnl: number;
    unrealized_pnl_pct: number;
    display_currency: string;
    thesis?: {
        title: string;
        overview: string;
        pillars?: Array<{
            name: string;
            allocation: string;
            thesis: string;
        }>;
    };
    investor_count?: number;
    holdings_count?: number;
    exchange_rates?: {
        USD_CAD: number;
        CAD_USD: number;
    };
    from_cache: boolean;
    processing_time: number;
}

interface DividendData {
    metrics: {
        total_dividends: number;
        total_us_tax: number;
        largest_dividend: number;
        largest_ticker: string;
        reinvested_shares: number;
        payout_events: number;
    };
    log: Array<{
        date: string;
        ticker: string;
        company_name?: string;
        type: string;
        amount: number;
        tax: number;
    }>;
    currency: string;
}

interface PerformanceChartData {
    data: any[]; // Plotly trace data
    layout: any; // Plotly layout
}

interface AllocationChartData {
    data: any[]; // Plotly trace data
    layout: any; // Plotly layout
}

interface PnlChartData {
    data: any[]; // Plotly trace data
    layout: any; // Plotly layout
}

interface IndividualHoldingsChartData {
    data: any[]; // Plotly trace data
    layout: any; // Plotly layout
    metadata?: {
        num_stocks: number;
        sectors: string[];
        industries: string[];
        days: number;
        filter: string;
    };
}

interface HoldingsData {
    data: Array<{
        ticker: string;
        name: string;
        sector: string;
        quantity: number;
        price: number;
        value: number;
        day_change: number;
        day_change_pct: number;
        total_return: number;
        total_return_pct: number;
    }>;
}

interface ActivityData {
    data: Array<{
        date: string;
        ticker: string;
        action: 'BUY' | 'SELL';
        shares: number;
        price: number;
        amount: number;
    }>;
}

interface MoverItem {
    ticker: string;
    company_name?: string;
    daily_pnl_pct?: number;
    daily_pnl?: number;
    five_day_pnl_pct?: number;
    five_day_pnl?: number;
    total_return_pct?: number;
    total_pnl?: number;
    current_price?: number;
    market_value?: number;
}

interface MoversData {
    gainers: MoverItem[];
    losers: MoverItem[];
    display_currency: string;
    processing_time: number;
}

interface ExchangeRateData {
    current_rate: number | null;
    rate_label: string;
    rate_help: string;
    inverse: boolean;
    chart: AllocationChartData | null;
}

interface Fund {
    name: string;
}

// Global state
const state = {
    currentFund: typeof window !== 'undefined' && window.INITIAL_FUND ? window.INITIAL_FUND : '',
    timeRange: 'ALL' as '1M' | '3M' | '6M' | '1Y' | 'ALL',
    useSolidLines: false, // Solid lines checkbox state
    charts: {} as Record<string, any>, // Charts now use Plotly (no longer ApexCharts)
    gridApi: null as any, // AG Grid API
    // Individual holdings state
    showIndividualHoldings: false,
    individualHoldingsDays: 7,
    individualHoldingsFilter: 'all',
    // Exchange rate state
    inverseExchangeRate: false
};

// Initialize theme sync for charts
function initThemeSync(): void {
    // Import chart theme utilities
    const themeManager = (window as Window & { themeManager?: { addListener: (callback: (theme: string) => void) => void } }).themeManager;
    if (themeManager) {
        themeManager.addListener((theme: string) => {
            console.log('[Dashboard] Theme changed, refreshing charts...', { theme });
            // Update AG Grid theme
            updateGridTheme();
            // Re-fetch charts with new theme
            fetchPerformanceChart().catch(err => console.error('[Dashboard] Error refreshing performance chart on theme change:', err));
            fetchSectorChart().catch(err => console.error('[Dashboard] Error refreshing sector chart on theme change:', err));
            fetchCurrencyChart().catch(err => console.error('[Dashboard] Error refreshing currency chart on theme change:', err));
            fetchExchangeRateData().catch(err => console.error('[Dashboard] Error refreshing exchange rate chart on theme change:', err));
            // Refresh individual holdings chart if visible
            if (state.showIndividualHoldings) {
                fetchIndividualHoldingsChart().catch(err => console.error('[Dashboard] Error refreshing individual holdings chart on theme change:', err));
            }
        });
    } else {
        console.warn('[Dashboard] ThemeManager not found. Chart theme synchronization disabled.');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', (): void => {
    console.log('[Dashboard] DOMContentLoaded event fired, initializing dashboard...');

    // Init components
    initTimeDisplay();
    initFundSelector();
    initTimeRangeControls();
    initSolidLinesCheckbox();
    initIndividualHoldingsControls();
    initExchangeRateControls();
    initGrid(); // Initialize empty grid
    initThemeSync(); // Initialize theme synchronization

    // Fetch Data
    refreshDashboard();

    // Auto-refresh every 60s (optional)
    // setInterval(refreshDashboard, 60000);
});

// --- Initialization Functions ---

async function initTimeDisplay(): Promise<void> {
    const el = document.getElementById('last-updated-text');
    if (!el) return;

    try {
        // Fetch latest timestamp from API (same as Streamlit)
        const fund = state.currentFund || '';
        const response = await fetch(`/api/dashboard/latest-timestamp?fund=${encodeURIComponent(fund)}`);

        if (response.ok) {
            const data = await response.json();
            if (data.timestamp) {
                // Parse ISO timestamp and format in local timezone with long format
                const timestamp = new Date(data.timestamp);
                const formatted = timestamp.toLocaleString('en-US', {
                    weekday: 'long',
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: true
                });
                el.textContent = `Last updated: ${formatted}`;
                return;
            }
        }
    } catch (error) {
        console.warn('[Dashboard] Failed to fetch latest timestamp:', error);
    }

    // Fallback to current time if API fails
    const now = new Date();
    const formatted = now.toLocaleString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
    });
    el.textContent = 'Last updated: ' + formatted;
}

async function initFundSelector(): Promise<void> {
    const selector = document.getElementById('global-fund-select') as HTMLSelectElement | null;
    console.log('[Dashboard] Initializing navigation fund selector...', {
        found: !!selector,
        current_state_fund: state.currentFund
    });

    if (!selector) {
        console.warn('[Dashboard] Global fund selector not found in sidebar!');
        return;
    }

    // Set initial state from selector if not already set
    if (!state.currentFund) {
        state.currentFund = selector.value;
        console.log('[Dashboard] Initial state set from selector value:', state.currentFund);
    } else {
        // Sync selector with state (e.g. if set from INITIAL_FUND)
        if (selector.value !== state.currentFund) {
            console.log('[Dashboard] Syncing selector value to state:', state.currentFund);
            selector.value = state.currentFund;
        }
    }

    // Listen for changes
    selector.addEventListener('change', (e: Event): void => {
        const target = e.target as HTMLSelectElement;
        state.currentFund = target.value;
        console.log('[Dashboard] Global fund changed to:', state.currentFund);
        refreshDashboard();
    });
}

function initTimeRangeControls(): void {
    document.querySelectorAll('.range-btn').forEach(btn => {
        btn.addEventListener('click', (e: Event): void => {
            const target = e.target as HTMLElement;

            // Update UI
            document.querySelectorAll('.range-btn').forEach(b => {
                b.classList.remove('active', 'ring-2', 'ring-blue-700', 'text-blue-700', 'z-10');
                b.classList.add('text-gray-900', 'hover:text-blue-700', 'dark:text-white');
            });
            target.classList.add('active', 'ring-2', 'ring-blue-700', 'text-blue-700', 'z-10');

            // Update State
            const range = target.dataset.range as '1M' | '3M' | '6M' | '1Y' | 'ALL';
            if (range) {
                state.timeRange = range;
                console.log('[Dashboard] Time range changed to:', state.timeRange);

                // Refresh Charts only
                fetchPerformanceChart();
            }
        });
    });
}

function initSolidLinesCheckbox(): void {
    const checkbox = document.getElementById('use-solid-lines') as HTMLInputElement | null;
    if (!checkbox) {
        console.warn('[Dashboard] Solid lines checkbox not found');
        return;
    }

    // Set initial state
    checkbox.checked = state.useSolidLines;

    // Listen for changes
    checkbox.addEventListener('change', (): void => {
        state.useSolidLines = checkbox.checked;
        console.log('[Dashboard] Solid lines changed to:', state.useSolidLines);
        // Refresh performance chart only
        fetchPerformanceChart();
        // Also refresh individual holdings if visible
        if (state.showIndividualHoldings) {
            fetchIndividualHoldingsChart();
        }
    });
}

function initIndividualHoldingsControls(): void {
    const showCheckbox = document.getElementById('show-individual-holdings') as HTMLInputElement | null;
    const container = document.getElementById('individual-holdings-container');
    const rangeButtons = document.querySelectorAll('.individual-range-btn');
    const filterSelect = document.getElementById('individual-stock-filter') as HTMLSelectElement | null;

    if (!showCheckbox || !container) {
        console.warn('[Dashboard] Individual holdings controls not found');
        return;
    }

    // Toggle container visibility
    showCheckbox.addEventListener('change', (): void => {
        state.showIndividualHoldings = showCheckbox.checked;
        if (showCheckbox.checked) {
            container.classList.remove('hidden');
            // Fetch chart if fund is selected (not "All")
            if (state.currentFund && state.currentFund.toLowerCase() !== 'all') {
                fetchIndividualHoldingsChart();
            } else {
                const chartEl = document.getElementById('individual-holdings-chart');
                if (chartEl) {
                    chartEl.innerHTML = '<div class="text-center text-gray-500 py-8">Select a specific fund to view individual stock performance</div>';
                }
            }
        } else {
            container.classList.add('hidden');
        }
    });

    // Date range buttons
    rangeButtons.forEach(btn => {
        btn.addEventListener('click', (e): void => {
            const target = e.currentTarget as HTMLElement;
            const days = parseInt(target.dataset.days || '7', 10);

            // Update visual state
            rangeButtons.forEach(b => {
                b.classList.remove('bg-blue-600', 'text-white');
                b.classList.add('bg-gray-100', 'dark:bg-gray-700', 'text-gray-700', 'dark:text-gray-300');
            });
            target.classList.remove('bg-gray-100', 'dark:bg-gray-700', 'text-gray-700', 'dark:text-gray-300');
            target.classList.add('bg-blue-600', 'text-white');

            // Update state and fetch
            state.individualHoldingsDays = days;
            if (state.showIndividualHoldings && state.currentFund && state.currentFund.toLowerCase() !== 'all') {
                fetchIndividualHoldingsChart();
            }
        });
    });

    // Filter dropdown
    if (filterSelect) {
        filterSelect.addEventListener('change', (): void => {
            state.individualHoldingsFilter = filterSelect.value;
            if (state.showIndividualHoldings && state.currentFund && state.currentFund.toLowerCase() !== 'all') {
                fetchIndividualHoldingsChart();
            }
        });
    }
}

function initExchangeRateControls(): void {
    const checkbox = document.getElementById('inverse-exchange-rate') as HTMLInputElement | null;

    if (!checkbox) {
        console.warn('[Dashboard] Exchange rate toggle not found');
        return;
    }

    // Set initial state from localStorage if available
    const savedPref = localStorage.getItem('inverse_exchange_rate');
    if (savedPref !== null) {
        state.inverseExchangeRate = savedPref === 'true';
        checkbox.checked = state.inverseExchangeRate;
    }

    // Listen for changes
    checkbox.addEventListener('change', (): void => {
        state.inverseExchangeRate = checkbox.checked;
        // Save preference to localStorage
        localStorage.setItem('inverse_exchange_rate', String(checkbox.checked));
        // Refresh exchange rate display
        fetchExchangeRateData();
    });
}

// Update AG Grid theme class based on current theme
// Ticker cell renderer - makes ticker clickable
interface AgGridCellRendererParams {
    value: string | null;
    data?: any;
}

interface AgGridCellRenderer {
    init(params: AgGridCellRendererParams): void;
    getGui(): HTMLElement;
}

class TickerCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        if (params.value && params.value !== 'N/A') {
            this.eGui.innerText = params.value;
            this.eGui.style.color = '#1f77b4';
            this.eGui.style.fontWeight = 'bold';
            this.eGui.style.textDecoration = 'underline';
            this.eGui.style.cursor = 'pointer';
            this.eGui.addEventListener('click', function (e: Event) {
                e.stopPropagation();
                const ticker = params.value;
                if (ticker && ticker !== 'N/A') {
                    window.location.href = `/v2/ticker?ticker=${encodeURIComponent(ticker)}`;
                }
            });
        } else {
            this.eGui.innerText = params.value || 'N/A';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

function updateGridTheme(): void {
    const gridEl = document.getElementById('holdings-grid');
    if (!gridEl) {
        return;
    }

    // Detect current theme
    const htmlElement = document.documentElement;
    const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
    let effectiveTheme: string = 'light';

    if (dataTheme === 'dark' || dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
        effectiveTheme = 'dark';
    } else if (dataTheme === 'light') {
        effectiveTheme = 'light';
    } else if (dataTheme === 'system') {
        // For 'system', check if page is actually in dark mode via CSS
        const bodyBg = window.getComputedStyle(document.body).backgroundColor;
        const isDark = bodyBg && (
            bodyBg.includes('rgb(31, 41, 55)') ||  // --bg-primary dark
            bodyBg.includes('rgb(17, 24, 39)') ||  // --bg-secondary dark  
            bodyBg.includes('rgb(55, 65, 81)')     // --bg-tertiary dark
        );
        effectiveTheme = isDark ? 'dark' : 'light';
    }

    // Update AG Grid theme class
    gridEl.classList.remove('ag-theme-alpine', 'ag-theme-alpine-dark');
    if (effectiveTheme === 'dark') {
        gridEl.classList.add('ag-theme-alpine-dark');
    } else {
        gridEl.classList.add('ag-theme-alpine');
    }
}

function initGrid(): void {
    console.log('[Dashboard] Initializing AG Grid...');
    const gridEl = document.getElementById('holdings-grid');
    if (!gridEl) {
        console.warn('[Dashboard] Holdings grid element not found');
        return;
    }

    // Apply theme before initializing
    updateGridTheme();

    const columnDefs = [
        { field: 'ticker', headerName: 'Ticker', width: 100, minWidth: 80, maxWidth: 120, pinned: 'left', cellRenderer: TickerCellRenderer },
        { field: 'name', headerName: 'Company', flex: 1.5, minWidth: 150, maxWidth: 300 },
        { field: 'sector', headerName: 'Sector', flex: 1, minWidth: 100, maxWidth: 200 },
        { field: 'opened', headerName: 'Opened', width: 100, minWidth: 80, maxWidth: 120 },
        { field: 'shares', headerName: 'Shares', flex: 0.8, minWidth: 90, maxWidth: 130, type: 'numericColumn', valueFormatter: (params: any) => (params.value || 0).toFixed(2) },
        { field: 'avg_price', headerName: 'Avg Price', flex: 0.9, minWidth: 90, maxWidth: 140, type: 'numericColumn', valueFormatter: (params: any) => formatMoney(params.value) },
        { field: 'price', headerName: 'Current', flex: 0.9, minWidth: 90, maxWidth: 140, type: 'numericColumn', valueFormatter: (params: any) => formatMoney(params.value) },
        { field: 'value', headerName: 'Value', flex: 1, minWidth: 100, maxWidth: 160, type: 'numericColumn', valueFormatter: (params: any) => formatMoney(params.value) },
        {
            field: 'total_return',
            headerName: 'Total P&L',
            flex: 1.2,
            minWidth: 130,
            maxWidth: 180,
            type: 'numericColumn',
            valueFormatter: (params: any) => {
                const val = params.value || 0;
                const pct = params.data?.total_return_pct || 0;
                const sign = val >= 0 ? '+' : '';
                return `${formatMoney(val)} ${sign}${pct.toFixed(1)}%`;
            },
            cellStyle: (params: any) => {
                const val = params.value || 0;
                if (val > 0) return { color: '#10b981', fontWeight: 'bold', textAlign: 'right' };
                if (val < 0) return { color: '#ef4444', fontWeight: 'bold', textAlign: 'right' };
                return { textAlign: 'right' };
            }
        },
        {
            field: 'day_change',
            headerName: '1-Day P&L',
            flex: 1.2,
            minWidth: 130,
            maxWidth: 180,
            type: 'numericColumn',
            valueFormatter: (params: any) => {
                const val = params.value || 0;
                const pct = params.data?.day_change_pct || 0;
                const sign = val >= 0 ? '+' : '';
                return `${formatMoney(val)} ${sign}${pct.toFixed(1)}%`;
            },
            cellStyle: (params: any) => {
                const val = params.value || 0;
                if (val > 0) return { color: '#10b981', fontWeight: 'bold', textAlign: 'right' };
                if (val < 0) return { color: '#ef4444', fontWeight: 'bold', textAlign: 'right' };
                return { textAlign: 'right' };
            }
        },
        {
            field: 'five_day_pnl',
            headerName: '5-Day P&L',
            flex: 1.2,
            minWidth: 130,
            maxWidth: 180,
            type: 'numericColumn',
            valueFormatter: (params: any) => {
                const val = params.value || 0;
                const pct = params.data?.five_day_pnl_pct || 0;
                const sign = val >= 0 ? '+' : '';
                return `${formatMoney(val)} ${sign}${pct.toFixed(1)}%`;
            },
            cellStyle: (params: any) => {
                const val = params.value || 0;
                if (val > 0) return { color: '#10b981', fontWeight: 'bold', textAlign: 'right' };
                if (val < 0) return { color: '#ef4444', fontWeight: 'bold', textAlign: 'right' };
                return { textAlign: 'right' };
            }
        },
        { field: 'weight', headerName: 'Weight', flex: 0.6, minWidth: 70, maxWidth: 100, type: 'numericColumn', valueFormatter: (params: any) => (params.value || 0).toFixed(1) + '%' }
    ];

    const gridOptions = {
        columnDefs: columnDefs,
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true
        },
        rowData: [],
        animateRows: true,
        // Default sort by weight descending (matching console app)
        sortModel: [
            { field: 'weight', sort: 'desc' }
        ]
    };

    // agGrid is loaded from CDN and available globally
    if (typeof (window as any).agGrid === 'undefined') {
        console.error('[Dashboard] AG Grid not loaded');
        return;
    }

    const agGrid = (window as any).agGrid;

    // Debug: Log what's available in agGrid
    console.log('[Dashboard] AG Grid object check:', {
        agGrid_available: !!agGrid,
        agGrid_type: typeof agGrid,
        has_createGrid: typeof agGrid.createGrid === 'function',
        has_Grid: typeof agGrid.Grid !== 'undefined',
        agGrid_keys: agGrid ? Object.keys(agGrid).slice(0, 20) : []
    });

    // AG Grid v31+ recommends createGrid() which returns the API directly
    // Check for createGrid first (v31+)
    if (typeof agGrid.createGrid === 'function') {
        console.log('[Dashboard] createGrid() is available, attempting to use it...');
        try {
            const gridApi = agGrid.createGrid(gridEl, gridOptions);
            if (gridApi && typeof gridApi.setRowData === 'function') {
                state.gridApi = gridApi;
                console.log('[Dashboard] AG Grid initialized with createGrid()', {
                    has_api: !!state.gridApi,
                    has_setRowData: typeof state.gridApi.setRowData === 'function',
                    gridApi_type: typeof state.gridApi,
                    gridApi_keys: state.gridApi ? Object.keys(state.gridApi).slice(0, 10) : []
                });
                return; // Success, exit early
            } else {
                console.error('[Dashboard] createGrid() returned invalid API:', {
                    gridApi,
                    has_setRowData: gridApi && typeof gridApi.setRowData === 'function'
                });
            }
        } catch (createError) {
            console.error('[Dashboard] Error creating grid with createGrid():', createError);
        }
    }

    // Fallback to deprecated new Grid() constructor (v30 and earlier)
    // This is the pattern used in congress_trades.ts which works
    if (agGrid.Grid) {
        console.log('[Dashboard] createGrid() not available or failed, falling back to new Grid()...');
        try {
            const gridInstance = new agGrid.Grid(gridEl, gridOptions);
            console.log('[Dashboard] Grid instance created:', {
                gridInstance,
                has_api: !!gridInstance.api,
                api_type: typeof gridInstance.api,
                api_keys: gridInstance.api ? Object.keys(gridInstance.api).slice(0, 10) : []
            });

            // In v30, the API is on gridInstance.api
            // In v31, createGrid returns the API directly
            if (gridInstance && gridInstance.api) {
                state.gridApi = gridInstance.api;
                console.log('[Dashboard] AG Grid initialized with new Grid() (deprecated)', {
                    has_api: !!state.gridApi,
                    has_setRowData: typeof state.gridApi.setRowData === 'function',
                    warning: 'Using deprecated new Grid() - consider upgrading to createGrid()'
                });
            } else {
                // Try waiting a bit for the API to be available (sometimes it's set asynchronously)
                setTimeout(() => {
                    if (gridInstance && gridInstance.api) {
                        state.gridApi = gridInstance.api;
                        console.log('[Dashboard] Grid API available after delay:', {
                            has_api: !!state.gridApi,
                            has_setRowData: typeof state.gridApi.setRowData === 'function'
                        });
                    } else {
                        console.error('[Dashboard] Grid instance created but API still not available after delay:', {
                            gridInstance,
                            has_api: gridInstance && !!gridInstance.api,
                            gridInstance_keys: gridInstance ? Object.keys(gridInstance) : []
                        });
                    }
                }, 100);
            }
        } catch (gridError) {
            console.error('[Dashboard] Error creating grid with new Grid():', gridError);
        }
    } else {
        console.error('[Dashboard] AG Grid API not found', {
            agGrid_available: typeof agGrid !== 'undefined',
            agGrid_keys: agGrid ? Object.keys(agGrid) : [],
            has_createGrid: typeof agGrid.createGrid === 'function',
            has_Grid: typeof agGrid.Grid !== 'undefined'
        });
    }
}

async function refreshDashboard(): Promise<void> {
    console.log('[Dashboard] Starting dashboard refresh...', {
        fund: state.currentFund,
        timeRange: state.timeRange,
        timestamp: new Date().toISOString()
    });

    // Hide any previous errors
    const errorContainer = document.getElementById('dashboard-error-container');
    if (errorContainer) {
        errorContainer.classList.add('hidden');
    }

    const startTime = performance.now();

    try {
        await Promise.all([
            fetchSummary(),
            fetchPerformanceChart(),
            fetchSectorChart(),
            fetchCurrencyChart(),
            fetchExchangeRateData(),
            loadPnlChart(state.currentFund),
            fetchMovers(),
            fetchHoldings(),
            fetchActivity(),
            fetchDividends()
        ]);

        // Refresh individual holdings chart if visible
        if (state.showIndividualHoldings) {
            await fetchIndividualHoldingsChart();
        }

        const duration = performance.now() - startTime;
        console.log('[Dashboard] Dashboard refresh completed successfully', {
            duration: `${duration.toFixed(2)}ms`,
            timestamp: new Date().toISOString()
        });

        // Update Time
        await initTimeDisplay();
    } catch (error) {
        const duration = performance.now() - startTime;
        console.error('[Dashboard] Error refreshing dashboard:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : undefined,
            duration: `${duration.toFixed(2)}ms`,
            timestamp: new Date().toISOString()
        });
        showDashboardError(error);
    }
}

function showDashboardError(error: unknown): void {
    const errorContainer = document.getElementById('dashboard-error-container');
    const errorMessage = document.getElementById('dashboard-error-message');

    if (errorContainer && errorMessage) {
        const errorText = error instanceof Error ? error.message : String(error);
        const errorStack = error instanceof Error && error.stack ? `<pre class="mt-2 text-xs overflow-auto">${error.stack}</pre>` : '';

        errorMessage.innerHTML = `<p>${errorText}</p>${errorStack}`;
        errorContainer.classList.remove('hidden');
    }
}

// --- Spinner Helpers ---

function showSpinner(spinnerId: string): void {
    let spinner = document.getElementById(spinnerId);
    if (!spinner) {
        // Spinner doesn't exist (might have been removed by Plotly), create it
        const chartEl = document.getElementById(spinnerId.replace('-spinner', ''));
        if (chartEl) {
            spinner = document.createElement('div');
            spinner.id = spinnerId;
            if (spinnerId === 'sector-chart-spinner') {
                spinner.className = 'flex items-center justify-center h-full';
            } else {
                spinner.className = 'absolute inset-0 flex items-center justify-center bg-white dark:bg-gray-800 z-10';
            }
            spinner.innerHTML = '<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 dark:border-blue-400"></div>';
            chartEl.appendChild(spinner);
        } else {
            return; // Can't create spinner without parent element
        }
    }
    spinner.classList.remove('hidden');
}

function hideSpinner(spinnerId: string): void {
    const spinner = document.getElementById(spinnerId);
    if (spinner) {
        spinner.classList.add('hidden');
    }
}

// --- Data Fetching ---

async function fetchSummary(): Promise<void> {
    const url = `/api/dashboard/summary?fund=${encodeURIComponent(state.currentFund)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching summary...', { url, fund: state.currentFund });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Summary response received', {
            status: response.status,
            statusText: response.statusText,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`,
            url: url
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            console.error('[Dashboard] Summary API error:', {
                status: response.status,
                errorData: errorData,
                url: url
            });
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: DashboardSummary = await response.json();
        console.log('[Dashboard] Summary data received', {
            total_value: data.total_value,
            cash_balance: data.cash_balance,
            day_change: data.day_change,
            unrealized_pnl: data.unrealized_pnl,
            display_currency: data.display_currency,
            has_thesis: !!data.thesis,
            has_pillars: !!data.thesis?.pillars,
            investors: data.investor_count,
            holdings: data.holdings_count,
            rates: data.exchange_rates,
            processing_time: data.processing_time,
            from_cache: data.from_cache
        });

        // Update Metrics
        updateMetric('metric-total-value', data.total_value, data.display_currency, true);
        updateMetric('metric-cash', data.cash_balance, data.display_currency, true);

        updateChangeMetric('metric-day-change', 'metric-day-pct', data.day_change, data.day_change_pct, data.display_currency);
        updateChangeMetric('metric-total-pnl', 'metric-total-pnl-pct', data.unrealized_pnl, data.unrealized_pnl_pct, data.display_currency);

        const currencyEl = document.getElementById('metric-currency');
        if (currencyEl) {
            currencyEl.textContent = data.display_currency;
        }

        // Update Fund Stats & Rates
        if (data.investor_count !== undefined) {
            const investorContainer = document.getElementById('investor-metric-container');
            if (investorContainer) {
                // Hide Investors metric if count <= 1 (single-investor or no-investor funds)
                if (data.investor_count <= 1) {
                    investorContainer.classList.add('hidden');
                } else {
                    investorContainer.classList.remove('hidden');
                    updateMetric('metric-investors', data.investor_count, '', false);
                }
            }
        }
        if (data.holdings_count !== undefined) updateMetric('metric-holdings-count', data.holdings_count, '', false);
        if (data.exchange_rates) {
            updateMetric('metric-usd-cad', data.exchange_rates.USD_CAD, '', false); // Just number, no currency format
            // Format rates with 4 decimals
            const usdCadEl = document.getElementById('metric-usd-cad');
            if (usdCadEl) usdCadEl.textContent = data.exchange_rates.USD_CAD.toFixed(4);

            const cadUsdEl = document.getElementById('metric-cad-usd');
            if (cadUsdEl) cadUsdEl.textContent = data.exchange_rates.CAD_USD.toFixed(4);
        }

        // Update Thesis
        const thesisContainer = document.getElementById('thesis-container');
        if (data.thesis && data.thesis.title) {
            if (thesisContainer) {
                thesisContainer.classList.remove('hidden');
            }
            const titleEl = document.getElementById('thesis-title');
            const contentEl = document.getElementById('thesis-content');
            if (titleEl) titleEl.textContent = data.thesis.title;
            if (contentEl) {
                // Use marked.js if available, otherwise plain text
                if (typeof (window as any).marked !== 'undefined') {
                    contentEl.innerHTML = (window as any).marked.parse(data.thesis.overview || '');
                } else {
                    contentEl.textContent = data.thesis.overview || '';
                }
            }
            // Render Pillars
            if (data.thesis.pillars && data.thesis.pillars.length > 0) {
                renderPillars(data.thesis.pillars);
            }
        } else {
            if (thesisContainer) {
                thesisContainer.classList.add('hidden');
            }
        }

    } catch (error) {
        const duration = performance.now() - startTime;
        console.error('[Dashboard] Error fetching summary:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : undefined,
            url: url,
            fund: state.currentFund,
            duration: `${duration.toFixed(2)}ms`,
            timestamp: new Date().toISOString()
        });

        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        // Show error in metrics
        const totalValueEl = document.getElementById('metric-total-value');
        const dayChangeEl = document.getElementById('metric-day-change');
        const totalPnlEl = document.getElementById('metric-total-pnl');
        const cashEl = document.getElementById('metric-cash');

        if (totalValueEl) totalValueEl.textContent = 'Error';
        if (dayChangeEl) dayChangeEl.textContent = 'Error';
        if (totalPnlEl) totalPnlEl.textContent = 'Error';
        if (cashEl) cashEl.textContent = 'Error';

        // Show error in UI
        showDashboardError(new Error(`Failed to load summary: ${errorMsg}`));
        throw error; // Re-throw so refreshDashboard can catch it
    }
}

async function fetchPerformanceChart(): Promise<void> {
    // Show spinner
    showSpinner('performance-chart-spinner');

    // Detect actual theme from page (same as sector chart)
    const htmlElement = document.documentElement;
    const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
    let theme: string = 'light'; // default

    if (dataTheme === 'dark' || dataTheme === 'light' || dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
        theme = dataTheme;
    } else if (dataTheme === 'system') {
        // For 'system', check if page is actually in dark mode via CSS
        const bodyBg = window.getComputedStyle(document.body).backgroundColor;
        // Check for dark mode background colors
        const isDark = bodyBg && (
            bodyBg.includes('rgb(31, 41, 55)') ||  // --bg-primary dark
            bodyBg.includes('rgb(17, 24, 39)') ||  // --bg-secondary dark  
            bodyBg.includes('rgb(55, 65, 81)')     // --bg-tertiary dark
        );
        theme = isDark ? 'dark' : 'light';
    }

    // Match Streamlit: use_solid_lines parameter from checkbox
    const url = `/api/dashboard/charts/performance?fund=${encodeURIComponent(state.currentFund)}&range=${state.timeRange}&use_solid=${state.useSolidLines}&theme=${encodeURIComponent(theme)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching performance chart...', { url, fund: state.currentFund, range: state.timeRange, use_solid: state.useSolidLines });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Performance chart response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorMsg = errorData.error || errorData.message || `HTTP ${response.status}: ${response.statusText}`;
            console.error('[Dashboard] Performance chart API error:', {
                status: response.status,
                statusText: response.statusText,
                error: errorMsg,
                errorData: JSON.stringify(errorData),
                url: url
            });
            throw new Error(errorMsg);
        }

        const data: PerformanceChartData = await response.json();
        console.log('[Dashboard] Performance chart data received', {
            has_data: !!data.data,
            has_layout: !!data.layout,
            trace_count: data.data ? data.data.length : 0
        });

        renderPerformanceChart(data);
        hideSpinner('performance-chart-spinner');

    } catch (error) {
        hideSpinner('performance-chart-spinner');
        const duration = performance.now() - startTime;
        const errorMsg = error instanceof Error ? error.message : String(error);
        const errorStack = error instanceof Error ? error.stack : undefined;
        console.error('[Dashboard] Error fetching performance chart:', {
            error: errorMsg,
            stack: errorStack,
            url: url,
            duration: `${duration.toFixed(2)}ms`,
            errorObject: JSON.stringify(error, Object.getOwnPropertyNames(error))
        });
        const chartEl = document.getElementById('performance-chart');
        if (chartEl) {
            chartEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error loading chart: ${errorMsg}</p></div>`;
        }
    }
}

async function fetchSectorChart(): Promise<void> {
    // Show spinner
    showSpinner('sector-chart-spinner');

    // Detect actual theme from page (same as performance chart)
    const htmlElement = document.documentElement;
    const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
    let theme: string = 'light'; // default

    if (dataTheme === 'dark' || dataTheme === 'light' || dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
        theme = dataTheme;
    } else if (dataTheme === 'system') {
        // For 'system', check if page is actually in dark mode via CSS
        const bodyBg = window.getComputedStyle(document.body).backgroundColor;
        // Check for dark mode background colors
        const isDark = bodyBg && (
            bodyBg.includes('rgb(31, 41, 55)') ||  // --bg-primary dark
            bodyBg.includes('rgb(17, 24, 39)') ||  // --bg-secondary dark  
            bodyBg.includes('rgb(55, 65, 81)')     // --bg-tertiary dark
        );
        theme = isDark ? 'dark' : 'light';
    }

    const url = `/api/dashboard/charts/allocation?fund=${encodeURIComponent(state.currentFund)}&theme=${encodeURIComponent(theme)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching sector chart...', { url, fund: state.currentFund, theme });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Sector chart response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            console.error('[Dashboard] Sector chart API error:', {
                status: response.status,
                errorData: errorData,
                url: url
            });
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: AllocationChartData = await response.json();
        console.log('[Dashboard] Sector chart data received', {
            has_data: !!data.data,
            has_layout: !!data.layout,
            trace_count: data.data ? data.data.length : 0
        });

        renderSectorChart(data);

    } catch (error) {
        const duration = performance.now() - startTime;
        console.error('[Dashboard] Error fetching sector chart:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            url: url,
            duration: `${duration.toFixed(2)}ms`
        });
        const chartEl = document.getElementById('sector-chart');
        if (chartEl) {
            chartEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error loading sector chart: ${error instanceof Error ? error.message : 'Unknown error'}</p></div>`;
        }
    }
}

async function fetchHoldings(): Promise<void> {
    // Show spinner
    showSpinner('holdings-grid-spinner');

    const url = `/api/dashboard/holdings?fund=${encodeURIComponent(state.currentFund)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching holdings...', { url, fund: state.currentFund });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Holdings response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorMsg = errorData.error || errorData.message || `HTTP ${response.status}: ${response.statusText}`;
            console.error('[Dashboard] Holdings API error:', {
                status: response.status,
                statusText: response.statusText,
                error: errorMsg,
                errorData: JSON.stringify(errorData),
                url: url
            });
            throw new Error(errorMsg);
        }

        const data: HoldingsData = await response.json();
        const rowCount = data.data ? data.data.length : 0;
        console.log('[Dashboard] Holdings data received', {
            row_count: rowCount,
            has_grid_api: !!state.gridApi
        });

        if (state.gridApi && typeof state.gridApi.setRowData === 'function') {
            state.gridApi.setRowData(data.data || []);
            console.log('[Dashboard] Holdings grid updated with', rowCount, 'rows');
            // Auto-size columns to fit content better
            if (typeof state.gridApi.autoSizeColumns === 'function') {
                // Auto-size all columns except pinned ticker
                const allColumns = state.gridApi.getColumns();
                if (allColumns && allColumns.length > 0) {
                    const columnsToAutoSize = allColumns.filter((col: any) => col.getColId() !== 'ticker');
                    if (columnsToAutoSize.length > 0) {
                        state.gridApi.autoSizeColumns(columnsToAutoSize, false);
                    }
                }
            } else if (typeof state.gridApi.sizeColumnsToFit === 'function') {
                // Fallback to sizeColumnsToFit if autoSizeColumns is not available
                setTimeout(() => {
                    state.gridApi.sizeColumnsToFit();
                }, 100);
            }
        } else {
            console.error('[Dashboard] Grid API not available for updating holdings', {
                has_gridApi: !!state.gridApi,
                gridApi_type: typeof state.gridApi,
                has_setRowData: state.gridApi && typeof state.gridApi.setRowData === 'function',
                gridApi_keys: state.gridApi ? Object.keys(state.gridApi).slice(0, 10) : []
            });
            // Try to reinitialize the grid
            console.log('[Dashboard] Attempting to reinitialize grid...');
            initGrid();
            // Try again after a short delay
            setTimeout(() => {
                if (state.gridApi && typeof state.gridApi.setRowData === 'function') {
                    state.gridApi.setRowData(data.data || []);
                    console.log('[Dashboard] Holdings grid updated after reinitialization');
                    // Auto-size columns after reinitialization
                    if (typeof state.gridApi.autoSizeColumns === 'function') {
                        const allColumns = state.gridApi.getColumns();
                        if (allColumns && allColumns.length > 0) {
                            const columnsToAutoSize = allColumns.filter((col: any) => col.getColId() !== 'ticker');
                            if (columnsToAutoSize.length > 0) {
                                state.gridApi.autoSizeColumns(columnsToAutoSize, false);
                            }
                        }
                    } else if (typeof state.gridApi.sizeColumnsToFit === 'function') {
                        state.gridApi.sizeColumnsToFit();
                    }
                }
            }, 100);
        }
        hideSpinner('holdings-grid-spinner');

    } catch (error) {
        hideSpinner('holdings-grid-spinner');
        const duration = performance.now() - startTime;
        const errorMsg = error instanceof Error ? error.message : String(error);
        const errorStack = error instanceof Error ? error.stack : undefined;
        console.error('[Dashboard] Error fetching holdings:', {
            error: errorMsg,
            stack: errorStack,
            url: url,
            duration: `${duration.toFixed(2)}ms`,
            errorObject: JSON.stringify(error, Object.getOwnPropertyNames(error))
        });
        const gridEl = document.getElementById('holdings-grid');
        if (gridEl) {
            gridEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error loading holdings: ${errorMsg}</p></div>`;
        }
    }
}

async function fetchActivity(): Promise<void> {
    // Show spinner
    showSpinner('activity-table-spinner');

    const url = `/api/dashboard/activity?fund=${encodeURIComponent(state.currentFund)}&limit=100`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching activity...', { url, fund: state.currentFund });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Activity response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            console.error('[Dashboard] Activity API error:', {
                status: response.status,
                errorData: errorData,
                url: url
            });
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: ActivityData = await response.json();
        const activityCount = data.data ? data.data.length : 0;
        console.log('[Dashboard] Activity data received', {
            activity_count: activityCount
        });

        const tbody = document.getElementById('activity-table-body');
        if (!tbody) {
            console.warn('[Dashboard] Activity table body not found');
            return;
        }

        tbody.innerHTML = '';

        if (!data.data || data.data.length === 0) {
            tbody.innerHTML = '<tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700"><td colspan="6" class="px-6 py-4 text-center text-gray-500">No recent activity</td></tr>';
        } else {
            data.data.forEach(row => {
                const tr = document.createElement('tr');
                tr.className = 'bg-white border-b dark:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600';

                const isBuy = row.action === 'BUY';
                const actionBadge = isBuy
                    ? '<span class="bg-green-100 text-green-800 text-xs font-medium px-2.5 py-0.5 rounded dark:bg-green-900 dark:text-green-300">BUY</span>'
                    : '<span class="bg-red-100 text-red-800 text-xs font-medium px-2.5 py-0.5 rounded dark:bg-red-900 dark:text-red-300">SELL</span>';

                tr.innerHTML = `
                     <td class="px-6 py-4 whitespace-nowrap">${row.date}</td>
                     <td class="px-6 py-4 font-bold text-blue-600 dark:text-blue-400">
                         <a href="/v2/ticker?ticker=${row.ticker}" class="hover:underline">${row.ticker}</a>
                     </td>
                     <td class="px-6 py-4">${actionBadge}</td>
                     <td class="px-6 py-4 text-right">${row.shares}</td>
                     <td class="px-6 py-4 text-right format-currency">${formatMoney(row.price)}</td>
                     <td class="px-6 py-4 text-right format-currency font-medium">${formatMoney(row.amount || (row.shares * row.price))}</td>
                `;
                tbody.appendChild(tr);
            });
        }
        hideSpinner('activity-table-spinner');

    } catch (error) {
        hideSpinner('activity-table-spinner');
        const duration = performance.now() - startTime;
        console.error('[Dashboard] Error fetching activity:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            url: url,
            duration: `${duration.toFixed(2)}ms`
        });
        const tableBody = document.getElementById('activity-table-body');
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="6" class="text-center text-red-500 py-4">Error loading activity: ${error instanceof Error ? error.message : 'Unknown error'}</td></tr>`;
        }
    }
}

async function fetchMovers(): Promise<void> {
    showSpinner('gainers-spinner');
    showSpinner('losers-spinner');

    const url = `/api/dashboard/movers?fund=${encodeURIComponent(state.currentFund)}&limit=10`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching movers...', { url, fund: state.currentFund });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Movers response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            console.error('[Dashboard] Movers API error:', {
                status: response.status,
                errorData: errorData,
                url: url
            });
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: MoversData = await response.json();
        console.log('[Dashboard] Movers data received', {
            gainers_count: data.gainers ? data.gainers.length : 0,
            losers_count: data.losers ? data.losers.length : 0
        });

        renderMovers(data);
        hideSpinner('gainers-spinner');
        hideSpinner('losers-spinner');

    } catch (error) {
        hideSpinner('gainers-spinner');
        hideSpinner('losers-spinner');
        const duration = performance.now() - startTime;
        console.error('[Dashboard] Error fetching movers:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            url: url,
            duration: `${duration.toFixed(2)}ms`
        });
        const gainersBody = document.getElementById('gainers-table-body');
        const losersBody = document.getElementById('losers-table-body');
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        if (gainersBody) {
            gainersBody.innerHTML = `<tr><td colspan="4" class="text-center text-red-500 py-4">Error: ${errorMsg}</td></tr>`;
        }
        if (losersBody) {
            losersBody.innerHTML = `<tr><td colspan="4" class="text-center text-red-500 py-4">Error: ${errorMsg}</td></tr>`;
        }
    }
}

function renderPillars(pillars: Array<{ name: string; allocation: string; thesis: string; }>): void {
    const container = document.getElementById('thesis-pillars');
    if (!container) return;

    container.innerHTML = '';
    container.classList.remove('hidden');

    pillars.forEach(pillar => {
        const div = document.createElement('div');
        div.className = 'flex flex-col gap-2';

        // Parse markdown for thesis text if available
        let thesisHtml = pillar.thesis || '';
        if (typeof (window as any).marked !== 'undefined') {
            thesisHtml = (window as any).marked.parse(thesisHtml);
        }

        div.innerHTML = `
            <div class="font-bold text-gray-900 dark:text-white border-b border-gray-100 dark:border-gray-700 pb-1 mb-1 flex justify-between">
                <span>${pillar.name}</span>
                <span class="text-xs font-normal text-gray-500 bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded">${pillar.allocation || 'N/A'}</span>
            </div>
            <div class="text-sm text-gray-600 dark:text-gray-400 prose dark:prose-invert max-w-none text-xs">
                ${thesisHtml}
            </div>
        `;
        container.appendChild(div);
    });
}

async function fetchDividends(): Promise<void> {
    const url = `/api/dashboard/dividends?fund=${encodeURIComponent(state.currentFund)}`;
    console.log('[Dashboard] Fetching dividends...', { url });

    try {
        const response = await fetch(url, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: DividendData = await response.json();

        renderDividends(data);
    } catch (error) {
        console.error('[Dashboard] Error fetching dividends:', error);
        // Set values to error state
        ['div-total', 'div-tax', 'div-largest', 'div-reinvested', 'div-events'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = 'Error';
        });
    }
}

function renderDividends(data: DividendData): void {
    const currency = data.currency || 'USD';

    // Update Metrics
    const fmt = (val: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: currency }).format(val);

    updateMetricText('div-total', fmt(data.metrics.total_dividends));
    updateMetricText('div-tax', fmt(data.metrics.total_us_tax));
    updateMetricText('div-largest', fmt(data.metrics.largest_dividend));
    updateMetricText('div-reinvested', data.metrics.reinvested_shares.toFixed(4));
    updateMetricText('div-events', data.metrics.payout_events.toString());

    const largestTickerEl = document.getElementById('div-largest-ticker');
    if (largestTickerEl) largestTickerEl.textContent = data.metrics.largest_ticker;

    // Update Log Table
    const tbody = document.getElementById('dividend-log-body');
    if (tbody) {
        tbody.innerHTML = '';
        if (data.log.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-2 text-center text-gray-500">No dividend history</td></tr>';
        } else {
            data.log.forEach(row => {
                const tr = document.createElement('tr');
                tr.className = 'bg-white border-b dark:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600';
                tr.innerHTML = `
                    <td class="px-4 py-2 font-medium text-gray-900 dark:text-white whitespace-nowrap">${row.date}</td>
                    <td class="px-4 py-2 text-blue-600 dark:text-blue-400 font-bold">${row.ticker}</td>
                    <td class="px-4 py-2 text-gray-700 dark:text-gray-300">${row.company_name || ''}</td>
                    <td class="px-4 py-2">
                        <span class="px-2 py-0.5 rounded text-xs font-medium ${row.type === 'DRIP' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'}">
                            ${row.type}
                        </span>
                    </td>
                    <td class="px-4 py-2 text-right font-medium text-green-600 dark:text-green-400">${fmt(row.amount)}</td>
                    <td class="px-4 py-2 text-right text-gray-500">${fmt(row.tax)}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    }
}

function updateMetricText(id: string, text: string): void {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

async function fetchCurrencyChart(): Promise<void> {
    showSpinner('currency-chart-spinner');

    // Theme logic (same as other charts)
    const htmlElement = document.documentElement;
    const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
    let theme: string = 'light';
    if (dataTheme === 'dark' || dataTheme === 'light' || dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
        theme = dataTheme;
    } else if (dataTheme === 'system') {
        const bodyBg = window.getComputedStyle(document.body).backgroundColor;
        const isDark = bodyBg && (bodyBg.includes('rgb(31, 41, 55)') || bodyBg.includes('rgb(17, 24, 39)') || bodyBg.includes('rgb(55, 65, 81)'));
        theme = isDark ? 'dark' : 'light';
    }

    const url = `/api/dashboard/charts/currency?fund=${encodeURIComponent(state.currentFund)}&theme=${encodeURIComponent(theme)}`;
    console.log('[Dashboard] Fetching currency chart...', { url });

    try {
        const response = await fetch(url, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data: AllocationChartData = await response.json();
        renderCurrencyChart(data);
    } catch (error) {
        console.error('[Dashboard] Error fetching currency chart:', error);
        const chartEl = document.getElementById('currency-chart');
        if (chartEl) chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>Error loading chart</p></div>';
    } finally {
        hideSpinner('currency-chart-spinner');
    }
}

function renderCurrencyChart(data: AllocationChartData): void {
    const chartEl = document.getElementById('currency-chart');
    if (!chartEl) return;

    const Plotly = (window as any).Plotly;
    if (!Plotly) return;

    const layout = { ...data.layout };
    const containerHeight = chartEl.offsetHeight || 350;
    layout.height = containerHeight;
    layout.autosize = true;
    layout.margin = { l: 20, r: 20, t: 30, b: 20 };

    try {
        Plotly.newPlot('currency-chart', data.data, layout, {
            responsive: true,
            displayModeBar: false
        });

        // Add resize handler
        if (!(window as any).__currencyChartResizeHandler) {
            const resizeHandler = () => {
                if (document.getElementById('currency-chart')) {
                    Plotly.Plots.resize('currency-chart');
                }
            };
            (window as any).__currencyChartResizeHandler = resizeHandler;
            window.addEventListener('resize', resizeHandler);
        }
    } catch (error) {
        console.error('[Dashboard] Error rendering currency chart:', error);
    }
}

async function fetchExchangeRateData(): Promise<void> {
    showSpinner('exchange-rate-chart-spinner');

    // Theme logic
    const htmlElement = document.documentElement;
    const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
    let theme: string = 'light';
    if (dataTheme === 'dark' || dataTheme === 'light' || dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
        theme = dataTheme;
    } else if (dataTheme === 'system') {
        const bodyBg = window.getComputedStyle(document.body).backgroundColor;
        const isDark = bodyBg && (bodyBg.includes('rgb(31, 41, 55)') || bodyBg.includes('rgb(17, 24, 39)') || bodyBg.includes('rgb(55, 65, 81)'));
        theme = isDark ? 'dark' : 'light';
    }

    const url = `/api/dashboard/exchange-rate?inverse=${state.inverseExchangeRate}&theme=${encodeURIComponent(theme)}`;
    console.log('[Dashboard] Fetching exchange rate data...', { url });

    try {
        const response = await fetch(url, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data: ExchangeRateData = await response.json();
        renderExchangeRateData(data);
    } catch (error) {
        console.error('[Dashboard] Error fetching exchange rate data:', error);
        const valueEl = document.getElementById('exchange-rate-value');
        if (valueEl) valueEl.textContent = '--';
    } finally {
        hideSpinner('exchange-rate-chart-spinner');
    }
}

function renderExchangeRateData(data: ExchangeRateData): void {
    // Update metric display
    const labelEl = document.getElementById('exchange-rate-label');
    const valueEl = document.getElementById('exchange-rate-value');
    const helpEl = document.getElementById('exchange-rate-help');

    if (labelEl) labelEl.textContent = data.rate_label;
    if (valueEl) valueEl.textContent = data.current_rate !== null ? data.current_rate.toFixed(4) : '--';
    if (helpEl) helpEl.textContent = data.rate_help;

    // Render historical chart
    if (data.chart) {
        const chartEl = document.getElementById('exchange-rate-chart');
        if (!chartEl) return;

        const Plotly = (window as any).Plotly;
        if (!Plotly) return;

        const layout = { ...data.chart.layout };
        layout.height = 200;
        layout.autosize = true;

        try {
            Plotly.newPlot('exchange-rate-chart', data.chart.data, layout, {
                responsive: true,
                displayModeBar: false
            });

            // Add resize handler
            if (!(window as any).__exchangeRateChartResizeHandler) {
                const resizeHandler = () => {
                    if (document.getElementById('exchange-rate-chart')) {
                        Plotly.Plots.resize('exchange-rate-chart');
                    }
                };
                (window as any).__exchangeRateChartResizeHandler = resizeHandler;
                window.addEventListener('resize', resizeHandler);
            }
        } catch (error) {
            console.error('[Dashboard] Error rendering exchange rate chart:', error);
        }
    }
}

const MOVERS_COLUMN_COUNT = 10;

function renderMovers(data: MoversData): void {
    const gainersBody = document.getElementById('gainers-table-body');
    const losersBody = document.getElementById('losers-table-body');

    const formatPct = (val: number | undefined | null, forcePlus: boolean = false) => {
        if (val == null) return '--';
        const sign = forcePlus && val > 0 ? '+' : '';
        return `${sign}${val.toFixed(2)}%`;
    };

    const formatPnl = (val: number | undefined | null, currency: string, forcePlus: boolean = false) => {
        if (val == null) return '--';
        const sign = forcePlus && val > 0 ? '+' : '';
        return `${sign}${formatMoney(val, currency)}`;
    };

    const getPnlColor = (val: number | null | undefined) => {
        if (val == null) return '';
        return val > 0
            ? 'text-green-600 dark:text-green-400 font-bold'
            : (val < 0 ? 'text-red-600 dark:text-red-400 font-bold' : '');
    };

    // For 5-day, matching the original styling which didn't have bold by default
    const getFiveDayColor = (val: number | null | undefined) => {
        if (val == null) return '';
        return val > 0
            ? 'text-green-600 dark:text-green-400'
            : (val < 0 ? 'text-red-600 dark:text-red-400' : '');
    };

    const renderTable = (tbody: HTMLElement, items: MoverItem[], isGainer: boolean) => {
        tbody.innerHTML = '';
        if (!items || items.length === 0) {
            tbody.innerHTML = `<tr class="bg-white dark:bg-gray-800"><td colspan="${MOVERS_COLUMN_COUNT}" class="px-4 py-4 text-center text-gray-500">No ${isGainer ? 'gainers' : 'losers'} to display</td></tr>`;
            return;
        }

        const dayColorClass = isGainer
            ? 'text-green-600 dark:text-green-400 font-medium'
            : 'text-red-600 dark:text-red-400 font-medium';

        items.forEach(item => {
            const tr = document.createElement('tr');
            tr.className = 'bg-white border-b dark:bg-gray-800 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600';

            tr.innerHTML = `
                <td class="px-4 py-3 font-bold text-blue-600 dark:text-blue-400">
                    <a href="/v2/ticker?ticker=${item.ticker}" class="hover:underline">${item.ticker}</a>
                </td>
                <td class="px-4 py-3 truncate max-w-[150px]" title="${item.company_name || item.ticker}">${item.company_name || item.ticker}</td>
                <td class="px-4 py-3 text-right ${dayColorClass}">${formatPct(item.daily_pnl_pct, isGainer)}</td>
                <td class="px-4 py-3 text-right ${dayColorClass}">${formatPnl(item.daily_pnl, data.display_currency, isGainer)}</td>
                <td class="px-4 py-3 text-right ${getFiveDayColor(item.five_day_pnl_pct)}">${formatPct(item.five_day_pnl_pct, true)}</td>
                <td class="px-4 py-3 text-right ${getFiveDayColor(item.five_day_pnl)}">${formatPnl(item.five_day_pnl, data.display_currency, true)}</td>
                <td class="px-4 py-3 text-right ${getPnlColor(item.total_return_pct)}">${formatPct(item.total_return_pct, true)}</td>
                <td class="px-4 py-3 text-right ${getPnlColor(item.total_pnl)}">${formatPnl(item.total_pnl, data.display_currency, true)}</td>
                <td class="px-4 py-3 text-right">${formatMoney(item.current_price || 0, data.display_currency)}</td>
                <td class="px-4 py-3 text-right font-medium">${formatMoney(item.market_value || 0, data.display_currency)}</td>
            `;
            tbody.appendChild(tr);
        });
    };

    if (gainersBody) renderTable(gainersBody, data.gainers, true);
    if (losersBody) renderTable(losersBody, data.losers, false);
}

// --- Rendering Helpers ---

function formatMoney(val: number, currency?: string): string {
    if (typeof val !== 'number' || isNaN(val)) return '--';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency || 'USD' }).format(val);
}

function updateMetric(id: string, value: number, currency: string, isCurrency: boolean): void {
    const el = document.getElementById(id);
    if (el) {
        if (isCurrency) {
            // Format number with commas and 2 decimal places, without currency symbol
            el.textContent = new Intl.NumberFormat('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }).format(value);
        } else {
            el.textContent = String(value);
        }
    }
}

function updateChangeMetric(valId: string, pctId: string, change: number, pct: number, currency: string): void {
    const valEl = document.getElementById(valId);
    const pctEl = document.getElementById(pctId);

    if (valEl) {
        // Format number with $ sign, without currency code prefix
        const formatted = new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD', // Use USD to get $ sign, then we'll replace if needed
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(change);
        valEl.textContent = (change >= 0 ? '+' : '') + formatted;
    }
    if (pctEl) {
        pctEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';

        // Color classes
        pctEl.className = `text-sm font-medium px-2 py-0.5 rounded ${change >= 0
            ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300'
            : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300'}`;

        if (valEl) {
            valEl.className = `text-2xl font-bold ${change >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`;
        }
    }
}

function renderPerformanceChart(data: PerformanceChartData): void {
    // Clear any existing chart
    const chartEl = document.getElementById('performance-chart');
    if (!chartEl) {
        console.warn('[Dashboard] Performance chart element not found');
        return;
    }

    // Clear previous content
    chartEl.innerHTML = '';

    if (!data || !data.data || !data.layout) {
        chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>No performance data available</p></div>';
        return;
    }

    // Render with Plotly (same as ticker_details.ts)
    const Plotly = (window as any).Plotly;
    if (!Plotly) {
        console.error('[Dashboard] Plotly not loaded');
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error: Plotly library not loaded</p></div>';
        return;
    }

    // Match Streamlit exactly: use_container_width=True means use full width and keep original height
    // Streamlit doesn't modify the layout at all - it just passes the figure through
    // Use the layout directly without any modifications
    try {
        Plotly.newPlot('performance-chart', data.data, data.layout, {
            responsive: true,  // Equivalent to use_container_width=True in Streamlit
            displayModeBar: true,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d']
        });
        console.log('[Dashboard] Performance chart rendered with Plotly');
    } catch (error) {
        console.error('[Dashboard] Error rendering Plotly chart:', error);
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error rendering chart</p></div>';
    }
}

async function fetchIndividualHoldingsChart(): Promise<void> {
    // Check if fund is selected
    if (!state.currentFund || state.currentFund.toLowerCase() === 'all') {
        const chartEl = document.getElementById('individual-holdings-chart');
        if (chartEl) {
            chartEl.innerHTML = '<div class="text-center text-gray-500 py-8">Select a specific fund to view individual stock performance</div>';
        }
        return;
    }

    // Show spinner
    showSpinner('individual-holdings-spinner');

    // Detect theme
    const htmlElement = document.documentElement;
    const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
    let theme: string = 'light';

    if (dataTheme === 'dark' || dataTheme === 'light' || dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
        theme = dataTheme;
    } else if (dataTheme === 'system') {
        const bodyBg = window.getComputedStyle(document.body).backgroundColor;
        const isDark = bodyBg && (
            bodyBg.includes('rgb(31, 41, 55)') ||
            bodyBg.includes('rgb(17, 24, 39)') ||
            bodyBg.includes('rgb(55, 65, 81)')
        );
        theme = isDark ? 'dark' : 'light';
    }

    const url = `/api/dashboard/charts/individual-holdings?fund=${encodeURIComponent(state.currentFund)}&days=${state.individualHoldingsDays}&filter=${encodeURIComponent(state.individualHoldingsFilter)}&use_solid=${state.useSolidLines}&theme=${encodeURIComponent(theme)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching individual holdings chart...', { url, fund: state.currentFund, days: state.individualHoldingsDays, filter: state.individualHoldingsFilter });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Individual holdings chart response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorMsg = errorData.error || errorData.message || `HTTP ${response.status}: ${response.statusText}`;
            throw new Error(errorMsg);
        }

        const data: IndividualHoldingsChartData = await response.json();
        renderIndividualHoldingsChart(data);
        hideSpinner('individual-holdings-spinner');

    } catch (error) {
        hideSpinner('individual-holdings-spinner');
        const errorMsg = error instanceof Error ? error.message : String(error);
        console.error('[Dashboard] Error fetching individual holdings chart:', errorMsg);
        const chartEl = document.getElementById('individual-holdings-chart');
        if (chartEl) {
            chartEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error loading chart: ${errorMsg}</p></div>`;
        }
    }
}

function renderIndividualHoldingsChart(data: IndividualHoldingsChartData): void {
    const chartEl = document.getElementById('individual-holdings-chart');
    if (!chartEl) {
        console.warn('[Dashboard] Individual holdings chart element not found');
        return;
    }

    // Clear previous content
    chartEl.innerHTML = '';

    if (!data || !data.data || !data.layout) {
        chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>No holdings data available</p></div>';
        return;
    }

    // Render with Plotly
    const Plotly = (window as any).Plotly;
    if (!Plotly) {
        console.error('[Dashboard] Plotly not loaded');
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error: Plotly library not loaded</p></div>';
        return;
    }

    try {
        Plotly.newPlot('individual-holdings-chart', data.data, data.layout, {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d']
        });
        console.log('[Dashboard] Individual holdings chart rendered with Plotly');

        // Update stock count display
        if (data.metadata) {
            const countEl = document.getElementById('individual-stock-count');
            if (countEl) {
                const daysText = data.metadata.days === 0 ? 'all time' : `last ${data.metadata.days} days`;
                countEl.textContent = `Showing ${data.metadata.num_stocks} stocks over ${daysText}`;
            }

            // Update filter dropdown with dynamic sector/industry options
            updateIndividualHoldingsFilters(data.metadata.sectors, data.metadata.industries);
        }
    } catch (error) {
        console.error('[Dashboard] Error rendering individual holdings chart:', error);
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error rendering chart</p></div>';
    }
}

function updateIndividualHoldingsFilters(sectors: string[], industries: string[]): void {
    const filterSelect = document.getElementById('individual-stock-filter') as HTMLSelectElement | null;
    if (!filterSelect) return;

    // Get current value to preserve selection
    const currentValue = filterSelect.value;

    // Remove any existing sector/industry options
    const existingOptions = Array.from(filterSelect.options);
    let foundSeparator = false;
    for (const opt of existingOptions) {
        if (opt.value.startsWith('---') || opt.value.startsWith('sector:') || opt.value.startsWith('industry:')) {
            opt.remove();
            foundSeparator = true;
        }
    }

    // Add sector options if available
    if (sectors.length > 0) {
        const sectorSep = document.createElement('option');
        sectorSep.value = '---sectors---';
        sectorSep.textContent = '--- By Sector ---';
        sectorSep.disabled = true;
        filterSelect.appendChild(sectorSep);

        for (const sector of sectors) {
            const opt = document.createElement('option');
            opt.value = `sector:${sector}`;
            opt.textContent = `Sector: ${sector}`;
            filterSelect.appendChild(opt);
        }
    }

    // Add industry options if available
    if (industries.length > 0) {
        const industrySep = document.createElement('option');
        industrySep.value = '---industries---';
        industrySep.textContent = '--- By Industry ---';
        industrySep.disabled = true;
        filterSelect.appendChild(industrySep);

        for (const industry of industries) {
            const opt = document.createElement('option');
            opt.value = `industry:${industry}`;
            opt.textContent = `Industry: ${industry}`;
            filterSelect.appendChild(opt);
        }
    }

    // Restore selection if still valid
    if (currentValue && Array.from(filterSelect.options).some(o => o.value === currentValue)) {
        filterSelect.value = currentValue;
    }
}

function renderSectorChart(data: AllocationChartData): void {
    // Clear any existing chart
    const chartEl = document.getElementById('sector-chart');
    if (!chartEl) {
        console.warn('[Dashboard] Sector chart element not found');
        return;
    }

    // Hide spinner before rendering (Plotly will replace content)
    hideSpinner('sector-chart-spinner');

    if (!data || !data.data || !data.layout) {
        chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>No sector data available</p></div>';
        return;
    }

    // Render with Plotly (same as performance chart)
    const Plotly = (window as any).Plotly;
    if (!Plotly) {
        console.error('[Dashboard] Plotly not loaded');
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error: Plotly library not loaded</p></div>';
        return;
    }

    // Update layout height to match container and ensure centered margins
    const layout = { ...data.layout };

    // Use fixed height of 700px to match HTML container height
    // Disable autosize to prevent Plotly from shrinking the chart in flex container
    const containerHeight = 700;
    layout.height = containerHeight;
    layout.autosize = false;

    // Ensure proper margins - use reasonable values for centering
    if (!layout.margin) {
        layout.margin = { l: 20, r: 20, t: 40, b: 40 };
    } else {
        // Ensure left and right margins are equal for centering
        layout.margin.l = 20;
        layout.margin.r = 20;
        // Use reasonable top/bottom margins
        layout.margin.t = Math.min(60, layout.margin.t || 40);
        layout.margin.b = Math.min(80, layout.margin.b || 40);
    }

    try {
        Plotly.newPlot('sector-chart', data.data, layout, {
            responsive: false,  // Disable responsive to respect fixed height of 700px
            displayModeBar: true,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d']
        });
        console.log('[Dashboard] Sector chart rendered with Plotly');

        // Add resize handler to redraw chart when window resizes (only once)
        // Use relayout instead of resize to maintain fixed height of 700px
        if (!(window as any).__sectorChartResizeHandler) {
            const resizeHandler = () => {
                const Plotly = (window as any).Plotly;
                const el = document.getElementById('sector-chart');
                if (Plotly && el) {
                    // Relayout with fixed height to prevent flex container shrinking
                    Plotly.relayout('sector-chart', { height: 700 });
                }
            };
            (window as any).__sectorChartResizeHandler = resizeHandler;
            window.addEventListener('resize', resizeHandler);
        }

    } catch (error) {
        console.error('[Dashboard] Error rendering Plotly sector chart:', error);
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error rendering chart</p></div>';
    }
}

function renderPnlChart(data: PnlChartData): void {
    // Clear any existing chart
    const chartEl = document.getElementById('pnl-chart');
    if (!chartEl) {
        console.warn('[Dashboard] P&L chart element not found');
        return;
    }

    // Hide spinner before rendering (Plotly will replace content)
    hideSpinner('pnl-chart-spinner');

    if (!data || !data.data || !data.layout) {
        chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>No P&L data available</p></div>';
        return;
    }

    // Render with Plotly (same as sector chart)
    const Plotly = (window as any).Plotly;
    if (!Plotly) {
        console.error('[Dashboard] Plotly not loaded');
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error: Plotly library not loaded</p></div>';
        return;
    }

    // Update layout height to match container
    const layout = { ...data.layout };

    // Get actual container height or use default
    const containerHeight = chartEl.offsetHeight || 500;
    layout.height = containerHeight;
    layout.autosize = true;

    // Ensure proper margins - increase left margin for y-axis labels
    if (!layout.margin) {
        layout.margin = { l: 80, r: 20, t: 50, b: 100 };
    } else {
        // Use larger left margin to prevent y-axis labels from being cut off
        layout.margin.l = Math.max(80, layout.margin.l || 80);
        layout.margin.r = Math.max(20, layout.margin.r || 20);
        // Increase bottom margin to prevent legend cutoff
        layout.margin.b = Math.max(100, layout.margin.b || 100);
    }

    try {
        Plotly.newPlot('pnl-chart', data.data, layout, {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d']
        });
        console.log('[Dashboard] P&L chart rendered with Plotly');

        // Add resize handler to redraw chart when window resizes (only once)
        if (!(window as any).__pnlChartResizeHandler) {
            const resizeHandler = () => {
                const Plotly = (window as any).Plotly;
                if (Plotly && document.getElementById('pnl-chart')) {
                    Plotly.Plots.resize('pnl-chart');
                }
            };
            (window as any).__pnlChartResizeHandler = resizeHandler;
            window.addEventListener('resize', resizeHandler);
        }

    } catch (error) {
        console.error('[Dashboard] Error rendering Plotly P&L chart:', error);
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error rendering chart</p></div>';
    }
}

async function loadPnlChart(fund: string): Promise<void> {
    // Detect actual theme from page (same as other charts)
    const htmlElement = document.documentElement;
    const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
    let theme: string = 'light'; // default

    if (dataTheme === 'dark' || dataTheme === 'light' || dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
        theme = dataTheme;
    } else if (dataTheme === 'system') {
        // For 'system', check if page is actually in dark mode via CSS
        const bodyBg = window.getComputedStyle(document.body).backgroundColor;
        // Check for dark mode background colors
        const isDark = bodyBg && (
            bodyBg.includes('rgb(31, 41, 55)') ||  // --bg-primary dark
            bodyBg.includes('rgb(17, 24, 39)') ||  // --bg-secondary dark  
            bodyBg.includes('rgb(55, 65, 81)')     // --bg-tertiary dark
        );
        theme = isDark ? 'dark' : 'light';
    }

    const startTime = performance.now();
    const url = `/api/dashboard/charts/pnl?fund=${encodeURIComponent(fund || '')}&theme=${encodeURIComponent(theme)}`;

    console.log('[Dashboard] Loading P&L chart:', { fund, theme, url });

    try {
        showSpinner('pnl-chart-spinner');

        const response = await fetch(url, {
            method: 'GET',
            credentials: 'include',
            headers: {
                'Accept': 'application/json'
            }
        });

        const duration = performance.now() - startTime;
        console.log('[Dashboard] P&L chart API response', {
            status: response.status,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            console.error('[Dashboard] P&L chart API error:', {
                status: response.status,
                errorData: errorData,
                url: url
            });
            throw new Error(errorData.error || `HTTP ${response.status}: ${response.statusText}`);
        }

        const data: PnlChartData = await response.json();
        console.log('[Dashboard] P&L chart data received');

        renderPnlChart(data);

    } catch (error) {
        hideSpinner('pnl-chart-spinner');
        const duration = performance.now() - startTime;
        console.error('[Dashboard] Error fetching P&L chart:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            url: url,
            duration: `${duration.toFixed(2)}ms`
        });
        const chartEl = document.getElementById('pnl-chart');
        if (chartEl) {
            const errorMsg = error instanceof Error ? error.message : 'Unknown error';
            chartEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error: ${errorMsg}</p></div>`;
        }
    }
}

// Expose refreshDashboard globally for template onclick handlers
if (typeof window !== 'undefined') {
    (window as any).refreshDashboard = refreshDashboard;
    console.log('[Dashboard] refreshDashboard function exposed globally');
}
