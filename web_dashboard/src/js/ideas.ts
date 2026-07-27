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
  conclusion?: string;
  url?: string;
  logic_check?: string;
  sentiment?: string;
  /** Composite inbox rank (see ideas_quality.idea_score_sql). Drives ordering. */
  idea_score?: number;
  low_signal?: boolean;
  thesis_attention?: ThesisAttentionFlag[];
}

let loadSeq = 0;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;
/** Sticky for the session only — the inbox should default to the good rows. */
let includeLowSignal = false;

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
      return `<a href="${href}" class="inline-block ml-1 text-xs px-1.5 py-0.5 rounded border border-amber-500/40 text-amber-700 dark:text-amber-400 hover:underline" title="${esc(f.title || "")}">thesis: ${esc(String(reasons))}</a>`;
    })
    .join("");
}

/**
 * Escape for both attribute values and text nodes.
 *
 * Every field on a card is untrusted: titles, summaries and conclusions are LLM
 * output derived from scraped third-party pages. Escaping `&`, `"` and `<` is
 * sufficient for both contexts, so one helper covers the whole card.
 */
function esc(text: unknown): string {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

/** Banner for rows the ranking withheld. Never let a filter hide silently. */
function lowSignalBannerHtml(hidden: number): string {
  if (includeLowSignal) {
    return `<p class="text-xs text-text-secondary mb-3">Showing low-signal ideas.
      <button type="button" id="ideas-low-signal-toggle" class="underline">Hide them</button></p>`;
  }
  if (hidden <= 0) return "";
  return `<p class="text-xs text-text-secondary mb-3">${hidden} low-signal idea${hidden === 1 ? "" : "s"} hidden.
    <button type="button" id="ideas-low-signal-toggle" class="underline">Show anyway</button></p>`;
}

function bindLowSignalToggle(): void {
  document.getElementById("ideas-low-signal-toggle")?.addEventListener("click", () => {
    includeLowSignal = !includeLowSignal;
    void loadIdeas();
  });
}

function renderIdeas(rows: IdeaRow[], filter: string, hidden: number): void {
  const list = document.getElementById("ideas-list");
  const loading = document.getElementById("ideas-loading");
  if (loading) loading.classList.add("hidden");
  if (!list) return;
  const banner = lowSignalBannerHtml(hidden);
  if (!rows.length) {
    const empty = filter
      ? `<p class="text-sm text-text-secondary">No open ideas matching ticker prefix “${esc(filter)}”.</p>`
      : `<p class="text-sm text-text-secondary">Inbox empty — check back after the next alpha run.</p>`;
    list.innerHTML = banner + empty;
    bindLowSignalToggle();
    setFilterStatus(filter ? `0 matches for ${filter}` : "");
    return;
  }
  setFilterStatus(
    filter
      ? `${rows.length} match${rows.length === 1 ? "" : "es"} for ${filter}${rows.length >= 100 ? " (capped)" : ""}`
      : `${rows.length} idea${rows.length === 1 ? "" : "s"}${rows.length >= 50 ? " (top ranked)" : ""}`
  );
  list.innerHTML = banner + rows
    .map((row) => {
      const tickers = (row.tickers || []).join(", ");
      const badges = thesisBadgeHtml(row.thesis_attention);
      const hasTickers = (row.tickers || []).length > 0;
      // The conclusion is the model's own "so what" — it is the only field that
      // answers why this row deserves attention. Summary falls back in when the
      // conclusion is empty so a card is never left with nothing to say.
      const whyCare = (row.conclusion || "").trim() || (row.summary || "").trim();
      const hasSeparateSummary =
        (row.conclusion || "").trim() && (row.summary || "").trim();
      const titleHtml = row.url
        ? `<a href="${esc(row.url)}" target="_blank" rel="noopener noreferrer" class="hover:underline">${esc(row.title)}</a>`
        : esc(row.title);
      // relevance_score is deliberately NOT shown: it is derived from logic_check, a
      // genre label that rates ETF holdings tables 0.9 and real analysis 0.7. Showing
      // it next to a card invites trusting it. idea_score is what actually orders
      // this list, so that is the number on screen.
      const signal = `signal ${row.idea_score ?? "—"}/9`;
      return `<article class="bg-dashboard-surface border border-border rounded-lg p-4${
        row.low_signal ? " opacity-60" : ""
      }">
      <h3 class="font-medium text-text-primary">${titleHtml}</h3>
      <p class="text-xs text-text-secondary mt-1">${esc(row.article_type || "")} · ${esc(row.source || "")} · ${signal}</p>
      ${tickers ? `<p class="text-xs mt-1">Tickers: ${esc(tickers)}${badges}</p>` : badges ? `<p class="text-xs mt-1">${badges}</p>` : ""}
      ${
        whyCare
          ? `<p class="text-sm mt-2 text-text-primary whitespace-pre-line">${esc(whyCare)}</p>`
          : ""
      }
      ${
        hasSeparateSummary
          ? `<details class="mt-2">
        <summary class="text-xs text-text-secondary cursor-pointer hover:underline">Full summary</summary>
        <p class="text-sm mt-1 text-text-secondary whitespace-pre-line">${esc(row.summary)}</p>
      </details>`
          : ""
      }
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

  bindLowSignalToggle();
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
    if (includeLowSignal) params.set("include_low_signal", "1");
    const resp = await fetch(`/api/ideas/inbox?${params.toString()}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = (await resp.json()) as { data: IdeaRow[]; low_signal_total?: number };
    if (seq !== loadSeq) return;
    renderIdeas(body.data || [], filter, Number(body.low_signal_total || 0));
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
