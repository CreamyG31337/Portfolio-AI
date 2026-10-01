// Global ticker list cache
let tickerListCache = [];
let tickerNamesCache = {};
let tickerListLoaded = false;
let tickerListPending = null;
/**
 * Load ticker list from API endpoint, with deduplication and retry
 */
async function loadTickerList(url = '/api/v2/ticker/list', appendFundParam, withNames = false) {
    if (tickerListLoaded && tickerListCache.length > 0) {
        return { tickers: tickerListCache, names: tickerNamesCache };
    }
    // Deduplicate concurrent calls — share the same in-flight promise
    if (tickerListPending) {
        return tickerListPending;
    }
    const fetchOnce = async () => {
        let finalUrl = withNames ? `${url}${url.includes('?') ? '&' : '?'}with_names=1` : url;
        finalUrl = appendFundParam ? appendFundParam(finalUrl) : finalUrl;
        // Retry up to 2 times for transient errors (e.g. token refresh in progress)
        const MAX_RETRIES = 2;
        for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            try {
                if (attempt > 0) {
                    await new Promise(resolve => setTimeout(resolve, attempt * 1000));
                }
                const response = await fetch(finalUrl, { credentials: 'include' });
                if (!response.ok) {
                    throw new Error(`Failed to load ticker list (HTTP ${response.status})`);
                }
                const data = await response.json();
                tickerListCache = data.tickers || [];
                tickerNamesCache = data.ticker_names || {};
                tickerListLoaded = true;
                return { tickers: tickerListCache, names: tickerNamesCache };
            }
            catch (error) {
                if (attempt === MAX_RETRIES) {
                    console.error('Error loading ticker list:', error);
                    return { tickers: [], names: {} };
                }
            }
        }
        return { tickers: [], names: {} };
    };
    tickerListPending = fetchOnce().finally(() => { tickerListPending = null; });
    return tickerListPending;
}
/**
 * Get the cached company name for a ticker (if available)
 */
export function getCompanyName(ticker) {
    return tickerNamesCache[ticker.toUpperCase()];
}
/**
 * Set up ticker autocomplete on an input element
 */
export function setupTickerAutocomplete(config) {
    const { inputId, dropdownId, hiddenInputId, onSelect, allowAll = false, initialValue, tickerListUrl = '/api/v2/ticker/list', appendFundParam, showCompanyNames = false } = config;
    const inputEl = document.getElementById(inputId);
    const dropdownEl = document.getElementById(dropdownId);
    const hiddenInputEl = hiddenInputId ? document.getElementById(hiddenInputId) : null;
    if (!inputEl || !dropdownEl) {
        console.error(`Ticker autocomplete: Could not find input (${inputId}) or dropdown (${dropdownId})`);
        return;
    }
    // Store references to guarantee non-null in nested functions
    const input = inputEl;
    const dropdown = dropdownEl;
    const hiddenInput = hiddenInputEl;
    let selectedIndex = -1;
    let tickerList = [];
    let tickerNames = {};
    // Set initial value if provided
    if (initialValue) {
        input.value = initialValue;
        if (hiddenInput) {
            hiddenInput.value = initialValue;
        }
    }
    // Load ticker list (with names if configured)
    loadTickerList(tickerListUrl, appendFundParam, showCompanyNames).then((result) => {
        tickerList = result.tickers;
        tickerNames = result.names;
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
        // Filter tickers that start with the query, or whose company name contains the query
        const matches = tickerList.filter(t => {
            if (t.toUpperCase().startsWith(query))
                return true;
            if (showCompanyNames && tickerNames[t.toUpperCase()]) {
                return tickerNames[t.toUpperCase()].toUpperCase().includes(query);
            }
            return false;
        }).slice(0, 20);
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
        }
        else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIndex = Math.max(selectedIndex - 1, -1);
            updateSelection(items);
        }
        else if (e.key === 'Enter') {
            e.preventDefault();
            if (selectedIndex >= 0 && items[selectedIndex]) {
                selectTicker(items[selectedIndex].dataset.ticker || '');
            }
            else if (input.value.trim()) {
                const value = input.value.toUpperCase().trim();
                if (allowAll && value === 'ALL') {
                    selectTicker('All');
                }
                else {
                    selectTicker(value);
                }
            }
        }
        else if (e.key === 'Escape') {
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
            const matches = tickerList.filter(t => {
                if (t.toUpperCase().startsWith(query))
                    return true;
                if (showCompanyNames && tickerNames[t.toUpperCase()]) {
                    return tickerNames[t.toUpperCase()].toUpperCase().includes(query);
                }
                return false;
            }).slice(0, 20);
            if (matches.length > 0) {
                showAutocomplete(matches);
            }
        }
    });
    function showAutocomplete(matches) {
        dropdown.innerHTML = '';
        // Add "All" option if allowed and no query or query is "all"
        if (allowAll && (input.value.trim().length === 0 || input.value.toUpperCase().trim() === 'ALL')) {
            const allItem = document.createElement('div');
            allItem.className = 'px-4 py-2 cursor-pointer hover:bg-dashboard-background text-text-primary';
            allItem.dataset.ticker = 'All';
            allItem.setAttribute('role', 'option');
            allItem.id = 'ticker-option-all';
            allItem.textContent = 'All Tickers';
            allItem.addEventListener('mousedown', (e) => {
                e.preventDefault();
                selectTicker('All');
            });
            dropdown.appendChild(allItem);
        }
        matches.forEach((ticker) => {
            const item = document.createElement('div');
            item.className = 'px-4 py-2 cursor-pointer hover:bg-dashboard-background text-text-primary flex items-center justify-between gap-2';
            item.dataset.ticker = ticker;
            item.setAttribute('role', 'option');
            item.id = `ticker-option-${ticker}`;
            const tickerSpan = document.createElement('span');
            tickerSpan.className = 'font-semibold';
            tickerSpan.textContent = ticker;
            item.appendChild(tickerSpan);
            // Show company name if available
            const companyName = tickerNames[ticker.toUpperCase()];
            if (showCompanyNames && companyName) {
                const nameSpan = document.createElement('span');
                nameSpan.className = 'text-text-secondary text-xs truncate ml-2';
                nameSpan.textContent = companyName;
                item.appendChild(nameSpan);
            }
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                selectTicker(ticker);
            });
            dropdown.appendChild(item);
        });
        dropdown.classList.remove('hidden');
        input.setAttribute('aria-expanded', 'true');
    }
    function hideAutocomplete() {
        dropdown.classList.add('hidden');
        input.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-activedescendant');
        selectedIndex = -1;
    }
    function updateSelection(items) {
        items.forEach((item, idx) => {
            if (idx === selectedIndex) {
                item.classList.add('bg-dashboard-background');
                item.setAttribute('aria-selected', 'true');
                if (item.id) {
                    input.setAttribute('aria-activedescendant', item.id);
                }
            }
            else {
                item.classList.remove('bg-dashboard-background');
                item.removeAttribute('aria-selected');
            }
        });
        // Scroll into view
        if (selectedIndex >= 0 && items[selectedIndex]) {
            items[selectedIndex].scrollIntoView({ block: 'nearest' });
        }
    }
    function selectTicker(ticker) {
        if (ticker === 'All' && allowAll) {
            input.value = '';
        }
        else {
            input.value = ticker;
        }
        // Update hidden input if present
        if (hiddenInput) {
            hiddenInput.value = ticker;
        }
        hideAutocomplete();
        // Call custom callback if provided (include company name)
        if (onSelect) {
            const companyName = tickerNames[ticker.toUpperCase()];
            onSelect(ticker, companyName);
        }
    }
}
//# sourceMappingURL=ticker_autocomplete.js.map