#!/usr/bin/env python3
"""Lay each title's reign chain beside its Wikipedia title history.

Reads the shipped bundle's title_reigns and the Wikipedia lists named in
src/title_lineages.py (plus the word-keyed titles in EXTRA), and prints, per
title, every stretch where the two sequences of champions differ. Names are
compared through the dashboard's own alias map, so a ring-name change is not a
difference. Dates are shown, not compared: we date a taped change by its air
date, Wikipedia by its taping date.

    uv run --with requests --with beautifulsoup4 lineup-check/title_audit.py [title name ...]
"""
import difflib
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from wiki_titles import fetch, reigns as wiki_reigns  # noqa: E402

# Titles keyed by words (not in the lineage map) and their lists.
EXTRA = {
    "WWE Intercontinental Title": "List of WWE Intercontinental Champions",
    "WWE United States Title": "List of WWE United States Champions",
    "WWF European Title": "List of WWE European Champions",
    "ECW World Heavyweight Title": "List of ECW World Heavyweight Champions",
    "WWE 24/7 Title": "List of WWE 24/7 Champions",
    "WWF Hardcore Title": "List of WWE Hardcore Champions",
}


def _plain(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def main():
    from src.build_update import load_existing
    from src.title_lineages import LINEAGES
    from lineup_match import match_strength
    data = load_existing()
    slug = {_plain(k): v for k, v in data["wrestlers_by_name"].items()}
    tr = data["title_reigns"]

    def key(name):
        name = re.sub(r"^The ", "", name or "")
        return slug.get(_plain(name)) or slug.get(_plain("The " + name)) or _plain(name)

    pairs = [(lin["name"], lin["wiki_list"]) for lin in LINEAGES] + list(EXTRA.items())
    only = set(sys.argv[1:])
    for name, page in pairs:
        if only and name not in only:
            continue
        ours = tr.get(name) or []
        if not ours:
            continue
        lo, hi = ours[0]["start"], max(r["end"] or r["start"] for r in ours)
        wiki = [r for r in wiki_reigns(fetch(page)["text"]) if lo <= r["date"] <= hi and r["champion"]]
        if not wiki:
            print(f"## {name}: no parsable reigns on {page}")
            continue
        a = [key(" & ".join(r["champion_names"])) if len(r["champion_names"]) == 1 else
             "+".join(sorted(key(n) for n in r["champion_names"])) for r in ours]
        b = [key(r["champion"]) for r in wiki]
        sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        diffs = [op for op in sm.get_opcodes() if op[0] != "equal"]
        print(f"## {name}: ours {len(ours)} reigns, Wikipedia {len(wiki)} in {lo}..{hi}, "
              f"{sum(1 for op in sm.get_opcodes() if op[0]=='equal' for _ in range(op[2]-op[1]))} matched, "
              f"{len(diffs)} differences")
        for tag, i1, i2, j1, j2 in diffs:
            print(f"   {tag:7} ours {[(ours[k]['start'], ', '.join(ours[k]['champion_names'])) for k in range(i1, i2)]}")
            print(f"           wiki {[(wiki[k]['date'], wiki[k]['champion'], wiki[k]['event'][:20]) for k in range(j1, j2)]}")


if __name__ == "__main__":
    main()
