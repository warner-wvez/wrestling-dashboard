const fs=require('fs');
const html=fs.readFileSync('/Users/warnervarnado/wrestling-dashboard/index.html','utf8');
const s=html.indexOf('<script id="wrestling-data"');
const o=html.indexOf('>',s)+1, c=html.indexOf('</script>',o);
const W=JSON.parse(html.slice(o,c)).wrestlers;
const slugs=new Set(Object.keys(W));
const imgs=fs.readdirSync('/Users/warnervarnado/wrestling-dashboard/roster-img').filter(f=>f.endsWith('.webp')).map(f=>f.replace(/\.webp$/,''));
const orphans=imgs.filter(sl=>!slugs.has(sl));
console.log('live wrestlers:',slugs.size);
console.log('webp images   :',imgs.length);
console.log('ORPHANS       :',orphans.length, orphans.length?orphans.join(', '):'(none)');
for(const k of ['gunther','ted-dibiase','ted-dibiase-jr','scott-hall','mr-perfect','eve-torres']){
  const w=W[k]; console.log('  check',k.padEnd(16), w?`OK "${w.name}" ${w.first_match_date||'?'}..${w.last_match_date||'?'} (${w.total_matches}m)`:'<<< NOT IN LIVE DATA');
}
