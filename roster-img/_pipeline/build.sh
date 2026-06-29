#!/usr/bin/env bash
set -e
BASE=/private/tmp/claude-501/-Users-warnervarnado/6fd62886-94ed-46ed-bcc1-07dfa557d10b/scratchpad
RAW=$BASE/png-raw; OUT=$BASE/headshots-out; mkdir -p "$OUT"; rm -f "$OUT"/*.webp
n=0
while IFS=$'\t' read -r sdh dash; do
  [ -z "$sdh" ] && continue
  bb=$(magick "$RAW/$sdh.png" -alpha extract -threshold 25% -format "%@" info: 2>/dev/null)  # WxH+X+Y
  W=${bb%%x*}; rest=${bb#*x}; H=${rest%%+*}; rest=${rest#*+}; X=${rest%%+*}; Y=${rest#*+}
  cx=$((X + W/2))
  side=$(awk "BEGIN{printf \"%d\", $H*0.78}")
  [ $side -gt 566 ] && side=566
  cl=$((cx - side/2)); [ $cl -lt 0 ] && cl=0; maxc=$((800-side)); [ $cl -gt $maxc ] && cl=$maxc
  pad=$(awk "BEGIN{printf \"%d\", $side*0.08}")
  ct=$((Y-pad)); [ $ct -lt 0 ] && ct=0; maxt=$((566-side)); [ $maxt -lt 0 ] && maxt=0; [ $ct -gt $maxt ] && ct=$maxt
  magick "$RAW/$sdh.png" -crop ${side}x${side}+${cl}+${ct} +repage \
    -resize 320x320 -background none -gravity center -extent 320x320 \
    -define webp:method=6 -define webp:alpha-quality=92 -quality 82 \
    "$OUT/$dash.webp"
  n=$((n+1))
done < "$BASE/map.tsv"
echo "Built $n webp files"
echo "Total size:"; du -sh "$OUT"
echo "Size distribution (KB):"; ls -l "$OUT"/*.webp | awk '{s+=$5; if($5>max){max=$5;mf=$9}} END{printf "  avg=%.1fKB  max=%.1fKB (%s)\n", s/NR/1024, max/1024, mf}'
