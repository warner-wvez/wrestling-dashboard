#!/usr/bin/env bash
# Fetch missing wrestler headshots directly from The SmackDown Hotel's full-body
# image directory and crop them to 320x320 webp, same spec as build.sh.
#
# Usage:  bash roster-img/_pipeline/sdh-fetch.sh [TOPN]
#   TOPN = ensure the top-N wrestlers by match count have a headshot (default 500).
#
# Why direct fetch: the original www.thesmackdownhotel.com.har only held one
# roster page (~142 renders). The same images are addressable by URL, so we pull
# the rest by slug. Paced at ~1 req/sec (per REQUEST, not per slug) with
# backoff; faster bursts get rate-limited (every request then fails, which
# reads as a false miss).
#
# Records: appends slug<TAB>sdh-name to sdh-fetched.tsv; rewrites sdh-misses.txt
# with this run's unresolved names (only when at least one target existed, so a
# broken run can never wipe the worklist). Safe to re-run: slugs that already
# have a webp are skipped. Crops land in roster-img/ atomically (temp file +
# mv), so an interrupted run never leaves a truncated webp that the
# skip-if-exists check would then treat as done forever.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1            # repo root
TOPN="${1:-500}"
PIPE="roster-img/_pipeline"
B="https://www.thesmackdownhotel.com/images/wrestling/wrestlers/full-body"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FET="$PIPE/sdh-fetched.tsv"; MISS="$PIPE/sdh-misses.txt"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# Target list. A node failure (missing SLUGS.tsv, parse error) must abort, not
# silently continue with zero targets and then clobber the miss worklist.
if ! node -e '
const fs=require("fs");
const rows=fs.readFileSync("roster-img/SLUGS.tsv","utf8").trim().split("\n").slice(1).map(l=>{const[s,n,m]=l.split("\t");return{s,m:+m}});
const have=new Set(fs.readdirSync("roster-img").filter(f=>f.endsWith(".webp")).map(f=>f.replace(/\.webp$/,"")));
rows.slice(0,+process.argv[1]).filter(r=>!have.has(r.s)).forEach(r=>console.log(r.s+"\t"+r.m));
' "$TOPN" > "$WORK/targets.txt"; then
  echo "FATAL: could not build target list (is roster-img/SLUGS.tsv present?)" >&2
  exit 1
fi
TOTAL=$(wc -l < "$WORK/targets.txt" | tr -d ' '); echo "missing within top $TOPN: $TOTAL"

candidates_for(){ local s="$1"; local -a c=()
  case "$s" in finn-blor) c+=(finn-balor);; montel-vontavious-porter) c+=(mvp);; esac
  c+=("$s"); [[ "$s" == the-* ]] && c+=("${s#the-}"); [[ "$s" != the-* ]] && c+=("the-$s")
  [[ "$s" == *-jr ]] && c+=("${s%-jr}"); [[ "$s" == *-sr ]] && c+=("${s%-sr}")
  printf '%s\n' "${c[@]}" | awk '!seen[$0]++'; }

crop_one(){ local src="$1" out="$2" CW CH bb W rest H X Y cx side cl maxc pad ct maxt
  read CW CH < <(magick identify -format "%w %h\n" "${src}[0]" 2>/dev/null); [ -z "${CW:-}" ] && return 1
  bb=$(magick "$src" -alpha extract -threshold 25% -format "%@" info: 2>/dev/null); [ -z "$bb" ] && return 1
  W=${bb%%x*}; rest=${bb#*x}; H=${rest%%+*}; rest=${rest#*+}; X=${rest%%+*}; Y=${rest#*+}; [ -z "${H:-}" ] && return 1
  cx=$((X + W/2)); side=$(awk "BEGIN{printf \"%d\",$H*0.78}"); [ "$side" -gt "$CH" ] && side=$CH; [ "$side" -lt 1 ] && return 1
  cl=$((cx - side/2)); [ $cl -lt 0 ] && cl=0; maxc=$((CW-side)); [ $maxc -lt 0 ] && maxc=0; [ $cl -gt $maxc ] && cl=$maxc
  pad=$(awk "BEGIN{printf \"%d\",$side*0.08}"); ct=$((Y-pad)); [ $ct -lt 0 ] && ct=0; maxt=$((CH-side)); [ $maxt -lt 0 ] && maxt=0; [ $ct -gt $maxt ] && ct=$maxt
  magick "$src" -crop ${side}x${side}+${cl}+${ct} +repage -resize 320x320 -background none -gravity center -extent 320x320 \
    -define webp:method=6 -define webp:alpha-quality=92 -quality 82 "$out"; }

hits=0; misses=0; i=0; : > "$WORK/miss.txt"
while IFS=$'\t' read -r slug mc; do
  [ -z "$slug" ] && continue; i=$((i+1)); [ -f "roster-img/$slug.webp" ] && continue
  attempt=0; got=""; outcome=""
  while :; do
    throttled=0
    while read -r cand; do
      code=$(curl -s -o "$WORK/$slug.png" -w "%{http_code} %{content_type}" -A "$UA" -H "Referer: https://www.thesmackdownhotel.com/" --max-time 25 "$B/$cand.png")
      rc=$?
      sleep 1                                   # pace EVERY request, not every slug
      # A dropped connection (rc!=0) can leave a truncated body behind 200
      # headers: treat it as transient (backoff + retry), never as a hit.
      if [ "$rc" -ne 0 ]; then throttled=1; break; fi
      [[ "$code" == 200\ image/* ]] && { got="$cand"; break; }
      [[ "${code%% *}" == 404 ]] && continue
      throttled=1; break
    done < <(candidates_for "$slug")
    [ -n "$got" ] && { outcome=hit; break; }
    if [ "$throttled" -eq 1 ]; then attempt=$((attempt+1)); [ "$attempt" -gt 5 ] && { outcome=throttle; break; }
      bo=$((15*attempt)); echo "[$i/$TOTAL] throttled $slug, backoff ${bo}s"; sleep "$bo"; continue; fi
    outcome=miss; break
  done
  # Crop to a temp file and move into place: the shipped dir never holds a
  # half-written webp (which the skip above would treat as done forever).
  if [ "$outcome" = hit ] && crop_one "$WORK/$slug.png" "$WORK/$slug.webp"; then
    mv "$WORK/$slug.webp" "roster-img/$slug.webp"
    printf '%s\t%s\n' "$slug" "$got" >> "$FET"; hits=$((hits+1)); echo "[$i/$TOTAL] HIT $slug <= $got"
  else
    reason="$outcome"; [ "$outcome" = hit ] && reason=crop-fail   # download OK, crop failed
    printf '%s\t%sm\t%s\n' "$slug" "$mc" "$reason" >> "$WORK/miss.txt"
    misses=$((misses+1)); echo "[$i/$TOTAL] miss $slug ($reason)"
  fi
done < "$WORK/targets.txt"
if [ "$TOTAL" -gt 0 ]; then
  { echo "# SDH had no full-body image for these. slug<TAB>matches<TAB>reason"; sort -t$'\t' -k2 -nr "$WORK/miss.txt"; } > "$MISS"
else
  echo "no targets processed: leaving $MISS untouched"
fi
echo "DONE  HITS:$hits  MISSES:$misses"
echo "Run: node $PIPE/verify.js   to confirm 0 orphans."
