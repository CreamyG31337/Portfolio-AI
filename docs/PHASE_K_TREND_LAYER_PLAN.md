# Phase K — trend layer plan (K7-K11)

**Status:** planned, 2026-07-30. Nothing here is built.

Companion to [`PHASE_K_SOURCE_LIST.md`](PHASE_K_SOURCE_LIST.md) §20, which establishes *why*
this exists: five research rounds rejected ten sectors against the **event-alpha** bar, and
that bar was never the only use for the corpus. This doc plans the second use — trend,
context, sentiment, and cross-source corroboration.

**The one-line thesis:** no single YouTube source is reliable, and we have now proven that
across five rounds. But *agreement between independent sources is measurable*, and
disagreement is itself information. Double-nomination was our best research instrument; it
should become the product's core algorithm.

---

## 0. What already exists — build on it, do not rebuild it

This is the most important section. Most of what the trend layer needs is shipped, and the
hook for YouTube is already written into the roadmap.

| Capability | Where | Status |
|---|---|---|
| Caption fetch | `web_dashboard/yt_captions.py` | **K1 shipped** |
| Normalize → `research_articles` | `web_dashboard/yt_articles.py` | **K2 shipped** |
| Allowlist poll job | `web_dashboard/scheduler/jobs_yt.py` | **K3 shipped**, off by default |
| Cross-source idea clusters | `ROADMAP.md` §2.2 ideas inbox | shipped — **explicitly waiting on YouTube** (`ROADMAP.md:886`) |
| Sector stance over time | `sector_meta_analysis` | shipped |
| Market regime prior | `market_daily_brief` | shipped |
| Per-ticker fusion | `ticker_meta_analysis` + Phase 1 signal fusion | shipped |
| Source-ROI scoring | Phase H1; **K5** is the YouTube slice | H1 shipped, K5 open |
| Outcome feedback | `jobs_stance_outcomes.py`, ledger, baselines (M5) | shipped |

**Consequence:** the trend layer is mostly *wiring*, not new architecture. Phase K's job is to
become one well-characterised source among many inside machinery that already merges sources
and already measures which ones pay. The roadmap's own framing for K5 — *"kill channels that
fail the source-ROI slice"* — is exactly the discipline §20 asks for, and it already exists.

**Anti-goal:** do not build a parallel YouTube-specific analytics stack. If a question can be
answered by feeding `research_articles` into the existing meta layers, do that.

---

## 1. Success criteria, fixed before building

§20's stated risk is that trend work degenerates into an unfalsifiable vibes generator. The
countermeasure is committing to numbers now.

| Component | Ships only if | Killed if |
|---|---|---|
| ~~K7 filters~~ | ~~Friction-word score separates known-promotional from known-primary~~ | **KILLED 2026-07-30 (source list §21).** Ran backwards: 95% of *known-primary* videos trip `zero_friction` vs 33% of interviews. Friction words track topic, not integrity. `disclosure_hits` survived; module ships with the honest interpretation |
| K8 on-demand retrieval | ≥50% of agent-issued queries return ≥1 transcript judged relevant to the question asked | Mostly irrelevant results; keyword search is too noisy (the §9 prediction) |
| K9 trend series | A ticker/theme series moves **before or with** a corroborating external series (earnings mention, price move, filing) on ≥3 dated instances | Series is noise, or lags everything |
| K10 corroboration | Multi-source-corroborated claims outperform single-source claims on the existing stance-outcome measure | No difference — corroboration adds cost, not accuracy |
| K11 promotion detector | Flags ≥1 true paid-IR wave on a held name with an acceptable false-positive rate | Fires constantly or never |

None of these need new measurement infrastructure — M5 baselines and
`jobs_stance_outcomes.py` already do outcome scoring.

---

## 2. K7 — cheap content filters (do first; smallest, best-justified)

Three filters, all double-nominated by independent models, all cheap. **They are per-article
*features*, not gates** — that distinction is the whole point of §20. A promotional video is
not deleted; it is labelled, and the label is itself data (see K11).

1. **Friction-word zero-count** (§19, both models). Count occurrences of `burn rate`,
   `dilution`, `warrant overhang`, `bought deal`, `G&A`, `cost overrun`, `inferred only`,
   `AISC`, `going concern`. Paid-IR interviews score zero on all of them. No LLM call.
   *Best single filter any research round produced.*
2. **Caption-gap detector** (§17, Model A). Distribution of timestamp gaps in a transcript;
   long silent stretches = b-roll or on-screen-graphics dependence. A computable proxy for
   `visual_dependence`, which did real rejecting work in §17 and §19.
3. **Derived-content score** (§8). Attribution phrases (*"according to a report"*, *"analysts
   say"*) vs technical-term density. Specced since §8, still unbuilt.

Plus the convergent macro tells from §17/§19 as a lexicon: `TAM`, `CAGR`, `hyperscaler`,
`game-changer`, `multi-bagger`, *"in this video we will explore"*.

**Validation before use:** run all three across the existing Stage 0 corpus. Gamers Nexus must
score as primary and Resource Talks (which openly discloses paid content creation) must score
as promotional. If they don't, the heuristics are wrong and that is worth knowing before they
gate anything — same check §8 specced and we never ran.

---

## 3. K8 — on-demand retrieval (the architectural change)

**Push → pull.** Today K3 polls an allowlist nightly and asks *"what did my sources say?"*.
The capability we actually have is transcript retrieval for **any** video, which answers
*"what does YouTube know about X?"* when something is asking.

This directly addresses the objection in §20: it is implausible that YouTube holds nothing on
a given company or sector, and an allowlist is a bad instrument for finding out.

**Shape:** a tool the research/analysis agents can call —
`youtube_research(question, tickers, lookback)` → search → rank → fetch top *k* transcripts →
summarize against the question → return with sources and dates.

**Why it fits the budget:** episodic, not continuous. The ~90 fetches/IP/day ceiling (§14) is
crippling for polling and generous for a handful of research queries. A nightly poll of 15
sources costs 45-75 fetches *every day*; ten on-demand queries at 3 transcripts each cost 30,
only when asked.

**Reuses the §9 discovery ranking**, which is unbuilt and needed here anyway:
- listing is **not** rate-limited, only caption fetch is (§13) — so search, rank and filter
  cost nothing
- rank by multi-query recurrence, then structural rejects (sub count, cadence, duration),
  then K7 filters, and only then spend fetches
- **query the observation, not the ticker** — `transformer lead times 2026`, not `VRT stock`.
  Ticker-targeted queries select for promotional content by construction (§19 makes this
  concrete: the promotional corpus is *organised* around tickers)

**Build the §9 discovery script first** — it is the shared substrate for K8 and would have
caught 3 of 4 dead grid/power channels (§17) without a research round.

---

## 4. K9 — trend and sentiment series

The unit stops being the video. Aggregate `research_articles` into per-(ticker | theme |
sector) weekly series:

- mention volume, and share of corpus
- stance distribution and its **delta** — levels are nearly meaningless, changes are the
  signal
- named-entity co-occurrence (e.g. `MU` × `DRAM pricing` × `price increase`)
- the K7 feature averages (promotion score, derived score) as corpus-health context

**Themes, not just tickers.** §20's example: no grid channel leads on transformer lead times,
but a rising count of contractors mentioning backorders across months is a real read on
VRT/ETN backlog. That is invisible per-video and obvious in aggregate. Same for
DRAM/component pricing, which §3 called the strongest thread and §14's extractor then scored
at only 1 PRICING hit — a bucketing failure worth fixing here (§14 note 2).

**Feeds `sector_meta_analysis`**, which already tracks sector stance over time. This is
wiring, not a new store.

**Guard against the obvious trap:** a trend series built from a corpus whose composition
changes is measuring its own composition. Normalise by corpus size and hold the source set
fixed within a comparison window.

---

## 5. K10 — cross-source corroboration (the core algorithm)

Double-nomination was the most reliable instrument across all five research rounds — more
reliable than any single model's ranking, and it worked for rejections as well as picks
(§16). Promote it from method to product.

**Unit of output:** not *"a claim from a video"* but *"a claim, corroborated by N independent
sources, with a divergence score."*

- **Independence matters more than count.** Two channels reading the same press release are
  one source (§8's derived-content problem, §19's "YouTubers subscribe to UxC and read the
  numbers out days later"). K7's derived score is the independence proxy.
- **Cross-modal corroboration is the strongest form** — a YouTube claim agreeing with a
  filing, an insider trade, a congressional trade, or a price move is worth far more than two
  YouTubers agreeing. All of those collectors already exist in this codebase.
- **Disagreement is signal, not noise.** Sources diverging on a name is a flag for human
  attention. The ideas inbox already has a contradictions surface; this feeds it.

**Where it lands:** `ROADMAP.md` §2.2 cross-source idea clusters, which line 886 says is
waiting for YouTube. This is the intended consumer — it exists, it is unblocked since K2
shipped, and it is the natural home for "merge and rate ideas."

---

## 6. K11 — promotion-wave detector (defensive, and the clearest near-term win)

Built entirely from a Use 1 rejection (§19), which makes it the proof of §20's argument.

Both models independently: attention alpha **is** live for TSXV juniors, and it is the paid-IR
machine working as designed — a video drop produces a 24-48h retail spike, then reverses into
the bought deal that follows.

**We do not trade that** (§19: it is buying a promotion to sell into retail, and our
week-scale outcome machinery would capture the reversal and miss the spike). **We detect it on
names we hold.** We own GLO.TO; both models name it as a promotion target.

- Input: K7 friction-word score + K9 mention-volume spike, on held tickers only
- Output: a risk flag — *"paid-IR wave running on GLO.TO"* — into the existing alerts path
- Interpretation: elevated probability of a financing and of adverse selection; a review
  trigger, never an auto-trade

Same tells, opposite direction, no ethical problem, and it matches the horizon our machinery
actually measures.

---

## 7. Open empirical question, answerable now with existing tooling

Both models made a **falsifiable** claim in §19: a promotional video produces a measurable
24-48h abnormal volume/price move in DNN/NXE/GLO-type names, which then reverses.

> **Design constraint from §22 — read before running it.** View counts are now measured, and
> the mining interview corpus runs a **2,350-13,000 median**, not the "80K+ subscribers" the
> claim was argued from. Sample the **high-view tail** (Mining Stock Education's 252k
> outlier, Palisades' 107k), with `view_count` as the independent variable — effect size
> should scale with viewers if the mechanism is real. Running the study on median-view videos
> would return a null that proves nothing, because 2,350 viewers cannot move anything.

`scripts/insider_event_study.py` and the cap-aware abnormal-return machinery in
`benchmarks.py` already do exactly this measurement. It needs **zero caption fetches and zero
research rounds**, and it is §7's Stage 1 — described there as the highest information-per-hour
work available.

It decides whether the single YES in five rounds of research is real, and it calibrates K11.

---

## 8. Sequence

Cheapest and most decisive first.

| # | Item | Cost | Why here |
|---|---|---|---|
| 1 | ~~§9 discovery script~~ | — | **Done 2026-07-30** — `scripts/yt_discover_channels.py`. Confirmed §17's absence claim by measurement in ~2 min / 0 fetches (source list §17). |
| 2 | ~~**K7 filters**~~ | — | **Done 2026-07-30**, and the headline filter was falsified — see source list §21. `web_dashboard/yt_content_filters.py` ships the survivors (`disclosure_hits`, `finance_topic_rate`) with the measured interpretation |
| 3 | **Event study** (§7 above) | small | Existing tooling; decides if attention alpha is real |
| 4 | **K4** enrichment parity | small | Already on the roadmap; makes K9 possible |
| 5 | **K9** trend series | medium | Where the discarded 73% of the corpus starts paying |
| 6 | **K11** promotion detector | medium | Depends on K7 + K9 + event study |
| 7 | **K10** corroboration → ideas inbox | medium | The core algorithm; wants K9 in place |
| 8 | **K5** source-ROI slice | after ~30d | Decides what survives. Needs outcome history |

Deliberately **not** next: more sector research rounds. Five rounds produced two adopted
sectors and six structured-dataset findings; the marginal round is worth less than any item
above. Resume only when K5 can say which existing sources pay.

---

## 9. Parked, with a note

**Structured public datasets.** Six rounds surfaced these repeatedly, and they are the single
most-confirmed finding in the whole research programme (§18 failure mode 2, fired 5×):

- FAA TFRs, FCC OET, SAM.gov (space); NHTSA (recalls); FBI NICS (firearms)
- Cass Freight Index (freight); ISO/RTO interconnection queues + FERC + EPA air permits (grid)
- **SEDAR+ / EDGAR / NRC / CNSC / EIA Uranium Marketing Annual** (uranium — all free)

All free, all leading, all structured. **This is a different project from a captions
pipeline** and should not be smuggled into Phase K. Interconnection queues at 18-24 months are
the longest-dated signal found anywhere in these docs, and the EPA air-permit → datacenter
buildout link (§17) is the most novel. Worth its own phase when Phase K's fate is settled.

**Automotive seeding.** §12 adopted 6 verified channels; they are still not in
`scripts/seed_yt_sources.py`, and §14's run aborted before reaching them, so the tech-vs-auto
yield comparison is still open. Cheap, and the channels are already caption-verified 6/6.
Caveat from §15: automotive has near-zero portfolio relevance (TSLA 0.7%, no F/GM/RIVN/LCID),
so this is a mechanism experiment, not a coverage decision.
