# Wrestling Dashboard

Spoiler-safe chronological watch companion for WWE 2001-2019. Single-file HTML bundle, no backend, no account, no streaming. Built for new wrestling fans who want to watch the Attitude Era and Ruthless Aggression Era in order without spoilers.

[![Open the live demo](https://img.shields.io/badge/Live_Demo-Open-C8102E?style=for-the-badge&labelColor=0A0A0A)](https://warner-wvez.github.io/wrestling-dashboard/)

## What it does

- Full WWE calendar of every Raw, SmackDown, and PPV
- Each event shows its match card with participants, stipulations, duration, and results
- Spoilers hidden by default, per-match reveal toggle
- Runs entirely in the browser from a single HTML file
- No account, no streaming, no backend

## Why it exists

I became a wrestling fan this past year by watching full shows chronologically starting with Backlash 2002. The onboarding problem for new fans is brutal: clips strip out promos, energy, and transitions, and official platforms are hostile to new viewers. Built this to help other new fans start from the beginning the way I did.

## Current coverage

- 2001-2019 complete (2,266 events, 15,144 matches, 296 PPVs)
- Includes every Raw and SmackDown episode, 30 NXT TakeOvers (2014-2019), 3 Starrcade revivals (2017-2019), 5 Saudi Arabia specials (Greatest Royal Rumble, Crown Jewel, Super ShowDown), WWE Evolution 2018, and 8 Tribute to the Troops specials

## What's in the corpus

- **Raw**: 983 episodes
- **SmackDown**: 987 episodes
- **PPV**: 296 events (includes all NXT TakeOvers, Starrcade 2017-2019, Saudi events, Evolution, Tribute specials)
- **Years**: 2001 through 2019 (19 full years)
- Every match has full raw descriptive text from Cagematch. About 21% carry community Match Guide ratings.

## Run it yourself

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Open `dist/wrestling-dashboard.html` directly in a browser. Works offline.

To regenerate the bundle from your own scraped database at `data/wrestling.db`:

```bash
.venv/bin/python src/export_to_html.py
```

To run the development backend:

```bash
.venv/bin/python -m uvicorn src.api:app --reload
```

## Project structure

```
wrestling-dashboard/
├── README.md
├── LICENSE
├── .gitignore
├── requirements.txt
├── index.html              Hosted landing page (copy of dist bundle)
├── frontend/
│   └── index.html          Development template
├── src/                    Python pipeline
└── dist/
    └── wrestling-dashboard.html  Built artifact (the product)
```

## Data sources

- Primary: [Cagematch.net](https://www.cagematch.net/) (scraped)
- Verification: Wikipedia, [prowrestling.fandom.com](https://prowrestling.fandom.com/)

Not affiliated with WWE. This is a fan-made companion tool.

## Known issues

- Multi-episode-per-date tournaments are NOT included in the current corpus. Affected shows: Cruiserweight Classic 2016 (10 episodes), Mae Young Classic 2017 (10 episodes), Mae Young Classic 2018 (8 episodes), UK Championship Tournament 2018 (2 episodes), and Worlds Collide 2019 (4 episodes on 2 dates). The SQLite schema enforces UNIQUE (air_date, show_type) which drops subsequent events sharing a date, so bringing these in requires a scraper-side consolidation pass. Queued as a backlog item.
- NXT weeklies, WWE 205 Live, WWE Main Event, WWE Superstars, and WWE Mixed Match Challenge are intentionally out of corpus. The watch-companion thesis prioritizes canonical narrative broadcasts (Raw, SmackDown, PPV, NXT TakeOver specials), not the full weekly taping slate.
- Tribute to the Troops specials are covered for 2015-2019 as standalone PPV-style events. Earlier instances (2003-2014) often aired as Raw or SmackDown episodes and may be embedded in those rows rather than standalone entries. A few 2004, 2006, and 2007 Tributes are already in corpus via their Raw/SmackDown episode. Complete historical backfill is queued.
- Beast in the East 2015 (a one-off Network special from Tokyo) is not in corpus. Queued for a dedicated backfill task.
- Pre-2016 SmackDown air dates use a tape-plus-2-estimate derivation. The show taped Tuesday night and aired the following Friday, so the estimated air_date is always in the right calendar week but not always the exact air-night. Fandom verification pass for accurate day-level air dates is queued.
- Some tag team participant strings from older scrapes have parsing edge cases (stray parentheses, match-result text bleeding into names). Low urgency, cleanup queued.
- Timestamp display uses browser local timezone.

## Roadmap

- Multi-episode-per-date tournament consolidation (unlocks ~34 events across CWC 2016, MYC 2017/2018, UK Championship Tournament 2018, Worlds Collide 2019)
- Historical Tribute to the Troops backfill (2008-2014)
- NXT UK TakeOver 2018 backfill
- Beast in the East 2015 one-off
- Fandom enrichment pass for SmackDown air date accuracy (2004-2015)
- Parser cleanup for edge cases in team name fields
- Optional filters (by brand, superstar, title, year)
- Watch-tracking feature (local storage, no account)

---

## Technical deep-dive

This section is for developers looking at the repo. It explains the pipeline, the architectural bets, and the interesting implementation choices.

### Pipeline overview

```
Cagematch HTML  →  discover.py  →  events_to_scrape.json
                                          ↓
                                  cagematch_scraper.py
                                          ↓
                                   SQLite (wrestling.db)
                                          ↓
                                  export_to_html.py
                                          ↓
                          dist/wrestling-dashboard.html
                        (JSON dataset inlined into HTML)
                                          ↓
                                 Browser (offline)
```

Five stages, each idempotent: discover, scrape, store, bundle, render.

### Why single-file HTML with inlined JSON

The core architectural bet is that the product is a static artifact, not a service. Everything the user needs is inlined into one HTML file via a `<script id="wrestling-data" type="application/json">` tag. At page load, JavaScript parses the JSON blob once into memory and renders from there. No fetch calls, no backend, no CDN, no API keys, no auth.

Trade-offs of this choice:

- **Pro:** Works offline. Hosts anywhere static (GitHub Pages, S3, Vercel, a USB drive). Zero cost at any scale. No rate limits, no downtime, no backend maintenance.
- **Pro:** The file IS the product. Users can download it, email it, archive it. It will work in 2035 the same way it works today.
- **Con:** Bundle size grows linearly with dataset. Currently 10.98 MB for 19 years (2001-2019). Projected 12-13 MB if extended to present day. Still well within single-file delivery comfort zone.
- **Con:** Can't push updates without re-bundling and redeploying.

For a corpus that's historical (2001-2019 won't change), the upsides dominate.

### SQLite with raw `sqlite3` module, no ORM

`src/db.py` uses Python's stdlib `sqlite3` directly. No SQLAlchemy, no Peewee, no Django ORM. Reasons:

- Schema is ~5 tables, stable, and authored once. ORM overhead isn't worth it.
- Raw SQL is easier to debug when scrape data is messy (and wrestling data is very messy).
- Zero dependencies beyond Python stdlib for the DB layer.
- SQLite files are portable, inspectable with any `sqlite3` CLI, and backup/restore is a file copy.

The trade-off is manual parameterization everywhere, but with a fixed schema that's fine.

### Schema shape

```
events
  id, air_date, tape_date, show_type, ppv_name, title,
  episode_number, venue, city, attendance, tv_network,
  tv_rating, commentary, match_count, verification_status,
  source_url, created_at

matches
  id, event_id, match_order, match_type, title_at_stake,
  stipulation, duration_seconds, raw_description,
  match_guide_rating, created_at

match_teams
  id, match_id, team_order, team_name, participants,
  was_winner, was_champion_entering, match_outcome,
  accompaniment
```

Normalized enough to query meaningfully, denormalized enough that a single event detail fetch hits 3 tables tops.

### The classifier

`src/cagematch_scraper.py` contains `classify_show_type`, which maps Cagematch's `(title, cm_type)` tuple into one of the project's three internal show_type values (Raw, SmackDown, PPV), or to a SKIP sentinel that excludes the event from corpus. The final classifier after a full pass on 2001-2019 has 7 PPV-promoting branches (covering Pay Per View, Premium Live Event, TV-Show+Tribute, Event+Tribute, Event+Starrcade, Online Stream+Starrcade, Online Stream+Smackville) and 7 SKIP branches (House Show, Online Stream+Pre-Show, Online Stream+Kickoff, Online Stream+Axxess, Event+Axxess, Event+Fan Fest, Event+On-Sale Party), plus the standard weekly pattern matchers for Raw and SmackDown.

The interesting design choice is the **error-as-canary pattern**. When the classifier encounters an unknown combination, it raises `ValueError` rather than defaulting to a fallback category. This causes the scrape to halt on that event, surfacing it to the operator.

Why this matters: the scraper is pulling from a community-maintained database spanning decades. Edge cases exist (Axxess conventions, Revenge Tour house shows, Online Stream pre-shows) and silently categorizing them wrong would pollute the corpus invisibly. Instead, every unknown pattern is a hand-reviewed decision: add a rule, skip the category, or drop the data.

The classifier has three branches:

1. **Promote:** patterns that map cleanly to core types (e.g., "WWE RAW #N" → Raw).
2. **SKIP:** patterns that don't fit the watch-companion thesis (tour house shows, conventions). These inserts are tracked in `data/cagematch_skipped.json` so they don't get re-processed.
3. **Raise:** anything unrecognized. Forces a decision.

### The stop-gate protocol

When a scrape run errors, the operator has a choice: patch the classifier and re-scrape, or accept the drop. To support both:

- `cagematch_errors.json` records everything that failed to classify, with event ID, title, and cm_type.
- Re-scraping the same year is idempotent (UPSERT on `cagematch_nr`).
- Already-successfully-scraped events within a run stay put. Only the errored events get re-attempted on the next pass.

This means adding a classifier branch and re-running is cheap. The 2001-2019 corpus was built through roughly 14 halt-propose-approve cycles across 19 years of content. Each one caught a real Cagematch taxonomy shift: Pre-Show getting rebranded to Kickoff in 2013, the Pay Per View cm_type gaining a Premium Live Event alias in 2014, Axxess conventions splitting across Event and Online Stream types between years, Starrcade's cm_type flipping from Event in 2017 to Online Stream in 2018, Tribute to the Troops drifting from TV-Show to Event in 2019, and so on. Zero silent corpus pollution across the full run.

### The bundler

`src/export_to_html.py` is ~100 lines. It:

1. Opens `frontend/index.html` as a template.
2. Queries the SQLite database for all events and matches.
3. Shapes the result into a `{events: {...}, events_by_date: {...}, meta: {...}}` JSON structure.
4. Injects that JSON via string replacement into a `<script id="wrestling-data">` tag in the template.
5. Writes the result to `dist/wrestling-dashboard.html`.

The `meta` block includes `year_range: [min_year, max_year]` computed from the dataset. The frontend reads this at load time to build the year selector dynamically. This means adding more years never requires a frontend code change, just a re-scrape and re-bundle.

### Spoiler UI (CSS-only, no per-element state)

Default behavior hides match winners, durations, and outcomes. A toggle reveals them.

Implementation is a single CSS class toggle on `<body>`. Every match card renders with full data in the DOM at page load. Spoiler-sensitive elements (winner highlight, duration display, "DEF." text instead of "VS") have their visibility controlled by CSS selectors gated on `body.spoilers-on`.

```css
.match-extras { opacity: 0; pointer-events: none; }
body.spoilers-on .match-extras { opacity: 1; pointer-events: auto; }
```

Pros of this approach: no JS re-renders on toggle, no per-card state to track, stagger animations come for free via CSS transition delays, and the HTML is cacheable as a single rendered pass. The data is always there in the DOM, just not always visible.

Cons: technically, a user could `View Source` and read spoilers. For a spoiler-safe watch companion, the user isn't an adversary. Threat model is "don't accidentally see the winner while scrolling," not "prevent any possible leak."

### Scrape ethics

The scraper respects a 2.5-second inter-request delay, sends a descriptive User-Agent, and caches every fetched page in `data/cagematch/` and `data/fandom/` so re-runs don't hit upstream again. The SQLite database and HTML caches are gitignored to avoid republishing scraped content in the public repo. This is a companion tool that points people at existing sources, not a replacement for them.

### Frontend stack

Vanilla JS, no framework, no build step for the frontend itself. The frontend is one HTML file with inline `<style>` and inline `<script>`. At ~54 KB uncompressed before the data blob is injected. Fewer moving parts = longer project lifetime.

### Testing philosophy

Currently manual: each scrape run has a post-scrape verification block (`SELECT COUNT(*) FROM events WHERE strftime('%Y', air_date)=?`) that asserts the year bucket grew by the expected amount. Bundle verification greps the output for expected year string occurrences. A proper test suite would live in `tests/` with fixtures pulled from a small representative subset of Cagematch events, but at the current scale the manual checks catch regressions fast enough.

## License

MIT

## Built by

Warner Varnado. WVEZ Solutions LLC.
