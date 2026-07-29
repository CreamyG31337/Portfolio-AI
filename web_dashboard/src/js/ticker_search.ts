/**
 * Shared ticker/company search dropdown (Enter-to-search via /api/v2/ticker/search).
 * Used by ticker details and watchlist.
 */

export interface TickerSearchResult {
  symbol: string;
  name: string;
  exchange: string;
  type: string;
}

interface TickerSearchResponse {
  results: TickerSearchResult[];
  exact_match: boolean;
  error?: string;
}

export interface TickerSearchConfig {
  inputId: string;
  resultsId: string;
  spinnerId?: string;
  searchUrl?: string;
  appendFundParam?: (url: string) => string;
  clearInputOnSelect?: boolean;
  onSelect: (symbol: string, result?: TickerSearchResult) => void;
}

export function setupTickerSearch(config: TickerSearchConfig): void {
  const input = document.getElementById(config.inputId) as HTMLInputElement | null;
  const resultsPanel = document.getElementById(config.resultsId) as HTMLDivElement | null;
  const spinner = config.spinnerId
    ? (document.getElementById(config.spinnerId) as HTMLDivElement | null)
    : null;

  if (!input || !resultsPanel) {
    console.error("Ticker search: could not find input or results panel", config.inputId, config.resultsId);
    return;
  }

  const baseSearchUrl = config.searchUrl || "/api/v2/ticker/search";
  let lastResults: TickerSearchResult[] = [];
  let selectedIdx = -1;

  function selectTicker(symbol: string, result?: TickerSearchResult): void {
    if (config.clearInputOnSelect) {
      input!.value = "";
    } else {
      input!.value = symbol;
    }
    hideResults();
    selectedIdx = -1;
    config.onSelect(symbol, result);
  }

  function hideResults(): void {
    resultsPanel!.classList.add("hidden");
    resultsPanel!.innerHTML = "";
    lastResults = [];
  }

  function showResults(results: TickerSearchResult[]): void {
    lastResults = results;
    resultsPanel!.innerHTML = "";

    if (results.length === 0) {
      const noResults = document.createElement("div");
      noResults.className = "px-4 py-3 text-text-secondary text-sm";
      noResults.textContent = "No results found. Try a different search term.";
      resultsPanel!.appendChild(noResults);
      resultsPanel!.classList.remove("hidden");
      return;
    }

    results.forEach((result, idx) => {
      const item = document.createElement("div");
      item.className =
        "px-4 py-3 cursor-pointer hover:bg-dashboard-background border-b border-border last:border-b-0 flex items-center gap-3";
      item.dataset.symbol = result.symbol;
      item.dataset.idx = String(idx);

      const symbolSpan = document.createElement("span");
      symbolSpan.className =
        "font-semibold text-accent bg-accent/10 px-2 py-0.5 rounded text-sm min-w-[60px] text-center";
      symbolSpan.textContent = result.symbol;
      item.appendChild(symbolSpan);

      const infoDiv = document.createElement("div");
      infoDiv.className = "flex flex-col min-w-0";

      const nameSpan = document.createElement("span");
      nameSpan.className = "text-text-primary text-sm truncate";
      nameSpan.textContent = result.name || result.symbol;
      infoDiv.appendChild(nameSpan);

      if (result.exchange || result.type) {
        const metaSpan = document.createElement("span");
        metaSpan.className = "text-text-secondary text-xs";
        const parts: string[] = [];
        if (result.exchange) parts.push(result.exchange);
        if (result.type) parts.push(result.type);
        metaSpan.textContent = parts.join(" \u00b7 ");
        infoDiv.appendChild(metaSpan);
      }

      item.appendChild(infoDiv);

      // mousedown fires before blur — do not change to click
      item.addEventListener("mousedown", (e) => {
        e.preventDefault();
        selectTicker(result.symbol, result);
      });

      resultsPanel!.appendChild(item);
    });

    resultsPanel!.classList.remove("hidden");
  }

  async function performSearch(query: string): Promise<void> {
    if (!query) return;

    if (spinner) spinner.classList.remove("hidden");

    try {
      let searchUrl = `${baseSearchUrl}?q=${encodeURIComponent(query)}`;
      if (config.appendFundParam) {
        searchUrl = config.appendFundParam(searchUrl);
      }

      const response = await fetch(searchUrl, { credentials: "include" });
      if (!response.ok) {
        throw new Error(`Search failed: ${response.status}`);
      }

      const data = (await response.json()) as TickerSearchResponse;

      if (data.exact_match && data.results.length > 0) {
        selectTicker(data.results[0].symbol, data.results[0]);
        return;
      }

      showResults(data.results || []);
    } catch (error) {
      console.error("Ticker search error:", error);
      resultsPanel!.innerHTML = "";
      const errDiv = document.createElement("div");
      errDiv.className = "px-4 py-3 text-theme-error-text text-sm";
      errDiv.textContent = "Search failed. Please try again.";
      resultsPanel!.appendChild(errDiv);
      resultsPanel!.classList.remove("hidden");
    } finally {
      if (spinner) spinner.classList.add("hidden");
    }
  }

  input.addEventListener("keydown", (e) => {
    const items = resultsPanel!.querySelectorAll("[data-symbol]");

    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!resultsPanel!.classList.contains("hidden") && items.length > 0) {
        selectedIdx = Math.min(selectedIdx + 1, items.length - 1);
        updateHighlight(items);
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!resultsPanel!.classList.contains("hidden") && items.length > 0) {
        selectedIdx = Math.max(selectedIdx - 1, -1);
        updateHighlight(items);
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (selectedIdx >= 0 && items[selectedIdx]) {
        const idx = Number((items[selectedIdx] as HTMLElement).dataset.idx);
        const result = Number.isFinite(idx) ? lastResults[idx] : undefined;
        const sym = (items[selectedIdx] as HTMLElement).dataset.symbol || "";
        selectTicker(sym, result);
      } else {
        const query = input.value.trim();
        if (query) {
          selectedIdx = -1;
          void performSearch(query);
        }
      }
    } else if (e.key === "Escape") {
      hideResults();
      selectedIdx = -1;
    }
  });

  function updateHighlight(items: NodeListOf<Element>): void {
    items.forEach((item, idx) => {
      if (idx === selectedIdx) {
        item.classList.add("bg-dashboard-background");
      } else {
        item.classList.remove("bg-dashboard-background");
      }
    });
    if (selectedIdx >= 0 && items[selectedIdx]) {
      items[selectedIdx].scrollIntoView({ block: "nearest" });
    }
  }

  document.addEventListener("click", (e) => {
    if (!input.contains(e.target as Node) && !resultsPanel!.contains(e.target as Node)) {
      hideResults();
      selectedIdx = -1;
    }
  });
}
