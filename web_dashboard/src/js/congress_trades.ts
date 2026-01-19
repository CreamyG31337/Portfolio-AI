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
    getAllColumns(): any[];
    getAllDisplayedColumns(): any[];
    autoSizeColumns(colIds: string[], skipHeader?: boolean): void;
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
    field?: string;
    headerName?: string;
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
    checkboxSelection?: boolean;
    headerCheckboxSelection?: boolean;
    suppressMenu?: boolean;
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
    _logo_url?: string;
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

// Ticker cell renderer - makes ticker clickable with logo
class TickerCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement; // Definitely assigned in init()

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('div');
        this.eGui.style.display = 'flex';
        this.eGui.style.alignItems = 'center';
        this.eGui.style.gap = '6px';
        
        if (params.value && params.value !== 'N/A') {
            const ticker = params.value;
            const logoUrl = params.data?._logo_url;
            
            // Add logo image if available
            if (logoUrl) {
                const img = document.createElement('img');
                img.src = logoUrl;
                img.alt = ticker;
                img.style.width = '24px';
                img.style.height = '24px';
                img.style.objectFit = 'contain';
                img.style.borderRadius = '4px';
                img.style.flexShrink = '0';
                // Handle image load errors gracefully - try fallback
                img.onerror = function() {
                    // Try Yahoo Finance as fallback if Parqet fails
                    const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${ticker}.png`;
                    if (img.src !== yahooUrl) {
                        img.src = yahooUrl;
                    } else {
                        // Both failed, hide the image
                        img.style.display = 'none';
                    }
                };
                this.eGui.appendChild(img);
            }
            
            // Add ticker text
            const tickerSpan = document.createElement('span');
            tickerSpan.innerText = ticker;
            tickerSpan.style.color = '#1f77b4';
            tickerSpan.style.fontWeight = 'bold';
            tickerSpan.style.textDecoration = 'underline';
            tickerSpan.style.cursor = 'pointer';
            tickerSpan.addEventListener('click', function (e: Event) {
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

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Party cell renderer - colors Democrat (blue) and Republican (red)
// Option 1: Full text with colors (current)
// Option 2: Emoji + letter (🔵 D, 🔴 R, 🟣 I)
// Option 3: Just emoji (🔵, 🔴, 🟣)
class PartyCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;
    private useEmoji: boolean = true; // Set to false for full text
    private emojiOnly: boolean = false; // Set to true for emoji only (no letter)

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        
        // Color based on party
        const partyLower = value.toLowerCase();
        let displayText = '';
        let color = '';
        
        if (partyLower.includes('democrat') || partyLower === 'd') {
            color = '#2563eb'; // Blue
            if (this.emojiOnly) {
                displayText = '🔵';
            } else if (this.useEmoji) {
                displayText = '🔵 D';
            } else {
                displayText = value || 'N/A';
            }
        } else if (partyLower.includes('republican') || partyLower === 'r') {
            color = '#dc2626'; // Red
            if (this.emojiOnly) {
                displayText = '🔴';
            } else if (this.useEmoji) {
                displayText = '🔴 R';
            } else {
                displayText = value || 'N/A';
            }
        } else if (partyLower.includes('independent') || partyLower === 'i') {
            color = '#7c3aed'; // Purple
            if (this.emojiOnly) {
                displayText = '🟣';
            } else if (this.useEmoji) {
                displayText = '🟣 I';
            } else {
                displayText = value || 'N/A';
            }
        } else {
            displayText = value || 'N/A';
        }
        
        this.eGui.innerText = displayText;
        if (color) {
            this.eGui.style.color = color;
            this.eGui.style.fontWeight = '500';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Type cell renderer - colors Purchase/Buy (green) and Sale/Sell (red)
// Option 1: Full text with colors (current)
// Option 2: Emoji + text (📈 Buy, 📉 Sell)
// Option 3: Just emoji (📈, 📉)
class TypeCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;
    private useEmoji: boolean = false; // Set to true for emoji
    private emojiOnly: boolean = false; // Set to true for emoji only

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        const typeLower = value.toLowerCase();
        
        let displayText = '';
        let color = '';
        
        if (typeLower === 'purchase' || typeLower === 'buy') {
            color = '#16a34a'; // Green
            if (this.emojiOnly) {
                displayText = '📈';
            } else if (this.useEmoji) {
                displayText = '📈 Buy';
            } else {
                displayText = value || 'N/A';
            }
        } else if (typeLower === 'sale' || typeLower === 'sell') {
            color = '#dc2626'; // Red
            if (this.emojiOnly) {
                displayText = '📉';
            } else if (this.useEmoji) {
                displayText = '📉 Sell';
            } else {
                displayText = value || 'N/A';
            }
        } else {
            displayText = value || 'N/A';
        }
        
        this.eGui.innerText = displayText;
        if (color) {
            this.eGui.style.color = color;
            this.eGui.style.fontWeight = '500';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Amount cell renderer - shows moneybag/diamond emojis based on amount range
// Based on actual data analysis:
// 💰 = $1k-$15k (1 moneybag) - 74.4% of trades
// 💰💰 = $15k-$50k (2 moneybags) - 16.9% of trades
// 💰💰💰 = $50k-$100k (3 moneybags) - 4.9% of trades
// 💎 = $100k-$250k (1 diamond) - 2.6% of trades
// 💎💎 = $250k-$500k (2 diamonds) - 0.6% of trades
// 💎💎💎 = $500k-$1M (3 diamonds) - 0.5% of trades
// 💎💎💎💎 = $1M-$5M (4 diamonds) - rare
// 💎💎💎💎💎 = $5M+ (5 diamonds) - very rare (max seen: $25M)
class AmountCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        
        if (!value || value === 'N/A') {
            this.eGui.innerText = 'N/A';
            return;
        }
        
        // Parse amount range to determine emoji
        const amountStr = value.toLowerCase();
        
        // Extract numeric values from amount string
        // Format is usually "$1,001 - $15,000" or "$15,001 - $50,000" etc.
        // Also handle "Over $1,000,000" format
        let maxValue: number | null = null;
        
        if (amountStr.includes('over') || amountStr.includes('>')) {
            // Handle "Over $1,000,000" format - extract the number
            const overMatch = amountStr.match(/\$?([\d,]+)/);
            if (overMatch) {
                maxValue = parseInt(overMatch[1].replace(/,/g, ''), 10);
                // For "Over X", use X as the threshold
            }
        } else {
            // Regular range format "$1,001 - $15,000"
            const maxMatch = amountStr.match(/\$?([\d,]+)/g);
            if (maxMatch && maxMatch.length > 0) {
                // Get the last (highest) number
                const maxValueStr = maxMatch[maxMatch.length - 1].replace(/[$,]/g, '');
                maxValue = parseInt(maxValueStr, 10);
            }
        }
        
        if (maxValue !== null && !isNaN(maxValue)) {
            if (maxValue <= 15000) {
                this.eGui.innerText = '💰'; // 1 moneybag
            } else if (maxValue <= 50000) {
                this.eGui.innerText = '💰💰'; // 2 moneybags
            } else if (maxValue <= 100000) {
                this.eGui.innerText = '💰💰💰'; // 3 moneybags
            } else if (maxValue <= 250000) {
                this.eGui.innerText = '💎'; // 1 diamond
            } else if (maxValue <= 500000) {
                this.eGui.innerText = '💎💎'; // 2 diamonds
            } else if (maxValue <= 1000000) {
                this.eGui.innerText = '💎💎💎'; // 3 diamonds
            } else if (maxValue <= 5000000) {
                this.eGui.innerText = '💎💎💎💎'; // 4 diamonds
            } else {
                this.eGui.innerText = '💎💎💎💎💎'; // 5 diamonds for $5M+
            }
        } else {
            // Fallback if parsing fails
            this.eGui.innerText = '💰';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Chamber cell renderer - just shows text (emoji is in header)
class ChamberCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        this.eGui.innerText = value || 'N/A';
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// State cell renderer - converts 2-letter abbreviations to full state names
class StateCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;
    
    // US State abbreviations to full names mapping
    private stateMap: Record<string, string> = {
        'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
        'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
        'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
        'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
        'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
        'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
        'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
        'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
        'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
        'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
        'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
        'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
        'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
    };

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        
        if (!value || value === 'N/A') {
            this.eGui.innerText = 'N/A';
            return;
        }
        
        // Convert abbreviation to full name if it's a 2-letter code
        const valueUpper = value.toUpperCase().trim();
        if (valueUpper.length === 2 && this.stateMap[valueUpper]) {
            this.eGui.innerText = this.stateMap[valueUpper];
        } else {
            // Already a full name or unknown, use as-is
            this.eGui.innerText = value;
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Score cell renderer - adds spy icon for high conflict scores (>= 0.9)
class ScoreCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        
        if (!value || value === 'N/A' || value.includes('⚪')) {
            this.eGui.innerText = value || 'N/A';
            return;
        }
        
        // Parse the score from the display string (format: "🔴 0.90" or "🟡 0.50" etc.)
        const scoreMatch = value.match(/([\d.]+)/);
        if (scoreMatch) {
            const score = parseFloat(scoreMatch[1]);
            if (!isNaN(score) && score >= 0.9) {
                // Add spy icon for high conflict scores (>= 0.9)
                this.eGui.innerText = '🕵️ ' + value;
            } else {
                // Keep original display
                this.eGui.innerText = value;
            }
        } else {
            // No score found, use as-is
            this.eGui.innerText = value;
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
            headerName: '',
            checkboxSelection: true,
            headerCheckboxSelection: true,
            width: 50,
            pinned: 'left',
            suppressMenu: true,
            sortable: false,
            filter: false,
            resizable: false
        },
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
            headerName: '🏛️ Chamber',
            minWidth: 60,
            flex: 0.6,
            sortable: true,
            filter: true,
            cellRenderer: ChamberCellRenderer
        },
        {
            field: 'Party',
            headerName: 'Party',
            minWidth: 50,
            flex: 0.5,
            sortable: true,
            filter: true,
            cellRenderer: PartyCellRenderer
        },
        {
            field: 'State',
            headerName: 'State',
            minWidth: 100,
            flex: 1.2,
            sortable: true,
            filter: true,
            cellRenderer: StateCellRenderer
        },
        {
            field: 'Date',
            headerName: 'Date',
            minWidth: 90,
            flex: 0.9,
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
            headerName: '💰 Amount',
            minWidth: 60,
            flex: 0.6,
            sortable: true,
            filter: true,
            cellRenderer: AmountCellRenderer,
            tooltipValueGetter: function (params: AgGridParams): string {
                // Show full amount text in tooltip
                return params.value || '';
            }
        },
        {
            field: 'Score',
            headerName: 'Score',
            minWidth: 100,
            flex: 1,
            sortable: true,
            filter: true,
            cellRenderer: ScoreCellRenderer
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
            flex: 4, // Increased from 3 to give more space
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
        rowSelection: 'multiple',
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

    // Auto-size columns based on content
    if (gridApi && gridColumnApi) {
        // Function to auto-size columns based on their content
        const autoSizeColumns = () => {
            if (gridColumnApi) {
                // Auto-size all displayed columns based on content
                // Get all displayed column IDs from the grid
                const allColumns = gridColumnApi.getAllDisplayedColumns();
                if (allColumns && allColumns.length > 0) {
                    const columnIds = allColumns.map((col: any) => col.getColId()).filter(Boolean);
                    if (columnIds.length > 0) {
                        gridColumnApi.autoSizeColumns(columnIds, false); // false = skipHeader (include header in sizing)
                    }
                }
            }
        };

        // Wait for grid to be ready before auto-sizing
        gridApi.addEventListener('firstDataRendered', () => {
            // Small delay to ensure all content is rendered (especially logos)
            setTimeout(() => {
                autoSizeColumns();
            }, 300);
        });

        // Also auto-size on window resize (with debounce for performance)
        let resizeTimeout: number | null = null;
        window.addEventListener('resize', () => {
            if (resizeTimeout) {
                clearTimeout(resizeTimeout);
            }
            resizeTimeout = window.setTimeout(() => {
                autoSizeColumns();
            }, 150);
        });
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

        // Auto-size columns after data is loaded (with delay for logos/images to load)
        if (gridColumnApi) {
            setTimeout(() => {
                if (gridColumnApi) {
                    const allColumns = gridColumnApi.getAllDisplayedColumns();
                    if (allColumns && allColumns.length > 0) {
                        const columnIds = allColumns.map((col: any) => col.getColId()).filter(Boolean);
                        if (columnIds.length > 0) {
                            gridColumnApi.autoSizeColumns(columnIds, false);
                        }
                    }
                }
            }, 500); // Wait for images/logos to load
        }

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

// Re-analyze all visible trades
async function reanalyzeSelectedTrades(): Promise<void> {
    if (!gridApi) {
        alert('Grid not initialized');
        return;
    }
    
    // Get selected trades (only rows with checkboxes checked)
    const selectedRows = gridApi.getSelectedRows() as CongressTrade[];
    
    if (selectedRows.length === 0) {
        alert('Please select at least one trade to re-analyze');
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
    
    try {
        const button = document.querySelector('button[onclick="reanalyzeSelectedTrades()"]') as HTMLButtonElement;
        if (button) {
            button.disabled = true;
            button.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Re-Analyzing...';
        }
        
        // Call the analysis API
        const response = await fetch('/api/congress_trades/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ trade_ids: tradeIds })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const result = await response.json();
        
        if (!result.success) {
            throw new Error(result.error || 'Analysis failed');
        }
        
        const message = result.message || `Successfully re-analyzed ${result.processed || tradeIds.length} trade(s)`;
        alert(`✅ ${message}. Refreshing...`);
        
        // Refresh the page to show updated data
        window.location.reload();
        
    } catch (error) {
        console.error('Failed to re-analyze trades:', error);
        alert(`❌ Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
        
        // Restore button
        const button = document.querySelector('button[onclick="reanalyzeSelectedTrades()"]') as HTMLButtonElement;
        if (button) {
            button.disabled = false;
            button.innerHTML = '<i class="fas fa-redo mr-2"></i>Re-Analyze Selected';
        }
    }
}

// Make function available globally for template usage
(window as any).initializeCongressTradesGrid = initializeCongressTradesGrid;
(window as any).analyzeSelectedTrades = analyzeSelectedTrades;
(window as any).reanalyzeSelectedTrades = reanalyzeSelectedTrades;
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
