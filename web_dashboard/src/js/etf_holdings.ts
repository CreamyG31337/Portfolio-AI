/**
 * ETF Holdings Watchtower Typescript
 * Handles AgGrid initialization and interactions
 */

// Interface for AgGrid params
interface GridParams {
    value: any;
    data: any;
    eGridCell: HTMLElement;
}

let gridApi: any = null;
let gridColumnApi: any = null;

// Ticker cell renderer - makes ticker clickable
class TickerCellRenderer {
    eGui!: HTMLElement;

    init(params: GridParams) {
        this.eGui = document.createElement('span');
        if (params.value && params.value !== 'N/A') {
            this.eGui.innerText = params.value;
            this.eGui.style.color = '#1f77b4';
            this.eGui.style.fontWeight = 'bold';
            this.eGui.style.textDecoration = 'underline';
            this.eGui.style.cursor = 'pointer';
            this.eGui.addEventListener('click', function (e) {
                e.stopPropagation();
                const ticker = params.value;
                if (ticker && ticker !== 'N/A') {
                    // Link to Streamlit page for now
                    window.location.href = `/pages/ticker_details?ticker=${encodeURIComponent(ticker)}`;
                }
            });
        }
        else {
            this.eGui.innerText = params.value || 'N/A';
        }
    }
    getGui() {
        return this.eGui;
    }
}

// Make TickerCellRenderer globally accessible for AgGrid
(window as any).TickerCellRenderer = TickerCellRenderer;

export function initializeEtfGrid(holdingsData: any[], viewMode: string) {
    const gridDiv = document.querySelector('#etf-holdings-grid');
    if (!gridDiv) {
        console.error('ETF holdings grid container not found');
        return;
    }
    if (!(window as any).agGrid) {
        console.error('AgGrid not loaded');
        return;
    }

    let columnDefs: any[] = [];

    if (viewMode === 'holdings') {
        columnDefs = [
            { field: 'date', headerName: 'Date', width: 110, sortable: true, filter: true },
            // ETF ticker is redundant if we selected one, but good for export/context
            { field: 'etf_ticker', headerName: 'ETF', width: 80, sortable: true, filter: true },
            {
                field: 'holding_ticker',
                headerName: 'Ticker',
                width: 90,
                pinned: 'left',
                cellRenderer: TickerCellRenderer,
                sortable: true,
                filter: true
            },
            { field: 'holding_name', headerName: 'Name', width: 250, sortable: true, filter: true },
            {
                field: 'user_shares',
                headerName: 'We Hold',
                width: 100,
                sortable: true,
                valueFormatter: (params: any) => params.value > 0 ? "✓" : "—",
                cellStyle: (params: any) => params.value > 0 ? { color: '#2d5a3d', fontWeight: 'bold' } : null
            },
            {
                field: 'user_shares',
                headerName: 'Our Shares',
                width: 110,
                sortable: true,
                valueFormatter: (params: any) => params.value > 0 ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"
            },
            {
                field: 'current_shares',
                headerName: 'Shares',
                width: 120,
                sortable: true,
                valueFormatter: (params: any) => params.value ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "0"
            },
            {
                field: 'weight_percent',
                headerName: 'Weight %',
                width: 100,
                sortable: true,
                valueFormatter: (params: any) => params.value ? params.value.toFixed(2) + '%' : "0.00%"
            }
        ];
    } else {
        // Changes View
        columnDefs = [
            { field: 'date', headerName: 'Date', width: 110, sortable: true, filter: true },
            { field: 'etf_ticker', headerName: 'ETF', width: 80, sortable: true, filter: true },
            {
                field: 'holding_ticker',
                headerName: 'Ticker',
                width: 90,
                pinned: 'left',
                cellRenderer: TickerCellRenderer,
                sortable: true,
                filter: true
            },
            { field: 'holding_name', headerName: 'Name', width: 200, sortable: true, filter: true },
            {
                field: 'user_shares',
                headerName: 'We Hold',
                width: 90,
                sortable: true,
                valueFormatter: (params: any) => params.value > 0 ? "✓" : "—",
                cellStyle: (params: any) => params.value > 0 ? { color: '#2d5a3d', fontWeight: 'bold' } : null
            },
            {
                field: 'user_shares',
                headerName: 'Our Shares',
                width: 100,
                sortable: true,
                valueFormatter: (params: any) => params.value > 0 ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"
            },
            {
                field: 'action',
                headerName: 'Action',
                width: 90,
                sortable: true,
                filter: true,
                cellStyle: (params: any) => {
                    if (params.value === 'BUY') return { backgroundColor: '#d4edda', color: '#155724', fontWeight: 'bold', textAlign: 'center' };
                    if (params.value === 'SELL') return { backgroundColor: '#f8d7da', color: '#721c24', fontWeight: 'bold', textAlign: 'center' };
                    return { textAlign: 'center' };
                }
            },
            {
                field: 'share_change',
                headerName: 'Change',
                width: 100,
                sortable: true,
                valueFormatter: (params: any) => (params.value > 0 ? '+' : '') + params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }),
                cellStyle: (params: any) => {
                    if (params.value > 0) return { color: '#155724', fontWeight: 'bold' };
                    if (params.value < 0) return { color: '#721c24', fontWeight: 'bold' };
                    return null;
                }
            },
            {
                field: 'percent_change',
                headerName: '% Change',
                width: 100,
                sortable: true,
                valueFormatter: (params: any) => (params.value > 0 ? '+' : '') + params.value.toFixed(2) + '%'
            },
            {
                field: 'previous_shares',
                headerName: 'Prev Shares',
                width: 110,
                sortable: true,
                valueFormatter: (params: any) => params.value ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "0"
            },
            {
                field: 'current_shares',
                headerName: 'New Shares',
                width: 110,
                sortable: true,
                valueFormatter: (params: any) => params.value ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "0"
            }
        ];
    }

    // Grid options
    const gridOptions = {
        columnDefs: columnDefs,
        rowData: holdingsData,
        defaultColDef: {
            editable: false,
            sortable: true,
            filter: true,
            resizable: true
        },
        pagination: true,
        paginationPageSize: 100,
        paginationPageSizeSelector: [100, 250, 500, 1000],
        animateRows: true,
        // Optional: Highlight rows we hold
        getRowStyle: (params: any) => {
            if (params.data.user_shares > 0) {
                return { backgroundColor: '#f0fff4' }; // Light green background for owned stocks
            }
            return null;
        }
    };

    // Create grid
    const gridInstance = new (window as any).agGrid.Grid(gridDiv, gridOptions);
    gridApi = gridInstance.api;
    gridColumnApi = gridInstance.columnApi;

    // Auto-size columns
    if (gridApi) {
        gridApi.sizeColumnsToFit();
    }
}


// Handle multi-select logic
(window as any).handleFundSelection = function (checkbox: HTMLInputElement) {
    const allCheckbox = document.querySelector('input[value="All Funds"]') as HTMLInputElement;
    const otherCheckboxes = Array.from(document.querySelectorAll('.fund-checkbox')).filter(cb => (cb as HTMLInputElement).value !== 'All Funds') as HTMLInputElement[];
    const labelSpan = document.getElementById('fund-select-label');
    const hiddenInput = document.getElementById('fund-input') as HTMLInputElement;

    // Logic: 
    // If "All Funds" is clicked, uncheck others.
    // If other is clicked, uncheck "All Funds".
    // If no others are checked, check "All Funds".

    if (checkbox.value === 'All Funds') {
        if (checkbox.checked) {
            otherCheckboxes.forEach(cb => cb.checked = false);
            if (labelSpan) labelSpan.textContent = 'All Funds (Show All)';
            if (hiddenInput) hiddenInput.value = 'All Funds';
        } else {
            // Validate at least one selection or revert
            if (otherCheckboxes.filter(cb => cb.checked).length === 0) {
                checkbox.checked = true; // Force check if nothing else selected
            }
        }
    } else {
        if (checkbox.checked) {
            if (allCheckbox.checked) allCheckbox.checked = false;
        } else {
            // If all unchecked, check "All Funds"
            if (otherCheckboxes.filter(cb => cb.checked).length === 0) {
                allCheckbox.checked = true;
            }
        }

        // Update Label and Input
        const selected = otherCheckboxes.filter(cb => cb.checked).map(cb => cb.value);
        if (selected.length === 0) {
            if (labelSpan) labelSpan.textContent = "All Funds (Show All)";
            if (hiddenInput) hiddenInput.value = 'All Funds';
        } else if (selected.length === 1) {
            if (labelSpan) labelSpan.textContent = selected[0];
            if (hiddenInput) hiddenInput.value = selected[0];
        } else {
            if (labelSpan) labelSpan.textContent = `${selected.length} Funds Selected`;
            if (hiddenInput) hiddenInput.value = selected.join(',');
        }
    }
};

// Update Filters function
(window as any).updateFilters = function (shouldRefresh = false) {
    const form = document.getElementById('filters-form') as HTMLFormElement;
    // Ensure hidden input is up to date (though handleFundSelection updates it)

    if (shouldRefresh) {
        // Add refresh key
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'refresh_key';
        input.value = Math.floor(Math.random() * 1000).toString();
        form.appendChild(input);
    }

    form.submit();
};

(window as any).initializeEtfGrid = initializeEtfGrid;

// Auto-initialize if config is present
document.addEventListener('DOMContentLoaded', () => {
    const configElement = document.getElementById('etf-holdings-config');
    if (configElement) {
        try {
            const config = JSON.parse(configElement.textContent || '{}');
            if (config.holdingsData) {
                initializeEtfGrid(config.holdingsData, config.viewMode || 'holdings');
            }
        } catch (err) {
            console.error('[EtfHoldings] Failed to auto-init:', err);
        }
    }
});
