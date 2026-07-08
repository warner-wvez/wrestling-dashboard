# Wrestler profiles pipeline (SmackDown Hotel)

Scrapes structured wrestler bio data from The SmackDown Hotel profile pages
(`thesmackdownhotel.com/wrestlers/<slug>`) into a single sidecar shard,
`shards/profiles.json`, keyed by roster slug. The site is a Joomla install whose
custom-field markup is stable and mostly dated per era, so the parse is clean and
the data is time-aware (roles, promotions/brands, finishers, themes, face/heel
turns, card positions, tag teams all carry from/to dates).

This mirrors the two existing pipelines: `media-pipeline/` (watch links) and
`roster-img/_pipeline/` (headshots, also from SDH). The tool is committed; the
`cache/`, `node_modules/`, and logs are gitignored. The `shards/profiles.json`
output is committed, same as `shards/media.json`.

## What gets extracted per wrestler

Flat bio: `real_name`, `gender`, `born`, `nationality`, `birth_place`,
`billed_from`, `height`, `weight`, `nicknames[]`.
Career (each dated where SDH dates it): `ring_names[]`, `roles[]`,
`promotions[]` (promotion + brand), `finishers[]`, `signature_moves[]`,
`themes[]` (title + artist), `alignment_history[]` (face/heel turns with the
reason), `card_positions[]` (upper/mid/low/injured status over time),
`tag_teams[]`, `managers[]`, `rivals[]`, `titles{}` (reigns grouped by
promotion), `career_awards[]`, `source_url`.

## Run it

```bash
# one-time: install the HTML parser (npm cache workaround avoids ~/.npm EACCES)
cd profiles-pipeline && npm install --cache "$(mktemp -d)" node-html-parser@6 && cd ..

# 1. fetch profile pages (default: the ~428 wrestlers that have a headshot;
#    ~1.1s/req polite pacing + backoff, skip-if-exists, atomic writes)
bash profiles-pipeline/fetch.sh
#    or a custom subset: bash profiles-pipeline/fetch.sh path/to/slugs.txt

# 2. (optional) download the two image sets scraped from each page:
#    - Ring Names & Gimmicks thumbnails -> gimmick-img/<slug>-<i>.webp
#    - Images History look-snapshots     -> era-img/<slug>-<i>.webp
#    Both: ~1 req/s, resumable, 160px lossy webp. gimmick-img powers the Ring
#    Names & Gimmicks profile section; era-img powers the time-accurate headshot.
node profiles-pipeline/fetch-gimmicks.js
node profiles-pipeline/fetch-era.js

# 3. parse every cached page into shards/profiles.json (keyed by roster slug).
#    Attaches local image paths for any downloaded thumbnails; safe to run with
#    none, some, or all images present.
node profiles-pipeline/build-profiles.js
```

## Time-accurate headshots

`images_history` (from the Images History section) is a newest-first list of
dated look-snapshots (`{iso, date, img}`). The UI's `eraImageFor(slug, date)`
picks the snapshot on/before a match's date, so a 2002 Undertaker shows his
biker look, not the Deadman. It falls back to a dated Ring Names gimmick image,
then the default `roster-img/<slug>.webp`. Applied to roster cards (scoped to the
as-of date) and the profile header (scoped to the event you arrived from).

## Slug notes

The profile-page slug usually equals the roster slug. For ~a dozen it differs
(e.g. roster `finn-blor` → SDH `finn-balor`, `riddle` → `matt-riddle`); the
fetcher tries the roster slug first, then the override from
`roster-img/_pipeline/sdh-fetched.tsv`. Unresolved slugs land in `misses.txt`.

## Files

- `parse-profile.js` — pure `parseProfile(html)` function + CLI. Handles both
  Joomla markup shapes: `<li>` lists and `<table class="fields-container">` grids.
- `fetch.sh` — polite scraper with slug fallback and a miss log.
- `build-profiles.js` — runs the parser over `cache/*.html`, prunes empty fields,
  writes `shards/profiles.json`, prints field coverage.
