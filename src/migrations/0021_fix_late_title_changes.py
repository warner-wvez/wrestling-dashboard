"""
Seven title changes our cards carry as matches but the reign walk could not
read, so each reign started at the champion's next match instead.

Found by the date check in lineup-check/title_audit.py: every reign the walk
shares with the belt's Wikipedia list must start within a week of Wikipedia's
date or WWE.com's air date. Each change below is listed by both.

  Raw 2021-09-13 (match 29492). Big E cashed in Money in the Bank on Bobby
    Lashley. The match names no belt, so no title walk saw it; it gets the WWE
    Championship. Big E's reign started two weeks late.
  WrestleMania 38 night 2 (match 33283). Roman Reigns, Universal champion,
    beat Brock Lesnar, WWE champion, winner takes all. The card marks neither
    man "(c)", so Lesnar kept the WWE title to 2022-06-17.
  One Night Stand 2008 (match 33381). Edge beat The Undertaker in a TLC match
    for the vacant World Heavyweight title. No title change mark, so the belt
    stayed empty until Night of Champions.
  Raw 2006-05-15 (match 8475). Chris Masters, Shelton Benjamin and Triple H
    beat John Cena and Rob Van Dam with both men's belts on the line. Benjamin
    pinned Van Dam for the Intercontinental title; Cena kept the WWE title.
    The card's TITLE CHANGE mark cannot say which belt it means, so the walk
    moved neither.
  Wrestlepalooza 2025 (match 33075). Stephanie Vaquer beat Iyo Sky for the
    vacant Women's World title. No title change mark.
  Elimination Chamber 2020 (match 32527). Sami Zayn pinned Braun Strowman in
    a three-on-one handicap match beside Shinsuke Nakamura and Cesaro. A
    singles belt never moves on a multi-man win without a ruling.
  Survivor Series: WarGames 2025 (match 33096). Dominik Mysterio beat John
    Cena. The card lists Roxanne Perez, at ringside, on his side, so the win
    read as a multi-man one.

Safety gate: each match is found by match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0021_fix_late_title_changes.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

WIKI = "https://en.wikipedia.org/wiki/"
WWE_TITLE = WIKI + "List_of_WWE_Champions"
WHC_2002 = WIKI + "List_of_World_Heavyweight_Champions_(WWE,_2002%E2%80%932013)"
WOMENS_WORLD = WIKI + "List_of_Women%27s_World_Champions_(WWE)"
IC = WIKI + "List_of_WWE_Intercontinental_Champions"


def ruling(*belts, why, source):
    """belts: (title, champions) pairs, one ruling per belt on the match."""
    def apply(m):
        want = [{"title": t, "champions": c, "why": why, "source": source} for t, c in belts]
        if m.get("title_result") == want:
            return False
        m["title_result"] = want
        return True
    return apply


def stake(title):
    def apply(m):
        if m.get("title_at_stake") == title:
            return False
        m["title_at_stake"] = title
        return True
    return apply


FIXES = [
    # (match id, start of stored text (the same before and after the fix), fix)
    (29492, "Big E defeats Bobby Lashley (c) to win the title", stake("WWE Championship")),
    (33283, "[[Roman Reigns]] ([[WWE Universal Championship|Universal Champion]])",
     ruling(("WWE Championship", ["Roman Reigns"]), ("WWE Universal Championship", ["Roman Reigns"]),
            why="winner takes all: Reigns, Universal champion, beat Lesnar, WWE champion, and held both",
            source=WWE_TITLE)),
    (33381, "[[Edge (wrestler)|Edge]] defeated [[The Undertaker]]",
     ruling(("World Heavyweight Title", ["Edge"]),
            why="Edge beat The Undertaker in a TLC match for the vacant title", source=WHC_2002)),
    (8475, "Chris Masters , Shelton Benjamin & Triple H defeat John Cena (c) [WWE] & Rob Van Dam (c)",
     ruling(("WWE Intercontinental Title", ["Shelton Benjamin"]),
            why="a three-on-two handicap match with both belts on the line; Benjamin pinned Van Dam for the "
                "Intercontinental title and Cena kept the WWE title", source=IC)),
    (33075, "[[Stephanie Vaquer]] defeated [[Iyo Sky]] by [[pinfall]]",
     ruling(("Women's World Title", ["Stephanie Vaquer"]),
            why="Vaquer beat Iyo Sky for the vacant title", source=WOMENS_WORLD)),
    (32527, "The Artist Collective ([[Sami Zayn]], [[Shinsuke Nakamura]], and [[Claudio Castagnoli|Cesa",
     ruling(("WWE Intercontinental Title", ["Sami Zayn"]),
            why="a three-on-one handicap match; Zayn pinned Braun Strowman", source=IC)),
    (33096, "[[Dominik Mysterio]] (with [[Raquel Rodriguez (wrestler)|Raquel Rodriguez]] and [[Roxanne ",
     ruling(("WWE Intercontinental Title", ["Dominik Mysterio"]),
            why="Mysterio beat John Cena; Roxanne Perez was at ringside, not in the match", source=IC)),
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
