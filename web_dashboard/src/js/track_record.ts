export {};

interface DomainRow {
  domain: string;
  scored: number;
  hits: number;
  hit_rate: number | null;
  mean_excess: number | null;
  stance_touches: number;
}

interface CoverageRow {
  rows: number;
  with_evidence: number;
  with_article_ids: number;
  pct_with_evidence: number | null;
  pct_with_article_ids: number | null;
}

interface Summary {
  horizon_days: number;
  total_scored: number;
  hit_rate_by_source: Record<string, number | null>;
  hit_rate_by_verdict: Record<string, number | null>;
  avg_excess_by_source?: Record<string, number | null>;
  median_excess_by_source?: Record<string, number | null>;
  counts_by_source?: Record<string, { scored: number; hits: number; misses: number; unscoreable: number }>;
  by_domain?: DomainRow[];
  evidence_coverage?: Record<string, CoverageRow>;
  best_calls: Array<Record<string, unknown>>;
  worst_calls: Array<Record<string, unknown>>;
}

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function excess(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
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
           <p class="text-xs text-text-secondary mt-1">mean excess ${excess((data.avg_excess_by_source || {})[src])}</p>
         </div>`
      ).join("") || `<p class="text-sm text-text-secondary col-span-2">No scored outcomes yet.</p>`;
    }

    const sourceTable = document.getElementById("track-source-table");
    if (sourceTable) {
      sourceTable.classList.remove("hidden");
      const sources = Object.keys(data.hit_rate_by_source || {}).sort();
      const rows = sources.map((src) => {
        const c = (data.counts_by_source || {})[src];
        return `<tr class="border-b border-border">
          <td class="py-1.5 pr-3 text-sm">${src}</td>
          <td class="py-1.5 pr-3 text-sm text-right">${c?.scored ?? 0}</td>
          <td class="py-1.5 pr-3 text-sm text-right">${pct((data.hit_rate_by_source || {})[src])}</td>
          <td class="py-1.5 text-sm text-right">${excess((data.avg_excess_by_source || {})[src])}</td>
        </tr>`;
      }).join("");
      sourceTable.innerHTML = `<h2 class="text-lg font-semibold mb-2">By source</h2>
        <table class="w-full text-left">
          <thead><tr class="text-xs text-text-secondary border-b border-border">
            <th class="py-1 pr-3">Source</th><th class="py-1 pr-3 text-right">Scored</th>
            <th class="py-1 pr-3 text-right">Hit rate</th><th class="py-1 text-right">Mean excess</th>
          </tr></thead>
          <tbody>${rows || `<tr><td colspan="4" class="text-sm text-text-secondary py-2">No data.</td></tr>`}</tbody>
        </table>`;
    }

    const domainTable = document.getElementById("track-domain-table");
    if (domainTable) {
      domainTable.classList.remove("hidden");
      const domains = data.by_domain || [];
      if (!domains.length) {
        domainTable.innerHTML = `<h2 class="text-lg font-semibold mb-2">By article domain</h2>
          <p class="text-sm text-text-secondary">No resolvable article domains yet (G1 evidence required on scoreable stances).</p>`;
      } else {
        const rows = domains.map((d) =>
          `<tr class="border-b border-border">
            <td class="py-1.5 pr-3 text-sm">${d.domain}</td>
            <td class="py-1.5 pr-3 text-sm text-right">${Number(d.scored).toFixed(2)}</td>
            <td class="py-1.5 pr-3 text-sm text-right">${pct(d.hit_rate)}</td>
            <td class="py-1.5 text-sm text-right">${excess(d.mean_excess)}</td>
          </tr>`
        ).join("");
        domainTable.innerHTML = `<h2 class="text-lg font-semibold mb-2">By article domain (top ${domains.length})</h2>
          <p class="text-xs text-text-secondary mb-2">Fractional 1/N credit when a stance cites multiple domains.</p>
          <table class="w-full text-left">
            <thead><tr class="text-xs text-text-secondary border-b border-border">
              <th class="py-1 pr-3">Domain</th><th class="py-1 pr-3 text-right">Scored</th>
              <th class="py-1 pr-3 text-right">Hit rate</th><th class="py-1 text-right">Mean excess</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>`;
      }
    }

    const coverage = document.getElementById("track-coverage");
    if (coverage) {
      coverage.classList.remove("hidden");
      const cov = data.evidence_coverage || {};
      const lines = Object.keys(cov).sort().map((src) => {
        const c = cov[src];
        return `<div class="text-sm flex justify-between py-1 border-b border-border">
          <span>${src}</span>
          <span class="text-text-secondary">evidence ${c.pct_with_evidence ?? "—"}% · article_ids ${c.pct_with_article_ids ?? "—"}%</span>
        </div>`;
      }).join("");
      coverage.innerHTML = `<h2 class="text-lg font-semibold mb-2">G1 evidence coverage</h2>
        ${lines || `<p class="text-sm text-text-secondary">No coverage stats.</p>`}`;
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
        ).join("") || `<p class="text-sm text-text-secondary">Need ledger data with scored outcomes.</p>`}`;
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
