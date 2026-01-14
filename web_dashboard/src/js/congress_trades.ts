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
}

// Global AgGrid reference
// Note: agGrid is also declared in globals.d.ts as optional 'any'
// This declaration makes it required and properly typed for this file
declare global {
    interface Window {
        agGrid: AgGridGlobal; // Override the optional 'any' from globals.d.ts with proper type
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

// Global click handler - manages navigation vs selection
function onCellClicked(params: AgGridParams): void {
    if (params.data) {
        // Determine action based on column
        let action = 'details';
        if (params.column?.colId === 'Ticker' && params.value && params.value !== 'N/A') {
            action = 'navigate';
            // Navigate immediately for ticker clicks
            const ticker = params.value;
            window.location.href = `/v2/ticker?ticker=${encodeURIComponent(ticker)}`;
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

// Handle row selection - show AI reasoning
function onSelectionChanged(): void {
    if (!gridApi) return;

    const selectedRows = gridApi.getSelectedRows();
    if (selectedRows && selectedRows.length > 0) {
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
        // Hide reasoning section if no selection
        const reasoningSection = document.getElementById('ai-reasoning-section');
        if (reasoningSection) {
            reasoningSection.classList.add('hidden');
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
            filter: true
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
            filter: true
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
            checkboxes: false,
            enableClickSelection: false,
        },
        // suppressRowClickSelection deprecated
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
        suppressCellFocus: false
    };

    // Create grid
    const gridInstance = new window.agGrid.Grid(gridDiv, gridOptions);
    gridApi = gridInstance.api;
    gridColumnApi = gridInstance.columnApi;

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

// Make function available globally for template usage
(window as any).initializeCongressTradesGrid = initializeCongressTradesGrid;
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
            if (config.tradesData) {
                initializeCongressTradesGrid(config.tradesData);
            }
        } catch (err) {
            console.error('[CongressTrades] Failed to auto-init:', err);
        }
    }
});
