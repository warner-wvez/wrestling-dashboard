'use strict';
// Parse every cached SDH page in profiles-pipeline/cache/*.html into a single
// sidecar shards/profiles.json keyed by roster slug (the cache filename). Empty
// fields are dropped to keep the sidecar small; a wrestler with nothing usable
// is omitted entirely. Run after fetch.sh.
//
//   node profiles-pipeline/build-profiles.js
const fs = require('fs');
const path = require('path');
const { parseProfile } = require('./parse-profile');

const ROOT = path.join(__dirname, '..');
const CACHE = path.join(__dirname, 'cache');
const OUT = path.join(ROOT, 'shards', 'profiles.json');
const SDH_BASE = 'https://www.thesmackdownhotel.com/wrestlers';

// Roster slug -> SDH profile slug, so source_url points at the page we scraped.
// slug-overrides.tsv (curated combined ring-name slugs) wins over the image-dir
// map in sdh-fetched.tsv.
const override = {};
const loadMap = (p) => {
  try {
    for (const l of fs.readFileSync(p, 'utf8').trim().split('\n')) {
      if (l.startsWith('#')) continue;
      const [r, s] = l.split('\t');
      if (r && s && r !== s) override[r] = s;
    }
  } catch (_) { /* optional */ }
};
loadMap(path.join(__dirname, '..', 'roster-img', '_pipeline', 'sdh-fetched.tsv'));
loadMap(path.join(__dirname, 'slug-overrides.tsv'));

const isEmpty = (v) =>
  v == null || v === '' ||
  (Array.isArray(v) && v.length === 0) ||
  (typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0);

function prune(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj)) if (!isEmpty(v)) out[k] = v;
  return out;
}

const files = fs.existsSync(CACHE) ? fs.readdirSync(CACHE).filter((f) => f.endsWith('.html')) : [];
const profiles = {};
let kept = 0, skipped = 0;
const fieldCounts = {};

for (const f of files) {
  const slug = f.replace(/\.html$/, '');
  let obj;
  try {
    const html = fs.readFileSync(path.join(CACHE, f), 'utf8');
    obj = parseProfile(html, {});
  } catch (e) {
    console.error('PARSE FAIL', slug, e.message);
    skipped++;
    continue;
  }
  obj.source_url = `${SDH_BASE}/${override[slug] || slug}`;
  // Attach the downloaded local gimmick thumbnail to each ring name (if present)
  // and drop the remote src from the shipped data.
  if (Array.isArray(obj.ring_names)) {
    obj.ring_names = obj.ring_names.map((r, i) => {
      const rel = `gimmick-img/${slug}-${i}.webp`;
      const out = { name: r.name, from: r.from, to: r.to };
      if (fs.existsSync(path.join(ROOT, rel))) out.img = rel;
      return out;
    });
  }
  // Images History drives the time-accurate headshot: keep the sortable iso date
  // and the local era-img path, drop the remote src.
  if (Array.isArray(obj.images_history)) {
    obj.images_history = obj.images_history.map((r, i) => {
      const rel = `era-img/${slug}-${i}.webp`;
      const out = { iso: r.iso, date: r.date };
      if (fs.existsSync(path.join(ROOT, rel))) out.img = rel;
      return out;
    }).filter((r) => r.img);   // only entries whose photo we actually have
  }
  const pruned = prune(obj);
  // Require at least some real bio content (not just source_url).
  const meaningful = Object.keys(pruned).filter((k) => k !== 'source_url');
  if (meaningful.length === 0) { skipped++; continue; }
  for (const k of meaningful) fieldCounts[k] = (fieldCounts[k] || 0) + 1;
  profiles[slug] = pruned;
  kept++;
}

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(profiles));
const bytes = fs.statSync(OUT).size;
console.log(`wrote ${OUT}`);
console.log(`  kept ${kept}, skipped ${skipped}, size ${(bytes / 1024).toFixed(0)} KB`);
console.log('  field coverage (wrestlers with each field):');
for (const [k, c] of Object.entries(fieldCounts).sort((a, b) => b[1] - a[1])) {
  console.log(`    ${String(c).padStart(4)}  ${k}`);
}
