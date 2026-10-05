"""
Repair two match records our source garbled, each from its own stored text.

  SmackDown 2007-01-26, Over The Top Rope Challenge (match 9053). The text
    reads "Chris Benoit vs. Finlay vs. Kane vs. King Booker vs. Montel
    Vontavious Porter vs. The Miz - No Contest (8:30)", but only Chris Benoit
    was stored, as a one-man side. All six go back as their own sides, no
    contest, the way Cawthon and SmackDown Hotel list it.
  SmackDown 2002-08-22, Molly Holly vs Nidia (match 531). The text is a
    Cawthon-style sentence ("WWE Women's Champion Molly Holly defeated Nidia
    (w/ Jamie Noble) ... had Nidia won the title ..."), and its tail landed on
    Nidia's side as a second wrestler, "Molly knocked Noble into Nidia". The
    side is Nidia alone with Jamie Noble in her corner, the side names are
    clean, and the match carries the Women's title Molly defended, which the
    same text states.

Safety gate: each match is found by event id + match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0014_fix_two_garbled_matches.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

SIX_MAN = (721, 9053, "Chris Benoit vs. Finlay vs. Kane vs. King Booker vs. Montel Vontavious Porter vs. "
                      "The Miz - No Contest (8:30)",
           ["Chris Benoit", "Finlay", "Kane", "King Booker", "Montel Vontavious Porter", "The Miz"])
MOLLY = (86, 531, "WWE Women's Champion Molly Holly defeated Nidia (w/ Jamie Noble )")
WOMENS = "WWE World Women's Title"         # the corpus's name for the belt in mid-2002


def _find(events, eid, mid, text, exact=True):
    m = next((x for x in (events.get(str(eid)) or {}).get("matches") or [] if x["id"] == mid), None)
    raw = (m or {}).get("raw_description") or ""
    if m is None or (raw != text if exact else not raw.startswith(text)):
        raise SystemExit(f"ABORT: event {eid} match {mid} not found or its text changed")
    return m


def plan(events):
    eid, mid, text, people = SIX_MAN
    six = _find(events, eid, mid, text)
    six = six if len(six["teams"]) != len(people) else None
    eid, mid, text = MOLLY
    molly = _find(events, eid, mid, text, exact=False)
    molly = molly if any(len(t["participants"]) > 1 for t in molly["teams"]) else None
    return six, molly


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    six, molly = plan(data["events"])
    if not six and not molly:
        print("already applied")
        return
    print(f"six-man sides {'yes' if six else 'no'}, Molly Holly vs Nidia {'yes' if molly else 'no'}")
    if dry:
        print("dry run: nothing written")
        return
    if six:
        six["teams"] = [{"team_number": n, "team_name": p, "accompaniment": None, "was_winner": None,
                         "match_outcome": "no-contest", "was_champion_entering": False, "participants": [p]}
                        for n, p in enumerate(SIX_MAN[3], 1)]
    if molly:
        a, b = molly["teams"]
        a.update(team_name="Molly Holly", participants=["Molly Holly"], was_champion_entering=True)
        b.update(team_name="Nidia", participants=["Nidia"], accompaniment="Jamie Noble")
        molly["title_at_stake"] = WOMENS
        molly["match_type"] = f"{WOMENS} Match"
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
