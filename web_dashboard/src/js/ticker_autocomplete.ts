export { }; // Ensure file is treated as a module

// API Response interface
interface TickerListResponse {
    tickers: string[];
}

// Configuration interface for autocomplete setup
interface TickerAutocompleteConfig {
    inputId: string;
    dropdownId: string;
    hiddenInputId?: string;
    onSelect?: (ticker: string) => void;
    allowAll?: boolean;
    initialValue?: string;
    tickerListUrl?: string;
    appendFundParam?: (url: string) => string;
}

// Global ticker list cache
let tickerListCache: string[] = [];
let tickerListLoaded: boolean = false;

/**
 * Load ticker list from API endpoint
 */
async function loadTickerList(url: string = '/api/v2/ticker/list', appendFundParam?: (url: string) => string): Promise<string[]> {
    if (tickerListLoaded && tickerListCache.length > 0) {
        return tickerListCache;
    }

    try {
        const finalUrl = appendFundParam ? appendFundParam(url) : url;
        const response = await fetch(finalUrl, {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error('Failed to load ticker list');
        }

        const data: TickerListResponse = await response.json();
        tickerListCache = data.tickers || [];
        tickerListLoaded = true;
        return tickerListCache;
    } catch (error) {
        console.error('Error loading ticker list:', error);
        return [];
    }
}

/**
 * Set up ticker autocomplete on an input element
 */
export function setupTickerAutocomplete(config: TickerAutocompleteConfig): void {
    const {
        inputId,
        dropdownId,
        hiddenInputId,
        onSelect,
        allowAll = false,
        initialValue,
        tickerListUrl = '/api/v2/ticker/list',
        appendFundParam
    } = config;

    const inputEl = document.getElementById(inputId) as HTMLInputElement | null;
    const dropdownEl = document.getElementById(dropdownId) as HTMLDivElement | null;
    const hiddenInputEl = hiddenInputId ? document.getElementById(hiddenInputId) as HTMLInputElement | null : null;

    if (!inputEl || !dropdownEl) {
        console.error(`Ticker autocomplete: Could not find input (${inputId}) or dropdown (${dropdownId})`);
        return;
    }

    // Store references to guarantee non-null in nested functions
    const input: HTMLInputElement = inputEl;
    const dropdown: HTMLDivElement = dropdownEl;
    const hiddenInput: HTMLInputElement | null = hiddenInputEl;
    let selectedIndex = -1;
    let tickerList: string[] = [];

    // Set initial value if provided
    if (initialValue) {
        input.value = initialValue;
        if (hiddenInput) {
            hiddenInput.value = initialValue;
        }
    }

    // Load ticker list
    loadTickerList(tickerListUrl, appendFundParam).then((list) => {
        tickerList = list;
    });

    // Handle input changes
    input.addEventListener('input', () => {
        const query = input.value.toUpperCase().trim();
        
        // Handle "All" option if allowed
        if (allowAll && (query.length === 0 || query === 'ALL')) {
            if (hiddenInput) {
                hiddenInput.value = 'All';
            }
            hideAutocomplete();
            return;
        }

        if (query.length === 0) {
            hideAutocomplete();
            return;
        }

        // Filter tickers that start with the query
        const matches = tickerList.filter(t => t.toUpperCase().startsWith(query)).slice(0, 20);
        
        if (matches.length === 0) {
            hideAutocomplete();
            return;
        }

        selectedIndex = -1;
        showAutocomplete(matches);
    });

    // Handle keyboard navigation
    input.addEventListener('keydown', (e) => {
        const items = dropdown.querySelectorAll('[data-ticker]');
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
            updateSelection(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIndex = Math.max(selectedIndex - 1, -1);
            updateSelection(items);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (selectedIndex >= 0 && items[selectedIndex]) {
                selectTicker((items[selectedIndex] as HTMLElement).dataset.ticker || '');
            } else if (input.value.trim()) {
                const value = input.value.toUpperCase().trim();
                if (allowAll && value === 'ALL') {
                    selectTicker('All');
                } else {
                    selectTicker(value);
                }
            }
        } else if (e.key === 'Escape') {
            hideAutocomplete();
        }
    });

    // Handle blur (delayed to allow click on dropdown)
    input.addEventListener('blur', () => {
        setTimeout(() => hideAutocomplete(), 150);
    });

    // Focus shows dropdown if there's input
    input.addEventListener('focus', () => {
        const query = input.value.toUpperCase().trim();
        if (query.length > 0 && query !== 'ALL') {
            const matches = tickerList.filter(t => t.toUpperCase().startsWith(query)).slice(0, 20);
            if (matches.length > 0) {
                showAutocomplete(matches);
            }
        }
    });

    function showAutocomplete(matches: string[]): void {
        dropdown.innerHTML = '';
        
        // Add "All" option if allowed and no query or query is "all"
        if (allowAll && (input.value.trim().length === 0 || input.value.toUpperCase().trim() === 'ALL')) {
            const allItem = document.createElement('div');
            allItem.className = 'px-4 py-2 cursor-pointer hover:bg-dashboard-background text-text-primary';
            allItem.dataset.ticker = 'All';
            allItem.textContent = 'All Tickers';
            allItem.addEventListener('mousedown', (e) => {
                e.preventDefault();
                selectTicker('All');
            });
            dropdown.appendChild(allItem);
        }

        matches.forEach((ticker) => {
            const item = document.createElement('div');
            item.className = 'px-4 py-2 cursor-pointer hover:bg-dashboard-background text-text-primary';
            item.dataset.ticker = ticker;
            item.textContent = ticker;
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                selectTicker(ticker);
            });
            dropdown.appendChild(item);
        });
        dropdown.classList.remove('hidden');
    }

    function hideAutocomplete(): void {
        dropdown.classList.add('hidden');
        selectedIndex = -1;
    }

    function updateSelection(items: NodeListOf<Element>): void {
        items.forEach((item, idx) => {
            if (idx === selectedIndex) {
                item.classList.add('bg-dashboard-background');
            } else {
                item.classList.remove('bg-dashboard-background');
            }
        });
        // Scroll into view
        if (selectedIndex >= 0 && items[selectedIndex]) {
            items[selectedIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    function selectTicker(ticker: string): void {
        if (ticker === 'All' && allowAll) {
            input.value = '';
        } else {
            input.value = ticker;
        }
        
        // Update hidden input if present
        if (hiddenInput) {
            hiddenInput.value = ticker;
        }
        
        hideAutocomplete();

        // Call custom callback if provided
        if (onSelect) {
            onSelect(ticker);
        }
    }
}
