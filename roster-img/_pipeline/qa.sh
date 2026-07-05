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
if [ -n "${1:-}" ]; then
  # A typo'd list path must error, not silently degrade to a full scan that
  # reads as "your new batch is clean".
  [ -f "$1" ] || { echo "FATAL: slug list not found: $1" >&2; exit 1; }
  SLUGS=$(cat "$1")
else
  SLUGS=$(for f in roster-img/*.webp; do b="${f##*/}"; printf '%s\n' "${b%.webp}"; done)
fi
echo "slug | bytes | opaque_frac | std   (FLAG if opaque<0.22 or bytes<3500 or std<0.12, or unreadable)"
flagged=0; n=0
while read -r s; do
  [ -z "$s" ] && continue; f="roster-img/$s.webp"; [ -f "$f" ] || continue; n=$((n+1))
  bytes=$(wc -c < "$f" | tr -d ' ')
  of=$(magick "$f" -alpha extract -format "%[fx:mean]" info: 2>/dev/null) || of=""
  st=$(magick "$f" -alpha off -format "%[fx:standard_deviation]" info: 2>/dev/null) || st=""
  # A file magick can't read (zero-byte, truncated) is exactly what this QA
  # exists to catch: flag it instead of passing it via an awk syntax error.
  if [ -z "$of" ] || [ -z "$st" ]; then
    flagged=$((flagged+1)); printf '%-26s %7d  UNREADABLE  <<< FLAG\n' "$s" "$bytes"; continue
  fi
  if awk -v of="$of" -v bytes="$bytes" -v st="$st" 'BEGIN{exit !(of<0.22 || bytes<3500 || st<0.12)}'; then
    flagged=$((flagged+1)); printf '%-26s %7d  %0.3f  %0.3f  <<< FLAG\n' "$s" "$bytes" "$of" "$st"; fi
done <<< "$SLUGS"
echo "checked $n, flagged $flagged"
