/**
 * ETF Holdings Watchtower Typescript
 * Handles AgGrid initialization and interactions
 */

// Interface for AgGrid params
interface GridParams {
    value: any;
    data: any;
    eGridCell: HTMLElement;
    column?: {
        colId?: string;
        getColId?: () => string;
    };
}

let gridApi: any = null;
let gridColumnApi: any = null;

// Global cache of tickers that don't have logos (to avoid repeated 404s)
const failedLogoCache = new Set<string>();

// Helper function to detect dark mode
function isDarkMode(): boolean {
    const htmlElement = document.documentElement;
    const theme = htmlElement.getAttribute('data-theme') || 'system';

    if (theme === 'dark' || theme === 'midnight-tokyo' || theme === 'abyss') {
        return true;
    } else if (theme === 'system') {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return true;
        }
    }
    return false;
}

// Ticker cell renderer - makes ticker clickable with logo
class TickerCellRenderer {
    eGui!: HTMLElement;

    init(params: GridParams) {
        this.eGui = document.createElement('div');
        this.eGui.style.display = 'flex';
        this.eGui.style.alignItems = 'center';
        this.eGui.style.gap = '6px';

        if (params.value && params.value !== 'N/A') {
            const ticker = params.value;
            // Check for logo URL - use column-specific logo URL if available, fallback to generic
            // For holding_ticker column: use _holding_logo_url
            // For etf_ticker column: use _etf_logo_url
            // Fallback to either if column-specific not available (for compatibility)
            const columnId = params.column?.colId || params.column?.getColId?.() || '';
            const logoUrl = (columnId === 'holding_ticker' && params.data?._holding_logo_url)
                ? params.data._holding_logo_url
                : (columnId === 'etf_ticker' && params.data?._etf_logo_url)
                    ? params.data._etf_logo_url
                    : params.data?._holding_logo_url || params.data?._etf_logo_url;

            // Check cache first - skip if we know this ticker doesn't have a logo
            const cleanTicker = ticker.replace(/\s+/g, '').replace(/\.(TO|V|CN|TSX|TSXV|NE|NEO)$/i, '');
            const cacheKey = cleanTicker.toUpperCase();

            // Always add logo image (or transparent placeholder) for consistent alignment
            const img = document.createElement('img');
            img.style.width = '24px';
            img.style.height = '24px';
            img.style.objectFit = 'contain';
            img.style.borderRadius = '4px';
            img.style.flexShrink = '0';

            // Check if logo is already known to fail
            if (failedLogoCache.has(cacheKey) || !logoUrl) {
                // Use transparent placeholder for consistent spacing
                img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="24" height="24"%3E%3C/svg%3E';
                img.alt = '';
            } else {
                // Try to load logo
                img.src = logoUrl;
                img.alt = ticker;

                // Handle image load errors gracefully - try fallback
                let fallbackAttempted = false;
                img.onerror = function () {
                    if (fallbackAttempted) {
                        // Already tried fallback, use transparent placeholder for alignment
                        failedLogoCache.add(cacheKey);
                        // Use a transparent 24x24 SVG placeholder to maintain spacing
                        img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="24" height="24"%3E%3C/svg%3E';
                        img.alt = '';
                        img.onerror = null;
                        return;
                    }

                    // Mark that we've attempted fallback
                    fallbackAttempted = true;

                    // Try Yahoo Finance as fallback if Parqet fails
                    const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${cleanTicker}.png`;
                    if (img.src !== yahooUrl) {
                        img.src = yahooUrl;
                    } else {
                        // Same URL, use transparent placeholder for alignment
                        failedLogoCache.add(cacheKey);
                        img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="24" height="24"%3E%3C/svg%3E';
                        img.alt = '';
                        img.onerror = null;
                    }
                };
            }

            this.eGui.appendChild(img);

            // Add ticker text
            const tickerSpan = document.createElement('span');
            tickerSpan.innerText = ticker;
            // Theme-aware color using Tailwind classes
            tickerSpan.className = 'text-accent hover:text-accent-hover font-bold underline cursor-pointer';
            tickerSpan.addEventListener('click', function (e) {
                e.stopPropagation();
                if (ticker && ticker !== 'N/A') {
                    window.location.href = `/ticker?ticker=${encodeURIComponent(ticker)}`;
                }
            });
            this.eGui.appendChild(tickerSpan);
        } else {
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
    const gridDiv = document.querySelector('#etf-holdings-grid') as HTMLElement | null;
    if (!gridDiv) {
        console.error('ETF holdings grid container not found');
        return;
    }
    if (!(window as any).agGrid) {
        console.error('AgGrid not loaded');
        return;
    }

    // Detect theme and apply appropriate AgGrid theme
    if (isDarkMode()) {
        gridDiv.classList.remove('ag-theme-alpine');
        gridDiv.classList.add('ag-theme-alpine-dark');
    } else {
        gridDiv.classList.remove('ag-theme-alpine-dark');
        gridDiv.classList.add('ag-theme-alpine');
    }

    let columnDefs: any[] = [];

    if (viewMode === 'holdings') {
        columnDefs = [
            { field: 'date', headerName: 'Date', flex: 0.8, minWidth: 100, maxWidth: 130, sortable: true, filter: true },
            // ETF ticker is redundant if we selected one, but good for export/context
            {
                field: 'etf_ticker',
                headerName: 'ETF',
                flex: 0.6,
                minWidth: 70,
                maxWidth: 100,
                sortable: true,
                filter: true,
                cellRenderer: TickerCellRenderer  // Add logo support to ETF ticker column
            },
            {
                field: 'holding_ticker',
                headerName: 'Ticker',
                flex: 0.7,
                minWidth: 80,
                maxWidth: 110,
                pinned: 'left',
                cellRenderer: TickerCellRenderer,
                sortable: true,
                filter: true
            },
            { field: 'holding_name', headerName: 'Name', flex: 2, minWidth: 200, sortable: true, filter: true },
            {
                field: 'user_shares',
                headerName: 'We Hold',
                flex: 0.6,
                minWidth: 80,
                maxWidth: 110,
                sortable: true,
                valueFormatter: (params: any) => params.value > 0 ? "✓" : "—",
                cellClass: (params: any) => params.value > 0 ? 'text-theme-success-text font-bold' : ''
            },
            {
                field: 'user_shares',
                headerName: 'Our Shares',
                flex: 0.8,
                minWidth: 90,
                maxWidth: 130,
                sortable: true,
                valueFormatter: (params: any) => params.value > 0 ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"
            },
            {
                field: 'current_shares',
                headerName: 'Shares',
                flex: 1,
                minWidth: 100,
                maxWidth: 150,
                sortable: true,
                valueFormatter: (params: any) => params.value ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "0"
            },
            {
                field: 'weight_percent',
                headerName: 'Weight %',
                flex: 0.7,
                minWidth: 80,
                maxWidth: 120,
                sortable: true,
                valueFormatter: (params: any) => params.value ? params.value.toFixed(2) + '%' : "0.00%"
            }
        ];
    } else {
        // Changes View
        columnDefs = [
            { field: 'date', headerName: 'Date', flex: 0.8, minWidth: 100, maxWidth: 130, sortable: true, filter: true },
            {
                field: 'etf_ticker',
                headerName: 'ETF',
                flex: 0.6,
                minWidth: 70,
                maxWidth: 100,
                sortable: true,
                filter: true,
                cellRenderer: TickerCellRenderer  // Add logo support to ETF ticker column
            },
            {
                field: 'holding_ticker',
                headerName: 'Ticker',
                flex: 0.7,
                minWidth: 80,
                maxWidth: 110,
                pinned: 'left',
                cellRenderer: TickerCellRenderer,
                sortable: true,
                filter: true
            },
            { field: 'holding_name', headerName: 'Name', flex: 1.5, minWidth: 150, sortable: true, filter: true },
            {
                field: 'user_shares',
                headerName: 'We Hold',
                flex: 0.5,
                minWidth: 70,
                maxWidth: 100,
                sortable: true,
                valueFormatter: (params: any) => params.value > 0 ? "✓" : "—",
                cellClass: (params: any) => params.value > 0 ? 'text-theme-success-text font-bold' : ''
            },
            {
                field: 'user_shares',
                headerName: 'Our Shares',
                flex: 0.7,
                minWidth: 80,
                maxWidth: 120,
                sortable: true,
                valueFormatter: (params: any) => params.value > 0 ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"
            },
            {
                field: 'action',
                headerName: 'Action',
                flex: 0.7,
                minWidth: 90,
                maxWidth: 120,
                sortable: true,
                filter: true,
                valueFormatter: (params: any) => {
                    if (params.value === 'BUY') return '🟢 BUY';
                    if (params.value === 'SELL') return '🔴 SELL';
                    return params.value;
                },
                cellClass: (params: any) => {
                    if (params.value === 'BUY') return 'text-theme-success-text font-bold text-center';
                    if (params.value === 'SELL') return 'text-theme-error-text font-bold text-center';
                    return 'text-center';
                }
            },
            {
                field: 'share_change',
                headerName: 'Δ Shares',  // Delta symbol for mathematical clarity
                flex: 0.8,
                minWidth: 90,
                maxWidth: 130,
                sortable: true,
                valueFormatter: (params: any) => (params.value > 0 ? '+' : '') + params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }),
                cellClass: (params: any) => {
                    if (params.value > 0) return 'text-theme-success-text font-bold';
                    if (params.value < 0) return 'text-theme-error-text font-bold';
                    return '';
                }
            },
            {
                field: 'percent_change',
                headerName: '% Change',
                flex: 0.7,
                minWidth: 80,
                maxWidth: 120,
                sortable: true,
                valueFormatter: (params: any) => (params.value > 0 ? '+' : '') + params.value.toFixed(2) + '%'
            },
            {
                field: 'previous_shares',
                headerName: 'Prev Shares',
                flex: 0.9,
                minWidth: 100,
                maxWidth: 140,
                sortable: true,
                valueFormatter: (params: any) => params.value ? params.value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "0"
            },
            {
                field: 'current_shares',
                headerName: 'New Shares',
                flex: 0.9,
                minWidth: 100,
                maxWidth: 140,
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
        overlayNoRowsTemplate: viewMode === 'changes'
            ? '<span style="padding: 20px; font-size: 14px; color: #666;">📭 No changes found for the selected date and filters. Try selecting a different date or change type.</span>'
            : '<span style="padding: 20px; font-size: 14px; color: #666;">📭 No holdings data available. This ETF may not have data for the selected date.</span>',

        // Row styling: light backgrounds for BUY/SELL, border highlight for positions we own
        rowClassRules: {
            // BUY = Success background
            'bg-theme-success-bg/30': (params: any) => params.data && params.data.action === 'BUY',

            // SELL = Error background
            'bg-theme-error-bg/30': (params: any) => params.data && params.data.action === 'SELL',

            // If we own it, add a subtle border highlight (without overriding buy/sell background)
            'border-l-4 border-yellow-400': (params: any) => params.data && params.data.user_shares > 0
        }
    };

    // Create grid using v31 API (createGrid instead of new Grid)
    // createGrid returns the grid API directly
    gridApi = (window as any).agGrid.createGrid(gridDiv, gridOptions);
    // gridColumnApi is deprecated in v31 - column API methods are now on the main grid API
    gridColumnApi = null; // Keep for compatibility but don't use

    const spinner = document.getElementById("latest-changes-loading");
    if (spinner) {
        spinner.classList.add("hidden");
    }

    // Auto-size columns to fit container
    if (gridApi) {
        // Function to auto-size columns to content (fallback to fit if unavailable)
        const resizeColumns = () => {
            if (!gridApi) {
                return;
            }
            if (typeof gridApi.autoSizeAllColumns === "function") {
                gridApi.autoSizeAllColumns(false);
            } else if (typeof gridApi.sizeColumnsToFit === "function") {
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

// Function to update grid theme dynamically
function updateEtfGridTheme(): void {
    const gridDiv = document.querySelector('#etf-holdings-grid') as HTMLElement | null;
    if (!gridDiv) {
        return;
    }

    // Update grid container class based on theme
    if (isDarkMode()) {
        gridDiv.classList.remove('ag-theme-alpine');
        gridDiv.classList.add('ag-theme-alpine-dark');
    } else {
        gridDiv.classList.remove('ag-theme-alpine-dark');
        gridDiv.classList.add('ag-theme-alpine');
    }

    // Refresh grid to update cell and row styles
    if (gridApi) {
        gridApi.refreshCells();
        gridApi.refreshHeader();
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

    // Auto-submit the form when fund selection changes
    (window as any).updateFilters();
};

// Update Filters function - submits the form to apply filters
(window as any).updateFilters = function () {
    const form = document.getElementById('filters-form') as HTMLFormElement;
    // Ensure hidden input is up to date (though handleFundSelection updates it)
    form.submit();
};

(window as any).initializeEtfGrid = initializeEtfGrid;

// Auto-initialize if config is present
document.addEventListener('DOMContentLoaded', () => {
    const configElement = document.getElementById('etf-holdings-config');
    if (configElement) {
        try {
            const spinner = document.getElementById("latest-changes-loading");
            if (spinner) {
                spinner.classList.remove("hidden");
                spinner.classList.add("flex");
            }
            const config = JSON.parse(configElement.textContent || '{}');
            if (config.holdingsData) {
                initializeEtfGrid(config.holdingsData, config.viewMode || 'holdings');
            }
        } catch (err) {
            console.error('[EtfHoldings] Failed to auto-init:', err);
        }
    }

    const gridDiv = document.getElementById("etf-holdings-grid");
    if (!(window as any).agGrid || !gridApi) {
        if (gridDiv) {
            gridDiv.classList.remove("hidden");
        }
        const spinner = document.getElementById("latest-changes-loading");
        if (spinner) {
            spinner.classList.add("hidden");
        }
    }

    // Listen for theme changes
    const themeManager = (window as any).themeManager;
    if (themeManager && typeof themeManager.addListener === 'function') {
        themeManager.addListener(() => {
            console.log('[EtfHoldings] Theme changed, updating grid theme...');
            updateEtfGridTheme();
        });
    } else {
        // Fallback: Use MutationObserver to watch for data-theme attribute changes
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
                    updateEtfGridTheme();
                }
            });
        });
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-theme']
        });
    }
});
