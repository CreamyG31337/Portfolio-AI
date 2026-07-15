import { getCsrfHeaders } from "./csrf.js";
import { setupTickerSearch } from "./ticker_search.js";

export {};

interface WatchlistRow {
  fund?: string;
  ticker: string;
  priority_tier?: string;
  is_active?: boolean;
  source?: string | null;
  created_at?: string | null;
  analyzed?: boolean;
  analysis_date?: string | null;
  analysis_updated_at?: string | null;
  sentiment?: string | null;
  stance?: string | null;
  confidence_score?: number | null;
  summary_snippet?: string | null;
  has_meta?: boolean;
  meta_conviction?: string | null;
  meta_updated_at?: string | null;
  queue_status?: string | null;
  dossier_url?: string | null;
}

function el(id: string): HTMLElement | null {
  return document.getElementById(id);
}

function getSelectedFund(): string | null {
  const fromUi = (
    window as unknown as { ui?: { getSelectedFund?: () => string | null } }
  ).ui?.getSelectedFund?.();
  if (fromUi) return fromUi;
  const sel = document.getElementById("global-fund-select") as HTMLSelectElement | null;
  const v = (sel?.value || "").trim();
  if (!v || v.toLowerCase() === "all") return null;
  return v;
}

function formatShortDate(raw: string | null | undefined): string {
  if (!raw) return "";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) {
    return String(raw).slice(0, 10);
  }
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setMsg(id: string, text: string, ok: boolean): void {
  const node = el(id);
  if (!node) return;
  node.textContent = text;
  node.classList.remove("hidden", "text-theme-error-text", "text-green-600");
  node.classList.add(ok ? "text-green-600" : "text-theme-error-text");
}

function setAddMsg(text: string, ok: boolean): void {
  setMsg("watchlist-add-msg", text, ok);
}

function analysisBadge(r: WatchlistRow): string {
  if (r.queue_status === "leased") {
    return '<span class="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100">running</span>';
  }
  if (r.queue_status === "pending") {
    return '<span class="text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-900 dark:bg-blue-900 dark:text-blue-100">queued</span>';
  }
  if (r.analyzed) {
    const when = formatShortDate(r.analysis_date || r.analysis_updated_at);
    const stance = r.stance || r.sentiment || "";
    return `<span class="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">analyzed</span>
      <span class="text-xs text-text-secondary ml-1">${escapeHtml(when)}${stance ? ` · ${escapeHtml(stance)}` : ""}</span>`;
  }
  return '<span class="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200">not analyzed</span>';
}

function metaBadge(r: WatchlistRow): string {
  if (!r.has_meta) {
    return '<span class="text-xs text-text-secondary">—</span>';
  }
  const when = formatShortDate(r.meta_updated_at);
  const conv = r.meta_conviction || "meta";
  return `<span class="text-xs px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-900 dark:bg-indigo-900 dark:text-indigo-100">${escapeHtml(conv)}</span>
    <span class="text-xs text-text-secondary ml-1">${escapeHtml(when)}</span>`;
}

async function patchItem(
  fund: string,
  ticker: string,
  patch: { is_active?: boolean; priority_tier?: string }
): Promise<boolean> {
  const resp = await fetch("/api/watchlist/item", {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
    body: JSON.stringify({ fund, ticker, ...patch }),
  });
  if (!resp.ok) {
    const body = (await resp.json().catch(() => ({}))) as { error?: string };
    alert(body.error || `HTTP ${resp.status}`);
    return false;
  }
  return true;
}

async function enqueueAnalyze(fund: string, tickers: string[]): Promise<boolean> {
  const resp = await fetch("/api/watchlist/analyze", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
    body: JSON.stringify({ fund, tickers, include_meta: true }),
  });
  const body = (await resp.json().catch(() => ({}))) as {
    error?: string;
    enqueued?: number;
  };
  if (!resp.ok) {
    setMsg("watchlist-analyze-msg", body.error || `HTTP ${resp.status}`, false);
    return false;
  }
  setMsg(
    "watchlist-analyze-msg",
    `Queued ${body.enqueued ?? tickers.length} ticker(s). Refresh in a few minutes; open dossier to read results.`,
    true
  );
  return true;
}

async function addTicker(symbol: string): Promise<void> {
  const fund = getSelectedFund();
  if (!fund) {
    setAddMsg("Select a fund first.", false);
    return;
  }
  const ticker = symbol.trim().toUpperCase();
  if (!ticker) return;
  const tierSel = el("watchlist-add-tier") as HTMLSelectElement | null;
  try {
    const resp = await fetch("/api/watchlist", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
      body: JSON.stringify({
        fund,
        tickers: [ticker],
        priority_tier: tierSel?.value || "B",
        source: "watchlist_search",
      }),
    });
    const body = (await resp.json().catch(() => ({}))) as {
      error?: string;
      failed_tickers?: string[];
    };
    if (!resp.ok) {
      setAddMsg(body.error || `HTTP ${resp.status}`, false);
      return;
    }
    const failed = body.failed_tickers || [];
    if (failed.length) {
      setAddMsg(`Could not add ${failed.join(", ")}`, false);
    } else {
      setAddMsg(`Added ${ticker}.`, true);
    }
    await loadList();
  } catch (e) {
    setAddMsg(e instanceof Error ? e.message : String(e), false);
  }
}

function renderRows(fund: string, rows: WatchlistRow[]): void {
  const tbody = el("watchlist-tbody");
  const wrap = el("watchlist-table-wrap");
  const empty = el("watchlist-empty");
  const count = el("watchlist-count");
  if (!tbody || !wrap || !empty) return;

  const activeCount = rows.filter((r) => r.is_active).length;
  if (count) count.textContent = `(${activeCount} active)`;

  if (!rows.length) {
    wrap.classList.add("hidden");
    empty.classList.remove("hidden");
    tbody.innerHTML = "";
    return;
  }
  empty.classList.add("hidden");
  wrap.classList.remove("hidden");
  tbody.innerHTML = rows
    .map((r) => {
      const tier = r.priority_tier || "B";
      const active = !!r.is_active;
      const href = r.dossier_url || `/ticker?ticker=${encodeURIComponent(r.ticker)}`;
      const preview = r.summary_snippet
        ? `<span class="text-xs text-text-secondary line-clamp-2 max-w-xs inline-block" title="${escapeHtml(r.summary_snippet)}">${escapeHtml(r.summary_snippet)}</span>`
        : '<span class="text-xs text-text-secondary">—</span>';
      return `<tr class="border-b border-border last:border-0 align-top" data-ticker="${r.ticker}">
        <td class="py-2 pr-3">
          <a href="${href}" class="text-accent hover:underline font-semibold">${r.ticker}</a>
          <div class="text-xs text-text-secondary mt-0.5">${escapeHtml(r.source || "—")}</div>
        </td>
        <td class="py-2 pr-3">
          <select data-action="tier" data-ticker="${r.ticker}"
            class="rounded border border-border bg-dashboard-background text-sm px-1 py-0.5">
            ${["A", "B", "C"]
              .map((t) => `<option value="${t}" ${t === tier ? "selected" : ""}>${t}</option>`)
              .join("")}
          </select>
        </td>
        <td class="py-2 pr-3">${analysisBadge(r)}</td>
        <td class="py-2 pr-3">${metaBadge(r)}</td>
        <td class="py-2 pr-3">${preview}</td>
        <td class="py-2 pr-3">${
          active
            ? '<span class="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">active</span>'
            : '<span class="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200">inactive</span>'
        }</td>
        <td class="py-2 pr-3 whitespace-nowrap">
          <a href="${href}" class="text-xs text-accent hover:underline mr-2">Open dossier</a>
          <button type="button" data-action="analyze" data-ticker="${r.ticker}"
            class="text-xs text-accent hover:underline mr-2">Analyze</button>
          <button type="button" data-action="${active ? "deactivate" : "activate"}" data-ticker="${r.ticker}"
            class="text-xs text-text-secondary hover:underline">${active ? "Remove" : "Reactivate"}</button>
        </td>
      </tr>`;
    })
    .join("");

  tbody.querySelectorAll("[data-action]").forEach((node) => {
    const btn = node as HTMLElement;
    const action = btn.getAttribute("data-action");
    const ticker = btn.getAttribute("data-ticker") || "";
    if (action === "tier" && btn instanceof HTMLSelectElement) {
      btn.addEventListener("change", async () => {
        const ok = await patchItem(fund, ticker, { priority_tier: btn.value });
        if (ok) void loadList();
      });
      return;
    }
    btn.addEventListener("click", async () => {
      if (action === "deactivate") {
        const ok = await patchItem(fund, ticker, { is_active: false });
        if (ok) void loadList();
      } else if (action === "activate") {
        const ok = await patchItem(fund, ticker, { is_active: true });
        if (ok) void loadList();
      } else if (action === "analyze") {
        const ok = await enqueueAnalyze(fund, [ticker]);
        if (ok) void loadList();
      }
    });
  });
}

async function loadList(): Promise<void> {
  const fund = getSelectedFund();
  const fundLabel = el("watchlist-fund-label");
  const loading = el("watchlist-loading");
  const err = el("watchlist-error");
  if (fundLabel) fundLabel.textContent = fund || "(select a fund)";
  if (!fund) {
    if (loading) loading.classList.add("hidden");
    if (err) {
      err.textContent = "Select a fund in the sidebar to manage its watchlist.";
      err.classList.remove("hidden");
    }
    return;
  }
  if (err) err.classList.add("hidden");
  if (loading) {
    loading.textContent = "Loading…";
    loading.classList.remove("hidden");
  }
  const showInactive = (el("watchlist-show-inactive") as HTMLInputElement | null)?.checked;
  try {
    const qs = new URLSearchParams({
      fund,
      include_inactive: showInactive ? "1" : "0",
    });
    const resp = await fetch(`/api/watchlist?${qs}`, { credentials: "include" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = (await resp.json()) as { data?: WatchlistRow[] };
    if (loading) loading.classList.add("hidden");
    renderRows(fund, body.data || []);
  } catch (e) {
    if (loading) loading.classList.add("hidden");
    if (err) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.classList.remove("hidden");
    }
  }
}

async function analyzeAllActive(): Promise<void> {
  const fund = getSelectedFund();
  if (!fund) {
    setMsg("watchlist-analyze-msg", "Select a fund first.", false);
    return;
  }
  const tickers = Array.from(
    document.querySelectorAll("#watchlist-tbody tr[data-ticker]")
  )
    .map((n) => n.getAttribute("data-ticker") || "")
    .filter(Boolean);
  if (!tickers.length) {
    setMsg("watchlist-analyze-msg", "No tickers to analyze.", false);
    return;
  }
  const btn = el("watchlist-analyze-all") as HTMLButtonElement | null;
  if (btn) btn.disabled = true;
  try {
    const ok = await enqueueAnalyze(fund, tickers);
    if (ok) await loadList();
  } finally {
    if (btn) btn.disabled = false;
  }
}

function init(): void {
  setupTickerSearch({
    inputId: "watchlist-search-input",
    resultsId: "watchlist-search-results",
    spinnerId: "watchlist-search-spinner",
    clearInputOnSelect: true,
    onSelect: (symbol) => void addTicker(symbol),
  });
  el("watchlist-show-inactive")?.addEventListener("change", () => void loadList());
  el("watchlist-analyze-all")?.addEventListener("click", () => void analyzeAllActive());
  window.addEventListener("fundChanged", () => void loadList());
  void loadList();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
