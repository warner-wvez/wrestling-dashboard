'use strict';
// Download the dated look-snapshots from the Images History section of each
// cached SDH page into era-img/<roster-slug>-<index>.webp (index = position in
// the images_history list). These power the time-accurate headshot: for a match
// on a given date, show the wrestler as they looked closest to (and not after)
// that date. Same download machinery as fetch-gimmicks.js (resumable, atomic,
// polite pacing, forced webp output).
//
//   node profiles-pipeline/fetch-era.js
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { parseProfile } = require('./parse-profile');

const ROOT = path.join(__dirname, '..');
const CACHE = path.join(__dirname, 'cache');
const OUT = path.join(ROOT, 'era-img');
const MISS = path.join(__dirname, 'era-misses.txt');
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';
fs.mkdirSync(OUT, { recursive: true });
const sleep = (s) => { try { execFileSync('sleep', [String(s)]); } catch (_) {} };

const tasks = [];
for (const f of fs.readdirSync(CACHE).filter((x) => x.endsWith('.html'))) {
  const slug = f.replace(/\.html$/, '');
  let o;
  try { o = parseProfile(fs.readFileSync(path.join(CACHE, f), 'utf8')); } catch (_) { continue; }
  (o.images_history || []).forEach((r, i) => { if (r.src) tasks.push({ slug, i, src: r.src }); });
}
console.log(`images-history photos to consider: ${tasks.length}`);

let got = 0, skip = 0, fail = 0, n = 0;
const misses = [];
for (const t of tasks) {
  n++;
  const dest = path.join(OUT, `${t.slug}-${t.i}.webp`);
  if (fs.existsSync(dest)) { skip++; continue; }
  // Take the extension from the LAST PATH SEGMENT only. Splitting the whole URL
  // on '.' pulls dots out of the host ('host.com/img/foo' -> 'com/img/foo'), a
  // bogus extension magick can't decode. Default to jpg when the path has none.
  const seg = t.src.split('?')[0].split('#')[0].split('/').pop() || '';
  const ext = (seg.includes('.') ? seg.split('.').pop() : 'jpg').toLowerCase().replace(/[^a-z0-9]/g, '') || 'jpg';
  const raw = dest + '.dl.' + ext;
  const tmp = dest + '.tmp';
  let ok = false;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      execFileSync('curl', ['-sSLf', '-A', UA, '--max-time', '45', '-o', raw, t.src], { stdio: 'ignore' });
      if (fs.statSync(raw).size < 400) throw new Error('short body');
      execFileSync('magick', [raw, '-resize', '160x160^', '-gravity', 'center', '-extent', '160x160',
        '-strip', '-define', 'webp:lossless=false', '-quality', '72', 'webp:' + tmp], { stdio: 'ignore' });
      fs.renameSync(tmp, dest);
      ok = true;
      break;
    } catch (e) {
      try { fs.unlinkSync(tmp); } catch (_) {}
      sleep(attempt * 2);
    } finally {
      try { fs.unlinkSync(raw); } catch (_) {}
    }
  }
  if (ok) { got++; if (n % 50 === 0) process.stdout.write(`\r[${n}/${tasks.length}] got=${got} skip=${skip} fail=${fail}   `); }
  else { fail++; misses.push(`${t.slug}-${t.i} ${t.src}`); }
  sleep(0.6);
}
fs.writeFileSync(MISS, misses.join('\n') + (misses.length ? '\n' : ''));
console.log(`\ndone. got=${got} skip=${skip} fail=${fail}  (misses in ${MISS})`);
