export {};

interface Summary {
  horizon_days: number;
  total_scored: number;
  hit_rate_by_source: Record<string, number | null>;
  hit_rate_by_verdict: Record<string, number | null>;
  best_calls: Array<Record<string, unknown>>;
  worst_calls: Array<Record<string, unknown>>;
}

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

async function loadTrackRecord(): Promise<void> {
  const loading = document.getElementById("track-loading");
  const err = document.getElementById("track-error");
  try {
    const resp = await fetch("/api/track-record/summary?horizon=30");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = (await resp.json()) as Summary;
    if (loading) loading.classList.add("hidden");

    const summary = document.getElementById("track-summary");
    if (summary) {
      summary.classList.remove("hidden");
      summary.innerHTML = Object.entries(data.hit_rate_by_source || {}).map(([src, rate]) =>
        `<div class="bg-dashboard-surface border border-border rounded-lg p-4">
           <p class="text-xs text-text-secondary">${src}</p>
           <p class="text-2xl font-semibold">${pct(rate)}</p>
           <p class="text-xs">hit rate (${data.horizon_days}d)</p>
         </div>`
      ).join("") || `<p class="text-sm text-text-secondary col-span-2">No scored outcomes yet.</p>`;
    }

    const verdict = document.getElementById("track-verdict");
    if (verdict) {
      verdict.classList.remove("hidden");
      const rows = Object.entries(data.hit_rate_by_verdict || {});
      verdict.innerHTML = `<h2 class="text-lg font-semibold mb-2">AI review calibration (ALIGNED vs TENSION)</h2>
        ${rows.length ? rows.map(([v, rate]) =>
          `<div class="text-sm flex justify-between py-1 border-b border-border"><span>${v}</span><span>${pct(rate)}</span></div>`
        ).join("") : `<p class="text-sm text-text-secondary">No action_queue verdict outcomes yet.</p>`}`;
    }

    const calls = document.getElementById("track-calls");
    if (calls) {
      calls.classList.remove("hidden");
      const best = (data.best_calls || []).slice(0, 3);
      calls.innerHTML = `<h2 class="text-lg font-semibold mb-2">Recent calls</h2>
        ${best.map((c) =>
          `<div class="text-sm py-1">${c.ticker} ${c.stance} excess ${c.excess_return}</div>`
        ).join("") || `<p class="text-sm text-text-secondary">Need ~30 days of ledger data.</p>`}`;
    }
  } catch (e) {
    if (loading) loading.classList.add("hidden");
    if (err) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.classList.remove("hidden");
    }
  }
}

document.addEventListener("DOMContentLoaded", () => void loadTrackRecord());
