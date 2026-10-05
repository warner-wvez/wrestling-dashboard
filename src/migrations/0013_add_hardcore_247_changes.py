"""
Add the televised 24/7 Hardcore title changes our 2001-2002 cards never carried.

Under the 24/7 rule the Hardcore title changed hands backstage, in parking
lots and in the middle of other people's matches, and our source only kept
the bouts. Wikipedia's List of WWE Hardcore Champions has 45 changes on Raw,
SmackDown and pay-per-view in 2001-2002; our cards had 29 of the nights right
and none of the 24/7 pinfalls. Each change added here is on Wikipedia's list
(its reign number is in the note) and in Cawthon's results, and on weekly shows
SmackDown Hotel lists it too as its own line ("Raven defeats Hardcore Holly
(c) to win the title"). Order on the card follows Cawthon, and Wikipedia's
WrestleMania X8 article for the four backstage changes that night.

  pinfalls  29 changes that were their own segment: a backstage pin, or a third
            man pinning the champion during a defense (the defense stays on the
            card as our source has it).
  within    2 matches where the belt changed hands inside the match before the
            final result: No Way Out 2001 (Billy Gunn, then Raven, before the Big
            Show won) and the Raw 2002-08-19 Hardcore battle royal (Bradshaw,
            then Crash, before Tommy Dreamer). They get title_result.within, so
            the history shows those reigns without inventing matches.

  kept      Raw 2002-05-13's mixed tag (Bubba Ray Dudley & Trish Stratus beat
            Jazz and Steven Richards) was read as a two-belt swap that gave Bubba
            the Hardcore title. Trish pinned Jazz for the Women's title;
            Richards was never pinned and kept his, so the match gets a
            title_result for the Hardcore belt only.

House show changes (about 130 in these two years) are not on any card and are
not added here.

Safety gates: every anchor match must still be on its card with its stored
text; a pinfall is added only if that winner and champion do not already meet
on the card. Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0013_add_hardcore_247_changes.py [--dry-run]
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
LIST = "https://en.wikipedia.org/wiki/List_of_WWE_Hardcore_Champions"
WMX8 = "https://en.wikipedia.org/wiki/WrestleMania_X8"
SOURCE = "Cawthon + Wikipedia + SmackDown Hotel (24/7 Hardcore title change)"
WWF, WWE = "WWF Hardcore Title", "WWE Hardcore Title"

# event id: (anchor match id, start of its stored text,
#            [(winner, champion, Wikipedia reign number, after this anchor)...])
# Pinfalls listed under one anchor go in after it, in the order given.
PINFALLS = [
    (6, 34, "Hardcore Holly defeated Raven (c)", WWF, [("Raven", "Hardcore Holly", 61)]),
    (182, 1120, "Chris Jericho defeats The Big Show (c)", WWF, [("Rhyno", "Chris Jericho", 79)]),
    (187, 1151, "Rhyno defeats Test (c)", WWF, [("Mike Awesome", "Rhyno", 82)]),
    (195, 1217, "Rob Van Dam (c) vs. Kurt Angle", WWF, [("Jeff Hardy", "Rob Van Dam", 85)]),
    (63, 1601, "Al Snow (c) vs. The Big Show", WWF, [("Maven", "Al Snow", 93)]),
    (236, 1606, "Maven (c) vs. Goldust", WWF, [("Spike Dudley", "Maven", 94),
                                                 ("The Hurricane", "Spike Dudley", 95)]),
    (236, 1609, "Edge defeats Booker T", WWF, [("Mighty Molly", "The Hurricane", 96)]),
    (236, 1611, "Billy & Chuck (c) defeat", WWF, [("Christian", "Mighty Molly", 97)]),
    (236, 1613, "Jazz (c) defeats Lita", WWF, [("Maven", "Christian", 98)]),
    (241, 1666, "Raven defeats Bubba Ray Dudley (c)", WWF, [("Tommy Dreamer", "Raven", 114),
                                                            ("Steven Richards", "Tommy Dreamer", 115),
                                                            ("Bubba Ray Dudley", "Steven Richards", 116)]),
    (244, 1702, "Bubba Ray Dudley (c) vs. Jazz", WWF, [("Steven Richards", "Bubba Ray Dudley", 123)]),
    (3084, 33405, "[[Booker T (wrestler)|Booker T]] defeated", WWF, [("Crash", "Booker T", 136),
                                                                     ("Booker T", "Crash", 137),
                                                                     ("Steven Richards", "Booker T", 138)]),
    (245, 1711, "Jazz (w/ Steven Richards ) (c) defeats Trish Stratus", WWE, [
        ("Bubba Ray Dudley", "Steven Richards", 139), ("Raven", "Bubba Ray Dudley", 140),
        ("Justin Credible", "Raven", 141), ("Crash", "Justin Credible", 142),
        ("Trish Stratus", "Crash", 143), ("Steven Richards", "Trish Stratus", 144)]),
    (249, 1737, "Spike Dudley & Trish Stratus (c)", WWE, [("Terri", "Steven Richards", 151),
                                                          ("Steven Richards", "Terri", 152)]),
    (257, 1793, "Bradshaw (c) vs. Christopher Nowinski", WWE, [("Johnny Stamboli", "Bradshaw", 191),
                                                              ("Bradshaw", "Johnny Stamboli", 192)]),
    (260, 1812, "Jeff Hardy defeats Bradshaw (c)", WWE, [("Johnny Stamboli", "Jeff Hardy", 206),
                                                        ("Tommy Dreamer", "Johnny Stamboli", 207)]),
]
WITHIN = [
    # (event id, match id, start of stored text, holders inside the match, final holder, reigns)
    (165, 987, "The Big Show defeats Raven (c)", [["Billy Gunn"], ["Raven"]], ["The Big Show"], "71-73"),
    (263, 1829, "Tommy Dreamer (c) defeats Bradshaw", [["Bradshaw"], ["Crash"]], ["Tommy Dreamer"], "227-229"),
]

KEPT = [
    # (event id, match id, start of stored text, belt, holder after the match)
    (246, 1720, "Bubba Ray Dudley & Trish Stratus defeat Jazz", WWE, ["Steven Richards"]),
]


def _anchor(ev, mid, text):
    m = next((x for x in (ev or {}).get("matches") or [] if x["id"] == mid), None)
    if m is None or not (m.get("raw_description") or "").startswith(text):
        raise SystemExit(f"ABORT: match {mid} not found or its text changed")
    return m


def _meet(ev, winner, champion):
    return any(m.get("title_at_stake") and {p for t in m["teams"] for p in t["participants"]} == {winner, champion}
               and any(t.get("was_winner") and t["participants"] == [winner] for t in m["teams"])
               for m in ev["matches"])


def pinfall(new_id, winner, champion, belt, reign, eid):
    src = WMX8 if eid == 236 else LIST
    teams = [{"team_number": 1, "team_name": winner, "accompaniment": None, "was_winner": True,
              "match_outcome": "win", "was_champion_entering": False, "participants": [winner]},
             {"team_number": 2, "team_name": champion, "accompaniment": None, "was_winner": False,
              "match_outcome": "loss", "was_champion_entering": True, "participants": [champion]}]
    return {"id": new_id, "match_order": None, "match_type": f"{belt} Match", "stipulation": "hardcore",
            "title_at_stake": belt, "duration_seconds": None, "result_method": "defeated",
            "match_guide_rating": None,
            "raw_description": f"{winner} defeats {champion} (c) - TITLE CHANGE !!!",
            "teams": teams, "source": SOURCE,
            "source_note": f"24/7 pinfall, Hardcore reign #{reign} on {LIST}" +
                           (f"; place on the card from {src}" if src != LIST else "")}


def plan(events):
    adds, withins = [], []
    for eid, mid, text, belt, pins in PINFALLS:
        ev = events.get(str(eid))
        _anchor(ev, mid, text)
        todo = [(w, c, n) for w, c, n in pins if not _meet(ev, w, c)]
        if todo:
            adds.append((ev, mid, belt, todo))
    for eid, mid, text, inside, final, reigns in WITHIN:
        m = _anchor(events.get(str(eid)), mid, text)
        if (m.get("title_result") or {}).get("within") != inside:
            withins.append((m, inside, final, reigns))
    kept = []
    for eid, mid, text, belt, holder in KEPT:
        m = _anchor(events.get(str(eid)), mid, text)
        if (m.get("title_result") or {}).get("champions") != holder:
            kept.append((m, belt, holder))
    return adds, withins, kept


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    events = data["events"]
    adds, withins, kept = plan(events)
    if not adds and not withins and not kept:
        print("already applied")
        return
    print(f"pinfalls {sum(len(t) for *_, t in adds)} on {len({id(a[0]) for a in adds})} shows, "
          f"in-match changes on {len(withins)} matches, kept {len(kept)}")
    if dry:
        print("dry run: nothing written")
        return
    next_id = max(m["id"] for e in events.values() for m in e["matches"]) + 1
    media = json.loads(MEDIA.read_text(encoding="utf-8"))
    touched = {}
    for ev, mid, belt, todo in adds:
        at = [m["id"] for m in ev["matches"]].index(mid) + 1
        for winner, champion, reign in todo:
            ev["matches"].insert(at, pinfall(next_id, winner, champion, belt, reign, ev["id"]))
            next_id += 1
            at += 1
        touched[str(ev["id"])] = ev
    for eid, ev in touched.items():
        ev["match_count"] = len(ev["matches"])
        moved = m6.renumber(ev["matches"])
        if eid in media and moved:
            media[eid] = m6.remap_media(media[eid], moved)
    for m, inside, final, reigns in withins:
        m["title_result"] = {"champions": final, "within": inside,
                             "why": "the belt changed hands inside this match", "source": f"{LIST} (reigns {reigns})"}
    for m, belt, holder in kept:
        m["title_result"] = {"title": belt, "champions": holder,
                             "why": "Trish Stratus pinned Jazz; Steven Richards was not pinned",
                             "source": LIST}
    atomic_write_text(MEDIA, json.dumps(media, ensure_ascii=False, separators=(",", ":")))
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
