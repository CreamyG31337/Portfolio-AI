export {};

interface InsiderCluster {
  ticker: string;
  insider_count: number;
  buy_count: number;
  total_value: number;
  latest_buy?: string;
  insiders?: Array<{ name: string; title?: string; value: number }>;
  held?: boolean;
  watched?: boolean;
}

interface LiquidityRow {
  ticker: string;
  shares: number;
  days_to_exit?: number | null;
  pct_of_adv?: number | null;
  avg_daily_volume?: number | null;
  risk_bucket: string;
}

interface DilutionAlert {
  ticker: string;
  window_days: number;
  pct_change: number;
  shares_start?: number;
  shares_end?: number;
  as_of?: string;
}

interface FilingAlert {
  ticker: string;
  form_type: string;
  category: string;
  direction: string;
  filed_at?: string;
  title?: string;
  url?: string;
}

interface ConfluenceEvent {
  ticker: string;
  direction: string;
  score: number;
  families?: string[] | unknown;
  as_of?: string;
}

interface CongressHerd {
  ticker: string;
  politician_count: number;
  buy_count: number;
  latest_buy?: string;
  politicians?: Array<{
    politician_id: string;
    name: string;
    party?: string;
    chamber?: string;
    buy_count?: number;
    latest_buy?: string;
  }>;
  held?: boolean;
  watched?: boolean;
}

interface ThesisAttention {
  id: string;
  ticker: string;
  title?: string;
  disposition?: string;
  intent?: string;
  review_status?: string | null;
  llm_verdict?: string | null;
  is_weak?: boolean;
  age_days?: number | null;
  attention_reasons?: string[];
}

interface AdviseRow {
  ticker: string;
  advise: string;
  score?: number;
  reasons?: string[];
  queue_verdict?: string | null;
  thesis_verdict?: string | null;
  thesis_id?: string | null;
  dual_tension?: boolean;
  meta_conviction?: string | null;
  // Signal-fallback rows (A3): shown when queue + Insights are empty.
  reason?: string;
  confidence?: number | null;
  fear_level?: string | null;
  source?: string;
  // A2 tension (live-signal vs stored-research conflict), annotated upstream.
  tension?: boolean;
  tension_reason?: string | null;
}

interface Briefing {
  market_regime?: { risk_regime?: string; as_of?: string };
  market_brief_headline?: string;
  advise_pack?: AdviseRow[];
  advise_source?: string;
  stance_flips?: Array<Record<string, unknown>>;
  action_queue?: Array<Record<string, unknown>>;
  alpha_articles?: Array<Record<string, unknown>>;
  insider_cluster_buys?: InsiderCluster[];
  congress_herd_buys?: CongressHerd[];
  dilution_alerts?: DilutionAlert[];
  filing_alerts?: FilingAlert[];
  confluence_events?: ConfluenceEvent[];
  theses_attention?: ThesisAttention[];
  watchlist_movers?: Array<Record<string, unknown>>;
  upcoming_dividends?: Array<Record<string, unknown>>;
}

function el(id: string): HTMLElement | null {
  return document.getElementById(id);
}

function showSection(id: string, html: string): void {
  const node = el(id);
  if (!node) return;
  node.innerHTML = html;
  node.classList.remove("hidden");
}

function formatCompact(value: number | null | undefined): string {
  const n = Number(value || 0);
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toFixed(0);
}

const BUCKET_BADGES: Record<string, string> = {
  low: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  elevated: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  high: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  unknown: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
};

async function loadLiquidityPanel(fund: string | undefined): Promise<void> {
  // Separate request on purpose: cold cache fans out to yfinance and can take
  // tens of seconds; the rest of the briefing must not wait on it.
  const node = el("today-liquidity");
  if (!node) return;
  node.innerHTML = `<h2 class="text-lg font-semibold mb-2">Liquidity / exit risk</h2>
    <p class="text-sm text-text-secondary">Loading volume data…</p>`;
  node.classList.remove("hidden");
  try {
    const qs = fund ? `?fund=${encodeURIComponent(fund)}` : "";
    const resp = await fetch(`/api/liquidity/panel${qs}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const payload = (await resp.json()) as { data?: LiquidityRow[] };
    const rows = payload.data || [];
    showSection(
      "today-liquidity",
      `<h2 class="text-lg font-semibold mb-2">Liquidity / exit risk
         <span class="text-xs font-normal text-text-secondary">(days to exit at 10% of avg daily volume)</span></h2>
       ${rows.length ? rows.map((r) => {
         const badge = BUCKET_BADGES[r.risk_bucket] || BUCKET_BADGES.unknown;
         const days = r.days_to_exit != null ? `${r.days_to_exit} d` : "no volume data";
         return `<div class="text-sm py-1 border-b border-border last:border-0 flex items-center gap-2">
            <a href="/ticker?ticker=${encodeURIComponent(r.ticker)}" class="text-accent hover:underline font-semibold">${r.ticker}</a>
            <span class="text-xs px-1.5 py-0.5 rounded ${badge}">${r.risk_bucket}</span>
            <span>${days}</span>
            ${r.pct_of_adv != null ? `<span class="text-xs text-text-secondary">position = ${r.pct_of_adv}% of daily volume</span>` : ""}
          </div>`;
       }).join("") : `<p class="text-sm text-text-secondary">No open positions.</p>`}`
    );
  } catch (e) {
    showSection(
      "today-liquidity",
      `<h2 class="text-lg font-semibold mb-2">Liquidity / exit risk</h2>
       <p class="text-sm text-theme-error-text">Failed to load: ${e instanceof Error ? e.message : String(e)}</p>`
    );
  }
}

async function loadBriefing(): Promise<void> {
  const loading = el("today-loading");
  const err = el("today-error");
  try {
    const fund = (window as unknown as { ui?: { getSelectedFund?: () => string } }).ui?.getSelectedFund?.();
    void loadLiquidityPanel(fund);
    const qs = fund ? `?fund=${encodeURIComponent(fund)}` : "";
    const resp = await fetch(`/api/today/briefing${qs}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = (await resp.json()) as Briefing;
    if (loading) loading.classList.add("hidden");

    const regime = data.market_regime?.risk_regime || "UNKNOWN";
    showSection(
      "today-regime",
      `<h2 class="text-lg font-semibold mb-2">Market regime</h2>
       <p class="text-sm">${data.market_brief_headline || "No brief yet"}</p>
       <p class="text-xs text-text-secondary mt-1">Regime: <strong>${regime}</strong></p>`
    );

    const advise = data.advise_pack || [];
    const adviseBadge = (a: string): string => {
      const u = a.toUpperCase();
      if (u === "SELL" || u === "RISK") {
        return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
      }
      if (u === "BUY") {
        return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200";
      }
      return "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200";
    };
    const fromSignals = (data.advise_source || "advise") === "signal_fallback";
    const adviseSourceNote = fromSignals
      ? `<span class="text-xs font-normal text-text-secondary">(no queue/Insights items — ranked from watchlist signals; not auto-trade)</span>`
      : `<span class="text-xs font-normal text-text-secondary">(ranked from queue + Insights — not auto-trade)</span>`;
    showSection(
      "today-advise",
      `<h2 class="text-lg font-semibold mb-2">Advise ${adviseSourceNote}</h2>
       ${
         advise.length
           ? advise
               .slice(0, 12)
               .map((row) => {
                 // Advise rows carry reasons[]; signal-fallback rows carry a
                 // single reason string + fear level.
                 const chips = (row.reasons && row.reasons.length
                   ? row.reasons.slice(0, 5)
                   : [row.reason, row.fear_level ? `fear ${row.fear_level}` : ""].filter(
                       Boolean
                     ) as string[]
                 )
                   .map(
                     (r) =>
                       `<span class="text-xs px-1.5 py-0.5 rounded border border-border text-text-secondary">${r}</span>`
                   )
                   .join(" ");
                 const thesisLink = row.thesis_id
                   ? ` <a href="/insights?thesis=${encodeURIComponent(row.thesis_id)}" class="text-xs text-accent hover:underline">thesis</a>`
                   : "";
                 const dual = row.dual_tension
                   ? `<span class="ml-1 text-xs px-1.5 py-0.5 rounded border border-amber-500/40 text-amber-700 dark:text-amber-400">dual tension</span>`
                   : "";
                 const tension = row.tension
                   ? `<span class="ml-1 text-xs px-1.5 py-0.5 rounded border border-amber-500/40 text-amber-700 dark:text-amber-400" title="${
                       row.tension_reason || "live signal vs stored research"
                     }">tension</span>`
                   : "";
                 const metric =
                   typeof row.score === "number"
                     ? `score ${row.score}`
                     : typeof row.confidence === "number"
                       ? `conf ${row.confidence.toFixed(2)}`
                       : "";
                 return `<div class="text-sm py-1.5 border-b border-border last:border-0">
            <a href="/ticker?ticker=${encodeURIComponent(row.ticker)}" class="text-accent hover:underline font-semibold">${row.ticker}</a>
            <span class="ml-1 text-xs px-1.5 py-0.5 rounded ${adviseBadge(row.advise)}">${row.advise}</span>
            ${metric ? `<span class="ml-1 text-xs text-text-secondary">${metric}</span>` : ""}
            ${tension}${dual}${thesisLink}
            <div class="mt-1 flex flex-wrap gap-1">${chips}</div>
          </div>`;
               })
               .join("")
           : `<p class="text-sm text-text-secondary">No ranked advise items yet (need Action Queue, Insights tension, or active watchlist signals).</p>`
       }`
    );

    const theses = data.theses_attention || [];
    const reasonChip = (r: string): string => {
      const k = r.toLowerCase();
      if (k === "tension" || k === "stale_thesis") {
        return `<span class="ml-1 text-xs px-1.5 py-0.5 rounded border border-amber-500/40 text-amber-700 dark:text-amber-400">${k}</span>`;
      }
      if (k === "stale" || k === "weak") {
        return `<span class="ml-1 text-xs px-1.5 py-0.5 rounded border border-red-500/40 text-red-600">${k}</span>`;
      }
      return `<span class="ml-1 text-xs px-1.5 py-0.5 rounded border border-border text-text-secondary">${k}</span>`;
    };
    showSection(
      "today-theses",
      `<h2 class="text-lg font-semibold mb-2">Theses due / in tension <span class="text-xs font-normal text-text-secondary">(Insights)</span></h2>
       ${
         theses.length
           ? theses
               .slice(0, 12)
               .map((t) => {
                 const reasons = (t.attention_reasons || []).map(reasonChip).join("");
                 const href = `/insights?thesis=${encodeURIComponent(t.id)}`;
                 return `<div class="text-sm py-1 border-b border-border last:border-0">
            <a href="${href}" class="text-accent hover:underline font-semibold">${t.ticker}</a>
            <span class="text-xs text-text-secondary ml-1">${t.disposition || ""} · ${t.intent || ""}</span>
            ${reasons}
            <span class="block text-xs text-text-secondary mt-0.5">${t.title || ""}</span>
          </div>`;
               })
               .join("")
           : `<p class="text-sm text-text-secondary">Nothing due or in tension. <a href="/insights" class="text-accent underline">Open Insights</a></p>`
       }`
    );

    const flips = data.stance_flips || [];
    showSection(
      "today-flips",
      `<h2 class="text-lg font-semibold mb-2">Stance flips</h2>
       ${flips.length ? flips.map((f) =>
         `<div class="text-sm py-1 border-b border-border last:border-0">
            <strong>${f.ticker}</strong> (${f.source}) ${f.from_stance} → ${f.to_stance}
          </div>`).join("") : `<p class="text-sm text-text-secondary">No flips in the last 2 days.</p>`}`
    );

    const actions = data.action_queue || [];
    showSection(
      "today-actions",
      `<h2 class="text-lg font-semibold mb-2">Action queue</h2>
       ${actions.slice(0, 8).map((a) =>
         `<div class="text-sm py-1 border-b border-border last:border-0">
            <strong>${a.ticker}</strong> ${a.action}
            ${(a as { ai_review?: { verdict?: string } }).ai_review?.verdict
              ? ` · ${(a as { ai_review?: { verdict?: string } }).ai_review?.verdict}` : ""}
          </div>`).join("")}`
    );

    const clusters = data.insider_cluster_buys || [];
    showSection(
      "today-insider-clusters",
      `<h2 class="text-lg font-semibold mb-2">Insider cluster buys <span class="text-xs font-normal text-text-secondary">(3+ insiders, 30d)</span></h2>
       ${clusters.length ? clusters.map((c) =>
         `<div class="text-sm py-1 border-b border-border last:border-0">
            <a href="/ticker?ticker=${encodeURIComponent(c.ticker)}" class="text-accent hover:underline font-semibold">${c.ticker}</a>
            ${c.held ? `<span class="ml-1 text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">held</span>` : ""}
            ${c.watched && !c.held ? `<span class="ml-1 text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200">watching</span>` : ""}
            · ${c.insider_count} insiders, ${c.buy_count} buys, $${formatCompact(c.total_value)}
            <span class="text-xs text-text-secondary">latest ${c.latest_buy || "?"}</span>
          </div>`).join("") : `<p class="text-sm text-text-secondary">No cluster buys in the last 30 days.</p>`}`
    );

    const herds = data.congress_herd_buys || [];
    showSection(
      "today-congress-herd",
      `<h2 class="text-lg font-semibold mb-2">Congress herd buys <span class="text-xs font-normal text-text-secondary">(2+ politicians, 30d)</span></h2>
       ${herds.length ? herds.map((h) =>
         `<div class="text-sm py-1 border-b border-border last:border-0">
            <a href="/ticker?ticker=${encodeURIComponent(h.ticker)}" class="text-accent hover:underline font-semibold">${h.ticker}</a>
            ${h.held ? `<span class="ml-1 text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">held</span>` : ""}
            ${h.watched && !h.held ? `<span class="ml-1 text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200">watching</span>` : ""}
            · ${h.politician_count} politicians, ${h.buy_count} purchases
            <span class="text-xs text-text-secondary">latest ${h.latest_buy || "?"}</span>
          </div>`).join("") : `<p class="text-sm text-text-secondary">No congress herd buys in the last 30 days.</p>`}`
    );

    const dilution = data.dilution_alerts || [];
    showSection(
      "today-dilution",
      `<h2 class="text-lg font-semibold mb-2">Dilution alerts <span class="text-xs font-normal text-text-secondary">(shares outstanding rising)</span></h2>
       ${dilution.length ? dilution.map((d) =>
         `<div class="text-sm py-1 border-b border-border last:border-0">
            <a href="/ticker?ticker=${encodeURIComponent(d.ticker)}" class="text-accent hover:underline font-semibold">${d.ticker}</a>
            <span class="ml-1 text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">+${d.pct_change}%</span>
            <span class="text-xs text-text-secondary">shares / ${d.window_days}d${d.as_of ? ` · as of ${d.as_of}` : ""}</span>
          </div>`).join("") : `<p class="text-sm text-text-secondary">No dilution flagged on holdings/watchlist.</p>`}`
    );

    const filings = data.filing_alerts || [];
    const filingBadge = (direction: string): string => {
      if (direction === "positive") return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200";
      if (direction === "neutral") return "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200";
      return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
    };
    showSection(
      "today-filings",
      `<h2 class="text-lg font-semibold mb-2">SEC filings (risk) <span class="text-xs font-normal text-text-secondary">(US EDGAR: shelf, distress, delisting, 13D)</span></h2>
       ${filings.length ? filings.map((f) =>
         `<div class="text-sm py-1 border-b border-border last:border-0">
            <a href="/ticker?ticker=${encodeURIComponent(f.ticker)}" class="text-accent hover:underline font-semibold">${f.ticker}</a>
            <span class="ml-1 text-xs px-1.5 py-0.5 rounded ${filingBadge(f.direction)}">${f.form_type}</span>
            <span class="text-xs text-text-secondary">${f.category}${f.filed_at ? ` · ${f.filed_at}` : ""}</span>
            ${f.url ? ` · <a href="${f.url}" target="_blank" rel="noopener" class="text-accent hover:underline text-xs">filing</a>` : ""}
          </div>`).join("") : `<p class="text-sm text-text-secondary">No SEC filing risk events on holdings/watchlist.</p>`}`
    );

    const confluence = data.confluence_events || [];
    const confluenceBadge = (direction: string): string => {
      if (direction === "bullish") {
        return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200";
      }
      return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
    };
    // TODO(today-ui): Type `families` as `string[]` end-to-end; prefer DOM APIs over
    // `.innerHTML` template strings for user-facing ticker data — see PR #393 review.
    const formatFamilies = (families: unknown): string => {
      if (Array.isArray(families)) return families.join(", ");
      return "";
    };
    showSection(
      "today-confluence",
      `<h2 class="text-lg font-semibold mb-2">Signal confluence <span class="text-xs font-normal text-text-secondary">(2+ families aligned, 10d)</span></h2>
       ${confluence.length ? confluence.map((c) =>
         `<div class="text-sm py-1 border-b border-border last:border-0">
            <a href="/ticker?ticker=${encodeURIComponent(c.ticker)}" class="text-accent hover:underline font-semibold">${c.ticker}</a>
            <span class="ml-1 text-xs px-1.5 py-0.5 rounded ${confluenceBadge(c.direction)}">${c.direction} · ${c.score}</span>
            <span class="text-xs text-text-secondary">${formatFamilies(c.families)}${c.as_of ? ` · ${c.as_of}` : ""}</span>
          </div>`).join("") : `<p class="text-sm text-text-secondary">No confluence events in the last 2 days.</p>`}`
    );

    const alpha = data.alpha_articles || [];
    showSection(
      "today-alpha",
      `<h2 class="text-lg font-semibold mb-2">New ideas</h2>
       ${alpha.slice(0, 5).map((a) =>
         `<div class="text-sm py-1"><a href="/ideas" class="text-accent hover:underline">${a.title}</a></div>`).join("")
         || `<p class="text-sm text-text-secondary">No new alpha articles.</p>`}`
    );

    const movers = data.watchlist_movers || [];
    showSection(
      "today-movers",
      `<h2 class="text-lg font-semibold mb-2">Movers</h2>
       ${movers.length ? movers.map((m) =>
         `<div class="text-sm">${m.ticker}: ${m.change_pct ?? m.pct_change ?? ""}%</div>`).join("")
         : `<p class="text-sm text-text-secondary">No mover data.</p>`}`
    );

    const divs = data.upcoming_dividends || [];
    showSection(
      "today-dividends",
      `<h2 class="text-lg font-semibold mb-2">Dividends</h2>
       ${divs.length ? divs.map((d) =>
         `<div class="text-sm">${d.ticker || ""} ${d.amount || ""}</div>`).join("")
         : `<p class="text-sm text-text-secondary">No upcoming dividends.</p>`}`
    );
  } catch (e) {
    if (loading) loading.classList.add("hidden");
    if (err) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.classList.remove("hidden");
    }
  }
}

document.addEventListener("DOMContentLoaded", () => void loadBriefing());
