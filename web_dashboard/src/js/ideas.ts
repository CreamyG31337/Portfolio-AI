import { getCsrfHeaders } from "./csrf.js";

export {};

interface ThesisAttentionFlag {
  thesis_id: string;
  title?: string;
  disposition?: string;
  intent?: string;
  review_status?: string | null;
  llm_verdict?: string | null;
  is_weak?: boolean;
  attention_reasons?: string[];
}

interface IdeaRow {
  id: string;
  title: string;
  article_type?: string;
  source?: string;
  relevance_score?: number;
  tickers?: string[];
  summary?: string;
  thesis_attention?: ThesisAttentionFlag[];
}

let loadSeq = 0;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

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

function currentTickerFilter(): string {
  const input = document.getElementById("ideas-ticker-filter") as HTMLInputElement | null;
  return (input?.value || "").trim().toUpperCase();
}

function setFilterStatus(text: string): void {
  const el = document.getElementById("ideas-filter-status");
  if (el) el.textContent = text;
}

async function triage(
  articleId: string,
  status: "accepted" | "dismissed" | "snoozed",
  tickers: string[],
  queueAnalysis = false
): Promise<boolean> {
  const fund = getSelectedFund();
  if (status === "accepted" && tickers.length && !fund) {
    alert("Select a fund in the sidebar before accepting into the watchlist.");
    return false;
  }
  const resp = await fetch("/api/ideas/triage", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
    body: JSON.stringify({
      article_id: articleId,
      status,
      fund,
      tickers,
      queue_analysis: queueAnalysis,
    }),
  });
  if (!resp.ok) {
    const body = (await resp.json().catch(() => ({}))) as { error?: string };
    alert(`Triage failed: ${body.error || `HTTP ${resp.status}`}`);
    return false;
  }
  const body = (await resp.json()) as {
    failed_tickers?: string[];
    analysis_enqueue?: { enqueued?: number; ok?: boolean };
  };
  if (body.failed_tickers?.length) {
    alert(
      `Saved, but these tickers could not be added to the watchlist: ${body.failed_tickers.join(", ")}`
    );
  }
  if (queueAnalysis && body.analysis_enqueue?.ok) {
    const n = body.analysis_enqueue.enqueued ?? tickers.length;
    alert(
      `Queued ASAP analysis for ${n} ticker(s). Open Watchlist or the ticker dossier when workers finish.`
    );
  }
  return true;
}

function thesisBadgeHtml(flags: ThesisAttentionFlag[] | undefined): string {
  if (!flags?.length) return "";
  return flags
    .slice(0, 3)
    .map((f) => {
      const reasons =
        (f.attention_reasons || []).join(", ") || f.llm_verdict || f.review_status || "due";
      const href = `/insights?thesis=${encodeURIComponent(f.thesis_id)}`;
      return `<a href="${href}" class="inline-block ml-1 text-xs px-1.5 py-0.5 rounded border border-amber-500/40 text-amber-700 dark:text-amber-400 hover:underline" title="${escapeAttr(f.title || "")}">thesis: ${escapeAttr(String(reasons))}</a>`;
    })
    .join("");
}

function escapeAttr(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function renderIdeas(rows: IdeaRow[], filter: string): void {
  const list = document.getElementById("ideas-list");
  const loading = document.getElementById("ideas-loading");
  if (loading) loading.classList.add("hidden");
  if (!list) return;
  if (!rows.length) {
    list.innerHTML = filter
      ? `<p class="text-sm text-text-secondary">No open ideas matching ticker prefix “${escapeAttr(filter)}”.</p>`
      : `<p class="text-sm text-text-secondary">Inbox empty — check back after the next alpha run.</p>`;
    setFilterStatus(filter ? `0 matches for ${filter}` : "");
    return;
  }
  setFilterStatus(
    filter
      ? `${rows.length} match${rows.length === 1 ? "" : "es"} for ${filter}${rows.length >= 100 ? " (capped)" : ""}`
      : `${rows.length} idea${rows.length === 1 ? "" : "s"}${rows.length >= 50 ? " (top by relevance)" : ""}`
  );
  list.innerHTML = rows
    .map((row) => {
      const tickers = (row.tickers || []).join(", ");
      const badges = thesisBadgeHtml(row.thesis_attention);
      const hasTickers = (row.tickers || []).length > 0;
      return `<article class="bg-dashboard-surface border border-border rounded-lg p-4">
      <h3 class="font-medium text-text-primary">${row.title}</h3>
      <p class="text-xs text-text-secondary mt-1">${row.article_type || ""} · ${row.source || ""} · score ${row.relevance_score ?? "—"}</p>
      ${tickers ? `<p class="text-xs mt-1">Tickers: ${tickers}${badges}</p>` : badges ? `<p class="text-xs mt-1">${badges}</p>` : ""}
      ${row.summary ? `<p class="text-sm mt-2 text-text-secondary line-clamp-3">${row.summary}</p>` : ""}
      <div class="flex flex-wrap gap-2 mt-3">
        <button type="button" data-action="accepted" data-id="${row.id}" data-tickers='${JSON.stringify(row.tickers || [])}'
          class="btn-outline-sm">Accept</button>
        ${
          hasTickers
            ? `<button type="button" data-action="accepted" data-queue-analysis="1" data-id="${row.id}" data-tickers='${JSON.stringify(row.tickers || [])}'
          class="btn-outline-sm">Accept &amp; analyze now</button>`
            : ""
        }
        <button type="button" data-action="dismissed" data-id="${row.id}"
          class="px-3 py-1 text-xs border border-border rounded-lg text-text-primary hover:bg-dashboard-surface-alt">Dismiss</button>
        <button type="button" data-action="snoozed" data-id="${row.id}"
          class="px-3 py-1 text-xs border border-border rounded-lg text-text-primary hover:bg-dashboard-surface-alt">Snooze</button>
      </div>
    </article>`;
    })
    .join("");

  list.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const b = btn as HTMLButtonElement;
      const id = b.dataset.id || "";
      const action = b.dataset.action as "accepted" | "dismissed" | "snoozed";
      const tickers = JSON.parse(b.dataset.tickers || "[]") as string[];
      const queueAnalysis = b.dataset.queueAnalysis === "1";
      if (await triage(id, action, tickers, queueAnalysis)) {
        b.closest("article")?.remove();
      }
    });
  });
}

async function loadIdeas(): Promise<void> {
  const seq = ++loadSeq;
  const filter = currentTickerFilter();
  const loading = document.getElementById("ideas-loading");
  const err = document.getElementById("ideas-error");
  if (loading) {
    loading.textContent = filter ? `Searching ideas for ${filter}…` : "Loading ideas…";
    loading.classList.remove("hidden");
  }
  if (err) err.classList.add("hidden");

  try {
    const params = new URLSearchParams();
    // Filtered queries use the API max so a deep ticker isn't lost to the top-50 default.
    params.set("limit", filter ? "100" : "50");
    if (filter) params.set("ticker", filter);
    const resp = await fetch(`/api/ideas/inbox?${params.toString()}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = (await resp.json()) as { data: IdeaRow[] };
    if (seq !== loadSeq) return;
    renderIdeas(body.data || [], filter);
  } catch (e) {
    if (seq !== loadSeq) return;
    if (loading) loading.classList.add("hidden");
    if (err) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.classList.remove("hidden");
    }
  }
}

function setupTickerFilter(): void {
  const input = document.getElementById("ideas-ticker-filter") as HTMLInputElement | null;
  if (!input) return;
  input.addEventListener("input", () => {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => void loadIdeas(), 200);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupTickerFilter();
  void loadIdeas();
});
