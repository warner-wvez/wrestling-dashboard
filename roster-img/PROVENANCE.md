# roster-img provenance

What is in `roster-img/`, where each headshot came from, and the judgment calls
behind the non-obvious ones. Read this before adding more so you do not
re-derive the same decisions. Runnable tooling is in `_pipeline/`.

Last verified: 2026-06-29 against the live `index.html` data (1,495 wrestlers).

## Summary

- 428 photographic head-and-shoulders headshots, all 320x320 webp, one per slug.
- Every file binds to a real slug in the live wrestlers map. Orphans: 0.
- Coverage by match count: top 50 = 100%, top 100 = 98%, top 200 = 96%,
  top 300 = 91%. (The long tail of low-match jobbers is mostly not on the source
  site, see Misses.)
- One source throughout: The SmackDown Hotel (thesmackdownhotel.com) full-body
  renders. No sprites. A lone pixel-art sprite was rejected, see Special cases.

## How the 428 break down

| Count | How | Record |
|---|---|---|
| 126 | Cropped from the captured `www.thesmackdownhotel.com.har` roster page | `_pipeline/map.tsv` |
| 1 | `ted-dibiase` copied from the son's render (see Special cases) | (note below) |
| 293 | Fetched directly from SDH's full-body image URLs | `_pipeline/sdh-fetched.tsv` |
| 8 | Copied from an existing headshot for a duplicate slug | `_pipeline/alias-copies.tsv` |

The har only held one roster page (about 142 renders). The same images are
addressable by URL, so the rest were pulled by slug with `_pipeline/sdh-fetch.sh`.

## Crop and encode spec (build.sh and sdh-fetch.sh use the same)

- Square side = 78% of the figure's alpha height, capped at the canvas height.
- Centered on the figure horizontally, anchored near the top with 8% headroom,
  so the result is head and upper body, not the full figure.
- Output: 320x320 webp, method 6, alpha-quality 92, quality 82. Transparent
  background preserved so the card's `#F5F5F5` slot shows through.
- The card renders the slot `object-fit: cover`, `object-position: top center`.

## SDH naming vs dashboard slugs

SDH names use ring names and are inconsistent about a leading "the". The fetcher
tries, in order: the slug, the slug without "the-", the slug with "the-" added,
and without a "-jr"/"-sr" suffix, plus a tiny manual map (e.g. `finn-blor` to
`finn-balor`, `montel-vontavious-porter` to `mvp`). Resolved names are recorded
per slug in `sdh-fetched.tsv` so a re-fetch is deterministic.

### Identity calls from the har batch (cross-checked against era in the data)

| Source render | Dashboard slug | Note |
|---|---|---|
| razor-ramon | scott-hall | Razor Ramon was Scott Hall's WWF name. Era: 2002 nWo. |
| jbl | john-bradshaw-layfield | Same person, full-name slug. |
| mr-perfect-curt-hennig | mr-perfect | Gimmick to slug. Era: 2002. |
| stone-cold-steve-austin | steve-austin | Same person. |
| jerry-lawler | jerry-the-king-lawler | Same person. |
| ricky-steamboat | ricky-the-dragon-steamboat | Same person. |
| hacksaw-jim-duggan | jim-duggan | Same person. |
| eve | eve-torres | Eve Torres. Era: 2008 to 2013. |

Plus mechanical spelling / "the-" fixes (big-show to the-big-show,
vladamir-kozlov to vladimir-kozlov, etc). Full record: `_pipeline/map.tsv`.

## Duplicate slugs (same wrestler, two slugs in the data)

The dataset has separate slugs for some wrestlers' different ring-name eras. For
those, the same face is copied to both (recorded in `alias-copies.tsv`):
`primo`=primo-colon, `bradshaw`=john-bradshaw-layfield, `stardust`=cody-rhodes,
`charlotte`=charlotte-flair, `johnny-nitro`=john-morrison,
`king-corbin`=baron-corbin, `faarooq`=ron-simmons, `king-booker`=booker-t.

## Special cases

### ted-dibiase (the son, not the Million Dollar Man)

The dashboard's `ted-dibiase` slug (159 matches, 2007 to 2012) is Ted DiBiase
Jr, not his father. The SDH render `ted-dibiase-jr.png` (the son) was mapped to
the `ted-dibiase-jr` slug and copied to `ted-dibiase.webp` so the son's main
159-match card also shows his face. The father (`million-dollar-man.png`) was
skipped: he has no slug in the corpus.

### gunther (rejected, in `_pipeline/rejected/`)

`gunther.webp` was added out of band from a pixel-art source (a sprite site), not
from SDH. It is a full-body 8-bit sprite, off-style among photographic head-and-
shoulders renders, so it was pulled. The card falls back to initials, which is
cleaner. To replace: SDH had no Gunther/Walter render at capture time; check
again later and run it through `_pipeline/sdh-fetch.sh`.

## Misses (what SDH did not have)

95 wrestlers within the top-500 by match count returned no full-body image under
any name tried. They are listed with match count in `_pipeline/sdh-misses.txt`.
Causes: not in SDH's roster set, or a ring name SDH files differently than tried
(a few were recovered this way, e.g. `titus-oneil` from `titus-o-neil`). The
file is the worklist for the next pass or a fresh capture.

## Adding more

```
bash roster-img/_pipeline/sdh-fetch.sh 800   # ensure top-800 by matches are covered
node roster-img/_pipeline/verify.js          # must print ORPHANS: 0
bash roster-img/_pipeline/qa.sh              # flags blank/sprite/tiny outliers
```

Start from the top of `SLUGS.tsv` (sorted by match count): those are the
wrestlers a viewer sees first. Pace the fetcher at about 1 request/second; faster
bursts trip SDH rate-limiting, which makes every request fail as a false miss.
