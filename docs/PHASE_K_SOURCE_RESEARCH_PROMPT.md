# Phase K — source research prompt (reusable template)

Prompt for handing sector-source discovery to a research LLM (Gemini / Grok / etc).

**Why this template exists.** The first research round
([`PHASE_K_SOURCE_LIST.md`](PHASE_K_SOURCE_LIST.md) §2) came back with three wrong handles,
inverted live-stream figures, wrong caption-status claims, and a fabricated ticker. All of
it read as confident. The instructions below are shaped specifically to make those failure
modes less likely and — more importantly — cheap to catch.

**Rules for using the output:**

1. Never paste results straight into `youtube_sources`. Every handle, cadence, caption
   status and live share gets verified with `yt-dlp` first.
2. Treat the output as *candidate leads*, not data. Its real value is surfacing channels
   we did not know existed.
3. Run the same prompt at two different models and **weight the overlap** — independent
   double-nomination proved far more reliable than either model's own ranking.

---

## §1 The space/aerospace instance (ready to send)

> I'm building an automated pipeline that ingests YouTube captions and extracts
> potentially tradeable claims about public companies. It already runs on ~13
> tech/semiconductor channels. I want to extend it to **space and aerospace**, and I need
> candidate channels.
>
> **How the pipeline works, because it constrains what's useful:**
> - It reads captions only. No video, no images, no audio tone. If the signal is a
>   screenshot, an oscilloscope trace, or a chart, it is invisible to me.
> - It costs tokens per video. A 3-hour stream is ~25-35k tokens and usually low density.
>   Short, information-dense videos are worth far more than long ones.
> - It works from a curated allowlist, so I need a *small* number of high-quality sources,
>   not broad coverage.
> - It needs English captions (manual or auto-generated both fine).
>
> **Two distinct mechanisms interest me, and I want them labelled separately:**
> - **INFORMATION** — the video contains a material fact not yet priced in: a schedule
>   slip, a test failure, a contract award, a hardware change spotted before it was
>   announced. The video does not need to move the stock; it needs to *predict* the move.
> - **ATTENTION** — the video itself is the catalyst, because the audience trades on it.
>   This only works on small caps with retail followings. In my tech list this mechanism
>   turned out to be unavailable (96% of coverage was mega-cap). **Space may be different**
>   — RKLB, ASTS, LUNR, PL, RDW are small/mid caps with real retail interest. I
>   specifically want to know whether attention alpha is live in this sector.
>
> **Tickers I care about:** RKLB, ASTS, LUNR, PL, RDW, BKSY, MNTS, SPCE, plus primes and
> suppliers (LMT, NOC, BA, RTX, HEI, TDG, LHX) and any small-cap supplier I've missed.
> Private entities (SpaceX, Blue Origin, Firefly, Stoke, Relativity) matter when they move
> a public competitor or customer.
>
> **Critical honesty requirements — please follow these literally:**
> - I will mechanically verify every handle, cadence and caption claim with `yt-dlp`
>   immediately. A wrong handle is worse than no handle, because it silently ingests
>   nothing. **If you are not certain a channel's handle is exact, write `HANDLE UNSURE`
>   and give the channel's full name instead of guessing.**
> - Last round a model reported a channel had "0% live streams, records live-to-tape" when
>   its `/streams` tab held 30+ videos at a 191-minute median. **If you do not actually
>   know a channel's live/VOD split, write `UNKNOWN`.** This matters enormously here,
>   because launch coverage is inherently live and multi-hour.
> - Do not invent tickers. Last round a model reported ASUS trades as `ASY`, which is not a
>   real ticker. If a company is private, foreign-listed, or you are unsure, say so.
> - Separate what you *know* from what you *infer*. Unfalsifiable praise is not useful;
>   `UNVERIFIED` is a perfectly good answer and I will trust the rest of your output more
>   because of it.
>
> **For each channel, give me:**
> 1. Channel name and handle (or `HANDLE UNSURE` + full name)
> 2. Mechanism: INFORMATION / ATTENTION / BOTH
> 3. Which of the tickers above it actually discusses — not which it theoretically could
> 4. **Primary vs derived**: does this channel generate original observation/analysis, or
>    does it summarise press releases and news? I want to exclude news-rehash channels, and
>    space YouTube has a lot of them. What is the tell?
> 5. **Live vs VOD split**, and whether the analysis VODs are separable from launch-day
>    streams (e.g. a separate channel or a clear title convention I can filter on)
> 6. Typical video length for the *non-stream* content
> 7. Lead time vs mainstream financial press
> 8. One dated, checkable example where this channel had something material first — or
>    `UNVERIFIED` if you cannot supply one
> 9. Conflicts: sponsorships, launch-provider access that could be withdrawn, held positions
>
> **Also give me:**
>
> **A. A blocklist** of space channels that look authoritative but are not — especially
> retail-pump channels around small-cap space stocks, and AI-narrated news-rehash channels.
> Give the behavioural tell for each, phrased so I could detect it from caption text alone.
>
> **B. The negative space:** what kinds of space/aerospace signal will YouTube captions
> simply never be a good source for, where I should use filings, launch manifests, FCC/FAA
> records, or contract award databases instead? I would rather know this now.
>
> **C. Your read on the core question:** is ATTENTION alpha actually live for small-cap
> space stocks — do videos from these channels measurably move RKLB/ASTS/LUNR — or is that
> wishful thinking on my part? Say so plainly if it is.

---

## §2 Reusing this for another sector

Swap the sector, the ticker list, and the sector-specific hazard in the honesty block.
Keep unchanged:

- the caption-only / token-cost / allowlist constraints
- the INFORMATION vs ATTENTION split
- the `HANDLE UNSURE` and `UNKNOWN` escape hatches
- the primary-vs-derived question (item 4) — this is the highest-value question in the
  prompt and the one whose answer generalises best
- parts A, B and C

The sector-specific hazard to name in the honesty block, by sector:

| Sector | Hazard to call out explicitly |
|---|---|
| Space | Live launch coverage inflates volume; retail pump channels around small caps |
| Autos/EV | Heavy sponsorship by manufacturers; delivery-number speculation |
| Mining | Junior-stock promotion is endemic; primary data is in filings, not video |
| Broad market | Almost entirely derived commentary; fails the primary-source test by design |

---

## §3 Verification checklist for whatever comes back

Before anything reaches `youtube_sources`:

1. Resolve every handle → `channel_id` with `yt-dlp`. Expect ~25% to be wrong.
2. Read the `/streams` tab, not just `/videos` — `/videos` hides live content and will
   make any channel look VOD-only.
3. Pull duration distribution; set `min_duration_s` / `max_duration_s` per source.
4. Check subtitle tracks on one recent video (`manual` vs `automatic_captions`).
5. Run `fetch_caption_text` against the newest video end-to-end.
6. Scan ~60 recent titles for the target tickers to confirm the channel discusses the
   companies claimed, and at what market cap — this is what disproved the small-cap
   hypothesis for tech (§3 of the source list).

---

## §4 Round 3 — what four rounds of measurement changed about the ask

Rounds 1–2 covered tech (adopted), space (rejected), consumer electronics (rejected) and
automotive (adopted). Three findings now dominate what is worth asking for, and the §1
prompt does **not** encode them:

1. **Tradeability is the binding constraint, not channel quality.** Space and displays both
   failed with excellent channels. Quality of measurement turned out to be *inversely*
   correlated with tradeability, twice, for the same reason: the best primary observation
   points at private companies (SpaceX) or foreign listings (LG, Samsung, MSI, ASUS,
   Gigabyte). **A channel is worthless to us if its subjects are not tradeable.**

   > **Corrected 2026-07-29 — the universe is North American, not US-only.** Reading the
   > actual book (source list §15) shows **41% of holdings are Canadian-listed** (`.TO` /
   > `.V`). Earlier rounds of this prompt said "US-listed", which understates the tradeable
   > set and wrongly excludes TSX/TSXV miners — a theme the portfolio is heavily in. Ask for
   > **US + TSX + TSXV**. This does not revive space or displays (SpaceX is still private;
   > LG/Samsung/TCL are still Korean and Chinese), but it does put mining and uranium back
   > in scope, including the TSXV juniors where ATTENTION alpha is plausibly live.
2. **Materiality scales with revenue share, not defect severity** (source list §11).
   Nvidia's melting connectors were severe, viral, and close to immaterial to a
   datacenter-driven P&L. So the target is **mid-cap pure plays where the thing the channel
   measures *is* the business** — not more mega-cap coverage. Automotive scored best so far
   precisely because Munro's BOM teardowns *are* the RIVN/LCID equity thesis.
3. **The corpus must stay small.** ~90 caption fetches per egress IP per day (§14). We can
   afford roughly 20-30 enabled sources total. Asking for "comprehensive coverage" is
   actively harmful; we want a handful of high-yield sources per sector.

Also worth stating to the model: a **new** wrong-handle failure mode appeared in round 2 —
`@iFixit` resolves to a 290-subscriber impostor, which would have silently ingested an
almost-empty channel rather than erroring. Sub count is now part of the verification.

### Sector shortlist for round 3

Ranked by *expected* fit under criteria 1+2 above. This ranking is a hypothesis, not a
finding — the point of §5 is to have two models attack it before we spend probe time.

| Sector | Pure-play tickers where the measured product ≈ the business | Why it might beat tech |
|---|---|---|
| **Residential solar / home energy** | ENPH, SEDG, FSLR, RUN, NOVA, ARRY, NXT, SHLS, GNRC | Installer and field-failure channels. Microinverter reliability *is* the ENPH thesis; there is no second business line to dilute it. All US-listed. |
| **Agriculture** | DE, AGCO, CNH, CTVA, MOS, NTR, FMC, LNN, TWI | Farmer-operator channels report input costs, yields, equipment downtime and right-to-repair continuously — genuinely leading on ag capex and fertiliser demand. |
| **Power tools / outdoor equipment** | SWK, TTC, GNRC, DE, plus HD/LOW as demand read-through | Destructive-testing channels (Project Farm genre) measure the exact SKU that generates the revenue. DeWalt is most of SWK. |
| **RV / powersports / marine** | THO, WGO, LCII, PATK, HOG, PII, BC, MBUU | Quality-defect and dealer-inventory content on small/mid caps with real retail followings — the one shortlist sector where **ATTENTION** alpha is plausibly live. |
| **Firearms / ammunition** | RGR, SWBI, AOUT, POWW, OLN, VSTO | Enormous, technically rigorous product-test corpus; RGR and SWBI are small caps whose entire revenue is the tested product. Hazard: heavy sponsorship and affiliate revenue. |
| **Trucking / heavy diesel** | PCAR, CMI, CAT, plus KNX, ODFL, XPO, SAIA | Owner-operator channels discuss spot rates and emissions-system failures — spot-rate commentary is a leading indicator for the carriers, and it is *observed*, not derived. |
| **Restaurants / consumer** | CAVA, WING, CMG, SG, PTLO, DNUT, TXRH | Store-visit and franchisee channels. Pure plays, retail-followed. Hazard: almost all of it is sponsored or derived. |
| **3D printing / prosumer hardware** | DDD, SSYS, PRLB, XMTR, MKFG | Micro/small caps plus a rigorous review corpus. Hazard: the market leader (Bambu) is private — the space failure mode again. |

**Run order recommendation:** solar, then agriculture, then trucking. Solar has the cleanest
pure-play/materiality story; agriculture has the best claim to *leading* rather than
concurrent information; trucking is the only shortlist sector offering a macro read-through
(freight rates) rather than single-issuer claims.

---

## §5 Sector-triage prompt (send this first, to two models)

Cheap, one response each, and it decides where probe time goes. Send verbatim.

> I run an automated pipeline that ingests **YouTube captions only** (no video, no audio
> tone, no images) and extracts potentially-tradeable claims about **US-listed** public
> companies. It is live on ~13 tech/semiconductor channels and 6 automotive channels.
>
> I need to pick which sector to expand into next, and I want you to attack my ranking
> rather than agree with it.
>
> **Hard constraints, because they have already killed two sectors for me:**
> - **Tradeable or worthless.** I can trade **US, TSX and TSXV** listings with reasonable
>   liquidity — note that includes Canadian miners and juniors. I
>   evaluated space/aerospace and rejected it: the best channels are overwhelmingly about
>   SpaceX, which is private. I evaluated TVs/displays and rejected it: the best channel is
>   excellent, and LG/Samsung/TCL are Korean and Chinese listings. In both cases the
>   *quality of observation was inversely correlated with tradeability*. Assume that is the
>   default failure mode and tell me where it bites.
> - **Materiality scales with revenue share, not with how dramatic the finding is.** A
>   severe defect in a mega-cap's minor product line is noise. What I want is **mid-cap pure
>   plays where the thing the channel measures is substantially the whole business.**
> - **Small corpus.** Rate limits cap me at roughly 20-30 enabled channels in total. I want
>   3-6 excellent sources per sector, not coverage.
> - **Captions only.** If the signal is a chart, a thermal image, or an oscilloscope trace,
>   it is invisible to me. Channels whose value is visual score badly regardless of quality.
>
> - **I must already have exposure.** This is a live portfolio, not a screener. A brilliant
>   sector I hold nothing in is worth less to me than a mediocre one that covers 12% of my
>   book. My weights are given below; use them.
>
> **My candidate sectors, with my actual portfolio weight in each — rank by fit *and*
> weight:**
>
> | Sector | My weight | Tickers I hold / care about |
> |---|---|---|
> | Grid / power / datacenter electrical | **11.9%** | VRT (my largest single position), GEV, ETN, AOS, FTS.TO, ENB.TO, KEY.TO, ATRL.TO; also PWR, HUBB, NVT, CEG, VST unheld |
> | Gold / precious metals | **10.8%** | AEM.TO, GMIN.TO, XGD.TO, GLCC.TO, CGL.TO, TECK.B.TO, XMA.TO |
> | Defense / aerospace primes | **6.7%** | GE, LHX, GD, ATRL.TO, ITA |
> | Uranium / nuclear fuel cycle | 2.4% overall but **~19% of the fund I actively trade** | CCO.TO, GLO.TO, LEU, URNM, URNJ, HURA.TO, OKLO, CEG; also DNN.TO, NXE.TO, UEC, UUUU |
> | Agriculture / heavy equipment | 2.8% | DE, CMI, TRMB; also AGCO, CNH, CTVA, MOS, NTR unheld |
> | Rail / freight / industrials | 2.8% | SNA, FAST, RAIL, DRX.TO, CNR.TO; also PCAR, KNX, ODFL unheld |
>
> Note the currency mix: **41% of my book is Canadian-listed (TSX / TSXV)**, so Canadian
> miners and uranium juniors are fully tradeable for me — do not exclude them as "foreign".
>
> I have **no position at all** in residential solar, RV/powersports/marine, HVAC, power
> tools, firearms, restaurants or 3D printing. A previous round of this prompt ranked solar
> and RV as the top two sectors; both were useless to me for exactly this reason. If you
> want to recommend a sector I hold nothing in, you need to argue it is worth *adding
> exposure* to, and say so explicitly rather than just ranking it first.
>
> **For each of those six sectors, in one compact table row each, give me:**
> 1. Sector
> 2. **Tradeable share** — of the companies that sector's YouTube channels actually talk
>    about, roughly what fraction are US/TSX/TSXV-listed and liquid? This is the criterion
>    that killed space (0-3%) and displays (26%). Automotive scored 70-100%.
> 3. **Pure-play score (1-5)** — does a channel-observable fact move a large share of some
>    issuer's revenue, or only a minor product line?
> 4. **Primary-observation depth (1-5)** — is there a real corpus of people doing original
>    measurement, teardown, field-failure or cost analysis? Or is the sector's YouTube mostly
>    people reading press releases and analyst notes aloud?
> 5. **Caption-legibility (1-5)** — does the value survive being reduced to a transcript?
> 6. **Lead time** — does this sector's YouTube know things *before* the sell-side, or
>    concurrently? Concurrent is worthless to me.
> 7. **Is ATTENTION alpha live** — are there small caps here whose retail base actually
>    trades on these videos? YES / NO / UNKNOWN. In tech the answer was a clear no.
> 8. **The one thing most likely to make me reject this sector after I spend a day on it.**
>
> **Then, in prose, and this is the part I actually care about:**
>
> **A.** Rank the sectors and tell me plainly where my ordering is wrong.
> **B.** **Name a sector I did not list** that fits the constraints better than my top pick.
> Non-obvious is fine — the constraint that matters is a US/TSX-listed mid-cap pure play with
> a genuine primary-observation YouTube corpus that reduces well to text. **Name specific
> tickers.** A prior round proposed a sector but could not name a single company in it, which
> made it unverifiable and therefore useless.
> **C.** Which sectors are ones where I should skip video entirely and ingest a structured
> public dataset instead? I already learned this for space (FAA TFRs, FCC licences,
> SAM.gov beat every space channel) and for auto recalls (NHTSA filings). Tell me where the
> same pattern applies, and name the dataset.
> **D.** Where you are guessing rather than reporting, say so. `UNKNOWN` is a perfectly
> good answer and I will trust the rest of your output more because of it — I will be
> mechanically verifying whatever survives, and confident-and-wrong costs me a day.

---

## §6 Per-sector channel prompt (round 3 revision of §1)

Once triage picks a sector, send this. Substitute the `{{...}}` fields; keep everything
else. This is §1 plus the three round-2 findings, and with a machine-checkable output
format so two models' answers can be diffed for overlap without hand-transcription.

> I'm building an automated pipeline that ingests YouTube captions and extracts
> potentially-tradeable claims about US-listed companies. It runs on ~13
> tech/semiconductor channels and 6 automotive channels. I want to extend it to
> **{{SECTOR}}** and I need candidate channels.
>
> **How the pipeline works, because it constrains what is useful:**
> - Captions only. No video, no images, no audio tone. If the signal is a screenshot, a
>   chart, or a thermal image, it is invisible to me.
> - Tokens per video. A 3-hour stream is ~25-35k tokens at low density. Short,
>   information-dense videos are worth far more than long ones.
> - **Hard rate limit: ~90 caption fetches per day, total, across all sources.** I want
>   **4-8 channels**, not coverage. Recommending twenty is the same as recommending none.
> - Curated allowlist, English captions (manual or auto both fine).
>
> **The two mechanisms, labelled separately:**
> - **INFORMATION** — the video contains a material fact not yet priced: a cost estimate, a
>   field-failure pattern, a price change, a schedule slip, a spec change spotted before
>   announcement. It does not need to move the stock; it needs to *predict* the move.
> - **ATTENTION** — the video is itself the catalyst because the audience trades on it.
>   Requires a small cap with a retail following. In my tech list this turned out to be
>   unavailable (96.5% of coverage was mega-cap). {{ATTENTION_HYPOTHESIS}}
>
> **Tickers I care about:** {{TICKERS}}. Also flag any US-listed small/mid-cap supplier in
> this sector that I have missed. Private and foreign-listed companies matter **only** when
> they move a US-listed competitor or customer — say explicitly when that is the case.
>
> **Two criteria that have already killed sectors for me. Apply them ruthlessly:**
> - **Tradeability.** I rejected space (best channels are about SpaceX — private) and
>   displays (best channel is excellent; LG/Samsung/TCL are foreign-listed). Quality of
>   observation was *inversely* correlated with tradeability in both. For every channel you
>   name, tell me what fraction of the companies it actually discusses are US-listed.
> - **Revenue-share materiality.** A defect or cost finding matters in proportion to the
>   affected product's share of the issuer's revenue, not to how dramatic it is. Severe
>   findings about a mega-cap's minor product line are noise to me. Prefer channels covering
>   products that are substantially the whole business of some mid-cap.
>
> **Critical honesty requirements — follow these literally:**
> - I mechanically verify every handle immediately. Across three prior rounds, **4 of ~30
>   handles were wrong**, and one (`@iFixit`) resolved to a 290-subscriber impostor that
>   would have silently ingested an empty channel instead of erroring. **If you are not
>   certain a handle is exact, write `HANDLE UNSURE` and give the channel's full name and
>   approximate subscriber count instead of guessing.**
> - A prior round claimed a channel had "0% live streams, records live-to-tape" when its
>   `/streams` tab held 30+ videos at a 191-minute median. **If you do not know a channel's
>   live/VOD split, write `UNKNOWN`.**
> - Do not invent tickers. A prior round reported ASUS trades as `ASY`, which does not
>   exist. If a company is private or foreign-listed, say which.
> - Separate what you know from what you infer. Unfalsifiable praise is useless.
>   `UNVERIFIED` is a good answer and increases how much I trust the rest.
> - **Sector-specific hazard here: {{HAZARD}}.** Tell me which of your own recommendations
>   is most exposed to it.
>
> **Output format — part 1, a JSON array, one object per channel, no prose inside it:**
>
> ```json
> [{
>   "name": "channel name",
>   "handle": "@handle or HANDLE UNSURE",
>   "subs_approx": "1.2M or UNKNOWN",
>   "mechanism": "INFORMATION | ATTENTION | BOTH",
>   "tickers_actually_discussed": ["..."],
>   "tradeable_share_estimate": "e.g. 80% or UNKNOWN",
>   "primary_or_derived": "PRIMARY | DERIVED | MIXED",
>   "derived_tell": "how I would detect it from caption text alone",
>   "live_vod_split": "e.g. mostly VOD, ~5 streams/yr, or UNKNOWN",
>   "typical_nonstream_minutes": 20,
>   "lead_time_vs_press": "days | concurrent | lagging | UNKNOWN",
>   "dated_example": "YYYY-MM: what they had first, and on which ticker — or UNVERIFIED",
>   "conflicts": "sponsorships, affiliate revenue, manufacturer access, held positions",
>   "confidence": "HIGH | MEDIUM | LOW"
> }]
> ```
>
> **Part 2, in prose:**
>
> **A. A blocklist** of {{SECTOR}} channels that look authoritative but are not —
> especially sponsored review mills and AI-narrated news-rehash channels. Give the
> behavioural tell for each, phrased so I could detect it from **caption text alone**. Two
> prior models' blocklists had *zero* overlap, so I now weight the generalisable tells far
> above the specific names — please lead with the tells.
>
> **B. The negative space:** what {{SECTOR}} signal will captions never be good for, where
> I should use filings, regulatory records, or a public dataset instead? Name the dataset.
> I would rather know now — this is how I learned NHTSA beats auto-recall videos.
>
> **C. Your read on the core question:** {{CORE_QUESTION}} Say plainly if it is wishful
> thinking. A prior model's flat "I will be plain: it is wishful thinking" about space
> attention alpha was correct and saved me real time.

### Fill-ins for the three recommended sectors

**Solar / home energy**
- `SECTOR` = residential solar and home energy storage
- `TICKERS` = ENPH, SEDG, FSLR, RUN, NOVA, ARRY, NXT, SHLS, GNRC, TSLA (Powerwall only)
- `ATTENTION_HYPOTHESIS` = "SEDG, RUN and NOVA are small caps with heavily retail
  shareholder bases and active short interest, so attention alpha may be live here — I want
  a direct answer."
- `HAZARD` = installer channels are frequently affiliates or dealers for a specific
  inverter brand, which is a direct financial interest in the comparison they publish
- `CORE_QUESTION` = "Do installer and field-failure channels actually surface inverter and
  battery reliability problems before they show up in warranty accruals and earnings — and
  is there a channel with enough installed-base visibility for that to be more than
  anecdote?"

**Agriculture**
- `SECTOR` = row-crop agriculture, farm equipment and inputs
- `TICKERS` = DE, AGCO, CNH, CTVA, MOS, NTR, FMC, LNN, TWI, ADM, BG
- `ATTENTION_HYPOTHESIS` = "I doubt attention alpha exists here at all — farm channel
  audiences are operators, not traders. Tell me if I am wrong."
- `HAZARD` = most large farm channels are sponsored by an equipment dealer or an input
  supplier, and seed/chemical sponsorship is near-universal
- `CORE_QUESTION` = "Farmer-operator channels discuss input costs, planting decisions and
  equipment downtime in real time, months before the same information reaches quarterly
  results. Is that genuinely leading for DE/AGCO capex and MOS/NTR/CTVA demand, or is it
  anecdote from a sample too small and too geographically concentrated to aggregate?"

**Trucking / heavy diesel**
- `SECTOR` = trucking, freight and heavy diesel
- `TICKERS` = PCAR, CMI, CAT, KNX, ODFL, XPO, SAIA, WERN, HTLD, RXO
- `ATTENTION_HYPOTHESIS` = "Probably not live — but owner-operator audiences are large, so
  tell me if any small-cap carrier or broker has a retail base that reacts."
- `HAZARD` = owner-operator channels heavily monetise load-board and factoring affiliate
  deals, and spot-rate talk is often anecdote presented as market data
- `CORE_QUESTION` = "Is owner-operator spot-rate and freight-volume commentary a real
  leading indicator for carrier earnings, or does public spot-rate data (DAT, Cass, FTR)
  already give me the same signal earlier and cleaner? If the dataset wins, say so — I
  would rather ingest the dataset."

---

## §7 Handling round-3 output

1. **Diff the two JSON arrays on `handle`.** Independent double-nomination has been the
   single most reliable quality signal across all rounds — better than either model's own
   ranking. Probe the overlap first.
2. Run every survivor through the §3 checklist, plus the new step: **check subscriber
   count** against the model's `subs_approx`. An order-of-magnitude miss means an impostor
   channel, not a stale number.
3. Title-scan for tradeable share *before* fetching any captions. This is cheap (listing is
   not rate-limited, only caption fetch is — source list §13) and it is what rejected space
   and displays. Reject the sector at this step if tradeable share comes in under ~50%.
4. Only then spend caption fetches. Budget: **90/IP/day**, and Stage 0 needs ~10 videos per
   candidate source, so a 6-channel sector evaluation is a **full day's quota**. Sequence
   sectors; do not interleave.
5. Record the outcome as a new numbered section in
   [`PHASE_K_SOURCE_LIST.md`](PHASE_K_SOURCE_LIST.md), rejections included — the two
   rejected sectors have been more useful for calibrating the criteria than the adopted ones.

---

## §8 Holdings-derived fill-ins (2026-07-29 — use these first)

Source list §15 measured actual exposure and reset the run order. **Solar is dropped** —
there is no ENPH/SEDG/FSLR/RUN/NOVA position in any fund, so §6's top recommendation was
about a sector we have no stake in. Run these three instead, in order. All use the §6
prompt body.

### 8.1 Grid / power / datacenter electrical — run first

11.9% of the book and **VRT is the single largest individual position**. No promotion
problem, no listing problem, and the AI-datacenter power-constraint story is discussed
continuously and technically on YouTube. Best expected-value sector we have not tried.

- `SECTOR` = electrical power infrastructure, grid equipment and datacenter power/cooling
- `TICKERS` = VRT, ETN, GEV, PWR, HUBB, NVT, AOS, CEG, TLN, VST, plus Canadian utilities and
  midstream FTS.TO, ENB.TO, KEY.TO, TRP.TO, and engineering ATRL.TO
- `ATTENTION_HYPOTHESIS` = "I doubt it — these are mid and large caps with institutional
  bases. Say so if you agree; I want the INFORMATION mechanism here."
- `HAZARD` = the datacenter-power story is the most over-narrated theme on finance YouTube
  right now, and almost all of it is derived macro commentary rather than observation. I
  want people who install, spec, or test this equipment, not people with opinions about the
  AI buildout
- `CORE_QUESTION` = "Is there a genuine primary corpus here — electrical contractors,
  datacenter engineers, power-systems people, transformer/switchgear specialists — who
  discuss lead times, transformer and switchgear shortages, liquid-cooling retrofits and
  interconnection queues from direct experience? Lead times and equipment availability are
  exactly the kind of fact that shows up in VRT/ETN/PWR backlog a quarter or two later. Or
  is this sector's YouTube entirely macro talking heads, in which case tell me plainly and I
  will use filings and interconnection-queue data instead."

Note for the probe: `ServeTheHome` (already seeded) partially covers datacenter power, so
check for overlap before adding — and if the overlap is high that is itself an argument for
raising its `max_videos_per_poll` rather than adding new sources.

### 8.2 Uranium / nuclear fuel cycle — run second

~19% of Project Chimera, the fund the bot actually trades. Run second only because the
promotion filter needs building and validating first — this corpus is the most contaminated
we have evaluated.

- `SECTOR` = uranium mining and the nuclear fuel cycle, including SMR developers
- `TICKERS` = CCO.TO, DNN.TO, NXE.TO, GLO.TO, FCU.TO, UEC, UUUU, LEU, plus SMR/utility names
  OKLO, SMR, CEG, and the ETFs URNM, URNJ, HURA.TO for coverage checks
- `ATTENTION_HYPOTHESIS` = "**This is the sector where I think attention alpha might finally
  be live.** TSXV/TSX uranium juniors are genuine small caps with heavily retail
  shareholder bases, unlike the mega-caps that killed this mechanism in my tech list. I want
  a direct answer — and I am aware the same conditions that make attention alpha possible
  make paid promotion likely."
- `HAZARD` = junior-mining stock promotion is endemic and often *paid*, including channels
  that look like independent analysis but run investor-relations packages. Some channels
  disclose, many do not
- `CORE_QUESTION` = "Two parts. **(a)** Is there any channel in this space doing genuine
  primary work — drill-result interpretation, spot vs term price observation, conversion and
  enrichment capacity, utility contracting behaviour — as opposed to CEO interviews that are
  paid placement in substance if not in name? **(b)** For the CEO/management interview
  format specifically: a management interview *is* primary in the sense that the executive
  says new things on camera, but the channel has a direct financial conflict. How do I tell,
  **from caption text alone**, a substantive interview from a paid promotion? Give me
  concrete linguistic tells — that heuristic is worth more to me than any list of channel
  names."

### 8.3 Mining / precious metals — run as a follow-on to 8.2, not separately

10.8% of the book (XGD.TO, GLCC.TO, AEM.TO, CGL.TO, GMIN.TO), plus XMA.TO and TECK.B.TO.
Same corpus and same promotion problem as uranium, so reuse the calibrated tells rather than
spending a fresh research round. When you do run it: `TICKERS` = AEM.TO, ABX.TO, WPM.TO,
FNV.TO, GMIN.TO, K.TO, TECK.B.TO, plus US-listed NEM, and `HAZARD` / `CORE_QUESTION` as in
8.2 with "uranium junior" replaced by "gold junior".

**Prediction worth writing down before we look:** this sector fails the primary-source test
outright and the right answer is SEDAR+/technical-report ingestion rather than captions —
the same pattern as FAA/FCC for space and NHTSA for recalls. If the research comes back
enthusiastic, that is weak evidence, because promotional channels are *designed* to read as
authoritative.

### 8.4 Deprioritised, with reasons

- **Automotive** (§12, adopted, seeded pending) — best mechanism quality of any sector
  tested, and **almost no portfolio relevance**: TSLA 0.7%, no F/GM/RIVN/LCID at all. Keep it
  for the tech-vs-auto yield comparison, which is still the cheapest open question, but do
  not expand it.
- **Agriculture / trucking** — 5.6% combined (DE, CMI, TRMB, RAIL, CNR.TO, SNA, FAST). Still
  valid, below the three above.
- **Solar** — dropped, zero exposure.

---

## §9 Keyword search as a discovery path (avoiding the spam problem)

`youtube_sources.kind = 'search'` with `query_text` exists in the schema, and source list §9
already concluded search should feed **candidate discovery for human review**, never direct
ingestion. Two measured facts make a cheap discovery pipeline possible:

- **Listing is not rate-limited; only caption fetch is** (source list §13). Enumerating
  search results, channel metadata and video titles stayed available throughout the block
  that stopped 137 of 150 caption fetches.
- **Caption fetch is capped at ~90/IP/day** (§14), which is the entire budget for one
  sector's Stage 0.

So discovery should spend **zero caption fetches** and run entirely on listing metadata.
Proposed ranking, cheapest signal first, applied to search results for a set of queries:

1. **Aggregate to channels, not videos.** Run 10-20 queries per sector, collect every
   channel appearing in the results, and rank by how many *distinct* queries surfaced it.
   Multi-query recurrence is the same double-nomination signal that outperformed model
   rankings in every research round.
2. **Cheap structural rejects**, all from listing metadata: subscriber count under ~5k
   (impostor/dead), upload cadence over ~2/day (content mill), median duration under 120s
   (Shorts farm), channel younger than ~1 year with high volume, no English captions at all.
3. **Title-scan for tradeable share** — the step that rejected space (0-3%) and displays
   (26%). Free, and it is the single highest-value filter we have.
4. **Promotion tells from titles alone**, before touching captions: ticker-in-title with
   superlatives, price targets in titles, `$XYZ` cashtag density, "must own", "before it's
   too late", repeated single-junior focus. For mining/uranium (§8.2/8.3) this filter is the
   whole game.
5. **Only then** spend caption fetches, on the top handful, via the existing Stage 0 harness.

Queries should target the *observation*, not the ticker — ticker-targeted queries select for
promotional content by construction. For §8.1, prefer `transformer lead times 2026`,
`switchgear shortage datacenter`, `liquid cooling retrofit colocation`,
`interconnection queue delay` over `VRT stock`.

This is specced, not built. It is a small amount of code against the existing listing client
and would pay for itself the first time it saves a manual round of handle verification.
