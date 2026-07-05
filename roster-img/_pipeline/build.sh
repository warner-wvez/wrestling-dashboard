#!/usr/bin/env bash
# Batch-crop SDH full-body renders into 320x320 headshot webps (the crop spec
# sdh-fetch.sh reuses). Inputs live in a working directory:
#   $BASE/png-raw/<sdh-name>.png   the downloaded renders
#   $BASE/map.tsv                  sdh-name<TAB>roster-slug
# Output: $BASE/headshots-out/<roster-slug>.webp
#
# Usage:  bash roster-img/_pipeline/build.sh <BASE-dir>
#         (or set BASE in the environment)
set -euo pipefail
BASE="${1:-${BASE:-}}"
if [ -z "$BASE" ] || [ ! -d "$BASE/png-raw" ] || [ ! -f "$BASE/map.tsv" ]; then
  echo "usage: build.sh <BASE-dir>  (needs \$BASE/png-raw/ and \$BASE/map.tsv)" >&2
  exit 1
fi
RAW="$BASE/png-raw"; OUT="$BASE/headshots-out"; mkdir -p "$OUT"; rm -f "$OUT"/*.webp
n=0; skipped=0
while IFS=$'\t' read -r sdh dash; do
  [ -z "$sdh" ] && continue
  # One unreadable PNG must skip, not abort the whole batch (set -e would kill
  # the run mid-list and everything after it would silently never build).
  bb=$(magick "$RAW/$sdh.png" -alpha extract -threshold 25% -format "%@" info: 2>/dev/null) || bb=""
  if [ -z "$bb" ]; then echo "SKIP $sdh (unreadable or no alpha bounds)"; skipped=$((skipped+1)); continue; fi
  W=${bb%%x*}; rest=${bb#*x}; H=${rest%%+*}; rest=${rest#*+}; X=${rest%%+*}; Y=${rest#*+}
  cx=$((X + W/2))
  side=$(awk -v h="$H" 'BEGIN{printf "%d", h*0.78}')
  [ "$side" -gt 566 ] && side=566
  [ "$side" -lt 1 ] && { echo "SKIP $sdh (degenerate bounds $bb)"; skipped=$((skipped+1)); continue; }
  cl=$((cx - side/2)); [ "$cl" -lt 0 ] && cl=0; maxc=$((800-side)); [ "$maxc" -lt 0 ] && maxc=0; [ "$cl" -gt "$maxc" ] && cl=$maxc
  pad=$(awk -v s="$side" 'BEGIN{printf "%d", s*0.08}')
  ct=$((Y-pad)); [ "$ct" -lt 0 ] && ct=0; maxt=$((566-side)); [ "$maxt" -lt 0 ] && maxt=0; [ "$ct" -gt "$maxt" ] && ct=$maxt
  if magick "$RAW/$sdh.png" -crop "${side}x${side}+${cl}+${ct}" +repage \
    -resize 320x320 -background none -gravity center -extent 320x320 \
    -define webp:method=6 -define webp:alpha-quality=92 -quality 82 \
    "$OUT/$dash.webp"; then
    n=$((n+1))
  else
    echo "SKIP $sdh (crop failed)"; skipped=$((skipped+1))
  fi
done < "$BASE/map.tsv"
echo "Built $n webp files, skipped $skipped"
if [ "$n" -gt 0 ]; then
  echo "Total size:"; du -sh "$OUT"
  echo "Size distribution (KB):"
  for f in "$OUT"/*.webp; do printf '%s %s\n' "$(wc -c < "$f" | tr -d ' ')" "$f"; done \
    | awk '{s+=$1; if($1>max){max=$1;mf=$2}} END{if(NR)printf "  avg=%.1fKB  max=%.1fKB (%s)\n", s/NR/1024, max/1024, mf}'
fi
