import { getCsrfHeaders } from "./csrf.js";

export {};

interface WatchlistRow {
  fund?: string;
  ticker: string;
  priority_tier?: string;
  is_active?: boolean;
  source?: string | null;
  created_at?: string | null;
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

function parsePaste(text: string): string[] {
  const parts = text.split(/[\s,;]+/);
  const out: string[] = [];
  const seen = new Set<string>();
  for (const p of parts) {
    const t = p.trim().toUpperCase();
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

function setBulkMsg(text: string, ok: boolean): void {
  const node = el("watchlist-bulk-msg");
  if (!node) return;
  node.textContent = text;
  node.classList.remove("hidden", "text-theme-error-text", "text-green-600");
  node.classList.add(ok ? "text-green-600" : "text-theme-error-text");
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
      return `<tr class="border-b border-border last:border-0" data-ticker="${r.ticker}">
        <td class="py-2 pr-3">
          <a href="/ticker?ticker=${encodeURIComponent(r.ticker)}" class="text-accent hover:underline font-semibold">${r.ticker}</a>
        </td>
        <td class="py-2 pr-3">
          <select data-action="tier" data-ticker="${r.ticker}"
            class="rounded border border-border bg-dashboard-background text-sm px-1 py-0.5">
            ${["A", "B", "C"]
              .map((t) => `<option value="${t}" ${t === tier ? "selected" : ""}>${t}</option>`)
              .join("")}
          </select>
        </td>
        <td class="py-2 pr-3 text-text-secondary">${r.source || "—"}</td>
        <td class="py-2 pr-3">${
          active
            ? '<span class="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">active</span>'
            : '<span class="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200">inactive</span>'
        }</td>
        <td class="py-2 pr-3">
          <button type="button" data-action="${active ? "deactivate" : "activate"}" data-ticker="${r.ticker}"
            class="text-xs text-accent hover:underline mr-2">${active ? "Remove" : "Reactivate"}</button>
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

async function bulkAdd(): Promise<void> {
  const fund = getSelectedFund();
  if (!fund) {
    setBulkMsg("Select a fund first.", false);
    return;
  }
  const input = el("watchlist-bulk-input") as HTMLTextAreaElement | null;
  const tierSel = el("watchlist-bulk-tier") as HTMLSelectElement | null;
  const tickers = parsePaste(input?.value || "");
  if (!tickers.length) {
    setBulkMsg("Enter at least one ticker.", false);
    return;
  }
  const btn = el("watchlist-bulk-add") as HTMLButtonElement | null;
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/api/watchlist", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
      body: JSON.stringify({
        fund,
        tickers,
        priority_tier: tierSel?.value || "B",
        source: "bulk_paste",
      }),
    });
    const body = (await resp.json().catch(() => ({}))) as {
      error?: string;
      added_count?: number;
      failed_tickers?: string[];
    };
    if (!resp.ok) {
      setBulkMsg(body.error || `HTTP ${resp.status}`, false);
      return;
    }
    const failed = body.failed_tickers || [];
    setBulkMsg(
      failed.length
        ? `Added ${body.added_count ?? 0}; failed: ${failed.join(", ")}`
        : `Added ${body.added_count ?? tickers.length} ticker(s).`,
      failed.length === 0
    );
    if (input) input.value = "";
    await loadList();
  } finally {
    if (btn) btn.disabled = false;
  }
}

function init(): void {
  el("watchlist-bulk-add")?.addEventListener("click", () => void bulkAdd());
  el("watchlist-show-inactive")?.addEventListener("change", () => void loadList());
  window.addEventListener("fundChanged", () => void loadList());
  void loadList();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
