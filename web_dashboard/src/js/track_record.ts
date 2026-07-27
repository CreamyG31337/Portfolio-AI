export {};

interface CountBucket {
  scored: number;
  hits: number;
  misses: number;
  unscoreable: number;
}

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

interface CallRow {
  ticker?: string;
  stance?: string;
  source?: string;
  as_of?: string;
  excess_return?: number | string | null;
  ticker_return?: number | string | null;
  benchmark_return?: number | string | null;
}

interface Summary {
  horizon_days: number;
  total_scored: number;
  hit_rate_by_source: Record<string, number | null>;
  hit_rate_by_verdict: Record<string, number | null>;
  hit_rate_by_confidence_band?: Record<string, number | null>;
  // Directional: positive always means the call was right, bearish calls included.
  avg_excess_by_source?: Record<string, number | null>;
  median_excess_by_source?: Record<string, number | null>;
  excess_metric?: string;
  scoring_version?: number;
  broad_index_etf_excluded?: number;
  baselines?: {
    n?: number;
    actual_hit_rate?: number | null;
    always_bullish_hit_rate?: number | null;
    always_bearish_hit_rate?: number | null;
    shuffled_hit_rate?: number | null;
    edge_vs_shuffled?: number | null;
    edge_vs_always_bullish?: number | null;
    day_buckets?: number;
  };
  counts_by_source?: Record<string, CountBucket>;
  counts_by_confidence_band?: Record<string, CountBucket>;
  by_domain?: DomainRow[];
  evidence_coverage?: Record<string, CoverageRow>;
  best_calls: CallRow[];
  worst_calls?: CallRow[];
}

const SOURCE_LABELS: Record<string, string> = {
  ticker_analysis: "Single-ticker analysis",
  ticker_meta_analysis: "Daily meta-analysis",
};

const CONF_BANDS: Array<{ key: string; label: string }> = [
  { key: "lt_0.5", label: "Low confidence (< 50%)" },
  { key: "0.5_to_0.75", label: "Medium confidence (50–75%)" },
  { key: "gte_0.75", label: "High confidence (≥ 75%)" },
];

const MIN_SAMPLE = 30;

function esc(v: unknown): string {
  return String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string)
  );
}

function sourceLabel(src: string): string {
  return SOURCE_LABELS[src] || src;
}

function num(v: number | string | null | undefined): number | null {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function pct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function pp(v: number | string | null | undefined): string {
  const n = num(v);
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)} pp`;
}

function signClass(v: number | string | null | undefined): string {
  const n = num(v);
  if (n == null) return "text-text-secondary";
  return n >= 0 ? "text-theme-success-text" : "text-theme-error-text";
}

function hitRateClass(rate: number | null | undefined, scored: number): string {
  if (rate == null || scored < MIN_SAMPLE) return "";
  return rate >= 0.5 ? "text-theme-success-text" : "text-theme-error-text";
}

/** Half-width of the 95% band a no-edge (50/50) strategy would land in, as a rate. */
function coinFlipBand(n: number): number | null {
  if (n <= 0) return null;
  return 1.96 * Math.sqrt(0.25 / n);
}

function sampleNote(scored: number): string {
  if (scored >= MIN_SAMPLE) return "";
  return ` <span class="text-theme-warning-text">(small sample — treat as noise)</span>`;
}

function overallCounts(counts: Record<string, CountBucket>): CountBucket {
  const total: CountBucket = { scored: 0, hits: 0, misses: 0, unscoreable: 0 };
  for (const c of Object.values(counts)) {
    total.scored += c.scored || 0;
    total.hits += c.hits || 0;
    total.misses += c.misses || 0;
    total.unscoreable += c.unscoreable || 0;
  }
  return total;
}

function renderHeadline(data: Summary): void {
  const el = document.getElementById("track-headline");
  if (!el) return;
  el.classList.remove("hidden");
  const total = overallCounts(data.counts_by_source || {});
  if (!total.scored) {
    el.innerHTML = `<p class="text-sm text-text-secondary">No scored outcomes yet — stances need ${data.horizon_days} days to mature before they can be graded.</p>`;
    return;
  }
  const rate = total.hits / total.scored;
  const band = coinFlipBand(total.scored);
  const base = data.baselines || {};
  // The null is NOT 50%. The median stock underperforms its index routinely, so a
  // mostly-long book prints sub-50% on ordinary luck. Compare against what no skill
  // would have produced on these same rows.
  const nullRate = num(base.shuffled_hit_rate);
  let verdict = "";
  if (band != null && nullRate != null) {
    const lo = nullRate - band;
    const hi = nullRate + band;
    const edge = rate - nullRate;
    const bullBase = num(base.always_bullish_hit_rate);
    const context =
      bullBase != null
        ? ` Calling everything bullish would have scored ${pct(bullBase)} over the same rows.`
        : "";
    if (rate >= lo && rate <= hi) {
      verdict = `Randomly reassigning the same mix of calls would score ${pct(nullRate)}, and with ${total.scored} calls anything in ${pct(lo)}–${pct(hi)} is noise — so this is <strong>indistinguishable from no skill</strong> (edge ${pp(edge * 100)}).${context}`;
    } else if (rate > hi) {
      verdict = `That beats the ${pct(nullRate)} a random reassignment of the same calls would score, by more than the ${pct(lo)}–${pct(hi)} noise band — <strong>evidence of a real edge</strong>.${context}`;
    } else {
      verdict = `That trails the ${pct(nullRate)} a random reassignment of the same calls would score — the calls have been <strong>systematically wrong-way</strong>.${context}`;
    }
  } else if (band != null) {
    verdict = `With ${total.scored} calls, the noise band is ±${pct(band).replace("%", "")}pp. No baseline available yet.`;
  }
  // Scored-call-weighted average of per-source means.
  let wsum = 0;
  let wn = 0;
  for (const [src, mean] of Object.entries(data.avg_excess_by_source || {})) {
    const c = (data.counts_by_source || {})[src];
    const m = num(mean);
    if (m != null && c && c.scored > 0) {
      wsum += m * c.scored;
      wn += c.scored;
    }
  }
  const overallMean = wn > 0 ? wsum / wn : null;
  el.innerHTML = `
    <h2 class="text-lg font-semibold mb-2">Overall (${data.horizon_days}-day horizon)</h2>
    <div class="flex flex-wrap gap-6 mb-3">
      <div>
        <p class="text-2xl font-semibold ${hitRateClass(rate, total.scored)}">${pct(rate)}</p>
        <p class="text-xs text-text-secondary">hit rate · ${total.hits} of ${total.scored} calls right</p>
      </div>
      <div>
        <p class="text-2xl font-semibold ${signClass(overallMean)}">${pp(overallMean)}</p>
        <p class="text-xs text-text-secondary">avg excess return per call, in the call's direction</p>
      </div>
      ${
        num(data.baselines?.shuffled_hit_rate) != null
          ? `<div>
        <p class="text-2xl font-semibold ${signClass(num(data.baselines?.edge_vs_shuffled))}">${pp(
          (num(data.baselines?.edge_vs_shuffled) ?? 0) * 100
        )}</p>
        <p class="text-xs text-text-secondary">edge vs no-skill baseline (${pct(
          num(data.baselines?.shuffled_hit_rate)
        )})</p>
      </div>`
          : ""
      }
    </div>
    <p class="text-sm text-text-secondary">${verdict}</p>
    ${
      data.broad_index_etf_excluded
        ? `<p class="text-xs text-text-secondary mt-2">${data.broad_index_etf_excluded} broad-index ETF call${
            data.broad_index_etf_excluded === 1 ? "" : "s"
          } excluded — tracking the benchmark itself gives ~0 excess by construction, so they dilute the rate without being predictions.</p>`
        : ""
    }`;
}

function renderSummaryCards(data: Summary): void {
  const el = document.getElementById("track-summary");
  if (!el) return;
  el.classList.remove("hidden");
  const cards = Object.entries(data.hit_rate_by_source || {}).map(([src, rate]) => {
    const c = (data.counts_by_source || {})[src];
    const scored = c?.scored ?? 0;
    const mean = (data.avg_excess_by_source || {})[src];
    const med = (data.median_excess_by_source || {})[src];
    return `<div class="bg-dashboard-surface border border-border rounded-lg p-4">
       <p class="text-sm font-medium">${esc(sourceLabel(src))}</p>
       <p class="text-xs text-text-secondary mb-2">source: ${esc(src)}</p>
       <p class="text-2xl font-semibold ${hitRateClass(rate, scored)}">${pct(rate)}</p>
       <p class="text-xs text-text-secondary">hit rate over ${scored} scored calls${sampleNote(scored)}</p>
       <p class="text-xs mt-2">avg excess <span class="${signClass(mean)}">${pp(mean)}</span> · median <span class="${signClass(med)}">${pp(med)}</span></p>
     </div>`;
  });
  el.innerHTML = cards.join("") || `<p class="text-sm text-text-secondary col-span-2">No scored outcomes yet.</p>`;
}

function renderSourceTable(data: Summary): void {
  const el = document.getElementById("track-source-table");
  if (!el) return;
  el.classList.remove("hidden");
  const sources = Object.keys(data.hit_rate_by_source || {}).sort();
  const rows = sources.map((src) => {
    const c = (data.counts_by_source || {})[src];
    const scored = c?.scored ?? 0;
    const rate = (data.hit_rate_by_source || {})[src];
    const mean = (data.avg_excess_by_source || {})[src];
    const med = (data.median_excess_by_source || {})[src];
    return `<tr class="border-b border-border">
      <td class="py-1.5 pr-3 text-sm">${esc(sourceLabel(src))}</td>
      <td class="py-1.5 pr-3 text-sm text-right">${scored}</td>
      <td class="py-1.5 pr-3 text-sm text-right">${c?.hits ?? 0}</td>
      <td class="py-1.5 pr-3 text-sm text-right">${c?.misses ?? 0}</td>
      <td class="py-1.5 pr-3 text-sm text-right ${hitRateClass(rate, scored)}">${pct(rate)}</td>
      <td class="py-1.5 pr-3 text-sm text-right ${signClass(mean)}">${pp(mean)}</td>
      <td class="py-1.5 text-sm text-right ${signClass(med)}">${pp(med)}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `<h2 class="text-lg font-semibold mb-1">By source</h2>
    <p class="text-xs text-text-secondary mb-2">Which pipeline the stance came from. A hit means the call was directionally right vs the benchmark after ${data.horizon_days} days. Excess return is in percentage points and is signed to the call's direction, so a correct bearish call counts as positive.</p>
    <table class="w-full text-left">
      <thead><tr class="text-xs text-text-secondary border-b border-border">
        <th class="py-1 pr-3">Source</th>
        <th class="py-1 pr-3 text-right" title="Calls old enough to be graded">Scored</th>
        <th class="py-1 pr-3 text-right">Hits</th>
        <th class="py-1 pr-3 text-right">Misses</th>
        <th class="py-1 pr-3 text-right" title="Hits / scored. ~50% = coin flip">Hit rate</th>
        <th class="py-1 pr-3 text-right" title="Average excess return per call in percentage points, signed to the call's direction — a correct bearish call scores positive">Avg excess</th>
        <th class="py-1 text-right" title="Median excess return per call, signed to the call's direction — less sensitive to outliers">Median excess</th>
      </tr></thead>
      <tbody>${rows || `<tr><td colspan="7" class="text-sm text-text-secondary py-2">No data.</td></tr>`}</tbody>
    </table>`;
}

function renderConfidence(data: Summary): void {
  const el = document.getElementById("track-confidence");
  if (!el) return;
  el.classList.remove("hidden");
  const rates = data.hit_rate_by_confidence_band || {};
  const counts = data.counts_by_confidence_band || {};
  const bands = CONF_BANDS.filter((b) => b.key in rates || b.key in counts);
  if (!bands.length) {
    el.innerHTML = `<h2 class="text-lg font-semibold mb-2">Does confidence mean anything?</h2>
      <p class="text-sm text-text-secondary">No confidence values recorded on scored stances yet.</p>`;
    return;
  }
  const rows = bands.map((b) => {
    const c = counts[b.key];
    const scored = c?.scored ?? 0;
    const rate = rates[b.key];
    return `<div class="text-sm flex justify-between py-1 border-b border-border">
      <span>${b.label}</span>
      <span><span class="${hitRateClass(rate, scored)}">${pct(rate)}</span> <span class="text-text-secondary">hit rate over ${scored} calls${sampleNote(scored)}</span></span>
    </div>`;
  }).join("");
  el.innerHTML = `<h2 class="text-lg font-semibold mb-1">Does confidence mean anything?</h2>
    <p class="text-xs text-text-secondary mb-2">Each stance carries the AI's own confidence (0–1). If that confidence were well calibrated, hit rate should climb from the low band to the high band. A flat or inverted pattern means stated confidence isn't predictive and shouldn't drive position sizing.</p>
    ${rows}`;
}

function renderDomainTable(data: Summary): void {
  const el = document.getElementById("track-domain-table");
  if (!el) return;
  el.classList.remove("hidden");
  const domains = data.by_domain || [];
  if (!domains.length) {
    el.innerHTML = `<h2 class="text-lg font-semibold mb-2">Which news sources lead to good calls?</h2>
      <p class="text-sm text-text-secondary">No resolvable article domains yet — stances need cited article evidence before results can be attributed to the news sites they came from.</p>`;
    return;
  }
  const rows = domains.map((d) =>
    `<tr class="border-b border-border">
      <td class="py-1.5 pr-3 text-sm">${esc(d.domain)}</td>
      <td class="py-1.5 pr-3 text-sm text-right">${Number(d.scored).toFixed(2)}</td>
      <td class="py-1.5 pr-3 text-sm text-right ${hitRateClass(d.hit_rate, Number(d.scored))}">${pct(d.hit_rate)}</td>
      <td class="py-1.5 text-sm text-right ${signClass(d.mean_excess)}">${pp(d.mean_excess)}</td>
    </tr>`
  ).join("");
  el.innerHTML = `<h2 class="text-lg font-semibold mb-1">Which news sources lead to good calls? (top ${domains.length})</h2>
    <p class="text-xs text-text-secondary mb-2">Stances cite the articles they were based on; results are attributed back to those articles' websites. When one stance cites several domains, each gets fractional 1/N credit — which is why "Scored" can be a decimal. Domains with only a call or two are anecdotes, not track records.</p>
    <table class="w-full text-left">
      <thead><tr class="text-xs text-text-secondary border-b border-border">
        <th class="py-1 pr-3">Domain</th>
        <th class="py-1 pr-3 text-right" title="Credit-weighted number of scored calls citing this domain">Scored (weighted)</th>
        <th class="py-1 pr-3 text-right">Hit rate</th>
        <th class="py-1 text-right">Avg excess</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderCoverage(data: Summary): void {
  const el = document.getElementById("track-coverage");
  if (!el) return;
  el.classList.remove("hidden");
  const cov = data.evidence_coverage || {};
  const lines = Object.keys(cov).sort().map((src) => {
    const c = cov[src];
    return `<div class="text-sm flex justify-between py-1 border-b border-border">
      <span>${esc(sourceLabel(src))}</span>
      <span class="text-text-secondary">structured evidence ${c.pct_with_evidence ?? "—"}% · cited articles ${c.pct_with_article_ids ?? "—"}% of ${c.rows} stances</span>
    </div>`;
  }).join("");
  el.innerHTML = `<h2 class="text-lg font-semibold mb-1">Evidence coverage (data quality)</h2>
    <p class="text-xs text-text-secondary mb-2">How many stances recorded <em>why</em> they were made. The news-source table above can only credit domains for stances that cited articles, so low coverage here means that table understates reality.</p>
    ${lines || `<p class="text-sm text-text-secondary">No coverage stats.</p>`}`;
}

function renderVerdict(data: Summary): void {
  const el = document.getElementById("track-verdict");
  if (!el) return;
  el.classList.remove("hidden");
  const entries = Object.entries(data.hit_rate_by_verdict || {}).filter(([v]) => v !== "UNKNOWN");
  const header = `<h2 class="text-lg font-semibold mb-1">AI second-opinion review</h2>
    <p class="text-xs text-text-secondary mb-2">Some stances get an independent AI review before acting: ALIGNED (reviewer agrees) or TENSION (reviewer disagrees). If the review adds value, ALIGNED calls should hit more often than TENSION ones.</p>`;
  if (!entries.length) {
    el.innerHTML = `${header}<p class="text-sm text-text-secondary">None of the scored stances have a review verdict yet, so there's nothing to compare. This section will fill in once reviewed stances mature.</p>`;
    return;
  }
  el.innerHTML = header + entries.map(([v, rate]) =>
    `<div class="text-sm flex justify-between py-1 border-b border-border"><span>${esc(v)}</span><span>${pct(rate)}</span></div>`
  ).join("");
}

function callLine(c: CallRow): string {
  const asOf = String(c.as_of || "").slice(0, 10);
  const tkr = num(c.ticker_return);
  const bench = num(c.benchmark_return);
  const detail = tkr != null && bench != null
    ? `stock ${tkr >= 0 ? "+" : ""}${tkr.toFixed(1)}% vs index ${bench >= 0 ? "+" : ""}${bench.toFixed(1)}%`
    : "";
  return `<div class="text-sm py-1 flex justify-between border-b border-border">
    <span><span class="font-medium">${esc(c.ticker)}</span> <span class="text-text-secondary">${esc(c.stance)}${asOf ? ` · ${asOf}` : ""}</span></span>
    <span><span class="${signClass(c.excess_return)}">${pp(c.excess_return)}</span>${detail ? ` <span class="text-xs text-text-secondary">${detail}</span>` : ""}</span>
  </div>`;
}

function renderCalls(data: Summary): void {
  const el = document.getElementById("track-calls");
  if (!el) return;
  el.classList.remove("hidden");
  const best = (data.best_calls || []).slice(0, 5);
  const worst = (data.worst_calls || []).slice(0, 5);
  if (!best.length && !worst.length) {
    el.innerHTML = `<h2 class="text-lg font-semibold mb-2">Best and worst calls</h2>
      <p class="text-sm text-text-secondary">No scored calls yet.</p>`;
    return;
  }
  el.innerHTML = `<h2 class="text-lg font-semibold mb-1">Best and worst calls</h2>
    <p class="text-xs text-text-secondary mb-2">The biggest wins and losses among scored calls over the ${data.horizon_days}-day window, ranked by excess return in the call's own direction.</p>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <h3 class="text-sm font-medium mb-1 text-theme-success-text">Biggest wins</h3>
        ${best.map(callLine).join("") || `<p class="text-sm text-text-secondary">None yet.</p>`}
      </div>
      <div>
        <h3 class="text-sm font-medium mb-1 text-theme-error-text">Biggest losses</h3>
        ${worst.map(callLine).join("") || `<p class="text-sm text-text-secondary">None yet.</p>`}
      </div>
    </div>`;
}

async function loadTrackRecord(): Promise<void> {
  const loading = document.getElementById("track-loading");
  const err = document.getElementById("track-error");
  try {
    const resp = await fetch("/api/track-record/summary?horizon=30");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = (await resp.json()) as Summary;
    if (loading) loading.classList.add("hidden");
    renderHeadline(data);
    renderSummaryCards(data);
    renderSourceTable(data);
    renderConfidence(data);
    renderDomainTable(data);
    renderCoverage(data);
    renderVerdict(data);
    renderCalls(data);
  } catch (e) {
    if (loading) loading.classList.add("hidden");
    if (err) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.classList.remove("hidden");
    }
  }
}

document.addEventListener("DOMContentLoaded", () => void loadTrackRecord());
