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
