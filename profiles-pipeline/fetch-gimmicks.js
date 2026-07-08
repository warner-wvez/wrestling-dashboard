'use strict';
// Download the per-gimmick thumbnails from the Ring Names & Gimmicks section of
// each cached SDH page and store them as tiny local webp thumbnails in
// gimmick-img/<roster-slug>-<index>.webp (index = position in the ring_names
// list, so it stays stable with build-profiles.js). Resumable (skip-if-exists),
// atomic writes, polite pacing with backoff. Same spirit as roster-img fetch.
//
//   node profiles-pipeline/fetch-gimmicks.js
const { parse } = require('node-html-parser');            // via profiles-pipeline/node_modules
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { parseProfile } = require('./parse-profile');

const ROOT = path.join(__dirname, '..');
const CACHE = path.join(__dirname, 'cache');
const OUT = path.join(ROOT, 'gimmick-img');
const MISS = path.join(__dirname, 'gimmick-misses.txt');
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';
fs.mkdirSync(OUT, { recursive: true });

const sleep = (s) => { try { execFileSync('sleep', [String(s)]); } catch (_) {} };

// Gather every (slug, index, src) gimmick image task.
const tasks = [];
for (const f of fs.readdirSync(CACHE).filter((x) => x.endsWith('.html'))) {
  const slug = f.replace(/\.html$/, '');
  let o;
  try { o = parseProfile(fs.readFileSync(path.join(CACHE, f), 'utf8')); } catch (_) { continue; }
  (o.ring_names || []).forEach((r, i) => { if (r.src) tasks.push({ slug, i, src: r.src }); });
}
console.log(`gimmick images to consider: ${tasks.length}`);

let got = 0, skip = 0, fail = 0, n = 0;
const misses = [];
for (const t of tasks) {
  n++;
  const dest = path.join(OUT, `${t.slug}-${t.i}.webp`);
  if (fs.existsSync(dest)) { skip++; continue; }
  // Name the download with its real extension: magick picks its decoder by
  // extension, and a ".raw" name would wrongly route to a camera-RAW delegate.
  const ext = (t.src.split('?')[0].split('.').pop() || 'img').toLowerCase().replace(/[^a-z0-9]/g, '') || 'img';
  const raw = dest + '.dl.' + ext;
  const tmp = dest + '.tmp';
  let ok = false;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      execFileSync('curl', ['-sSLf', '-A', UA, '--max-time', '45', '-o', raw, t.src], { stdio: 'ignore' });
      if (fs.statSync(raw).size < 400) throw new Error('short body');
      // 160px square: the largest on-screen use is the ~160px roster card and the
      // 124px profile header. SDH sources are 200x200, so this keeps them crisp
      // everywhere (the 44px ring-names list just downscales the same file).
      // Force webp OUTPUT via the webp: prefix: the temp name ends in .tmp, so
      // without it magick would keep the source format (e.g. avif) and mislabel it.
      execFileSync('magick', [raw, '-resize', '160x160^', '-gravity', 'center', '-extent', '160x160',
        '-strip', '-define', 'webp:lossless=false', '-quality', '72', 'webp:' + tmp], { stdio: 'ignore' });
      fs.renameSync(tmp, dest);
      ok = true;
      break;
    } catch (e) {
      try { fs.unlinkSync(tmp); } catch (_) {}
      sleep(attempt * 2);                                 // backoff on 404/429/short
    } finally {
      try { fs.unlinkSync(raw); } catch (_) {}
    }
  }
  if (ok) { got++; if (n % 50 === 0) process.stdout.write(`\r[${n}/${tasks.length}] got=${got} skip=${skip} fail=${fail}   `); }
  else { fail++; misses.push(`${t.slug}-${t.i} ${t.src}`); }
  sleep(0.7);                                             // politeness pacing
}
fs.writeFileSync(MISS, misses.join('\n') + (misses.length ? '\n' : ''));
console.log(`\ndone. got=${got} skip=${skip} fail=${fail}  (misses in ${MISS})`);
