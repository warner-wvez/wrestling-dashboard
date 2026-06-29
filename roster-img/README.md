# roster-img

Portrait images for the time-aware Roster view. Drop a file here named by a
wrestler's slug and it shows up automatically on that wrestler's roster card.
No code change needed.

## How it works

Each roster card renders:

```html
<img src="roster-img/<slug>.webp" onerror="this.remove()">
```

If the file exists, it fills the card's square photo slot. If it does not, the
card falls back to the wrestler's initials. A missing image never shows a broken
image icon.

## Naming

- Filename is the wrestler's slug plus `.webp`, for example `john-cena.webp`,
  `rey-mysterio.webp`, `the-undertaker.webp`.
- The slug is the same id used everywhere in the dashboard. You can read it off
  any wrestler's profile URL: `#wrestler/<slug>`.
- The full list of slugs (all 1,495, sorted by match count) is in `SLUGS.tsv`
  next to this file: columns are slug, name, total_matches.

## Image specs

- Format: WebP.
- Shape: square. Cards crop to a 1:1 slot, anchored to the top
  (`object-position: top center`), so head and shoulders framing reads best.
- Size: around 400x400px is plenty. Smaller, optimized files load faster on
  mobile, which matters since the bundle is already near the mobile memory limit.

## Notes

- Images are not bundled into the dashboard HTML. They load on demand (lazy), so
  only cards you actually scroll to request a file.
- Start with the highest match-count names in `SLUGS.tsv`; those are the
  wrestlers a viewer is most likely to see first.
