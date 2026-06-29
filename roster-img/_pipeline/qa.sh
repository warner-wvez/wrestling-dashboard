#!/usr/bin/env bash
# Flag headshots that may be off-style (sprite / blank / tiny figure) without
# eyeballing every file. This is how the lone pixel-art sprite (gunther) was
# caught: it was 2.2KB and only 19% opaque while real renders are 8-16KB and
# fill most of the frame. Run after any batch of additions.
#
# Usage:  bash roster-img/_pipeline/qa.sh [slug-list-file]
#   no arg -> checks every webp in roster-img/.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
if [ "${1:-}" ] && [ -f "$1" ]; then SLUGS=$(cat "$1"); else SLUGS=$(ls roster-img/*.webp | xargs -n1 basename | sed 's/\.webp$//'); fi
echo "slug | bytes | opaque_frac | std   (FLAG if opaque<0.22 or bytes<3500 or std<0.12)"
flagged=0; n=0
while read -r s; do
  [ -z "$s" ] && continue; f="roster-img/$s.webp"; [ -f "$f" ] || continue; n=$((n+1))
  bytes=$(stat -f%z "$f")
  of=$(magick "$f" -alpha extract -format "%[fx:mean]" info: 2>/dev/null)
  st=$(magick "$f" -alpha off -format "%[fx:standard_deviation]" info: 2>/dev/null)
  if awk "BEGIN{exit !($of<0.22 || $bytes<3500 || $st<0.12)}"; then
    flagged=$((flagged+1)); printf '%-26s %7d  %0.3f  %0.3f  <<< FLAG\n' "$s" "$bytes" "$of" "$st"; fi
done <<< "$SLUGS"
echo "checked $n, flagged $flagged"