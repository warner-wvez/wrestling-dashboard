#!/usr/bin/env bash
# Photo/render -> pixel-art sprite, "pro" pipeline.
# Principles applied: flatten photo into regions (edge-preserving smoothing + posterize),
# punchy limited palette (saturation + contrast + few colors), crisp hard edges, clean outline.
# Usage: make_pro.sh <src> <slug> [size] [colors] [figh]
set -euo pipefail
SRC="$1"; SLUG="$2"; S="${3:-96}"; COLORS="${4:-16}"; FIGH="${5:-84}"
# Resolve a relative source path BEFORE cd'ing into the tool dir, or
# "make_pro.sh renders/foo.png foo" from the repo root resolves against
# sprite-tools/ and every step fails.
case "$SRC" in /*) ;; *) SRC="$PWD/$SRC" ;; esac
[ -f "$SRC" ] || { echo "FATAL: source image not found: $SRC" >&2; exit 1; }
cd "$(dirname "$0")"
mkdir -p pro final prev
ASE="$HOME/Applications/Aseprite/aseprite"
[ -x "$ASE" ] || { echo "FATAL: Aseprite not found at $ASE" >&2; exit 1; }
D="$PWD"

t="pro/${SLUG}"
# 1) Trim transparent border.
magick "$SRC" -trim +repage "${t}_trim.png"
# 2) Flatten COLOR into deliberate regions (alpha ignored): saturation up, punchy contrast,
#    edge-preserving smoothing to kill photo texture, posterize to band the tones.
magick "${t}_trim.png" -alpha off \
  -modulate 100,130 \
  -sigmoidal-contrast 4x50% \
  -kuwahara 4 \
  -posterize 5 \
  "${t}_color.png"
# 3) Hard silhouette from the original alpha (no soft halo).
magick "${t}_trim.png" -alpha extract -threshold 45% "${t}_mask.png"
# 4) Recombine, downscale to figure height, harden alpha again, lock to a tight palette.
magick "${t}_color.png" "${t}_mask.png" -compose CopyOpacity -composite \
  -filter Triangle -resize "x${FIGH}" \
  -channel A -threshold 50% +channel \
  -colors "${COLORS}" -dither None \
  "${t}_small.png"
# 5) Aseprite: pad to square + clean outline. Errors must surface, not vanish
#    into /dev/null while the script prints "done" anyway (stdout stays quiet,
#    stderr passes through, exit codes stop the run via set -e).
"$ASE" -b --script-param src="$D/${t}_small.png" --script-param out="$D/final/${SLUG}.png" --script-param size="$S" --script pad_outline.lua >/dev/null
[ -s "$D/final/${SLUG}.png" ] || { echo "FATAL: Aseprite produced no output for ${SLUG}" >&2; exit 1; }
# 6) Crisp 6x preview + webp.
"$ASE" -b "$D/final/${SLUG}.png" --scale 6 --save-as "$D/prev/${SLUG}.png" >/dev/null
cwebp -quiet "$D/final/${SLUG}.png" -o "$D/final/${SLUG}.webp"
echo "done ${SLUG}: $(sips -g pixelWidth -g pixelHeight "final/${SLUG}.png" 2>/dev/null | awk '/pixel/{print $2}' | tr '\n' 'x' | sed 's/x$//')"
