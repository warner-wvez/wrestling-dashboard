"""
Fix match records the title audit found after vacancies went in.

Each fix below came from laying a title's reign chain beside its Wikipedia
title history (lineup-check/title_audit.py) and reading the match itself.

  Raw 2024-04-22, Women's World title (match 30390). Becky Lynch won a
    14-woman battle royal for the title Rhea Ripley had relinquished a week
    earlier (Wikipedia's List of Women's World Champions). The stored belt read
    "Women's World Championship 14-Woman Battle Royal: Winner", a string no
    lineage knows, so the reign was missing: the title sat vacant from Ripley
    to Liv Morgan. The belt string is set to the corpus's name for the title,
    and a ruling names Lynch the champion after the match.
  WrestleMania XL, the undisputed tag titles (match 33202). The six-pack ladder
    match was stored as two sides, A-Town Down Under over The Judgment Day, so
    both belts went to A-Town Down Under. The Awesome Truth won too: A-Town
    Down Under pulled down the SmackDown belts and The Awesome Truth the Raw
    belts (the stored text and both Wikipedia lists say so). All six teams go
    back, with one ruling per belt.
  The Freebird rule, where a ruling has to say who the champions are: the
    Spirit Squad's Johnny and Nicky defended the World tag titles on Raw
    2006-04-10 (8411), but Wikipedia lists one Spirit Squad reign under Kenny
    and Mikey; Big E won the SmackDown tag titles alone for The New Day on
    2020-04-17 (31013); and Layla and Michelle McCool shared the Women's title
    in 2010 (12428, 12603, 12706), which Wikipedia credits to Layla.
  Night of Champions 2009, the unified tag titles (11802). Edge was injured and
    Chris Jericho picked The Big Show as his new partner; WWE counts it as a
    new reign (Wikipedia), so a ruling names them.
  Two names: "The Awesome Truth (The Miz)" on Raw 2024-04-29 (30395) and
    "Rey" for Rey Mysterio on SmackDown 2021-06-04 (31276, 31280).
  Seven results stored as clean wins the text calls a DQ or count-out, from
    SmackDown 2002 and Raw 2001-02-12. On SmackDown 2002-05-09 The Hurricane
    beat Tajiri by count-out, so Tajiri kept the Cruiserweight title until the
    next week; the clean win had moved it. On Raw 2001-02-12 the winner was
    even flipped: "Eddie Guerrero defeats Chris Jericho (c) by DQ" was stored
    as a Jericho win. The side names lose the result text the source left in
    them ("Kurt Angle via count-out when Angle left ringside").

Safety gate: each match is found by match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0017_fix_title_audit_findings.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

WOMENS_WORLD = "https://en.wikipedia.org/wiki/List_of_Women%27s_World_Champions_(WWE)"
WORLD_TAG_1971 = "https://en.wikipedia.org/wiki/List_of_World_Tag_Team_Champions_(WWE,_1971%E2%80%932010)"
WORLD_TAG = "https://en.wikipedia.org/wiki/List_of_World_Tag_Team_Champions_(WWE)"
WWE_TAG = "https://en.wikipedia.org/wiki/List_of_WWE_Tag_Team_Champions"
WOMENS_1956 = "https://en.wikipedia.org/wiki/List_of_WWE_Women%27s_Champions_(1956%E2%80%932010)"


def becky(m):
    want = {"title": "Women's World Title", "champions": ["Becky Lynch"],
            "why": "won the battle royal for the vacant title", "source": WOMENS_WORLD}
    if m.get("title_at_stake") == "Women's World Title" and m.get("title_result") == want:
        return False
    m["title_at_stake"] = "Women's World Title"
    m["match_type"] = "Women's World Title Battle Royal"
    m["title_result"] = want
    return True


def ruling(title, champions, why, source):
    def apply(m):
        want = {"title": title, "champions": champions, "why": why, "source": source}
        if m.get("title_result") == want:
            return False
        m["title_result"] = want
        return True
    return apply


def _side(n, name, people, won, champ=False):
    return {"team_number": n, "team_name": name, "accompaniment": None, "was_winner": won,
            "match_outcome": "win" if won else "loss", "was_champion_entering": champ,
            "participants": people}


WM40_SIDES = [
    _side(1, "A-Town Down Under", ["Austin Theory", "Grayson Waller"], True),
    _side(2, "Awesome Truth", ["The Miz", "R-Truth"], True),
    _side(3, "The Judgment Day", ["Finn Bálor", "Damian Priest"], False, champ=True),
    _side(4, "#DIY", ["Johnny Gargano", "Tommaso Ciampa"], False),
    _side(5, "The New Day", ["Kofi Kingston", "Xavier Woods"], False),
    _side(6, "New Catch Republic", ["Pete Dunne", "Tyler Bate"], False),
]
WM40_RULINGS = [
    {"title": "World Tag Team Championship", "champions": ["The Miz", "R-Truth"],
     "why": "The Awesome Truth pulled down the Raw belts", "source": WORLD_TAG},
    {"title": "WWE Tag Team Championship", "champions": ["Austin Theory", "Grayson Waller"],
     "why": "A-Town Down Under pulled down the SmackDown belts", "source": WWE_TAG},
]


def wm40(m):
    if m.get("teams") == WM40_SIDES and m.get("title_result") == WM40_RULINGS:
        return False
    m["teams"] = [dict(t, participants=list(t["participants"])) for t in WM40_SIDES]
    m["title_result"] = WM40_RULINGS
    return True


def rename(bad, good, text_old=None, text_new=None):
    def apply(m):
        changed = False
        for t in m["teams"]:
            if bad in t["participants"]:
                t["participants"] = [good if p == bad else p for p in t["participants"]]
                changed = True
            if text_old and text_old in (t.get("team_name") or ""):
                t["team_name"] = t["team_name"].replace(text_old, text_new)
                changed = True
        if text_old and text_old in (m.get("raw_description") or ""):
            m["raw_description"] = m["raw_description"].replace(text_old, text_new)
            changed = True
        return changed
    return apply


def by(kind, winner, side_names):
    """A DQ or count-out result: the named side won it, and each side's name
    is what it should read (the source left the result text in it)."""
    def apply(m):
        changed = False
        for t, name in zip(m["teams"], side_names):
            won = t["participants"] == winner
            want = (won, f"{kind}-win" if won else f"{kind}-loss", name)
            if (t.get("was_winner"), t.get("match_outcome"), t.get("team_name")) != want:
                t["was_winner"], t["match_outcome"], t["team_name"] = want
                changed = True
        return changed
    return apply


FIXES = [
    # (match id, start of stored text (the same before and after the fix), fix)
    (30390, "Becky Lynch, Liv Morgan, Nia Jax", becky),
    (33202, "[[A-Town Down Under]] ([[Austin Theory]] and [[Grayson Waller]])", wm40),
    (8411, "The Spirit Squad ( Johnny & Nicky )",
     ruling("World Tag Team Title", ["Kenny", "Mikey"],
            "the Spirit Squad held the titles as one team under the Freebird rule; Wikipedia lists Kenny and Mikey",
            WORLD_TAG_1971)),
    (11802, "Chris Jericho & The Big Show (c) defeat Cody Rhodes & Ted DiBiase",
     ruling("Unified WWE Tag Team Title", ["Chris Jericho", "The Big Show"],
            "Edge was injured and Jericho chose The Big Show as his partner; WWE counts a new reign",
            WORLD_TAG_1971)),
    (31013, "Big E defeats The Miz (c) and Jey Uso to win the titles",
     ruling("WWE SmackDown Tag Team Title", ["Big E", "Kofi Kingston"],
            "Big E won the titles for The New Day", WWE_TAG)),
    (12428, "Layla & Michelle McCool defeat Beth Phoenix (c)",
     ruling("WWE Women's Title", ["Layla"], "Layla pinned Phoenix; Wikipedia credits the reign to Layla",
            WOMENS_1956)),
    (12603, "Michelle McCool (c) (w/ Layla ) defeats Tiffany",
     ruling("WWE Women's Title", ["Layla"], "McCool defended Layla's title as unofficial co-champion",
            WOMENS_1956)),
    (12706, "Michelle McCool (c) defeats Melina (c) [Divas]",
     ruling("WWE Women's Title", ["Layla"], "McCool, Layla's unofficial co-champion, unified the title",
            WOMENS_1956)),
    (30395, "The Awesome Truth (The Miz",
     rename("The Awesome Truth (The Miz)", "The Miz",
            "The Awesome Truth (The Miz) & R-Truth", "The Awesome Truth (The Miz & R-Truth)")),
    (31276, "The Mysterios (Rey & Dominik Mysterio) (c)", rename("Rey", "Rey Mysterio")),
    (31280, "The Mysterios (Rey & Dominik Mysterio) (c)", rename("Rey", "Rey Mysterio")),
    (973, "Eddie Guerrero defeats Chris Jericho (c) by DQ",
     by("dq", ["Eddie Guerrero"], ["Eddie Guerrero", "Chris Jericho"])),
    (435, "The Hurricane defeated Tajiri (w/ Torrie Wilson ) (c) via count-out",
     by("countout", ["The Hurricane"], ["The Hurricane", "Tajiri"])),
    (514, "John Cena defeated Kurt Angle via disqualification",
     by("dq", ["John Cena"], ["John Cena", "Kurt Angle"])),
    (525, "Edge & Rey Mysterio Jr. defeated Eddie Guerrero & Chavo Guerrero Jr. via disqualification",
     by("dq", ["Edge", "Rey Mysterio Jr"], ["Edge & Rey Mysterio Jr", "Eddie Guerrero & Chavo Guerrero Jr."])),
    (529, "Billy Kidman defeated Kurt Angle via count-out",
     by("countout", ["Billy Kidman"], ["Billy Kidman", "Kurt Angle"])),
    (552, "Chris Benoit defeated Rikishi via disqualification",
     by("dq", ["Chris Benoit"], ["Chris Benoit", "Rikishi"])),
    (554, "Matt Hardy defeated The Undertaker via count-out",
     by("countout", ["Matt Hardy"], ["Matt Hardy", "The Undertaker"])),
]


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    import copy
    events = copy.deepcopy(data["events"]) if dry else data["events"]
    by_id = {m["id"]: m for e in events.values() for m in e["matches"]}
    changed = 0
    for mid, text, fix in FIXES:
        m = by_id.get(mid)
        if m is None or not (m.get("raw_description") or "").startswith(text):
            raise SystemExit(f"ABORT: match {mid} not found or its text changed")
        changed += fix(m)
    if not changed:
        print("already applied")
        return
    print(f"fixed {changed} matches")
    if dry:
        print("dry run: nothing written")
        return
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
