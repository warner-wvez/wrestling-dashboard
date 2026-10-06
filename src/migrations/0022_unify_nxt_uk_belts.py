"""
Worlds Collide 2022-09-04: the three matches that unified the NXT UK belts
into the NXT ones, which the card carries with no belt named.

Wikipedia's NXT UK histories (and WWE.com's, which end the same reigns that
night) retire each UK belt here with the loser as its final champion:

  Match 32766. Bron Breakker, NXT champion, beat Tyler Bate, United Kingdom
    champion. Breakker kept the NXT title; Bate is the last UK champion.
  Match 32764. Mandy Rose, NXT Women's champion, beat Meiko Satomura, NXT UK
    Women's champion, and Blair Davenport. Satomura is the last UK Women's
    champion.
  Match 32763. Pretty Deadly beat the Creed Brothers (NXT Tag champions),
    Gallus, and Brooks Jensen and Josh Briggs (NXT UK Tag champions). Pretty
    Deadly won the NXT Tag titles; Jensen and Briggs are the last UK Tag
    champions.

Each match gets both belts it was for and one ruling per belt. With no belt
named, the NXT UK reigns ran to the day they started and never reached the
show that retired them.

Safety gate: each match is found by match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0022_unify_nxt_uk_belts.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

WIKI = "https://en.wikipedia.org/wiki/"
UK = WIKI + "NXT_United_Kingdom_Championship"
UK_WOMENS = WIKI + "NXT_UK_Women%27s_Championship"
UK_TAG = WIKI + "NXT_UK_Tag_Team_Championship"


def unified(stake, rulings, why, source):
    """stake: the match's belts. rulings: (belt, holders after the match)."""
    def apply(m):
        want = [{"title": t, "champions": c, "why": why, "source": source} for t, c in rulings]
        if m.get("title_at_stake") == stake and m.get("title_result") == want:
            return False
        m["title_at_stake"] = stake
        m["title_result"] = want
        return True
    return apply


FIXES = [
    # (match id, start of stored text (the same before and after the fix), fix)
    (32766, "[[Bron Breakker]] (NXT) defeated [[Tyler Bate]] (NXT UK) by [[pinfall]]",
     unified("NXT Championship / United Kingdom Championship",
             [("NXT Championship", ["Bron Breakker"]), ("United Kingdom Championship", ["Tyler Bate"])],
             why="unified into the NXT title; the UK title was retired with Bate as its final champion",
             source=UK)),
    (32764, "[[Mandy Rose]] (NXT) defeated [[Meiko Satomura]] (NXT UK) and [[Blair Davenport]]",
     unified("NXT Women's Championship / NXT UK Women's Championship",
             [("NXT Women's Championship", ["Mandy Rose"]), ("NXT UK Women's Championship", ["Meiko Satomura"])],
             why="unified into the NXT Women's title; the UK title was retired with Satomura as its final champion",
             source=UK_WOMENS)),
    (32763, "[[Pretty Deadly (professional wrestling)|Pretty Deadly]] ([[Elton Prince]] and [[Kit Wilso",
     unified("NXT Tag Team Championship / NXT UK Tag Team Championship",
             [("NXT Tag Team Championship", ["Elton Prince", "Kit Wilson"]),
              ("NXT UK Tag Team Championship", ["Brooks Jensen", "Josh Briggs"])],
             why="unified into the NXT Tag titles; the UK titles were retired with Jensen and Briggs as their "
                 "final champions", source=UK_TAG)),
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
