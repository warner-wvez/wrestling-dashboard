#!/usr/bin/env bash
# Second-pass headshot fetch: resolve the image URL from the wrestler's SDH page
# instead of guessing the image filename.
#
# Usage:  bash roster-img/_pipeline/sdh-fetch-page.sh
#
# sdh-fetch.sh and sdh-fetch-aliases.sh both assume the render lives at
#   /images/wrestling/wrestlers/full-body/<slug>.png
# That is only true until SDH re-renders someone. Chad Gable's page is a 200 and
# his image is real, but the file is `chad-gable-2026.png`, so the guessed URL
# 404s and he reads as "SDH does not have him". He is not the exception: SDH
# year-stamps every refreshed render.
#
# So ask the page. `<meta property="og:image">` on /wrestlers/<slug> is exactly
# one URL and it is the full-body render, whatever it happens to be called.
# Two requests per wrestler instead of one, still paced at ~1 req/sec.
#
# Candidates come from the worker's alias list, which the identity resolver has
# already restricted to names no other wrestler used, so a candidate page can
# never yield a different person's face. The filename is checked against the
# candidate as a second guard: a page that somehow served an unrelated og:image
# is skipped rather than cropped and shipped.
#
# Same output spec as the other passes: alpha bbox -> square crop -> 320x320
# webp, atomic move.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
PIPE="roster-img/_pipeline"
SITE="https://www.thesmackdownhotel.com"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FET="$PIPE/sdh-page-fetched.tsv"; REMAIN="$PIPE/still-missing.tsv"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

# Targets: anything in needs_fetch.tsv that still has no webp. Recomputed rather
# than read from the previous pass's miss list, so the two passes compose and a
# re-run is always a no-op for whatever already landed.
if ! python3 - > "$WORK/targets.tsv" <<'PY'
import json, os, re, sys
ident = json.load(open('cagematch-pipeline/out/wrestler_identity.json'))
def slugify(n):
    x = n.lower(); x = re.sub(r'[^a-z0-9\s-]', '', x)
    return re.sub(r'[\s-]+', '-', x).strip('-') or 'unknown'
have = {f[:-5] for f in os.listdir('roster-img') if f.endswith('.webp')}
rows = [l.rstrip('\n').split('\t') for l in open('cagematch-pipeline/out/needs_fetch.tsv')
        if l.strip() and not l.startswith('#')]
if not rows:
    sys.exit("no targets in needs_fetch.tsv")
out = []
for slug, name, m in rows:
    if slug in have:
        continue
    cands = [slug] + [s for s in (slugify(a) for a in ident[slug]['aliases']) if s != slug]
    for c in list(cands):
        v = c[4:] if c.startswith('the-') else 'the-' + c
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
echo "still missing a headshot: $TOTAL"
[ "$TOTAL" -eq 0 ] && { echo "nothing to do"; exit 0; }

crop_one(){ local src="$1" out="$2" CW CH bb W rest H X Y cx side cl maxc pad ct maxt
  read CW CH < <(magick identify -format "%w %h\n" "${src}[0]" 2>/dev/null); [ -z "${CW:-}" ] && return 1
  bb=$(magick "$src" -alpha extract -threshold 25% -format "%@" info: 2>/dev/null); [ -z "$bb" ] && return 1
  W=${bb%%x*}; rest=${bb#*x}; H=${rest%%+*}; rest=${rest#*+}; X=${rest%%+*}; Y=${rest#*+}; [ -z "${H:-}" ] && return 1
  cx=$((X + W/2)); side=$(awk "BEGIN{printf \"%d\",$H*0.78}"); [ "$side" -gt "$CH" ] && side=$CH; [ "$side" -lt 1 ] && return 1
  cl=$((cx - side/2)); [ $cl -lt 0 ] && cl=0; maxc=$((CW-side)); [ $maxc -lt 0 ] && maxc=0; [ $cl -gt $maxc ] && cl=$maxc
  pad=$(awk "BEGIN{printf \"%d\",$side*0.08}"); ct=$((Y-pad)); [ $ct -lt 0 ] && ct=0; maxt=$((CH-side)); [ $maxt -lt 0 ] && maxt=0; [ $ct -gt $maxt ] && ct=$maxt
  magick "$src" -crop ${side}x${side}+${cl}+${ct} +repage -resize 320x320 -background none -gravity center -extent 320x320 \
    -define webp:method=6 -define webp:alpha-quality=92 -quality 82 "$out"; }

# Pull the full-body render URL out of a wrestler page. Empty output = no image.
og_image(){ grep -o '<meta property="og:image" content="[^"]*"' "$1" 2>/dev/null \
  | head -1 | sed 's/.*content="//; s/"$//' | grep '/full-body/' || true; }

# The wrestler this page is about, as lowercase alnum tokens. SDH's <title> is
# "Ashante Adonis: Profile, Career Stats, ... | Pro Wrestlers Database".
page_name_tokens(){ grep -o '<title>[^<]*' "$1" 2>/dev/null | head -1 \
  | sed 's/<title>//; s/:.*//' | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '\n' | grep -v '^$' || true; }

hits=0; misses=0; i=0; : > "$WORK/miss.tsv"
while IFS=$'\t' read -r slug mc cands; do
  [ -z "$slug" ] && continue; i=$((i+1))
  [ -f "roster-img/$slug.webp" ] && continue
  got=""; url=""
  while IFS= read -r cand; do
    [ -z "$cand" ] && continue
    # -L: SDH 301s an old ring name to the wrestler's current page
    # (/wrestlers/dominik-dijakovic -> the T-BAR page). Without following, every
    # renamed wrestler reads as "no page", which is exactly the population this
    # pass exists to serve.
    code=$(curl -sL -o "$WORK/page.html" -w "%{http_code}" -A "$UA" --max-time 25 "$SITE/wrestlers/$cand")
    sleep 1
    [ "$code" != "200" ] && continue
    url="$(og_image "$WORK/page.html")"
    [ -z "$url" ] && continue
    # Guard: the page must be ABOUT one of this wrestler's ring names. Check the
    # title, not the filename: SDH's filenames do not track their slugs
    # (`dominik-dijak.png`, the misspelled `ashtante-adonis.png`,
    # `tyler-taylor-rust.png`), so a filename check rejects correct images. A
    # candidate matches when every token of its name appears in the title, which
    # tolerates the extra token in "Tyler / Taylor Rust". Those names are already
    # restricted to ones no other wrestler used, so a title match is conclusive.
    base="$(basename "$url")"
    page_name_tokens "$WORK/page.html" | sort -u > "$WORK/title.txt"
    ok=0
    while IFS= read -r c2; do
      [ -z "$c2" ] && continue
      miss=0
      for tok in $(printf '%s\n' "$c2" | tr '-' ' '); do
        grep -qx "$tok" "$WORK/title.txt" || { miss=1; break; }
      done
      [ "$miss" -eq 0 ] && { ok=1; break; }
    done < <(printf '%s\n' "$cands" | tr ',' '\n')
    [ "$ok" -eq 0 ] && { echo "[$i/$TOTAL] skip $slug: page $cand titled '$(tr '\n' ' ' < "$WORK/title.txt")' served $base"; url=""; continue; }
    icode=$(curl -s -o "$WORK/$slug.png" -w "%{http_code} %{content_type}" -A "$UA" -H "Referer: $SITE/" --max-time 30 "$url")
    sleep 1
    [[ "$icode" == 200\ image/* ]] && { got="$cand"; break; }
    url=""
  done < <(printf '%s\n' "$cands" | tr ',' '\n')

  if [ -n "$got" ] && crop_one "$WORK/$slug.png" "$WORK/$slug.webp"; then
    mv "$WORK/$slug.webp" "roster-img/$slug.webp"
    printf '%s\t%s\t%s\n' "$slug" "$got" "$(basename "$url")" >> "$FET"
    hits=$((hits+1)); echo "[$i/$TOTAL] HIT $slug <= $(basename "$url")"
  else
    reason=no-page; [ -n "$got" ] && reason=crop-fail
    printf '%s\t%s\t%s\n' "$slug" "$mc" "$reason" >> "$WORK/miss.tsv"
    misses=$((misses+1)); echo "[$i/$TOTAL] miss $slug ($reason)"
  fi
done < "$WORK/targets.tsv"

{ echo "# no SDH page or no render under any known ring name. slug<TAB>matches<TAB>reason"
  sort -t$'\t' -k2 -nr "$WORK/miss.tsv"; } > "$REMAIN"
echo "DONE  HITS:$hits  MISSES:$misses  -> $REMAIN"
