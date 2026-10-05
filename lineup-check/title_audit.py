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
from datetime import date, timedelta
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
    "WWE Women's Tag Team Title": "List of WWE Women's Tag Team Champions",
}


# A list's name for a champion -> the name our cards use, where the two differ
# and the alias map does not join them.
ALIASES = {"Hollywood Hulk Hogan": "Hulk Hogan", "Chavo Classic": "Chavo Guerrero Classic",
           "Shane Helms": "Gregory Helms",
           # He won the interim title masked and unmasked a week later; our
           # roster knows him only as Santos Escobar.
           "El Hijo del Fantasma/Santos Escobar": "Santos Escobar"}


def _plain(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def align(a, b, same):
    """difflib-style opcodes for two sequences under a match predicate (the
    longest common subsequence, then the gaps between)."""
    n, m = len(a), len(b)
    L = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            L[i][j] = L[i + 1][j + 1] + 1 if same(a[i], b[j]) else max(L[i + 1][j], L[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if same(a[i], b[j]) and L[i][j] == L[i + 1][j + 1] + 1:
            pairs.append((i, j)); i += 1; j += 1
        elif L[i + 1][j] >= L[i][j + 1]:
            i += 1
        else:
            j += 1
    ops, pi, pj = [], 0, 0
    for i, j in pairs + [(n, m)]:
        if pi < i or pj < j:
            ops.append(("replace" if pi < i and pj < j else "delete" if pi < i else "insert", pi, i, pj, j))
        if (i, j) != (n, m):
            ops.append(("equal", i, i + 1, j, j + 1))
        pi, pj = i + 1, j + 1
    return ops


def main():
    from src.build_update import load_existing
    from src.title_lineages import LINEAGES
    from lineup_match import match_strength
    data = load_existing()
    slug = {_plain(k): v for k, v in data["wrestlers_by_name"].items()}
    tr = data["title_reigns"]

    def key(name):
        # A list writes a reign under its later name too ("Johnny Nitro/John
        # Morrison"); we name a reign as it was won.
        name = ALIASES.get(name, name).split("/")[0]
        name = re.sub(r"^The ", "", name or "")
        # Initials are spaced on one side and run together on the other
        # ("T. J. Perkins", "TJ Perkins").
        name = re.sub(r"\b([A-Z])\. ?(?=[A-Z]\.)", r"\1", name)
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
        rows = [r for r in wiki_reigns(fetch(page)["text"]) if r["champion"]]
        # From the reign in force when our history starts. A first reign we
        # found already running is dated from the first match we have, often
        # the night it ends, and a list dates a taped change days before we
        # air it, so the reign in force is the one won a week or more earlier.
        start = lo
        if ours[0].get("pre_corpus"):
            start = (date.fromisoformat(lo) - timedelta(days=7)).isoformat()
            first = max([i for i, r in enumerate(rows) if r["date"] <= start] or [0])
        else:
            # A belt born inside the corpus starts at its first reign, not at
            # the last of its first night (the 24/7 title changed hands three
            # times on 2019-05-20).
            first = min([i for i, r in enumerate(rows)
                         if r["date"] >= (date.fromisoformat(lo) - timedelta(days=14)).isoformat()] or [0])
        wiki = [r for r in rows[first:] if r["date"] <= hi]
        if not wiki:
            print(f"## {name}: no parsable reigns on {page}")
            continue
        if "Tag" in name:
            # Teams compare by members: two shared, or all of a smaller side.
            a = [frozenset(key(n) for n in r["champion_names"]) for r in ours]
            b = [frozenset(key(n) for n in (r["members"] or [r["champion"]])) for r in wiki]
            ops = align(a, b, lambda x, y: len(x & y) >= min(2, len(x), len(y)))
        else:
            # A team can hold a singles belt (The Revival shared the 24/7
            # title in 2019); then both sides compare by the pair.
            a = [key(r["champion_names"][0]) if len(r["champion_names"]) == 1
                 else tuple(sorted(key(n) for n in r["champion_names"])) for r in ours]
            b = [tuple(sorted(key(n) for n in r["members"])) if len(r["members"]) > 1 and "/" not in r["champion"]
                 else key(r["champion"]) for r in wiki]
            ops = difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
        diffs = [op for op in ops if op[0] != "equal"]
        print(f"## {name}: ours {len(ours)} reigns, Wikipedia {len(wiki)} in {lo}..{hi}, "
              f"{sum(op[2]-op[1] for op in ops if op[0]=='equal')} matched, "
              f"{len(diffs)} differences")
        for tag, i1, i2, j1, j2 in diffs:
            print(f"   {tag:7} ours {[(ours[k]['start'], ', '.join(ours[k]['champion_names'])) for k in range(i1, i2)]}")
            print(f"           wiki {[(wiki[k]['date'], ' & '.join(wiki[k]['members']) if 'Tag' in name else wiki[k]['champion'], wiki[k]['event'][:20]) for k in range(j1, j2)]}")


if __name__ == "__main__":
    main()
