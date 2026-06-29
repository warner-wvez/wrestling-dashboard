const fs = require('fs');
const RAW = '/private/tmp/claude-501/-Users-warnervarnado/6fd62886-94ed-46ed-bcc1-07dfa557d10b/scratchpad/png-raw';
const TSV = '/Users/warnervarnado/wrestling-dashboard/roster-img/SLUGS.tsv';
const rows = fs.readFileSync(TSV,'utf8').trim().split('\n').slice(1).map(l=>{const[slug,name,mc]=l.split('\t');return{slug,name,mc:+mc}});
const dashSlugs = new Set(rows.map(r=>r.slug));
// normalize a name/slug to a comparison key: lowercase, strip "the", punctuation, spaces->nothing
const norm = s => s.toLowerCase().replace(/[’']/g,'').replace(/[^a-z0-9]+/g,' ').replace(/\b(the|jr|sr)\b/g,' ').replace(/\s+/g,'').trim();
const byNorm = new Map();
for (const r of rows){ const k=norm(r.name); if(!byNorm.has(k)) byNorm.set(k,r); const ks=norm(r.slug); if(!byNorm.has(ks)) byNorm.set(ks,r); }
const sdh = fs.readdirSync(RAW).filter(f=>f.endsWith('.png')).map(f=>f.replace(/\.png$/,'')).sort();
const exact=[], named=[], unmatched=[];
for (const s of sdh){
  if (s==='vacant') { unmatched.push([s,'(skip: vacant)']); continue; }
  if (dashSlugs.has(s)) { exact.push(s); continue; }
  const k = norm(s.replace(/-/g,' '));
  if (byNorm.has(k)) { named.push([s, byNorm.get(k).slug, byNorm.get(k).name]); continue; }
  unmatched.push([s, k]);
}
console.log(`SDH images: ${sdh.length}`);
console.log(`\n== EXACT slug match: ${exact.length} ==`);
console.log(`\n== NAME-normalized match: ${named.length} ==`);
for (const [s,slug,name] of named) console.log(`  ${s}  ->  ${slug}  (${name})`);
console.log(`\n== UNMATCHED: ${unmatched.length} ==`);
for (const [s,k] of unmatched) console.log(`  ${s}   [norm:${k}]`);
