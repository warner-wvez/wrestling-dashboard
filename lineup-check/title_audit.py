#!/usr/bin/env python3
"""Lay each title's reign chain beside its Wikipedia title history.

Reads the shipped bundle's title_reigns and the Wikipedia lists named in
src/title_lineages.py (plus the word-keyed titles in EXTRA), and prints, per
title, every stretch where the two sequences of champions differ. Names are
compared through the dashboard's own alias map, so a ring-name change is not a
difference.

Then the dates: each reign the two lists share must start within a week of
Wikipedia's date, or of WWE.com's where WWE.com gives one (we date a taped
change by its air date, as WWE.com does; Wikipedia dates it by the taping).
A reign that starts later is one won on a show or pre-show we don't carry,
picked up at the champion's next match on a card of ours.

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
from offshow_titles import BELTS as OFFSHOW_BELTS, same as same_reign, wwe_com  # noqa: E402

# Titles keyed by words (not in the lineage map) and their lists.
EXTRA = {
    "WWE Intercontinental Title": "List of WWE Intercontinental Champions",
    "WWE United States Title": "List of WWE United States Champions",
    "WWF European Title": "List of WWE European Champions",
    "ECW World Heavyweight Title": "List of ECW World Heavyweight Champions",
    "WWE 24/7 Title": "List of WWE 24/7 Champions",
    "WWF Hardcore Title": "List of WWE Hardcore Champions",
    "WWE Women's Tag Team Title": "List of WWE Women's Tag Team Champions",
    "NXT Title": "List of NXT Champions",
    "NXT Women's Title": "List of NXT Women's Champions",
    "NXT North American Title": "List of NXT North American Champions",
    "WWE NXT Tag Team Title": "List of NXT Tag Team Champions",
    "NXT Women's Tag Team Title": "List of NXT Women's Tag Team Champions",
    "NXT Women's North American Title": "List of NXT Women's North American Champions",
}


# WWE.com's title history for each belt (cached in wwe-cache/), for its air
# dates. Its addresses keep the brand names a belt had in 2016: the Raw
# Women's page is today's WWE Women's Championship. No page was found for the
# 1956 Women's, WCW's or the 2023 World Heavyweight title.
WWE_COM = {
    "WWE Championship": "titlehistory/wwe-championship",
    "WWE Universal Championship": "titlehistory/universal-championship",
    "World Heavyweight Championship": "titlehistory/world-heavyweight-championship",
    "WWE Women's Championship": "titlehistory/raw-womens-championship",
    "WWE Women's World Championship": "titlehistory/smackdown-womens-championship",
    "WWE Divas Championship": "titlehistory/divas-championship",
    "World Tag Team Championship (1971-2010)": "titlehistory/world-tag-team-championship",
    "WWE World Tag Team Championship": "titlehistory/raw-tag-team-championship",
    "WWE Tag Team Championship": "titlehistory/smackdown-tag-team-championship",
    "WWE Cruiserweight Championship": "titlehistory/cruiserweight-championship",
    "WWE Intercontinental Title": "titlehistory/intercontinental-championship",
    "WWE United States Title": "titlehistory/united-states-championship",
    "WWF European Title": "titlehistory/european-championship",
    "ECW World Heavyweight Title": "titlehistory/ecw-championship",
    "WWE 24/7 Title": "classics/titlehistory/24-7-championship",
    "WWF Hardcore Title": "titlehistory/hardcore-championship",
    "WWE Women's Tag Team Title": "classics/titlehistory/wwe-womens-tag-team-championship",
    **{name: cfg["wwe"] for name, cfg in OFFSHOW_BELTS.items()},
}
SLACK = 7           # days a start may sit from the histories' date
AIRED_WITHIN = 35   # WWE.com's air date for a taped change (NXT taped a month ahead until 2019)


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def off_dates(ours, wiki, ops, aired):
    """Each reign both lists share whose start is more than SLACK days from
    Wikipedia's date and from every WWE.com air date for that change. Our
    first reign of a belt is dated from the first match we have, so it is
    skipped; a later reign the walk found already running (no title change on
    any card, so it starts at the champion's next match) is not."""
    out = []
    for tag, i1, i2, j1, j2 in ops:
        if tag != "equal":
            continue
        for o, w in zip(ours[i1:i2], wiki[j1:j2]):
            if (o is ours[0] and o.get("pre_corpus")) or abs(_days(w["date"], o["start"])) <= SLACK:
                continue
            # A list's team name ends in markup ("British Ambition<br />").
            named = {"champion": re.sub(r"<[^>]+>", " ", w["champion"]).strip(), "members": w["members"]}
            air = [e["date"] for e in aired
                   if same_reign(named, e) and 0 <= _days(w["date"], e["date"]) <= AIRED_WITHIN]
            if not any(abs(_days(a, o["start"])) <= SLACK for a in air):
                out.append((o, w, air))
    return out


# A list's name for a champion -> the name our cards use, where the two differ
# and the alias map does not join them.
ALIASES = {"Hollywood Hulk Hogan": "Hulk Hogan", "Chavo Classic": "Chavo Guerrero Classic",
           "Shane Helms": "Gregory Helms",
           # He won the interim title masked and unmasked a week later; our
           # roster knows him only as Santos Escobar.
           "El Hijo del Fantasma/Santos Escobar": "Santos Escobar",
           'Andrade "Cien" Almas': "Andrade Almas"}


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


def name_key(wrestlers_by_name):
    """A champion's name -> the dashboard profile it belongs to, so a list's
    "The Hurricane" and our "Hurricane Helms" are one man."""
    slug = {_plain(k): v for k, v in wrestlers_by_name.items()}

    def key(name):
        # A list writes a reign under its later name too ("Johnny Nitro/John
        # Morrison"); we name a reign as it was won.
        name = ALIASES.get(name, name).split("/")[0]
        name = re.sub(r"^The ", "", name or "")
        # Initials are spaced on one side and run together on the other
        # ("T. J. Perkins", "TJ Perkins").
        name = re.sub(r"\b([A-Z])\. ?(?=[A-Z]\.)", r"\1", name)
        return slug.get(_plain(name)) or slug.get(_plain("The " + name)) or _plain(name)
    return key


def main():
    from src.build_update import load_existing
    from src.title_lineages import LINEAGES
    from lineup_match import match_strength
    data = load_existing()
    tr = data["title_reigns"]
    key = name_key(data["wrestlers_by_name"])

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
            # times on 2019-05-20). We date a taped first reign by its air
            # date, up to five weeks after the list's taping date (Seth
            # Rollins won the first NXT title on 2012-07-26; it aired 08-29).
            first = min([i for i, r in enumerate(rows)
                         if r["date"] >= (date.fromisoformat(lo) - timedelta(days=35)).isoformat()] or [0])
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
        off = off_dates(ours, wiki, ops, wwe_com(WWE_COM[name]) if name in WWE_COM else [])
        print(f"## {name}: ours {len(ours)} reigns, Wikipedia {len(wiki)} in {lo}..{hi}, "
              f"{sum(op[2]-op[1] for op in ops if op[0]=='equal')} matched, "
              f"{len(diffs)} differences, {len(off)} off by date")
        for tag, i1, i2, j1, j2 in diffs:
            print(f"   {tag:7} ours {[(ours[k]['start'], ', '.join(ours[k]['champion_names'])) for k in range(i1, i2)]}")
            print(f"           wiki {[(wiki[k]['date'], ' & '.join(wiki[k]['members']) if 'Tag' in name else wiki[k]['champion'], wiki[k]['event'][:20]) for k in range(j1, j2)]}")
        for o, w, air in off:
            event = re.sub(r"<[^>]+>", "", w["event"]).strip()[:30]
            aired = f", aired {', '.join(air)}" if air else ""
            print(f"   date    ours {o['start']} {', '.join(o['champion_names'])}: "
                  f"{_days(w['date'], o['start']):+d} days from {w['date']} ({event}{aired})")


if __name__ == "__main__":
    main()
