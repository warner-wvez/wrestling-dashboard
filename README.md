# Wrestling Dashboard

Spoiler-safe chronological watch companion for WWE, 2001 to present (2001-2026). No backend, no account, no streaming. Built for new wrestling fans who want to watch the Attitude Era through the modern era in order, without spoilers.

[![Open the live demo](https://img.shields.io/badge/Live_Demo-Open-C8102E?style=for-the-badge&labelColor=0A0A0A)](https://warner-wvez.github.io/wrestling-dashboard/)

## What it does

- Continue Watching: open the app and pick up at the exact next show, in chronological order, like a TV series
- Browse every Raw, SmackDown, and PPV by week (the default) or by full month, from 2001 to the present
- Each event shows its match card with participants, stipulations, results, and (where the source carries them) durations
- Spoilers hidden by default, with a per-match reveal toggle
- Track your journey: mark shows watched, see how far through the timeline you are, and save individual matches
- A clean roster: one accurate profile per wrestler, with ring-name changes merged (WALTER and Gunther are one person, and the old name still links to the current profile)
- Search every event, wrestler, and stipulation
- Runs entirely in the browser, served as static files. No account, no streaming, no backend

## Why it exists

I became a wrestling fan this past year by watching full shows chronologically starting with Backlash 2002. The onboarding problem for new fans is brutal: clips strip out promos, energy, and transitions, and official platforms are hostile to new viewers. Built this to help other new fans start from the beginning the way I did.

## Current coverage

- 2001 to 2026 (3,053 events, 19,610 matches, 410 PPV/PLE events, 1,729 wrestlers)
- Every Raw and SmackDown episode across the full range, plus NXT TakeOver and NXT premium events, the Saudi Arabia specials, WWE Evolution, Tribute to the Troops, and the modern Premium Live Event slate
- 2026 is the current year and is therefore partial (covered through the most recent shows at build time)

## What's in the corpus

- **Raw**: 1,319 episodes
- **SmackDown**: 1,324 episodes
- **PPV / PLE**: 410 events (includes NXT premium events, Saudi shows, Evolution, Tribute specials, and the present-day PLE calendar)
- **Years**: 2001 through 2026
- Match detail richness varies by source era: the 2001-2019 base carries full descriptive text (about 21% with community Match Guide ratings), Wikipedia PPVs carry exact durations, and the present-day weekly shows are results-focused (no durations or ratings by design)

## Run it yourself

Requires Python 3.11+ (the build scripts run cleanly under `uv` as well).

Open `dist/wrestling-dashboard.html` directly in a browser. It inlines the entire dataset and works fully offline, no server needed.

The live site (`index.html` plus the `shards/` directory) is served statically, e.g. `python3 -m http.server` from the repo root, then open `http://localhost:8000/`.

To extend the corpus toward the present day and rebuild every artifact (lean core, era shards, and the single-file build):

```bash
uv run --with requests --with beautifulsoup4 src/build_update.py
```

To regenerate the single-file build from the historical SQLite database at `data/wrestling.db`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/export_to_html.py
```

## Project structure

```
wrestling-dashboard/
├── README.md
├── LICENSE
├── requirements.txt
├── index.html                   Live Pages build: lean inline core
├── sw.js                        Service worker (caches core + shards offline)
├── shards/
│   └── matches-<era>.json       Per-era match detail, lazy-loaded on demand
├── frontend/
│   └── index.html               Development template (one source of truth)
├── src/                         Python pipeline
│   ├── build_update.py          Present-day lanes + merge + bundle/shard
│   ├── smackdownhotel.py        Weekly Raw/SmackDown parser (2020-present)
│   ├── wikipedia_ppv.py         PPV/PLE parser via the MediaWiki API
│   ├── roster_aliases.py        Canonical-name / ring-name merge map
│   ├── export_to_html.py        Bundle + shard writer, index builders
│   └── ... (cagematch_scraper, db, discover, fandom_scraper, api)
└── dist/
    └── wrestling-dashboard.html  Single-file build (offline, archival)
```

## Data sources

The corpus is assembled from three lanes, each chosen because it serves to a normal request without circumventing any bot wall:

- **Historical base, 2001-2019**: [Cagematch.net](https://www.cagematch.net/) (scraped to the local SQLite database). Carries durations and community ratings.
- **Weekly TV, 2020 to present**: [The SmackDown Hotel](https://www.thesmackdownhotel.com/) editor-curated results (one page per show-year). Clean dates and accurate, era-consistent cards.
- **PPV / PLE, 2020 to present**: Wikipedia via the sanctioned MediaWiki API (`{{Pro wrestling results table}}`), which carries exact match durations.
- **Roster names**: The SmackDown Hotel WWE roster page is used to canonicalize wrestler names and merge ring-name changes (its profile slugs preserve a wrestler's earlier name, so renames are auto-detected).

Not affiliated with WWE. This is a fan-made companion tool that points people at existing sources, not a replacement for them.

## Known issues

- The present-day weekly shows carry no match durations or community ratings (the curated source is results-only). This is intentional; durations for those shows are an optional later enrichment.
- Masked rotating gimmicks (the "Americano" luchador characters) are kept as their own roster entries rather than merged into the wrestler under the mask, since the character is played by different people. This is deliberate.
- Title reigns are not yet name-canonicalized: a 2019 reign under an old ring name is still filed under that name rather than the merged current one.
- A small number of complex multi-way / battle-royal cards from the weekly source have best-effort team grouping (flagged low-confidence internally).
- Pre-2016 SmackDown air dates in the historical base use a tape-plus-2 estimate (right calendar week, not always the exact air night).
- Multi-episode-per-date tournaments in the historical base (Cruiserweight Classic, Mae Young Classic, UK Championship Tournament, Worlds Collide 2019) are not yet consolidated, because the historical SQLite schema enforces UNIQUE (air_date, show_type).
- Timestamp display uses the browser local timezone.

## Roadmap

- Weekly NXT show ingestion (the curated source covers it for recent years)
- Historical backfill toward the 1990s (a durations-and-dates source has been identified)
- Current-roster brand tags (Raw / SmackDown / NXT) on wrestler profiles, from the roster page already in use
- Title-reign name canonicalization (apply the roster alias map to reigns)
- Multi-episode-per-date tournament consolidation in the historical base
- Calendar-level filters (show only unwatched, filter by brand or title)

---

## Technical deep-dive

This section is for developers looking at the repo. It explains the pipeline, the architectural bets, and the interesting implementation choices.

### Pipeline overview

Two lanes feed one bundle. The historical base is scraped once into SQLite; the present-day lanes are fetched live and merged on top.

```
Historical (2001-2019)            Present day (2020 to now)
  Cagematch HTML                    SmackDown Hotel (weekly)   Wikipedia API (PPV)
       ↓                                    ↓                         ↓
  discover + scrape                  smackdownhotel.py          wikipedia_ppv.py
       ↓                                    └──────────┬──────────────┘
  SQLite (wrestling.db)                                ↓
       ↓                                        build_update.py
  export_to_html.py  ───────────────────────►  (drop+rebuild 2020+, merge,
                                                 canonicalize roster, recompute
                                                 indexes, shard the bundle)
                                                         ↓
                                 index.html (lean core)  +  shards/matches-<era>.json
                                 dist/wrestling-dashboard.html (single-file)
                                                         ↓
                                                 Browser (static, offline-capable)
```

`build_update.py` is idempotent: each run drops everything from 2020 on, keeps the clean pre-2020 base (with its event IDs), and re-ingests the present-day range with the current parsers, so an improved parse fully replaces the prior one instead of de-duping against it.

### Why a lean core plus lazy era shards

The original bet was a single static HTML file with the entire dataset inlined, which is unbeatable for offline and longevity. It held until the corpus reached the present day: the full bundle hit ~16.5 MB, and instantiating all ~19,600 nested match objects at once crowds the iOS Safari heap ceiling and blocked adding more data (NXT weekly, a deep backfill).

The fix keeps the static ethos. The 87% of the bundle that is heavy (per-match teams and participants) is split out of the inline core into `shards/matches-<era>.json`, grouped by 3-year era. The Pages build (`index.html`) now inlines only a ~5.8 MB core (event metadata, the wrestler and title indexes, and a compact match search index) and fetches an era shard (~1.3 MB) the first time a show in that era is opened. A service worker caches the core and visited shards for offline-after-first-visit.

The single-file build (`dist/wrestling-dashboard.html`) still inlines everything and works offline standalone. One frontend serves both modes: it detects at runtime whether match detail is inline or must be fetched, through the existing async event-detail seam.

Trade-offs:

- **Pro:** Page-load payload drops from ~16.5 MB to ~5.8 MB, and the heap-heavy match objects never all load at once. Each new era added is just another ~1.3 MB file fetched on demand, so the corpus can grow a lot without the phone choking.
- **Pro:** Still static. Hosts anywhere (GitHub Pages, S3, a USB drive for the single-file build). Zero backend, no rate limits, no downtime.
- **Con:** The Pages build is now a small site (a shell plus data files) rather than one emailable file; the single-file build is preserved for that use.
- **Con:** Offline on the Pages build is "works after the first visit" (via the service worker) rather than "works as a standalone file from scratch."

### Roster aliasing

The roster (`build_wrestlers_index`) is derived from match participants, so it is only as clean as the parsed names. Two problems were solved.

Junk: the present-day weekly parser had been leaking match prose into names ("X ends in a No Contest" as a fake wrestler, unsplit nested stables, scraped page comments). `smackdownhotel.py` now strips result tails and battle-royal elimination narrative per side, recursively flattens nested stables into individual members, and rejects comment list-items. The mis-recorded no-contest matches re-attribute to the real wrestlers.

Identity: the same person was split across ring-name and spelling variants. `roster_aliases.py` builds a canonical-name map. The key trick is that the SmackDown Hotel roster page encodes renames in its profile slugs (`/wrestlers/walter` titled "Gunther"), so current-roster name changes are detected automatically. A small curated map covers off-roster renames, a PROTECTED set stops the page mis-relabeling well-known wrestlers to a real name or masked gimmick, and pure spelling variants merge by a normalized key. The index aggregates under the canonical name, but match cards keep era-accurate names, and every alias maps to the canonical slug so an old name in a card still links to the merged profile.

### SQLite with raw `sqlite3`, no ORM

The historical base uses Python's stdlib `sqlite3` directly. No ORM. The schema is ~5 tables, stable, and authored once; raw SQL is easier to debug when scrape data is messy (and wrestling data is very messy); and SQLite files are portable and inspectable with any CLI. The present-day lanes skip the database entirely: they parse straight into the project's event/match shape and merge in `build_update.py`.

### The classifier (historical lane)

`src/cagematch_scraper.py` contains `classify_show_type`, which maps Cagematch's `(title, cm_type)` tuple into one of the project's three internal show_type values (Raw, SmackDown, PPV) or to a SKIP sentinel.

The interesting design choice is the **error-as-canary pattern**. When the classifier hits an unknown combination it raises `ValueError` rather than defaulting, halting the scrape and surfacing the event to the operator. Why this matters: Cagematch is community-maintained across decades, and silently miscategorizing an edge case (Axxess conventions, Online Stream pre-shows, a cm_type alias added in some year) would pollute the corpus invisibly. The 2001-2019 base was built through roughly 14 halt-propose-approve cycles, each catching a real taxonomy shift, with zero silent pollution.

### Spoiler UI (gated at render time, not just hidden with CSS)

Default behavior hides match winners, finishes, and outcomes; a toggle reveals them. The result is only ever placed in the DOM when spoilers are on. With spoilers off, cards render with no winner/loser markup and a "Result hidden" placeholder, the wrestler profile omits win/loss and title history, and battle royals show a nameless "Winner hidden" slot. Toggling re-renders so the outcome is added to (or removed from) the DOM rather than shown or hidden in place.

This is deliberate: an earlier version hid outcomes with `filter: blur()` while leaving the text in the DOM, which leaked the finish to the accessibility tree, text selection, reader mode, and disabled CSS. Rendering the outcome only on reveal closes all four. Residual: the inline data still contains plaintext results, so devtools can surface them. The threat model is "don't accidentally see the winner," not "prevent any possible leak."

### Scrape ethics

Every lane serves to a normal browser-style request without defeating a bot wall: Cagematch with a 2.5-second delay and a descriptive User-Agent (cached locally so re-runs don't re-hit it), the SmackDown Hotel at low volume, and Wikipedia through its sanctioned API. The SQLite database and HTML caches are gitignored so scraped content is not republished. Sources that gate bots behind a captcha are intentionally not bypassed.

### Frontend stack

Vanilla JS, no framework, no build step for the frontend. One HTML template with inline `<style>` and `<script>`. Watch state (Continue Watching position, watched shows, saved matches) lives in `localStorage`, so there is no account and no backend. The year selector, calendar, and search are all data-driven from the bundle's `meta.year_range` and indexes, so extending coverage never requires a frontend code change. Fewer moving parts means a longer project lifetime.

### Testing philosophy

Currently manual: each build run prints a before/after validation block (event and match deltas, year range, per-year/per-show counts, and a skipped-event list), and the bundle is spot-checked for structure, junk participant names, and shard round-trip integrity. A proper suite would live in `tests/` with fixtures from a representative subset, but at the current scale the manual checks catch regressions fast.

## License

MIT

## Built by

Warner Varnado. WVEZ Solutions LLC.
