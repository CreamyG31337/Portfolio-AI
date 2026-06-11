export {};

interface Briefing {
  market_regime?: { risk_regime?: string; as_of?: string };
  market_brief_headline?: string;
  stance_flips?: Array<Record<string, unknown>>;
  action_queue?: Array<Record<string, unknown>>;
  alpha_articles?: Array<Record<string, unknown>>;
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

async function loadBriefing(): Promise<void> {
  const loading = el("today-loading");
  const err = el("today-error");
  try {
    const fund = (window as unknown as { ui?: { getSelectedFund?: () => string } }).ui?.getSelectedFund?.();
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
