/**
 * Congress Trades TypeScript
 * Handles AgGrid initialization and interactions
 */

import { getCsrfHeaders } from './csrf.js';

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
    getColumnApi?: () => AgGridColumnApi;
    setDatasource(datasource: AgGridDatasource): void;
    purgeInfiniteCache(): void;
    getInfiniteRowCount(): number | null;
}

interface AgGridDatasource {
    getRows: (params: AgGridDatasourceParams) => void;
}

interface AgGridDatasourceParams {
    startRow: number;
    endRow: number;
    sortModel?: Array<{ colId: string; sort: 'asc' | 'desc' }>;
    filterModel?: Record<string, unknown>;
    successCallback: (rows: CongressTrade[], lastRow: number) => void;
    failCallback: () => void;
}

interface AgGridColumnApi {
    getAllColumns(): any[];
    getAllDisplayedColumns(): any[];
    autoSizeColumns(colIds: string[], skipHeader?: boolean): void;
}

interface AgGridGlobal {
    createGrid: (element: HTMLElement, options: AgGridOptions) => AgGridApi;
}

interface AgGridOptions {
    columnDefs: AgGridColumnDef[];
    rowData?: CongressTrade[];
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
    onSortChanged?: () => void;
    animateRows?: boolean;
    suppressCellFocus?: boolean;
    overlayLoadingTemplate?: string;
    overlayNoRowsTemplate?: string;
    rowModelType?: 'clientSide' | 'infinite' | 'serverSide' | 'viewport';
    cacheBlockSize?: number;
    maxBlocksInCache?: number;
    infiniteInitialRowCount?: number;
    datasource?: AgGridDatasource;
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
    wrapHeaderText?: boolean;
    autoHeaderHeight?: boolean;
    suppressSizeToFit?: boolean;
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
    Return?: number | null;
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
let resizeFitTimer: number | null = null;

// Model selection
let selectedModel: string | null = null;

// Context preview
let contextPreviewContent: string | null = null;

// Global cache of tickers that don't have logos (to avoid repeated 404s)
const failedLogoCache = new Set<string>();

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
                        failedLogoCache.add(cacheKey);
                        img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="24" height="24"%3E%3C/svg%3E';
                        img.alt = '';
                        img.onerror = null;
                        return;
                    }

                    fallbackAttempted = true;
                    const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${cleanTicker}.png`;
                    if (img.src !== yahooUrl) {
                        img.src = yahooUrl;
                    } else {
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
            tickerSpan.style.color = 'var(--accent-color)';
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
            color = 'var(--theme-info-text)'; // Blue
            if (this.emojiOnly) {
                displayText = '🔵';
            } else if (this.useEmoji) {
                displayText = '🔵 D';
            } else {
                displayText = value || 'N/A';
            }
        } else if (partyLower.includes('republican') || partyLower === 'r') {
            color = 'var(--theme-error-text)'; // Red
            if (this.emojiOnly) {
                displayText = '🔴';
            } else if (this.useEmoji) {
                displayText = '🔴 R';
            } else {
                displayText = value || 'N/A';
            }
        } else if (partyLower.includes('independent') || partyLower === 'i') {
            color = 'var(--theme-warning-text)'; // Purple -> mapped to Warning (or we could use semantic class)
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
        let background = '';

        if (typeLower === 'purchase' || typeLower === 'buy') {
            color = 'var(--theme-success-text)'; // Green
            background = 'var(--color-success-bg)';
            if (this.emojiOnly) {
                displayText = '📈';
            } else if (this.useEmoji) {
                displayText = '📈 Buy';
            } else {
                displayText = value || 'N/A';
            }
        } else if (typeLower === 'sale' || typeLower === 'sell') {
            color = 'var(--theme-error-text)'; // Red
            background = 'var(--color-error-bg)';
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
            this.eGui.style.fontWeight = '600';
            this.eGui.style.display = 'inline-flex';
            this.eGui.style.alignItems = 'center';
            this.eGui.style.justifyContent = 'center';
            this.eGui.style.padding = '2px 8px';
            this.eGui.style.borderRadius = '9999px';
            this.eGui.style.fontSize = '0.75rem';
            if (background) {
                this.eGui.style.backgroundColor = background;
            }
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

    // Load context preview for selected trades
    if (selectedRows && selectedRows.length > 0) {
        const tradeIds: number[] = [];
        for (const row of selectedRows) {
            if (row._trade_id && typeof row._trade_id === 'number') {
                tradeIds.push(row._trade_id);
            }
        }
        if (tradeIds.length > 0) {
            loadContextPreview(tradeIds);
        } else {
            // Hide context preview if no valid trade IDs
            const previewPanel = document.getElementById('congress-context-preview-panel');
            if (previewPanel) {
                previewPanel.classList.add('hidden');
            }
        }
    } else {
        // Hide context preview if no selection
        const previewPanel = document.getElementById('congress-context-preview-panel');
        if (previewPanel) {
            previewPanel.classList.add('hidden');
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

// Model selection functions
function initModelSelect(): void {
    const select = document.getElementById('congress-model-select') as HTMLSelectElement | null;
    if (!select) return;

    select.addEventListener('change', () => {
        selectedModel = select.value;
        saveModelPreference(selectedModel);
    });

    loadModelOptions();
}

function saveModelPreference(model: string): void {
    if (!model) return;

    // Save to localStorage for this page
    localStorage.setItem('congress_trades_model', model);

    // Also save to user preferences
    fetch('/api/settings/ai_model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
        body: JSON.stringify({ model: model })
    }).catch((err: Error) => {
        console.error('Error saving model preference:', err);
    });
}

async function loadModelOptions(): Promise<void> {
    const select = document.getElementById('congress-model-select') as HTMLSelectElement | null;
    if (!select) return;

    try {
        const response = await fetch('/api/v2/ai/models', {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error('Failed to load AI models');
        }

        const data = await response.json();
        const models = data.models || [];

        select.innerHTML = '';
        if (!Array.isArray(models) || models.length === 0) {
            select.innerHTML = '<option value="">No models available</option>';
            return;
        }

        models.forEach((model: { id: string; name: string; type?: string }) => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.name;
            select.appendChild(option);
        });

        // Load saved preference or use default
        const savedModel = localStorage.getItem('congress_trades_model') || data.default_model;
        if (savedModel && models.some((m: { id: string }) => m.id === savedModel)) {
            select.value = savedModel;
            selectedModel = savedModel;
            localStorage.setItem('congress_trades_model', savedModel);
        } else if (select.options.length > 0) {
            select.value = select.options[0].value;
            selectedModel = select.value;
            localStorage.setItem('congress_trades_model', selectedModel);
        }
    } catch (error) {
        console.error('Error loading AI models:', error);
        select.innerHTML = '<option value="">Error loading models</option>';
    }
}

// Context preview functions
async function loadContextPreview(tradeIds: number[]): Promise<void> {
    if (!tradeIds || tradeIds.length === 0) {
        const previewPanel = document.getElementById('congress-context-preview-panel');
        if (previewPanel) {
            previewPanel.classList.add('hidden');
        }
        return;
    }

    const previewPanel = document.getElementById('congress-context-preview-panel');
    const previewContent = document.getElementById('congress-context-preview-content');
    const previewBadge = document.getElementById('congress-context-char-badge');

    if (!previewPanel || !previewContent) return;

    try {
        // Show loading state
        previewContent.textContent = 'Loading context preview...';
        previewPanel.classList.remove('hidden');
        
        // Update toggle button icon
        const toggleBtn = previewPanel.querySelector('button[onclick="toggleContextPreview()"]') as HTMLButtonElement | null;
        if (toggleBtn) {
            toggleBtn.innerHTML = '<i class="fas fa-chevron-up"></i>';
        }

        const response = await fetch('/api/congress_trades/preview_context', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...getCsrfHeaders()
            },
            credentials: 'include',
            body: JSON.stringify({ trade_ids: tradeIds })
        });

        if (!response.ok) {
            throw new Error('Failed to load context preview');
        }

        const result = await response.json();

        if (result.success && result.context) {
            contextPreviewContent = result.context;
            previewContent.textContent = result.context;
            
            // Update character count badge
            if (previewBadge) {
                previewBadge.textContent = `${result.char_count || 0} chars`;
            }
        } else {
            previewContent.textContent = 'No context available';
            if (previewBadge) {
                previewBadge.textContent = '0 chars';
            }
        }
    } catch (error) {
        console.error('Error loading context preview:', error);
        previewContent.textContent = 'Error loading context preview';
        if (previewBadge) {
            previewBadge.textContent = 'Error';
        }
    }
}

function toggleContextPreview(): void {
    const previewPanel = document.getElementById('congress-context-preview-panel');
    const toggleBtn = previewPanel?.querySelector('button[onclick="toggleContextPreview()"]') as HTMLButtonElement | null;
    if (!previewPanel) return;

    const isHidden = previewPanel.classList.contains('hidden');
    if (isHidden) {
        previewPanel.classList.remove('hidden');
        if (toggleBtn) {
            toggleBtn.innerHTML = '<i class="fas fa-chevron-up"></i>';
        }
    } else {
        previewPanel.classList.add('hidden');
        if (toggleBtn) {
            toggleBtn.innerHTML = '<i class="fas fa-chevron-down"></i>';
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
                ...getCsrfHeaders()
            },
            credentials: 'include',
            body: JSON.stringify({ 
                trade_ids: tradeIds,
                model: selectedModel || null
            })
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

const SORTABLE_FIELDS: Record<string, string> = {
    Ticker: 'ticker',
    Politician: 'politician',
    Chamber: 'chamber',
    Party: 'party',
    State: 'state',
    Date: 'transaction_date',
    Type: 'type',
    Amount: 'amount',
    Return: 'pct_change',
    Owner: 'owner'
};

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

    // Check if grid is already initialized - for infinite model, refresh datasource
    if (gridDiv.getAttribute('data-initialized') === 'true') {
        if (gridApi) {
            // For infinite row model, purge cache and set new datasource
            gridApi.purgeInfiniteCache();
            gridApi.setDatasource(createDatasource());
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
            suppressSizeToFit: true,
            pinned: 'left',
            suppressMenu: true,
            sortable: false,
            filter: false,
            resizable: false
        },
        {
            field: 'Ticker',
            headerName: 'Ticker',
            width: 95,
            minWidth: 90,
            suppressSizeToFit: true,
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
            sortable: false,
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
            minWidth: 100,
            flex: 0.6,
            sortable: true,
            filter: true,
            cellRenderer: ChamberCellRenderer
        },
        {
            field: 'Party',
            headerName: 'Party',
            minWidth: 80,
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
            width: 125,
            minWidth: 130,
            suppressSizeToFit: true,
            sortable: true,
            filter: true
        },
        {
            field: 'Type',
            headerName: 'Type',
            width: 100,
            minWidth: 90,
            suppressSizeToFit: true,
            sortable: true,
            filter: true,
            cellRenderer: TypeCellRenderer
        },
        {
            field: 'Amount',
            headerName: '💰 Amount',
            width: 130,
            minWidth: 120,
            suppressSizeToFit: true,
            sortable: true,
            filter: true,
            cellRenderer: AmountCellRenderer,
            tooltipValueGetter: function (params: AgGridParams): string {
                // Show full amount text in tooltip
                return params.value || '';
            }
        },
        {
            field: 'Return',
            headerName: 'Return %',
            width: 100,
            minWidth: 95,
            suppressSizeToFit: true,
            sortable: true,
            filter: true,
            cellRenderer: class {
                private eGui!: HTMLElement;
                init(params: AgGridCellRendererParams) {
                    this.eGui = document.createElement('span');
                    const val = params.value as unknown as number | null;
                    if (val == null) {
                        this.eGui.className = 'text-gray-400 dark:text-gray-500';
                        this.eGui.textContent = '--';
                        return;
                    }
                    const numVal = Number(val);
                    if (isNaN(numVal)) {
                        this.eGui.className = 'text-gray-400 dark:text-gray-500';
                        this.eGui.textContent = '--';
                        return;
                    }
                    const isSale = params.data?.Type === 'Sale';
                    const isPositive = numVal >= 0;
                    const sign = isPositive ? '+' : '';
                    // Sales use cyan/orange to distinguish from purchase green/red
                    const colorClass = isSale
                        ? (isPositive ? 'text-cyan-400' : 'text-orange-400')
                        : (isPositive ? 'text-green-500' : 'text-red-500');
                    this.eGui.className = `font-semibold ${colorClass}`;
                    this.eGui.textContent = `${sign}${numVal.toFixed(1)}%`;
                }
                getGui() { return this.eGui; }
            }
        },
        {
            field: 'Score',
            headerName: 'Score',
            width: 120,
            minWidth: 130,
            suppressSizeToFit: true,
            sortable: false,
            filter: true,
            cellRenderer: ScoreCellRenderer
        },
        {
            field: 'Owner',
            headerName: 'Owner',
            width: 110,
            minWidth: 100,
            suppressSizeToFit: true,
            sortable: true,
            filter: true
        },
        {
            field: 'AI Reasoning',
            headerName: 'AI Reasoning',
            minWidth: 200,
            flex: 4, // Increased from 3 to give more space
            sortable: false,
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

    // Grid options - using infinite row model for server-side pagination
    const gridOptions: AgGridOptions = {
        columnDefs: columnDefs,
        defaultColDef: {
            editable: false,
            sortable: true, // Enable server-side sorting for infinite model
            filter: false, // Disable client-side filtering for infinite model
            resizable: true,
            wrapHeaderText: true,
            autoHeaderHeight: true
        },
        rowSelection: 'multiple',
        enableRangeSelection: true,
        enableCellTextSelection: true,
        ensureDomOrder: true,
        domLayout: 'autoHeight',
        // Infinite row model settings
        rowModelType: 'infinite',
        cacheBlockSize: 100, // Fetch 100 rows at a time
        maxBlocksInCache: 10, // Keep up to 10 blocks (1000 rows) in memory
        infiniteInitialRowCount: 100, // Initial placeholder count
        pagination: true,
        paginationPageSize: 100,
        paginationPageSizeSelector: [100, 250, 500],
        onCellClicked: onCellClicked,
        onSelectionChanged: onSelectionChanged,
        onSortChanged: () => {
            if (gridApi) {
                gridApi.purgeInfiniteCache();
            }
        },
        animateRows: false, // Disable for better infinite scroll performance
        suppressCellFocus: false,
        overlayLoadingTemplate: `
            <div class="flex flex-col items-center justify-center p-8">
                <i class="fas fa-spinner fa-spin text-4xl text-accent mb-4"></i>
                <span class="text-text-secondary">Loading congress trades...</span>
            </div>
        `,
        overlayNoRowsTemplate: `
            <div class="flex flex-col items-center justify-center p-8">
                <i class="fas fa-inbox text-4xl text-text-tertiary mb-4"></i>
                <span class="text-text-secondary">No trades found matching your filters.</span>
            </div>
        `,
        datasource: createDatasource()
    };

    // Create grid
    const gridApiInstance = window.agGrid.createGrid(gridDiv, gridOptions);
    gridApi = gridApiInstance;
    gridColumnApi =
        typeof gridApiInstance.getColumnApi === "function"
            ? gridApiInstance.getColumnApi()
            : ((gridApiInstance as any).columnApi ?? null);
    gridDiv.setAttribute('data-initialized', 'true');

    // Fit columns to viewport width (more reliable than content autosize for infinite model)
    if (gridApi) {
        const fitColumnsToGrid = () => {
            if (!gridApi) return;
            try {
                gridApi.sizeColumnsToFit();
            } catch (err) {
                console.debug('[CongressTrades] sizeColumnsToFit skipped:', err);
            }
        };

        // Initial fit once first rows are rendered
        gridApi.addEventListener('firstDataRendered', () => {
            setTimeout(() => fitColumnsToGrid(), 50);
        });

        // Re-fit when the browser window resizes
        window.addEventListener('resize', () => {
            if (resizeFitTimer) {
                window.clearTimeout(resizeFitTimer);
            }
            resizeFitTimer = window.setTimeout(() => {
                fitColumnsToGrid();
            }, 120);
        });
    }
}

// Fetch stats from API endpoint (aggregated server-side)
async function fetchStats(): Promise<void> {
    const searchParams = new URLSearchParams(window.location.search);

    try {
        const response = await fetch(`/api/congress_trades/stats?${searchParams.toString()}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const stats: CongressTradeStats = await response.json();

        // Render stats
        const setText = (id: string, text: string) => {
            const el = document.getElementById(id);
            if (el) el.textContent = text;
        };

        setText('stat-total-trades', stats.total_trades.toString());
        setText('stat-analyzed', `${stats.analyzed_count}/${stats.total_trades}`);
        setText('stat-house', stats.house_count.toString());
        setText('stat-senate', stats.senate_count.toString());
        setText('stat-buy-sell', `${stats.purchase_count}/${stats.sale_count}`);
        setText('stat-tickers', stats.unique_tickers_count.toString());
        setText('stat-high-risk', stats.high_risk_count.toString());
        setText('stat-most-active', stats.most_active_display);

    } catch (error) {
        console.error('Failed to fetch stats:', error);
        // Show error state in stats
        const setText = (id: string, text: string) => {
            const el = document.getElementById(id);
            if (el) el.textContent = text;
        };
        setText('stat-total-trades', 'Error');
    }
}

// Create a datasource for infinite row model
function createDatasource(): AgGridDatasource {
    const searchParams = new URLSearchParams(window.location.search);

    return {
        getRows: async (params: AgGridDatasourceParams) => {
            const { startRow, endRow, successCallback, failCallback } = params;
            const limit = endRow - startRow;
            const offset = startRow;

            console.log(`[CongressTrades] Fetching rows ${startRow}-${endRow}`);

            try {
                // Show loading overlay
                if (gridApi) {
                    gridApi.showLoadingOverlay();
                }

                // Build API URL with pagination
                const apiParams = new URLSearchParams(searchParams);
                apiParams.set('limit', limit.toString());
                apiParams.set('offset', offset.toString());

                if (params.sortModel && params.sortModel.length > 0) {
                    const { colId, sort } = params.sortModel[0];
                    if (colId && SORTABLE_FIELDS[colId]) {
                        apiParams.set('sort_by', colId);
                        apiParams.set('sort_dir', sort);
                    }
                }

                const response = await fetch(`/api/congress_trades/data?${apiParams.toString()}`);

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data: CongressTradeApiResponse = await response.json();

                if (data.error) {
                    console.error('API Error:', data.error);
                    failCallback();
                    return;
                }

                const trades = data.trades || [];
                const total = data.total || 0;

                console.log(`[CongressTrades] Received ${trades.length} trades (total: ${total})`);

                // Calculate lastRow for AgGrid
                // If we have fewer rows than requested, we've reached the end
                let lastRow = -1; // -1 means unknown/more data available
                if (trades.length < limit || !data.has_more) {
                    lastRow = startRow + trades.length;
                }

                successCallback(trades, lastRow);

            } catch (error) {
                console.error('Failed to fetch trades data:', error);
                failCallback();
            } finally {
                if (gridApi) {
                    gridApi.hideOverlay();
                }
            }
        }
    };
}

// Initialize grid with infinite row model
async function initializeInfiniteGrid(): Promise<void> {
    // First, fetch stats (runs in parallel conceptually)
    fetchStats();

    // Initialize the grid with infinite row model
    initializeCongressTradesGrid([]);
}

// Legacy function for backward compatibility - now uses infinite model
async function fetchTradeData(): Promise<void> {
    await initializeInfiniteGrid();
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
                ...getCsrfHeaders()
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
(window as any).toggleContextPreview = toggleContextPreview;
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
    // Initialize model selection
    initModelSelect();

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
