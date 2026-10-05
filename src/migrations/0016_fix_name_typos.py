"""
Correct misspelled wrestler names on the cards.

Each misspelling below appears once or twice in the corpus beside hundreds of
correct uses, and each made a wrestler of its own: a profile with one match,
and on Raw 2021-07-19 a Women's title reign for "Nikki A.H.S." instead of
Nikki A.S.H. Found by comparing every name with every other (spellings 80
percent alike or more that the alias map keeps apart), then read in context.
Names that only look alike were left alone: Chavo Guerrero Jr. and Sr., El
Local #1 and #2, and the local and one-off names (Brian Breaker, Matt Logan,
Fernando Vega, the Bryant Brothers, Bruto Americano).

The fix renames the name in the lineup, the side's name and the stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0016_fix_name_typos.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

TYPOS = {
    "Nikki A.H.S.": "Nikki A.S.H.",
    "Bobby Lashey": "Bobby Lashley", "Bobby Lashlay": "Bobby Lashley",
    "Chelsea Greeen": "Chelsea Green", "Chalsea Green": "Chelsea Green",
    "Stephane Vaquer": "Stephanie Vaquer",
    "Luke Galllows": "Luke Gallows",
    "Xavier Wooods": "Xavier Woods",
    "Cecric Alexander": "Cedric Alexander",
    "Charlotte Flari": "Charlotte Flair",
    "Angelo Dawking": "Angelo Dawkins",
    "Damien Priest": "Damian Priest",
    "Lyra Valkyrie": "Lyra Valkyria",
    "Bronson Redd": "Bronson Reed",
    "Robert Roods": "Robert Roode",
    "Murhpy": "Murphy",
    "Chad Gagle": "Chad Gable",
    "Naomo": "Naomi",
    "Zelina": "Zelina Vega",
}
# A short form that the right name starts with ("Zelina" in "Zelina Vega")
# must not match inside the right name.
_TEXT = {k: re.compile(r"(?<![\w.])" + re.escape(k) + r"(?![\w])" +
                       (r"(?!" + re.escape(v[len(k):]) + r")" if v.startswith(k) else ""))
         for k, v in TYPOS.items()}


def fix(m):
    changed = False
    for t in m["teams"]:
        new = [TYPOS.get(p, p) for p in t["participants"]]
        if new != t["participants"]:
            t["participants"], changed = new, True
            for bad, good in TYPOS.items():
                if t.get("team_name"):
                    t["team_name"] = _TEXT[bad].sub(good, t["team_name"])
    if changed:
        for bad, good in TYPOS.items():
            m["raw_description"] = _TEXT[bad].sub(good, m.get("raw_description") or "")
    return changed


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    hits = [m for e in data["events"].values() for m in e["matches"]
            if any(p in TYPOS for t in m["teams"] for p in t["participants"])]
    if not hits:
        print("already applied")
        return
    print(f"matches with a misspelled name: {len(hits)}")
    if dry:
        print("dry run: nothing written")
        return
    for m in hits:
        fix(m)
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
