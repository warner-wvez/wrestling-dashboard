"""
Apply the lineup check review rows that a person ruled a data change.

Each row here was read against three sources side by side (our card,
Cawthon's thehistoryofwwe.com, SmackDown Hotel) and, where they split, a
fourth: Wikipedia's title histories or WWE's own same-night recap. Rows ruled
"our card is right" go in lineup-check/rulings.csv instead and change nothing.

  second_bouts  A title that changed hands twice in one night, where our card
                has only the first change. Cawthon and SmackDown Hotel both
                list both bouts, and Wikipedia's List of WWE Hardcore Champions
                has both reigns starting that day:
                  Raw 2001-01-22     Al Snow beat Raven, then Raven took it back
                  Raw 2001-09-10     Kurt Angle beat Rob Van Dam, then RVD
                  SmackDown 2002-02-28  Maven beat Goldust, then Goldust pinned
                                     Maven backstage (taped 02-26)
                The bout goes in where Cawthon places it, the show's match
                numbers follow card order, and its watch links move with them.

Safety gates: the first bout must still be on the card with its stored text,
and a bout is added only if those people do not already meet a second time.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0009_apply_hand_rulings.py [--dry-run]
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "m6", Path(__file__).with_name("0006_apply_vote_fixes.py"))
m6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m6)

MEDIA = PROJECT_ROOT / "shards" / "media.json"
HARDCORE = "https://en.wikipedia.org/wiki/List_of_WWE_Hardcore_Champions"
SOURCE = "Cawthon + SmackDown Hotel + Wikipedia (hand-ruled second bout)"

SECOND_BOUTS = [
    # (event id, the first bout's match id and stored text, winner, champion,
    #  belt, Cawthon's line for the second bout, source)
    (160, 954, "Al Snow defeats Raven (c) (3:35) - TITLE CHANGE !!!", "Raven", "Al Snow",
     "WWF Hardcore Title",
     "Raven pinned WWF Hardcore Champion Al Snow to win the title after a masked woman "
     "knocked the champion out and put Raven on top for the cover", HARDCORE),
    (200, 1253, "Kurt Angle defeats Rob Van Dam (c) (5:57) - TITLE CHANGE !!!", "Rob Van Dam",
     "Kurt Angle", "WWF Hardcore Title",
     "Rob Van Dam pinned WWF Hardcore Champion Kurt Angle to win the title after Steve Austin "
     "attacked Angle from behind, threw him off the stage, and threw RVD off as well",
     HARDCORE),
    (61, 1575, "Al Snow vs. The Undertaker - No Contest (2:11)", "Goldust", "Maven",
     "WWF Hardcore Title",
     "Goldust pinned WWF Hardcore Champion Maven to win the title as the champion was "
     "backstage receiving medical treatment", HARDCORE),
]


def second_bout(new_id, winner, champion, belt, line, source):
    """A singles title change in the corpus's own shape. The text carries the
    source's TITLE CHANGE marker the reign walk and the card read."""
    teams = [{"team_number": 1, "team_name": winner, "accompaniment": None, "was_winner": True,
              "match_outcome": "win", "was_champion_entering": False, "participants": [winner]},
             {"team_number": 2, "team_name": champion, "accompaniment": None, "was_winner": False,
              "match_outcome": "loss", "was_champion_entering": True, "participants": [champion]}]
    return {"id": new_id, "match_order": None, "match_type": f"{belt} Match",
            "stipulation": "hardcore", "title_at_stake": belt, "duration_seconds": None,
            "result_method": "defeated", "match_guide_rating": None,
            "raw_description": f"{winner} defeats {champion} (c) - TITLE CHANGE !!!",
            "teams": teams, "source": SOURCE, "source_note": f"{line} ({source})"}


def plan(events):
    todo = []
    for eid, after_id, after_text, winner, champion, belt, line, source in SECOND_BOUTS:
        ev = events.get(str(eid))
        after = next((m for m in (ev or {}).get("matches") or [] if m["id"] == after_id), None)
        if after is None or after.get("raw_description") != after_text:
            raise SystemExit(f"ABORT: event {eid} match {after_id} not found or its text changed")
        people = {winner, champion}
        meets = [m for m in ev["matches"] if {p for t in m["teams"] for p in t["participants"]} == people]
        if len(meets) >= 2:
            continue                                                 # already added
        todo.append((ev, after_id, winner, champion, belt, line, source))
    return todo


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    events = data["events"]
    todo = plan(events)
    if not todo:
        print("already applied")
        return
    print(f"second bouts {len(todo)}")
    if dry:
        print("dry run: nothing written")
        return
    next_id = max(m["id"] for e in events.values() for m in e["matches"]) + 1
    media = json.loads(MEDIA.read_text(encoding="utf-8"))
    for ev, after_id, *rest in todo:
        at = [m["id"] for m in ev["matches"]].index(after_id) + 1
        ev["matches"].insert(at, second_bout(next_id, *rest))
        next_id += 1
        ev["match_count"] = len(ev["matches"])
        moved = m6.renumber(ev["matches"])
        if str(ev["id"]) in media and moved:
            media[str(ev["id"])] = m6.remap_media(media[str(ev["id"])], moved)
    atomic_write_text(MEDIA, json.dumps(media, ensure_ascii=False, separators=(",", ":")))
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
