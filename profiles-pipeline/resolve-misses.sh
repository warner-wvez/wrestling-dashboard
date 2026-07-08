#!/usr/bin/env bash
# Second-pass resolver for fetch.sh misses: roster slugs whose SDH profile lives
# at a different slug (usually a fuller ring name, e.g. charlotte -> charlotte-flair).
# For each miss, derive candidate SDH slugs from the roster DISPLAY name in
# roster-img/SLUGS.tsv (slugified, plus a couple transforms) and retry. Anything
# still unresolved is a genuine ring-name change we can't guess; it stays in
# misses and that wrestler simply gets no SDH depth (graceful).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PIPE="profiles-pipeline"; CACHE="$PIPE/cache"; MISS="$PIPE/misses.txt"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE="https://www.thesmackdownhotel.com/wrestlers"
[ -s "$MISS" ] || { echo "no misses to resolve"; exit 0; }

# Build "rslug<TAB>cand1 cand2 ..." from display names.
TARGETS="$(mktemp)"; trap 'rm -f "$TARGETS"' EXIT
node -e '
const fs=require("fs");
const names={};
for(const l of fs.readFileSync("roster-img/SLUGS.tsv","utf8").trim().split("\n").slice(1)){
  const [s,n]=l.split("\t"); if(s) names[s]=n||"";
}
const slugify=x=>x.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"")
  .replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
const misses=fs.readFileSync(process.argv[1],"utf8").trim().split("\n")
  .map(l=>l.split(" ")[0]).filter(Boolean);
for(const r of misses){
  const nm=names[r]||r.replace(/-/g," ");
  const cands=new Set();
  cands.add(slugify(nm));                        // full display name
  cands.add(slugify(nm.replace(/\s*[\/(].*$/,"")));// drop " / alt" or " (note)"
  cands.add(r.replace(/^the-/,""));               // drop leading the-
  cands.add("the-"+r);                            // add leading the-
  cands.delete(r);                                // already tried in pass 1
  console.log(r+"\t"+[...cands].filter(Boolean).join(" "));
}
' "$MISS" > "$TARGETS"

NEWMISS="$(mktemp)"
got=0; still=0
while IFS=$'\t' read -r rslug cands; do
  [ -z "$rslug" ] && continue
  out="$CACHE/$rslug.html"
  [ -s "$out" ] && continue
  ok=0; used=""
  for cand in $cands; do
    tmp="$(mktemp)"
    code=$(curl -sSL -A "$UA" -o "$tmp" -w '%{http_code}' --max-time 45 "$BASE/$cand" 2>/dev/null)
    sz=$(wc -c < "$tmp" | tr -d ' ')
    if [ "$code" = "200" ] && [ "$sz" -gt 20000 ]; then
      mv "$tmp" "$out"; ok=1; used="$cand"; break
    fi
    rm -f "$tmp"; sleep 1.1
  done
  if [ "$ok" = 1 ]; then
    got=$((got+1)); echo "RESOLVED $rslug -> $used"
  else
    still=$((still+1)); echo "$rslug -> tried [$cands] (unresolved)" >> "$NEWMISS"
  fi
  sleep 1.1
done < "$TARGETS"
mv "$NEWMISS" "$MISS"
echo "resolved=$got still-missing=$still (remaining in $MISS)"
