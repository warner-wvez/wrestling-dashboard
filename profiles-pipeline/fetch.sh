#!/usr/bin/env bash
# Fetch SmackDown Hotel wrestler profile pages for scraping into shards/profiles.json.
#
# Usage:  bash profiles-pipeline/fetch.sh [SLUGFILE]
#   SLUGFILE: newline list of ROSTER slugs to fetch. Default: every wrestler that
#   already has a headshot (roster-img/*.webp) — those are the cards that render
#   and are known to exist on SDH.
#
# Design mirrors roster-img/_pipeline/sdh-fetch.sh: same UA, ~1.1s/req pacing with
# backoff (faster bursts get rate-limited), skip-if-exists, atomic writes (temp +
# mv) so an interrupted run never leaves a truncated cache file, and a miss log.
# Output keyed by ROSTER slug; the page is fetched by SDH slug (12 differ, mapped
# from sdh-fetched.tsv). Targets are built by node (macOS ships bash 3.2, no
# associative arrays / mapfile), same tactic as the headshot pipeline.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1                 # repo root
PIPE="profiles-pipeline"
CACHE="$PIPE/cache"; mkdir -p "$CACHE"
MISS="$PIPE/misses.txt"; : > "$MISS"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE="https://www.thesmackdownhotel.com/wrestlers"

# Build "rosterSlug<TAB>sdhSlug" target list. sdh-fetched.tsv holds the 12 slugs
# that differ; everything else fetches under its own roster slug.
TARGETS="$(mktemp)"; trap 'rm -f "$TARGETS"' EXIT
if ! node -e '
const fs=require("fs");
const over={};
for(const l of fs.readFileSync("roster-img/_pipeline/sdh-fetched.tsv","utf8").trim().split("\n")){
  if(l.startsWith("#")) continue; const [r,s]=l.split("\t"); if(r&&s&&r!==s) over[r]=s;
}
let slugs;
const arg=process.argv[1];
if(arg){ slugs=fs.readFileSync(arg,"utf8").trim().split("\n").map(s=>s.trim()).filter(Boolean); }
else { slugs=fs.readdirSync("roster-img").filter(f=>f.endsWith(".webp")).map(f=>f.replace(/\.webp$/,"")); }
for(const r of slugs) console.log(r+"\t"+(over[r]||r));
' "${1:-}" > "$TARGETS"; then
  echo "FATAL: could not build target list" >&2; exit 1
fi
TOTAL=$(wc -l < "$TARGETS" | tr -d ' '); echo "targets: $TOTAL"

n=0; got=0; miss=0; skip=0
while IFS=$'\t' read -r rslug sdh; do
  [ -z "$rslug" ] && continue
  n=$((n+1))
  out="$CACHE/$rslug.html"
  if [ -s "$out" ]; then skip=$((skip+1)); continue; fi
  # Candidate profile slugs: roster slug first (matches ~97% of pages), then the
  # image-dir override from sdh-fetched.tsv (right for a handful like finn-balor,
  # matt-riddle). Roster slug is sometimes the correct one even when an override
  # exists (e.g. the-undertaker), so always try it first.
  cands="$rslug"
  [ "$sdh" != "$rslug" ] && cands="$rslug $sdh"
  ok=0; code=""
  for cand in $cands; do
    for attempt in 1 2 3; do
      tmp="$(mktemp)"
      code=$(curl -sSL -A "$UA" -o "$tmp" -w '%{http_code}' --max-time 45 "$BASE/$cand" 2>/dev/null)
      sz=$(wc -c < "$tmp" | tr -d ' ')
      if [ "$code" = "200" ] && [ "$sz" -gt 20000 ]; then
        mv "$tmp" "$out"; ok=1; break
      fi
      rm -f "$tmp"
      [ "$code" = "404" ] && break                 # wrong slug, try next candidate now
      sleep $((attempt*3))                          # backoff on 429/5xx/short body
    done
    [ "$ok" = 1 ] && break
  done
  if [ "$ok" = 1 ]; then
    got=$((got+1)); printf '\r[%d/%d] got=%d skip=%d miss=%d  %-30s' "$n" "$TOTAL" "$got" "$skip" "$miss" "$rslug"
  else
    miss=$((miss+1)); echo "$rslug -> tried [$cands] (last $code)" >> "$MISS"
    printf '\rMISS %-40s\n' "$rslug"
  fi
  sleep 1.1                                        # politeness pacing
done < "$TARGETS"
echo; echo "done. got=$got skip=$skip miss=$miss  (misses in $MISS)"
