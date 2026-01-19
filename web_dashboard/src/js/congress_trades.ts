/**
 * Congress Trades TypeScript
 * Handles AgGrid initialization and interactions
 */

// AgGrid types (using any for now - can install @types/ag-grid-community later)
interface AgGridParams {
    value: string | null;
    data?: CongressTrade;
    column?: {
        colId: string;
    };
    node?: AgGridNode;
}

interface AgGridNode {
    setDataValue(key: string, value: string): void;
    setSelected(selected: boolean): void;
}

interface AgGridApi {
    getSelectedRows(): CongressTrade[];
    getSelectedNodes(): AgGridNode[];
    sizeColumnsToFit(): void;
    addEventListener(event: string, callback: () => void): void;
    setGridOption(key: string, value: any): void;
    showLoadingOverlay(): void;
    hideOverlay(): void;
    applyTransaction(transaction: { add: CongressTrade[] }): void;
}

interface AgGridColumnApi {
    // Column API methods if needed
}

interface AgGridGrid {
    api: AgGridApi;
    columnApi: AgGridColumnApi;
}

interface AgGridGlobal {
    Grid: new (element: HTMLElement, options: AgGridOptions) => AgGridGrid;
}

interface AgGridOptions {
    columnDefs: AgGridColumnDef[];
    rowData: CongressTrade[];
    defaultColDef?: Partial<AgGridColumnDef>;
    rowSelection?: any;
    // suppressRowClickSelection deprecated
    enableRangeSelection?: boolean;
    enableCellTextSelection?: boolean;
    ensureDomOrder?: boolean;
    domLayout?: string;
    pagination?: boolean;
    paginationPageSize?: number;
    paginationPageSizeSelector?: number[];
    onCellClicked?: (params: AgGridParams) => void;
    onSelectionChanged?: () => void;
    animateRows?: boolean;
    suppressCellFocus?: boolean;
    overlayLoadingTemplate?: string;
}

interface AgGridColumnDef {
    field: string;
    headerName: string;
    width?: number;
    minWidth?: number;
    flex?: number;
    pinned?: string;
    cellRenderer?: any;
    sortable?: boolean;
    filter?: boolean;
    hide?: boolean;
    editable?: boolean;
    resizable?: boolean;
    tooltipValueGetter?: (params: AgGridParams) => string;
    cellStyle?: Record<string, string>;
}

interface AgGridCellRendererParams {
    value: string | null;
    data?: CongressTrade;
}

interface AgGridCellRenderer {
    init(params: AgGridCellRendererParams): void;
    getGui(): HTMLElement;
}

// Congress Trade data interface
interface CongressTrade {
    Ticker?: string;
    Company?: string;
    Politician?: string;
    Chamber?: string;
    Party?: string;
    State?: string;
    Date?: string;
    Type?: string;
    Amount?: string;
    Score?: string;
    Owner?: string;
    'AI Reasoning'?: string;
    _tooltip?: string;
    _click_action?: string;
    _full_reasoning?: string;
    _trade_id?: number;
}

interface CongressTradeStats {
    total_trades: number;
    analyzed_count: number;
    house_count: number;
    senate_count: number;
    purchase_count: number;
    sale_count: number;
    unique_tickers_count: number;
    high_risk_count: number;
    most_active_display: string;
}

interface CongressTradeApiResponse {
    trades: CongressTrade[];
    next_offset?: number;
    has_more: boolean;
    total?: number;
    error?: string;
}

// Global AgGrid reference
declare global {
    interface Window {
        agGrid: AgGridGlobal;
    }
}

let gridApi: AgGridApi | null = null;
let gridColumnApi: AgGridColumnApi | null = null;

// Ticker cell renderer - makes ticker clickable
class TickerCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement; // Definitely assigned in init()

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
                    window.location.href = `/ticker?ticker=${encodeURIComponent(ticker)}`;
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

// Party cell renderer - colors Democrat (blue) and Republican (red)
class PartyCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        this.eGui.innerText = value || 'N/A';
        
        // Color based on party
        const partyLower = value.toLowerCase();
        if (partyLower.includes('democrat') || partyLower === 'd') {
            this.eGui.style.color = '#2563eb'; // Blue
            this.eGui.style.fontWeight = '500';
        } else if (partyLower.includes('republican') || partyLower === 'r') {
            this.eGui.style.color = '#dc2626'; // Red
            this.eGui.style.fontWeight = '500';
        } else if (partyLower.includes('independent') || partyLower === 'i') {
            this.eGui.style.color = '#7c3aed'; // Purple
            this.eGui.style.fontWeight = '500';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Type cell renderer - colors Purchase/Buy (green) and Sale/Sell (red)
class TypeCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        this.eGui.innerText = value || 'N/A';
        
        // Color based on transaction type
        const typeLower = value.toLowerCase();
        if (typeLower === 'purchase' || typeLower === 'buy') {
            this.eGui.style.color = '#16a34a'; // Green
            this.eGui.style.fontWeight = '500';
        } else if (typeLower === 'sale' || typeLower === 'sell') {
            this.eGui.style.color = '#dc2626'; // Red
            this.eGui.style.fontWeight = '500';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Global click handler - manages navigation vs selection
function onCellClicked(params: AgGridParams): void {
    if (params.data) {
        // Determine action based on column
        let action = 'details';
        if (params.column?.colId === 'Ticker' && params.value && params.value !== 'N/A') {
            action = 'navigate';
            // Navigate immediately for ticker clicks
            const ticker = params.value;
            window.location.href = `/ticker?ticker=${encodeURIComponent(ticker)}`;
            return;
        }

        // Update hidden column
        if (params.node) {
            params.node.setDataValue('_click_action', action);

            // Select the row to trigger selection event
            if (gridApi) {
                const selectedNodes = gridApi.getSelectedNodes();
                selectedNodes.forEach(function (node: AgGridNode) {
                    node.setSelected(false);
                });
                params.node.setSelected(true);
            }
        }
    }
}

// Handle row selection - show AI reasoning and update analyze button
function onSelectionChanged(): void {
    if (!gridApi) return;

    const selectedRows = gridApi.getSelectedRows();
    const analyzeButton = document.getElementById('analyze-selected-btn') as HTMLButtonElement | null;
    const selectedCountEl = document.getElementById('selected-count');
    
    // Update analyze button visibility and count
    if (analyzeButton && selectedCountEl) {
        if (selectedRows && selectedRows.length > 0) {
            analyzeButton.classList.remove('hidden');
            selectedCountEl.textContent = selectedRows.length.toString();
            analyzeButton.disabled = false;
        } else {
            analyzeButton.classList.add('hidden');
            selectedCountEl.textContent = '0';
        }
    }
    
    if (selectedRows && selectedRows.length > 0) {
        // Show reasoning for first selected row (single row view)
        if (selectedRows.length === 1) {
            const selectedRow = selectedRows[0];
            // Get full reasoning - check both _full_reasoning and _tooltip fields
            const fullReasoning = (selectedRow._full_reasoning && selectedRow._full_reasoning.trim()) ||
                (selectedRow._tooltip && selectedRow._tooltip.trim()) ||
                '';

            if (fullReasoning) {
                // Show reasoning section
                const reasoningSection = document.getElementById('ai-reasoning-section');
                if (reasoningSection) {
                    reasoningSection.classList.remove('hidden');

                    // Populate fields
                    const tickerEl = document.getElementById('reasoning-ticker');
                    const companyEl = document.getElementById('reasoning-company');
                    const politicianEl = document.getElementById('reasoning-politician');
                    const dateEl = document.getElementById('reasoning-date');
                    const typeEl = document.getElementById('reasoning-type');
                    const scoreEl = document.getElementById('reasoning-score');
                    const textEl = document.getElementById('reasoning-text');

                    if (tickerEl) tickerEl.textContent = selectedRow.Ticker || '-';
                    if (companyEl) companyEl.textContent = selectedRow.Company || '-';
                    if (politicianEl) politicianEl.textContent = selectedRow.Politician || '-';
                    if (dateEl) dateEl.textContent = selectedRow.Date || '-';
                    if (typeEl) typeEl.textContent = selectedRow.Type || '-';
                    if (scoreEl) scoreEl.textContent = selectedRow.Score || '-';
                    if (textEl) textEl.textContent = fullReasoning;

                    // Scroll to reasoning section
                    reasoningSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            }
        } else {
            // Multiple rows selected - hide single row reasoning
            const reasoningSection = document.getElementById('ai-reasoning-section');
            if (reasoningSection) {
                reasoningSection.classList.add('hidden');
            }
        }
    } else {
        // Hide reasoning section if no selection
        const reasoningSection = document.getElementById('ai-reasoning-section');
        if (reasoningSection) {
            reasoningSection.classList.add('hidden');
        }
    }
}

// Analyze selected trades
async function analyzeSelectedTrades(): Promise<void> {
    if (!gridApi) return;
    
    const selectedRows = gridApi.getSelectedRows();
    if (!selectedRows || selectedRows.length === 0) {
        alert('Please select at least one trade to analyze');
        return;
    }
    
    // Extract trade IDs from selected rows
    const tradeIds: number[] = [];
    for (const row of selectedRows) {
        if (row._trade_id && typeof row._trade_id === 'number') {
            tradeIds.push(row._trade_id);
        }
    }
    
    if (tradeIds.length === 0) {
        alert('Could not extract trade IDs from selected rows');
        return;
    }
    
    const analyzeButton = document.getElementById('analyze-selected-btn') as HTMLButtonElement | null;
    if (analyzeButton) {
        analyzeButton.disabled = true;
        analyzeButton.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Analyzing...';
    }
    
    try {
        const response = await fetch('/api/congress_trades/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ trade_ids: tradeIds })
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.error || 'Analysis failed');
        }
        
        // Show success message
        const message = result.message || `Successfully analyzed ${result.processed || tradeIds.length} trade(s)`;
        alert(`✅ ${message}`);
        
        // Refresh the page to show updated analysis
        window.location.reload();
        
    } catch (error) {
        console.error('Error analyzing trades:', error);
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        alert(`❌ Failed to analyze trades: ${errorMsg}`);
        
        if (analyzeButton) {
            analyzeButton.disabled = false;
            analyzeButton.innerHTML = '<i class="fas fa-brain mr-2"></i>Analyze Selected (<span id="selected-count">0</span>)';
        }
    }
}

export function initializeCongressTradesGrid(tradesData: CongressTrade[]): void {
    const gridDiv = document.querySelector('#congress-trades-grid') as HTMLElement | null;
    if (!gridDiv) {
        console.error('Congress trades grid container not found');
        return;
    }

    if (!window.agGrid) {
        console.error('AgGrid not loaded');
        return;
    }

    // Check if grid is already initialized
    if (gridDiv.getAttribute('data-initialized') === 'true') {
        if (gridApi) {
            gridApi.setGridOption('rowData', tradesData);
            return;
        }
        // Grid was marked initialized but gridApi is null - clear and recreate
        gridDiv.innerHTML = '';
        gridDiv.removeAttribute('data-initialized');
    }

    // Detect theme and apply appropriate AgGrid theme
    const htmlElement = document.documentElement;
    const theme = htmlElement.getAttribute('data-theme') || 'system';
    let isDark = false;

    if (theme === 'dark' || theme === 'midnight-tokyo' || theme === 'abyss') {
        isDark = true;
    } else if (theme === 'system') {
        // Check system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            isDark = true;
        }
    }

    // Update grid container class based on theme
    if (isDark) {
        gridDiv.classList.remove('ag-theme-alpine');
        gridDiv.classList.add('ag-theme-alpine-dark');
    } else {
        gridDiv.classList.remove('ag-theme-alpine-dark');
        gridDiv.classList.add('ag-theme-alpine');
    }

    // Column definitions
    const columnDefs: AgGridColumnDef[] = [
        {
            field: 'Ticker',
            headerName: 'Ticker',
            minWidth: 80,
            flex: 0.8,
            pinned: 'left',
            cellRenderer: TickerCellRenderer,
            sortable: true,
            filter: true
        },
        {
            field: 'Company',
            headerName: 'Company',
            minWidth: 150,
            flex: 2,
            sortable: true,
            filter: true
        },
        {
            field: 'Politician',
            headerName: 'Politician',
            minWidth: 150,
            flex: 1.8,
            sortable: true,
            filter: true
        },
        {
            field: 'Chamber',
            headerName: 'Chamber',
            minWidth: 90,
            flex: 0.9,
            sortable: true,
            filter: true
        },
        {
            field: 'Party',
            headerName: 'Party',
            minWidth: 80,
            flex: 0.8,
            sortable: true,
            filter: true,
            cellRenderer: PartyCellRenderer
        },
        {
            field: 'State',
            headerName: 'State',
            minWidth: 70,
            flex: 0.7,
            sortable: true,
            filter: true
        },
        {
            field: 'Date',
            headerName: 'Date',
            minWidth: 110,
            flex: 1.1,
            sortable: true,
            filter: true
        },
        {
            field: 'Type',
            headerName: 'Type',
            minWidth: 90,
            flex: 0.9,
            sortable: true,
            filter: true,
            cellRenderer: TypeCellRenderer
        },
        {
            field: 'Amount',
            headerName: 'Amount',
            minWidth: 120,
            flex: 1.2,
            sortable: true,
            filter: true
        },
        {
            field: 'Score',
            headerName: 'Score',
            minWidth: 100,
            flex: 1,
            sortable: true,
            filter: true
        },
        {
            field: 'Owner',
            headerName: 'Owner',
            minWidth: 100,
            flex: 1,
            sortable: true,
            filter: true
        },
        {
            field: 'AI Reasoning',
            headerName: 'AI Reasoning',
            minWidth: 200,
            flex: 3,
            sortable: true,
            filter: true,
            tooltipValueGetter: function (params: AgGridParams): string {
                return params.data?._tooltip || params.value || '';
            },
            cellStyle: {
                'white-space': 'nowrap',
                'overflow': 'hidden',
                'text-overflow': 'ellipsis'
            }
        },
        {
            field: '_tooltip',
            headerName: '_tooltip',
            hide: true
        },
        {
            field: '_click_action',
            headerName: '_click_action',
            hide: true
        },
        {
            field: '_full_reasoning',
            headerName: '_full_reasoning',
            hide: true
        }
    ];

    // Grid options
    const gridOptions: AgGridOptions = {
        columnDefs: columnDefs,
        rowData: tradesData,
        defaultColDef: {
            editable: false,
            sortable: true,
            filter: true,
            resizable: true
        },
        rowSelection: {
            mode: 'multiRow',
            checkboxes: true,
            enableClickSelection: true,
        },
        enableRangeSelection: true,
        enableCellTextSelection: true,
        ensureDomOrder: true,
        domLayout: 'normal',
        pagination: true,
        paginationPageSize: 100,
        paginationPageSizeSelector: [100, 250, 500, 1000],
        onCellClicked: onCellClicked,
        onSelectionChanged: onSelectionChanged,
        animateRows: true,
        suppressCellFocus: false,
        overlayLoadingTemplate: '<span class="ag-overlay-loading-center">Please wait while your rows are loading...</span>'
    };

    // Create grid
    const gridInstance = new window.agGrid.Grid(gridDiv, gridOptions);
    gridApi = gridInstance.api;
    gridColumnApi = gridInstance.columnApi;
    gridDiv.setAttribute('data-initialized', 'true');

    // Auto-size columns to fit container
    if (gridApi) {
        // Function to resize columns
        const resizeColumns = () => {
            if (gridApi) {
                // Fit all columns to available width
                gridApi.sizeColumnsToFit();
            }
        };

        // Wait for grid to be ready before auto-sizing
        gridApi.addEventListener('firstDataRendered', () => {
            resizeColumns();
        });

        // Also auto-size on window resize (with debounce for performance)
        let resizeTimeout: number | null = null;
        window.addEventListener('resize', () => {
            if (resizeTimeout) {
                clearTimeout(resizeTimeout);
            }
            resizeTimeout = window.setTimeout(() => {
                resizeColumns();
            }, 150);
        });

        // Initial resize after a short delay to ensure grid is fully rendered
        setTimeout(() => {
            resizeColumns();
        }, 100);
    }
}

// Statistics Accumulator
const statsAccumulator = {
    total_trades: 0,
    analyzed_count: 0,
    house_count: 0,
    senate_count: 0,
    purchase_count: 0,
    sale_count: 0,
    unique_tickers: new Set<string>(),
    high_risk_count: 0,
    politician_counts_31d: new Map<string, number>()
};

function calculateAndRenderStats(newTrades: CongressTrade[]): void {
    const thirtyOneDaysAgo = new Date();
    thirtyOneDaysAgo.setDate(thirtyOneDaysAgo.getDate() - 31);

    for (const trade of newTrades) {
        statsAccumulator.total_trades++;

        // Analyzed count (check for non-null Score that isn't '⚪ N/A')
        if (trade.Score && !trade.Score.includes('⚪')) {
            statsAccumulator.analyzed_count++;
        }

        // High Risk
        if (trade.Score && trade.Score.includes('🔴')) {
            statsAccumulator.high_risk_count++;
        }

        // Chamber
        if (trade.Chamber === 'House') statsAccumulator.house_count++;
        if (trade.Chamber === 'Senate') statsAccumulator.senate_count++;

        // Type
        if (trade.Type === 'Purchase') statsAccumulator.purchase_count++;
        if (trade.Type === 'Sale') statsAccumulator.sale_count++;

        // Unique Tickers
        if (trade.Ticker && trade.Ticker !== 'N/A') {
            statsAccumulator.unique_tickers.add(trade.Ticker);
        }

        // Most Active (31d)
        if (trade.Date && trade.Politician && trade.Politician !== 'N/A') {
            const tradeDate = new Date(trade.Date);
            if (tradeDate >= thirtyOneDaysAgo) {
                // Check owner (skip spouse/child if needed, matching python logic)
                const owner = (trade.Owner || '').toLowerCase();
                if (owner !== 'child' && owner !== 'spouse') {
                    const count = statsAccumulator.politician_counts_31d.get(trade.Politician) || 0;
                    statsAccumulator.politician_counts_31d.set(trade.Politician, count + 1);
                }
            }
        }
    }

    // Determine most active
    let mostActiveDisplay = "N/A";
    let maxCount = 0;
    for (const [politician, count] of statsAccumulator.politician_counts_31d.entries()) {
        if (count > maxCount) {
            maxCount = count;
            mostActiveDisplay = `${politician} (${count})`;
        }
    }

    // Render
    const setText = (id: string, text: string) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    };

    setText('stat-total-trades', statsAccumulator.total_trades.toString());
    setText('stat-analyzed', `${statsAccumulator.analyzed_count}/${statsAccumulator.total_trades}`);
    setText('stat-house', statsAccumulator.house_count.toString());
    setText('stat-senate', statsAccumulator.senate_count.toString());
    setText('stat-buy-sell', `${statsAccumulator.purchase_count}/${statsAccumulator.sale_count}`);
    setText('stat-tickers', statsAccumulator.unique_tickers.size.toString());
    setText('stat-high-risk', statsAccumulator.high_risk_count.toString());
    setText('stat-most-active', mostActiveDisplay);
}

async function fetchTradeData(): Promise<void> {
    const searchParams = new URLSearchParams(window.location.search);

    try {
        // Reset stats
        statsAccumulator.total_trades = 0;
        statsAccumulator.analyzed_count = 0;
        statsAccumulator.house_count = 0;
        statsAccumulator.senate_count = 0;
        statsAccumulator.purchase_count = 0;
        statsAccumulator.sale_count = 0;
        statsAccumulator.unique_tickers.clear();
        statsAccumulator.high_risk_count = 0;
        statsAccumulator.politician_counts_31d.clear();

        // Update loading text
        const titleEl = document.querySelector('h2.text-xl.font-bold.mb-4.text-gray-900.dark\\:text-white');
        if (titleEl && titleEl.textContent?.includes('Congress Trades')) {
            titleEl.textContent = `📋 Congress Trades (Loading...)`;
        }

        const response = await fetch(`/api/congress_trades/data?${searchParams.toString()}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data: CongressTradeApiResponse = await response.json();

        console.log(`[CongressTrades] Received ${data.trades?.length || 0} trades`);

        if (data.error) {
            console.error('API Error:', data.error);
            return;
        }

        const newTrades = data.trades || [];

        // Initialize grid with ALL data
        initializeCongressTradesGrid(newTrades);

        // Calculate stats from full dataset
        calculateAndRenderStats(newTrades);

        // Done loading
        if (titleEl) {
            titleEl.textContent = '📋 Congress Trades';
        }

    } catch (error) {
        console.error('Failed to fetch trades data:', error);
        if (gridApi) {
            gridApi.hideOverlay();
        }
    }
}

// Make function available globally for template usage
(window as any).initializeCongressTradesGrid = initializeCongressTradesGrid;
(window as any).analyzeSelectedTrades = analyzeSelectedTrades;
(window as any).refreshData = function () {
    const currentUrl = new URL(window.location.href);
    const currentRefreshKey = parseInt(currentUrl.searchParams.get('refresh_key') || '0');
    currentUrl.searchParams.set('refresh_key', (currentRefreshKey + 1).toString());
    window.location.href = currentUrl.toString();
};

(window as any).copyReasoning = function () {
    const reasoningText = document.getElementById('reasoning-text');
    if (reasoningText) {
        const text = reasoningText.textContent || '';
        navigator.clipboard.writeText(text).then(function () {
            // Show temporary feedback
            const originalText = reasoningText.textContent;
            reasoningText.textContent = '✓ Copied to clipboard!';
            setTimeout(function () {
                reasoningText.textContent = originalText;
            }, 2000);
        });
    }
};

// Auto-initialize if config is present
document.addEventListener('DOMContentLoaded', () => {
    // Handle date filter toggle
    const useDateFilter = document.getElementById('use-date-filter') as HTMLInputElement | null;
    const dateRangeInputs = document.getElementById('date-range-inputs');
    if (useDateFilter && dateRangeInputs) {
        useDateFilter.addEventListener('change', function () {
            if (this.checked) {
                dateRangeInputs.classList.remove('hidden');
            } else {
                dateRangeInputs.classList.add('hidden');
            }
        });
    }

    const configElement = document.getElementById('congress-trades-config');
    if (configElement) {
        try {
            const config = JSON.parse(configElement.textContent || '{}');

            // Check for lazy load flag
            if (config.lazyLoad) {
                // Fetch data - grid will be initialized on first batch
                fetchTradeData();
            } else if (config.tradesData) {
                // Legacy direct load (if we revert)
                initializeCongressTradesGrid(config.tradesData);
            }
        } catch (err) {
            console.error('[CongressTrades] Failed to auto-init:', err);
        }
    }
});
