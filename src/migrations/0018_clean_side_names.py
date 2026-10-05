"""
Take the result text out of side names, and rebuild one battle royal.

About 315 sides carried part of the result in their name, because the source
wrote the result straight after the loser and the parser kept it: "The Big
Show by Count Out", "Christian to retain the WWE European Championship",
"Triple H - TITLE CHANGE !!!", "Kurt Angle via count-out when Angle left
ringside", "Bianca Belair & no contest", a German "by Matchabbruch", a
leftover time "(10:324". On a tag match the site prints a side's name under
its members ("as Eddie Guerrero & Chavo Guerrero Jr. via disqualification when
Kurt Angle interfered ..."). Each name is cut at the result and any champion
label in front ("WWE IC Champion Chris Benoit"), and the cut is kept only when
every wrestler on the side is still named in it.

Raw 2018-11-12, Tag Team Battle Royal (match 26952). The text lists six teams,
"Bobby Roode & Chad Gable vs. Heath Slater & Rhyno vs. The Ascension ... - No
Contest", but only two sides were stored, the second holding Heath Slater
alone under a name that ran on through the other four teams: twelve
wrestlers were missing. All six go back, no contest.

Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0018_clean_side_names.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

TAILS = [
    r"\s*-\s*TITLE CHANGE\s*!*\s*$",
    r"\s+by (?:Count ?Out|TKO|submission|forfeit|Matchabbruch|DQ|disqualification|pinfall)\b.*$",
    r"\s+to (?:retain|win|regain) the\b.*$",
    r"\s+(?:via|when|after) .*$",
    r"\s+with (?:a|an|the) .*$",
    r"\s*\(\d+:\d+.*$",
    r"\s*&\s*(?:disqualification|no contest|count ?out)\s*$",
]
# "WWE IC Champion Chris Benoit", "WWF Hardcore Champion Rob Van Dam".
CHAMPION_LABEL = re.compile(r"^(?:WW[EF] )?(?:[A-Z][\w'.]* ){1,3}Champion\s+")


def clean(name: str) -> str:
    s = name
    for p in TAILS:
        s = re.sub(p, "", s, flags=re.I)
    return CHAMPION_LABEL.sub("", s).strip()


def names_everyone(name: str, people: list[str]) -> bool:
    low = name.lower()
    return all(p.lower().split()[-1] in low for p in people if p)


BATTLE_ROYAL = (2126, 26952, "Bobby Roode & Chad Gable vs. Heath Slater & Rhyno vs. The Ascension")
BATTLE_ROYAL_SIDES = [
    ("Bobby Roode & Chad Gable", ["Bobby Roode", "Chad Gable"]),
    ("Heath Slater & Rhyno", ["Heath Slater", "Rhyno"]),
    ("The Ascension", ["Konnor", "Viktor"]),
    ("The B-Team", ["Bo Dallas", "Curtis Axel"]),
    ("The Lucha House Party", ["Gran Metalik", "Kalisto", "Lince Dorado"]),
    ("The Revival", ["Dash Wilder", "Scott Dawson"]),
]


def battle_royal(events):
    eid, mid, text = BATTLE_ROYAL
    m = next((x for x in (events.get(str(eid)) or {}).get("matches") or [] if x["id"] == mid), None)
    if m is None or not (m.get("raw_description") or "").startswith(text):
        raise SystemExit(f"ABORT: event {eid} match {mid} not found or its text changed")
    if len(m["teams"]) == len(BATTLE_ROYAL_SIDES):
        return None
    return m


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    sides = []
    for e in data["events"].values():
        for m in e["matches"]:
            for t in m["teams"]:
                name = t.get("team_name") or ""
                new = clean(name)
                if new != name and names_everyone(new, t["participants"]):
                    sides.append((t, new))
    royal = battle_royal(data["events"])
    if not sides and royal is None:
        print("already applied")
        return
    print(f"side names cleaned: {len(sides)}, battle royal rebuilt: {'yes' if royal else 'no'}")
    if dry:
        print("dry run: nothing written")
        return
    for t, new in sides:
        t["team_name"] = new
    if royal is not None:
        royal["teams"] = [{"team_number": n, "team_name": name, "accompaniment": None, "was_winner": None,
                           "match_outcome": "no-contest", "was_champion_entering": False,
                           "participants": list(people)}
                          for n, (name, people) in enumerate(BATTLE_ROYAL_SIDES, 1)]
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
