# Wrestling Dashboard, handoff

Written 2026-07-13. Everything below is on `main` and pushed. Working tree clean
(your `.gitignore` edit and the untracked `sprite-tools/` + `DESIGN-REVIEW.md`
files are untouched, same as before).

```
b2d19c3  feat: breadcrumbs on every page; promos lead with who, not what
06a541c  feat: title reign history is its own timeline page, watch-position aware
aafc0a6  feat: browse every title's reign history in the Titles view
8f3099c  feat: championship belts on champions, and one clean layout for every team
42e7a62  feat: show the main event with headshots in the Continue Watching billboard
314b66f  fix: dedupe redundant match tags and center the Details toggle
6c2e7a0  fix: translate the last German strings in show headers
6550566  feat: Titles view, a champions board sorted by prestige
b590cda  feat: drop the repeated show logo from every match row
eba8997  feat: backfill match type, stipulation and title from event pages
5e8b975  feat: tournaments-decided-here shelf, winner behind the spoiler toggle
45aee93  feat: storylines-around-this-show shelf from cagematch feuds
0da1d1b  feat: promos-from-this-show shelf on the event page
ec2136a  feat: backfill attendance, TV data and durations from cagematch event pages
```

---

## Pick up here: the title reign data is mis-derived, not missing

You asked whether the bad reigns on the timeline pages ("Triple H, Intercontinental,
Oct 2002 – May 2009") are an accuracy problem you need to re-scrape, or a cleansing
problem. **It is a cleansing problem. Every title change is already in the corpus.
Nothing to grab.**

### Why it happens

`src/export_to_html.build_title_reigns()` (line 408) groups title matches by the
**exact** `title_at_stake` string and ends each reign at the next match carrying
that exact string. The Intercontinental belt is tagged three ways across the
corpus:

| tag as stored | reigns | span |
|---|---|---|
| `WWF Intercontinental Title` | 19 | 2001–2007 |
| `WWE Intercontinental Title` | 78 | 2002–2026 |
| `Intercontinental Title` | 31 | 2003–2009 |

Each spelling becomes its own reign chain. When the belt was tagged the short way
through 2003–2009, the `WWE` chain saw no matches in that window, so Triple H's
Oct 2002 win runs unbroken to the next `WWE`-tagged match in **2009**. Eddie
Guerrero's 2002 win under the `WWF` spelling runs to **2007** the same way. The
three chains overlap each other in time. The same fragmentation splits the
wrestler index: Chris Jericho reads "WWF Intercontinental 3" and "WWE
Intercontinental 2" instead of "Intercontinental 5".

### It works. I re-derived one belt to prove it.

Pulled every IC-tagged match (all three spellings) out of the shards, sorted it
chronologically, and walked the same reign logic as one merged chain:

```
IC matches (all spellings):   545
re-derived reigns (merged):   126     (vs 128 fragmented across 3 keys)
Triple H IC reign:            2002-10-20 -> 2003-07-07     (was -> 2009-05-17)
Eddie Guerrero phantom span:  gone
```

The phantom cross-spelling spans collapse. (One residual, in Footguns, is a
different and smaller thing.)

### The plan

1. **Give `build_title_reigns` a lineage normalizer.** Group the timeline by a
   normalized title instead of the raw `title_at_stake` string, and keep a
   canonical display name. It is the same idea as `lineage_key` in
   `cagematch-pipeline/fill_titles.py` (lowercase, drop `championship`/`title`,
   strip `wwf`/`wwe`/`undisputed`). ONE nuance: do **not** merge the big-gold
   World Heavyweight (2002–2013) with the white 2023 strap, or you recreate exactly
   this phantom-gap problem across the 2013–2023 hole. Split them the way
   `fill_belts.belt_for` already does (`world-heavyweight-classic` vs `-modern`,
   keyed on the presence of `wwe`/`undisputed`).

2. **Patch the bundle in place; you cannot regenerate it.** There is no local
   `wrestling.db`. `cagematch-pipeline/apply_merge.load_events(bundle)` (line 44)
   already rebuilds the events dict with matches read back from the shards — reuse
   that exact pattern. Then write `cagematch-pipeline/fill_title_reigns.py` that:
   - `new = build_title_reigns(events)`   (now lineage-grouped)
   - `bundle["title_reigns"] = new`
   - `bundle["wrestler_reigns_by_date"] = build_wrestler_reigns_by_date(new)`
   - rebuild each wrestler's `title_wins` and `signature_title` from `new` — the
     `build_wrestlers_index` block at line 232 is the source of truth; run
     `build_wrestlers_index(events, canon=<shipped canon>, title_reigns=new)` and
     patch just those two fields into `bundle["wrestlers"]` (the rest of the index
     does not depend on `title_reigns`, so it is identical).
   - `inject(bundle, read(frontend/index.html))` and `atomic_write_text` to
     `index.html`, exactly like the other fill scripts.
   `--dry-run` first, eyeball IC / the WWE title / a tag title, make it idempotent.

### Footguns

**`title_reigns` feeds three things; move them together.** (a) the Titles timeline
pages (`fill_titles.py` reads it), (b) `wrestler_reigns_by_date` -> the frontend's
`titlesHeldOn` -> roster belts, the "Champ" badge on every match card, and the
title page's "As of your date" holder, (c) the wrestler index `title_wins` /
`signature_title`. Patch a subset and the roster and profiles disagree with the
timeline.

**The overlap assertion is your tripwire, not your enemy.**
`build_wrestler_reigns_by_date` (line 523) asserts no wrestler holds the SAME title
twice at once. It passes today only because the three spellings are three separate
title keys. Merge them and a sloppy re-derivation fires it. A correct re-derivation
is one continuous non-overlapping chain and passes — let the assertion catch a bad
merge.

**The fidelity gate stays green iff title_reigns and title_wins stay consistent.**
`apply_merge` rebuilds the wrestler index from `bundle["title_reigns"]` (line 104)
and asserts it reproduces the shipped index. Regenerate the shipped index's
`title_wins` from the same corrected reigns and the reconstruction still matches.
Patch `title_reigns` but leave `title_wins` stale and the next `apply_merge` run
trips the gate. So do step 2's third bullet, do not skip it.

**Not every long reign is wrong.** Gunther held the IC belt Oct 2022 -> Apr 2024
(~666 days) for real, and it survives the re-derivation as one reign. Do not filter
by length. Re-derive.

**One residual this does NOT fix.** `build_title_reigns` has no vacancy detection
(its own docstring, line 421). A belt deactivated then revived — the IC was unified
away in Oct 2002 and came back in 2003 — still shows one reign spanning the gap.
After the fix Triple H reads 2002 -> 2003 instead of the phantom 2002 -> 2009,
which is right about the *belt* but does not model the ~9-month vacancy. Separate,
smaller problem; leave it unless you want to source vacancy dates.

**`fill_titles.py` needs a re-run and a glance after.** Its own `lineage_key` merge
becomes a near no-op once `title_reigns` is already one-key-per-lineage, and the
board/timeline display names will change to whatever canonical name
`build_title_reigns` emits. Re-run `fill_titles.py`, open a title page, confirm the
timeline reads clean and the current champion still resolves.

---

## What shipped this run, one line each

All cagematch-derived content, all on `main`, all lazy sidecars under `shards/`
loaded on the same graceful seam as `media.json` (absent -> feature just does not
render).

- **Event-page backfill** (`backfill_event_pages.py`): fetched all 858 non-cagematch
  event pages via Firecrawl into `.firecrawl/cm-events/`, filled 3195 durations,
  664 attendances, 857 tv_networks, 858 commentary, plus match_type / stipulation /
  title_at_stake (SDH match types went 19% -> 98%). Gate: 2561 cross-checked
  ratings, zero disagreements.
- **Promos / Feuds / Tournaments shelves** on the event page (`parse_*` + `fill_*`
  in `cagematch-pipeline/`). Feud titles are German, so the matchup is extracted and
  roster-validated. Tournament winners and, now, promo lines are spoiler-gated.
- **Belts**: `belts/_pipeline/extract_belts.py` pulls 30 belt cutouts from
  `~/Downloads/www.wwe.com.har` into `belts/*.webp`; `fill_belts.py` maps every
  title to a belt (era-aware). A defending champion wears the belt on their headshot
  corner in title matches.
- **Titles view + timeline pages**: `#titles` board of active belts;
  clicking one opens `#title/<slug>`, its own reign-timeline page with the roster's
  "As of your date" vs "All-time" toggle. THIS is the page whose reign data the fix
  above cleans up.
- **Card format**: 2+ person teams stack one headshot per row (singles keep the
  faceoff); redundant title/stip tags deduped against match_type; Details toggle
  centered. Continue Watching billboard shows the main event with headshots.
- **Breadcrumbs** under the header on every page; **German tv_network/city
  leftovers** translated (`fix_german_leftovers.py`).

---

## Commands

```bash
# tests (system python is broken, use uv)
uv run --with pytest --with beautifulsoup4 --with requests python -m pytest -q

# the cagematch-content pipeline, in order. all idempotent, all take --dry-run
# except parse_*. run parse before its fill.
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_promos.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_promos.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_feuds.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_feuds.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_tournaments.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_tournaments.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_titles.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_belts.py     # after belts/ exists
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_titles.py    # needs cm_titles + belts

# belt images (one-time; needs the HAR at ~/Downloads/www.wwe.com.har)
uv run --with pillow python belts/_pipeline/extract_belts.py

# serve
python3 -m http.server 8777 --directory ~/wrestling-dashboard
```

The frontend is `frontend/index.html` (the template); `index.html` is that template
with the data `<script>` tag injected. Every fill script that touches the bundle
edits `index.html` via `src.export_to_html.inject`; the round-trip is byte-identical
outside the data tag, so a template-only change means re-injecting the current
bundle. `index.html` is 5.7MB, which times out chrome-devtools MCP on load — use
headless Chrome `--screenshot` with `--virtual-time-budget` to eyeball. If
chrome-devtools says "browser already running", another Claude session is holding
it; do NOT kill its Chrome.

`cagematch-pipeline/README.md` documents every parse/fill script and its join keys.

---

## After the title reigns

Still unused or half-there, in rough order of value:

- **Vacancy dates** for titles (the residual above) if you ever want reign spans to
  break on deactivations, not just title changes.
- The main-WWE-title and World-Heavyweight lineages will still carry some era-merge
  judgement calls even after the fix (WWE's own renames are a mess); eyeball those
  two on the timeline once the fix lands.
