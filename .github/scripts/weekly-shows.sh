#!/usr/bin/env bash
# Weekly show update, run by .github/workflows/weekly-shows.yml on Tuesday and
# Saturday mornings, after Raw and SmackDown have aired.
#
#   1. src/add_new_shows.py adds the shows that aired since the newest one on
#      file. If its ship gate blocks (a source failed, a show is missing), the
#      job fails, GitHub emails the failure, and nothing is pushed.
#   2. lineup-check/offshow_titles.py refreshes title changes on shows we do
#      not carry (NXT TV, pre-shows, specials) from fresh histories. Optional:
#      if a source refuses the runner, the pull request says so.
#   3. lineup-check/title_audit.py checks every belt against Wikipedia, and
#      anything that differs goes in the pull request for a person to rule on.
#   4. One pull request, branch data/weekly-shows. A run while the last one is
#      still open builds on it instead of opening a second. Nothing reaches the
#      live site until a person merges it.
#
# Locally, without a branch, push or pull request:
#     DRY_RUN=1 PYTHON="uv run --with requests --with beautifulsoup4 python" .github/scripts/weekly-shows.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

BRANCH=data/weekly-shows
PY=${PYTHON:-python3}
DRY=${DRY_RUN:-0}
OUT=$(mktemp -d)

pr=""
if [ "$DRY" != 1 ]; then
  pr=$(gh pr list --head "$BRANCH" --state open --json number -q '.[0].number' || true)
  if [ -n "$pr" ]; then
    git fetch origin "$BRANCH"
    git checkout -B "$BRANCH" "origin/$BRANCH"
  else
    git checkout -B "$BRANCH"
  fi
fi

# 1. New shows
cp index.html "$OUT/before.html"
$PY src/add_new_shows.py --summary "$OUT/shows.md" | tee "$OUT/add.log"
if grep -q "^Nothing new to add" "$OUT/add.log"; then
  echo "No new shows since the newest one on file."
  exit 0
fi

# 2. Off-show title changes, from histories fetched fresh this run. The cache
#    files are gitignored; on a runner they do not exist, locally they would
#    hold last week's copies.
rm -f lineup-check/wiki-cache/api_List_of_*Champion*.json lineup-check/wiki-cache/api_*Championship.json \
      lineup-check/wiki-cache/wt_* lineup-check/wwe-cache/titlehistory_*
offshow_note="Off-show title changes: none new."
if $PY lineup-check/offshow_titles.py > "$OUT/offshow.log" 2>&1; then
  if ! git diff --quiet -- data/offshow-title-changes.json; then
    $PY -m src.rebuild_indexes > "$OUT/rebuild.log"
    $PY cagematch-pipeline/fill_belts.py > /dev/null
    $PY cagematch-pipeline/fill_titles.py > "$OUT/titles.log"
    offshow_note="Off-show title changes: refreshed from Wikipedia, wrestling-titles.com and WWE.com (see data/offshow-title-changes.json in the diff)."
    # The summary's title changes and titles-page lines were written before
    # this refresh; rewrite both from the finished build.
    $PY - "$OUT" <<'PYEOF'
import re, sys
from pathlib import Path
from src.build_update import _inline_bundle
from src.add_new_shows import title_changes
out = Path(sys.argv[1])
before, after = _inline_bundle(out / "before.html"), _inline_bundle(Path("index.html"))
newest = max(e["air_date"] for e in before["events"].values() if e.get("air_date"))
changes = title_changes(before, after, newest)
board = [ln.strip() for ln in (out / "titles.log").read_text().splitlines()
         if ln.strip().startswith(("newer champion", "holders:")) or "keep the snapshot holder" in ln]
text = (out / "shows.md").read_text()
block = lambda head, lines: head + "\n" + "".join(f"- {x}\n" for x in lines)
text = re.sub(r"(No title changes on these shows\.|Title changes on these shows:\n(?:- .*\n)*)",
              lambda m: block("Title changes on these shows:", changes) if changes else "No title changes on these shows.",
              text, count=1)
text = re.sub(r"Titles page:\n(?:- .*\n)*", lambda m: block("Titles page:", board), text, count=1)
(out / "shows.md").write_text(text)
PYEOF
  fi
else
  offshow_note="Off-show title changes: the refresh failed (see the run log), so a change on a show we do not carry may be missing."
fi

# 3. Title audit. A belt that matches its Wikipedia list prints one line with
#    "0 differences, 0 off by date"; everything else is for review.
$PY lineup-check/title_audit.py > "$OUT/audit.log" 2>&1 || true
grep -v "0 differences, 0 off by date" "$OUT/audit.log" > "$OUT/audit-diff.log" || true
clean=$(grep -c "0 differences, 0 off by date" "$OUT/audit.log" || true)

head=$(head -n 1 "$OUT/shows.md")                      # "Adds N shows that aired A to B: ..."
n=$(sed -E 's/^Adds ([0-9]+) shows.*/\1/' <<<"$head")
span=$(sed -E 's/.*aired ([0-9-]+ to [0-9-]+).*/\1/' <<<"$head")
title="data: Add $n shows that aired $span"

{
  cat "$OUT/shows.md"
  echo
  echo "$offshow_note"
  echo
  echo "Title audit: $clean belts match Wikipedia reign for reign. Differences to review"
  echo "(the Hardcore 2002 house shows, the 24/7 order on 2019-12-29 and CM Punk's 2025"
  echo "World Heavyweight date are known, see lineup-check/README.md):"
  echo
  sed 's/^/    /' "$OUT/audit-diff.log"
} > "$OUT/body.md"

if [ "$DRY" = 1 ]; then
  echo
  echo "=== DRY RUN: would commit \"$title\" and open or extend a pull request with ==="
  cat "$OUT/body.md"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add index.html dist shards sw.js data
git commit -q -F - <<EOF
$title

$(cat "$OUT/body.md")
EOF
git push -f origin "$BRANCH"

if [ -n "$pr" ]; then
  gh pr comment "$pr" --body-file "$OUT/body.md"
else
  gh pr create --head "$BRANCH" --base main --title "data: Add the shows that aired since the last update" \
    --body-file "$OUT/body.md"
fi
