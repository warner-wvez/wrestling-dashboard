const fs = require('fs');
const RAW = '/private/tmp/claude-501/-Users-warnervarnado/6fd62886-94ed-46ed-bcc1-07dfa557d10b/scratchpad/png-raw';
const TSV = '/Users/warnervarnado/wrestling-dashboard/roster-img/SLUGS.tsv';
const rows = fs.readFileSync(TSV,'utf8').trim().split('\n').slice(1).map(l=>{const[slug,name,mc]=l.split('\t');return{slug,name,mc:+mc}});
const dashSlugs = new Set(rows.map(r=>r.slug));
const norm = s => s.toLowerCase().replace(/[’']/g,'').replace(/[^a-z0-9]+/g,' ').replace(/\b(the|jr|sr)\b/g,' ').replace(/\s+/g,'').trim();
const byNorm = new Map();
for (const r of rows){ const k=norm(r.name); if(!byNorm.has(k)) byNorm.set(k,r); const ks=norm(r.slug); if(!byNorm.has(ks)) byNorm.set(ks,r); }
// manual resolved overrides (sdh -> dashboard slug), confidence-checked
const OVERRIDE = {
  'eve':'eve-torres','hacksaw-jim-duggan':'jim-duggan','jbl':'john-bradshaw-layfield',
  'jerry-lawler':'jerry-the-king-lawler','mr-perfect-curt-hennig':'mr-perfect','razor-ramon':'scott-hall',
  'ricky-steamboat':'ricky-the-dragon-steamboat','stone-cold-steve-austin':'steve-austin',
  'trent-beretta':'trent-barreta','vladamir-kozlov':'vladimir-kozlov',
};
const SKIP = new Set(['vacant','andre-the-giant','bobby-heenan','bruno-sammartino','jake-the-snake-roberts',
  'jimmy-hart','million-dollar-man','mjf','paul-bearer','randy-savage','rick-steiner','ultimate-warrior',
  'yokozuna','jack-korpela','justin-roberts','scott-stanford']);
const sdh = fs.readdirSync(RAW).filter(f=>f.endsWith('.png')).map(f=>f.replace(/\.png$/,'')).sort();
const map=[]; const skipped=[]; const collide={};
for (const s of sdh){
  if (SKIP.has(s)) { skipped.push(s); continue; }
  let dash=null;
  if (OVERRIDE[s]) dash=OVERRIDE[s];
  else if (dashSlugs.has(s)) dash=s;
  else { const k=norm(s.replace(/-/g,' ')); if(byNorm.has(k)) dash=byNorm.get(k).slug; }
  if (!dash) { skipped.push(s+' (UNRESOLVED!)'); continue; }
  if (!dashSlugs.has(dash)) { skipped.push(s+' -> '+dash+' (NOT IN ROSTER!)'); continue; }
  (collide[dash]=collide[dash]||[]).push(s);
  map.push([s,dash]);
}
// collision check
const dupes = Object.entries(collide).filter(([d,ss])=>ss.length>1);
fs.writeFileSync('/private/tmp/claude-501/-Users-warnervarnado/6fd62886-94ed-46ed-bcc1-07dfa557d10b/scratchpad/map.tsv', map.map(r=>r.join('\t')).join('\n')+'\n');
console.log(`MAPPED: ${map.length}`);
console.log(`SKIPPED: ${skipped.length}`);
if (dupes.length){ console.log('!!! COLLISIONS:'); dupes.forEach(([d,ss])=>console.log('  '+d+' <= '+ss.join(', '))); }
else console.log('No collisions.');
console.log('\nSkipped list:'); skipped.forEach(s=>console.log('  '+s));
