#!/usr/bin/env bash
# Fetch the headshots the identity merge left without one, trying every ring
# name the wrestler used rather than only their canonical slug.
#
# Usage:  bash roster-img/_pipeline/sdh-fetch-aliases.sh
#
# Why this exists alongside sdh-fetch.sh: that script derives its targets from
# SLUGS.tsv (top-N by match count) and only ever asks SDH for the canonical
# slug. Both assumptions broke on split identities. Humberto Carrillo's 98
# matches were split three ways (Berto 31, Humberto Carrillo 31, Humberto 23),
# which pushed every fragment below the top-500 cutoff, so he was never
# attempted, even though SDH has him. And a wrestler SDH files under an old
# name (Chad Gable as "Shorty G") is a 404 under the canonical slug.
#
# So: targets come from cagematch-pipeline/out/needs_fetch.tsv, and candidates
# come from that worker's alias list in wrestler_identity.json. Those aliases
# are already guarded to names no other wrestler used, so a candidate can never
# pull down a different person's face.
#
# Misses go to alias-misses.tsv. Feed them to sdh-fetch-page.sh, which asks the
# wrestler's page for the image URL rather than guessing the filename.
#
# Cagematch is NOT a fallback for headshots, despite supplying the worker ids
# that drive this list. Its public worker pages carry no portrait at all: the
# overview, the ?gimmick= page, and the page=22 tab were each scraped and every
# one has zero non-chrome images. The "Images History" gallery is not in the
# public HTML.
#
# Same spec as sdh-fetch.sh: alpha bounding box -> square crop -> 320x320 webp,
# ~1 req/sec with backoff, atomic move so an interrupt cannot leave a truncated
# webp that the skip-if-exists check would treat as done forever.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1            # repo root
PIPE="roster-img/_pipeline"
B="https://www.thesmackdownhotel.com/images/wrestling/wrestlers/full-body"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FET="$PIPE/sdh-fetched.tsv"; MISSES="$PIPE/alias-misses.tsv"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# Target list: slug <TAB> matches <TAB> comma-separated candidate slugs.
# A generator failure must abort, not silently process zero targets and then
# clobber the worklist.
if ! python3 - > "$WORK/targets.tsv" <<'PY'
import json, re, sys
ident = json.load(open('cagematch-pipeline/out/wrestler_identity.json'))
def slugify(n):
    x = n.lower(); x = re.sub(r'[^a-z0-9\s-]', '', x)
    return re.sub(r'[\s-]+', '-', x).strip('-') or 'unknown'
rows = [l.rstrip('\n').split('\t') for l in open('cagematch-pipeline/out/needs_fetch.tsv')
        if l.strip() and not l.startswith('#')]
if not rows:
    sys.exit("no targets in needs_fetch.tsv")
out = []
for slug, name, m in rows:
    cands = [slug]
    for a in ident[slug]['aliases']:
        s = slugify(a)
        if s not in cands:
            cands.append(s)
    for c in list(cands):                       # mirrors candidates_for() in sdh-fetch.sh
        for v in ([c[4:]] if c.startswith('the-') else ['the-' + c]) + \
                 ([c[:-3]] if c.endswith(('-jr', '-sr')) else []):
            if v not in cands:
                cands.append(v)
    out.append((int(m), slug, cands))
out.sort(reverse=True)
for m, slug, cands in out:
    print(f"{slug}\t{m}\t{','.join(cands)}")
PY
then
  echo "FATAL: could not build target list" >&2; exit 1
fi
TOTAL=$(wc -l < "$WORK/targets.tsv" | tr -d ' ')
echo "targets: $TOTAL"

crop_one(){ local src="$1" out="$2" CW CH bb W rest H X Y cx side cl maxc pad ct maxt
  read CW CH < <(magick identify -format "%w %h\n" "${src}[0]" 2>/dev/null); [ -z "${CW:-}" ] && return 1
  bb=$(magick "$src" -alpha extract -threshold 25% -format "%@" info: 2>/dev/null); [ -z "$bb" ] && return 1
  W=${bb%%x*}; rest=${bb#*x}; H=${rest%%+*}; rest=${rest#*+}; X=${rest%%+*}; Y=${rest#*+}; [ -z "${H:-}" ] && return 1
  cx=$((X + W/2)); side=$(awk "BEGIN{printf \"%d\",$H*0.78}"); [ "$side" -gt "$CH" ] && side=$CH; [ "$side" -lt 1 ] && return 1
  cl=$((cx - side/2)); [ $cl -lt 0 ] && cl=0; maxc=$((CW-side)); [ $maxc -lt 0 ] && maxc=0; [ $cl -gt $maxc ] && cl=$maxc
  pad=$(awk "BEGIN{printf \"%d\",$side*0.08}"); ct=$((Y-pad)); [ $ct -lt 0 ] && ct=0; maxt=$((CH-side)); [ $maxt -lt 0 ] && maxt=0; [ $ct -gt $maxt ] && ct=$maxt
  magick "$src" -crop ${side}x${side}+${cl}+${ct} +repage -resize 320x320 -background none -gravity center -extent 320x320 \
    -define webp:method=6 -define webp:alpha-quality=92 -quality 82 "$out"; }

hits=0; misses=0; i=0; : > "$WORK/miss.tsv"
while IFS=$'\t' read -r slug mc cands; do
  [ -z "$slug" ] && continue; i=$((i+1))
  [ -f "roster-img/$slug.webp" ] && { echo "[$i/$TOTAL] skip $slug (already present)"; continue; }
  attempt=0; got=""; outcome=""
  while :; do
    throttled=0
    while IFS= read -r cand; do
      [ -z "$cand" ] && continue
      code=$(curl -s -o "$WORK/$slug.png" -w "%{http_code} %{content_type}" -A "$UA" \
             -H "Referer: https://www.thesmackdownhotel.com/" --max-time 25 "$B/$cand.png")
      rc=$?
      sleep 1                                   # pace EVERY request, not every slug
      if [ "$rc" -ne 0 ]; then throttled=1; break; fi      # truncated body behind a 200
      [[ "$code" == 200\ image/* ]] && { got="$cand"; break; }
      [[ "${code%% *}" == 404 ]] && continue
      throttled=1; break
    done < <(printf '%s\n' "$cands" | tr ',' '\n')
    [ -n "$got" ] && { outcome=hit; break; }
    if [ "$throttled" -eq 1 ]; then attempt=$((attempt+1)); [ "$attempt" -gt 5 ] && { outcome=throttle; break; }
      bo=$((15*attempt)); echo "[$i/$TOTAL] throttled $slug, backoff ${bo}s"; sleep "$bo"; continue; fi
    outcome=miss; break
  done
  if [ "$outcome" = hit ] && crop_one "$WORK/$slug.png" "$WORK/$slug.webp"; then
    mv "$WORK/$slug.webp" "roster-img/$slug.webp"
    printf '%s\t%s\n' "$slug" "$got" >> "$FET"; hits=$((hits+1)); echo "[$i/$TOTAL] HIT $slug <= $got"
  else
    reason="$outcome"; [ "$outcome" = hit ] && reason=crop-fail
    printf '%s\t%s\t%s\n' "$slug" "$mc" "$reason" >> "$WORK/miss.tsv"
    misses=$((misses+1)); echo "[$i/$TOTAL] miss $slug ($reason)"
  fi
done < "$WORK/targets.tsv"

if [ "$TOTAL" -gt 0 ]; then
  { echo "# SDH has no full-body image under any known ring name. slug<TAB>matches<TAB>reason"
    echo "# -> retry with sdh-fetch-page.sh, which resolves the URL from the wrestler page"
    sort -t$'\t' -k2 -nr "$WORK/miss.tsv"; } > "$MISSES"
else
  echo "no targets processed: leaving $MISSES untouched"
fi
echo "DONE  HITS:$hits  MISSES:$misses  -> $MISSES"
