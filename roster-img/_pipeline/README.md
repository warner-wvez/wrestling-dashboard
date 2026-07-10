# roster-img pipeline

The exact scripts used to turn a batch of transparent wrestler renders into the
320x320 webp headshots in `roster-img/`. Kept here so the recipe survives even
though the original working files lived in a temp dir that clears on reboot.

See `../PROVENANCE.md` for the full record of what was mapped, skipped, and why.

## Files

- `genmap.js`: reads source PNG filenames, resolves each to a dashboard slug
  (exact match, then name-normalized, then a manual OVERRIDE table), drops a
  SKIP list, and writes `map.tsv` (source-name TAB dashboard-slug). Flags any
  collision (two sources to one slug) or unresolved name.
- `build.sh`: for each row in `map.tsv`, finds the figure via its alpha bounding
  box, crops a head-and-upper-body square, and writes `<slug>.webp` at 320x320.
- `match.js`: dry-run reporter. Shows exact vs name-normalized vs unmatched
  before you commit to a mapping. Run this first when adding a new batch.
- `map.tsv`: the canonical source-name to slug record for the batch already
  shipped. Append to it when you add more.
- `verify.js`: loads the live wrestlers map from `index.html`, lists every webp
  in `roster-img/`, and reports orphans (a webp whose slug is not in the data).
  Run after any addition. Zero orphans is the pass condition.
- `sdh-fetch.sh`: fetches missing wrestlers straight from SDH's full-body image
  URLs (no har needed), crops, and logs. Repo-relative, no path edits.
  `bash sdh-fetch.sh [TOPN]`. Two assumptions limit it, both addressed below:
  it takes targets from `SLUGS.tsv` (top-N by match count) and it guesses the
  image filename from the slug.
- `sdh-fetch-aliases.sh`: run after an identity merge. Targets come from
  `cagematch-pipeline/out/needs_fetch.tsv`, and each wrestler is tried under
  *every ring name they used*, not only their canonical slug. Humberto
  Carrillo's 98 matches were split three ways, dropping every fragment below
  the top-500 cutoff, so `sdh-fetch.sh` never even asked for him.
- `sdh-fetch-page.sh`: second pass. Resolves the image URL from the wrestler's
  SDH page (`<meta property="og:image">`) instead of guessing it. SDH
  year-stamps refreshed renders (`chad-gable-2026.png`), 301s old ring names to
  the current page (`/wrestlers/dominik-dijakovic` -> the Dijak page), and does
  not keep filenames in sync with slugs (`dominik-dijak.png`,
  `ashtante-adonis.png` — their typo — `tyler-taylor-rust.png`). So it follows
  redirects, and checks the page `<title>` names the wrestler rather than
  checking the filename. Writes `still-missing.tsv`.

  Candidates for both come from the worker's alias list in
  `wrestler_identity.json`, already restricted to names no other wrestler used,
  so a candidate page can never yield a different person's face.
- `qa.sh`: flags off-style images (sprite / blank / tiny figure) by file size and
  opaque fraction, so you do not have to eyeball every file.
- `sdh-fetched.tsv`: slug TAB sdh-source-name for every directly fetched image.
- `alias-copies.tsv`: duplicate slug TAB the headshot it was copied from.
- `sdh-misses.txt`: wrestlers SDH had no image for. The worklist for next time.
- `rejected/`: images pulled from the active set, with the reason in PROVENANCE.

## Heads up: paths are hardcoded

`genmap.js` and `build.sh` carry absolute paths to the original temp session
(`/private/tmp/claude-501/.../scratchpad/png-raw` etc). Before re-running, edit
the `BASE` / `RAW` lines at the top of each to point at your new source folder.
`SLUGS.tsv` and `map.tsv` paths already point inside the repo.

## Primary recipe: fetch from SDH by slug (no har)

```
bash roster-img/_pipeline/sdh-fetch.sh 800   # ensure top-800 by matches covered
node roster-img/_pipeline/verify.js          # must print ORPHANS: 0
bash roster-img/_pipeline/qa.sh              # flags any off-style outliers
```

Pace stays at about 1 request/second with backoff. Faster bursts trip SDH
rate-limiting, which returns errors for everything and reads as false misses.
Re-runs are safe: slugs that already have a webp are skipped. Unresolved names
land in `sdh-misses.txt`; recover them by adding a name variant to the fetcher's
manual map, or copy from an existing slug if it is the same wrestler.

## Legacy recipe: crop a downloaded render batch (har / folder of PNGs)

1. Get transparent PNG renders, one per wrestler, named loosely after the
   wrestler (the matcher normalizes case, punctuation, and a leading "the").
   Put them in a folder, set that as `RAW`.
2. `node match.js` and read the UNMATCHED list. For each, either rename the PNG
   to the slug, or add an entry to the `OVERRIDE` table in `genmap.js`. Add
   anyone with no card to the `SKIP` set.
3. `node genmap.js` until it prints `No collisions.` and a clean skip list.
4. `bash build.sh` to produce the webp files, then copy them into `roster-img/`.
5. `node verify.js`. Confirm `ORPHANS: 0`.

## Crop and encode spec (from build.sh)

- Square side = 78% of the figure's alpha height, capped at 566px.
- Centered on the figure horizontally, anchored near the top with 8% headroom,
  so the result is head and upper body, not full figure.
- Output: 320x320 webp, method 6, alpha-quality 92, quality 82. Transparent
  background preserved so the card's gray slot shows through.
- The card renders the slot with `object-fit: cover`, `object-position: top
  center`, on a `#F5F5F5` background.
