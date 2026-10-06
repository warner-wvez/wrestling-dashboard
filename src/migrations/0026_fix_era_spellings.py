"""
Spell wrestlers the way their own era billed them.

Found by listing every wrestler whose name appears two ways in one month (216
wrestler-months as of 2026-10-06) and reading each pair. Most are real billing
and stay as they are: Big Show and The Big Show, Seth "Freakin" Rollins, Little
Guido to Nunzio, Bobby Roode to Robert Roode in April 2019, Santina Marella.
These are typos or another era's spelling:

  Buh Buh Ray Dudley (8, Jan-Feb 2001)   billed Bubba Ray Dudley from 1999
  Rey Mysterio Jr (6, 2002-2005)         billed Rey Mysterio in WWE from 2002
  Rhino (2, Feb-Mar 2001)                WWF spelled him Rhyno
  "Stone Cold" Steve Austin, Stone Cold Steve Austin (4)
                                         the corpus names him Steve Austin
  Dominick, Domink Mysterio, Domink Misteryo (6)   Dominik Mysterio
  Veer Mahan (1)                         Veer Mahaan

The lineup, the side's name and the stored text all change, as in migration
0016, since migration 0005 reads a match's sides back out of its text. Raw
2002-08-15's tag (match 525) keeps "Rey Mysterio Jr": migration 0017's ruling
on that match names him so and checks its text, and the two Rhyno matches of
2001 keep their text, which migration 0004 checks.

Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0026_fix_era_spellings.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

SPELLINGS = {
    "Buh Buh Ray Dudley": "Bubba Ray Dudley",
    "Rey Mysterio Jr": "Rey Mysterio",
    "Rhino": "Rhyno",
    '"Stone Cold" Steve Austin': "Steve Austin",
    "Stone Cold Steve Austin": "Steve Austin",
    "Dominick Mysterio": "Dominik Mysterio",
    "Domink Mysterio": "Dominik Mysterio",
    "Domink Misteryo": "Dominik Mysterio",
    "Veer Mahan": "Veer Mahaan",
}
PINNED = {525}          # migration 0017's ruling names "Rey Mysterio Jr" on this match
TEXT_KEPT = {994, 1005}  # migration 0004 checks these two matches' text ("Rhino defeats ...")
# A spelling inside a name or the text, never part of a longer word.
_IN_NAME = {k: re.compile(r"(?<![\w.\"])" + re.escape(k) + (r"\.?" if k.endswith(" Jr") else "") + r"(?![\w])")
            for k in SPELLINGS}


def fix(m):
    changed = False
    for t in m["teams"]:
        new = [SPELLINGS.get(p, p) for p in t["participants"]]
        if new != t["participants"]:
            t["participants"], changed = new, True
            for bad, good in SPELLINGS.items():
                if t.get("team_name"):
                    t["team_name"] = _IN_NAME[bad].sub(good, t["team_name"])
    if changed and m["id"] not in TEXT_KEPT:
        for bad, good in SPELLINGS.items():
            m["raw_description"] = _IN_NAME[bad].sub(good, m.get("raw_description") or "")
    return changed


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    hits = [m for e in data["events"].values() for m in e["matches"] if m["id"] not in PINNED
            and any(p in SPELLINGS for t in m["teams"] for p in t["participants"])]
    if not hits:
        print("already applied")
        return
    slots = sum(1 for m in hits for t in m["teams"] for p in t["participants"] if p in SPELLINGS)
    print(f"matches {len(hits)}, names respelled {slots}")
    if dry:
        print("dry run: nothing written")
        return
    for m in hits:
        fix(m)
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
