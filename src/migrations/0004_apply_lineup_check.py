"""
Apply the lineup check's automatic fixes to the shipped bundle.

lineup-check/lineup_check.py compares every 2001 to 2013 card with Graham
Cawthon's results archive and writes lineup-check/out/auto-fixes.json: only the
changes both sources agree on. This applies them and rebuilds every index the
way src/rebuild_indexes.py does (which also runs the junk-name cleanup):

  not_aired     match["aired"] = False. Our source labels it a dark match and
                Cawthon's televised list does not have it. The card greys it
                and labels it "Not on the broadcast"; it stays in the data and
                in profile counts.
  aired_heat    match["aired"] = False, match["aired_on"] = "Sunday Night Heat":
                a PPV card's match that aired on the pre-show instead.
  add_wrestler  the named wrestler joins the team: our own match text and
                Cawthon both list him, our stored lineup had lost him.

Safety gates, in order:
  1. Every fix is located by event id AND match id, and the match's stored
     raw_description must equal the text the check saw, or the run aborts.
  2. Counts must stay under the ceilings set from the 2026-10-05 run
     (800 / 4 / 20).
  3. Idempotent: a fix already in place is skipped, and a second run reports
     "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0004_apply_lineup_check.py [--dry-run]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

FIXES = PROJECT_ROOT / "lineup-check" / "out" / "auto-fixes.json"
# Upper bounds only: a re-run after other repairs (0005 fixed sides the check
# had queued as additions) legitimately finds fewer. Gate 1 still pins every
# fix to its exact match text.
WINDOWS = {"not_aired": range(0, 801), "aired_heat": range(0, 5), "add_wrestler": range(0, 21)}
HEAT = "Sunday Night Heat"


def locate(events, item):
    ev = events.get(str(item["event_id"]))
    match = next((m for m in (ev or {}).get("matches") or [] if m.get("id") == item["match_id"]), None)
    if match is None or (match.get("raw_description") or "") != item["ours"]:
        raise SystemExit(f"ABORT gate 1: event {item['event_id']} match {item['match_id']} "
                         f"not found or its text changed: {item['ours'][:80]}")
    return match


def plan(events, fixes):
    """[(kind, match, item)] still to apply."""
    todo = []
    for item in fixes["not_aired"]:
        m = locate(events, item)
        if m.get("aired") is not False:
            todo.append(("not_aired", m, item))
    for item in fixes["aired_heat"]:
        m = locate(events, item)
        if m.get("aired_on") != HEAT:
            todo.append(("aired_heat", m, item))
    for item in fixes["add_wrestler"]:
        m = locate(events, item)
        team = next((t for t in m["teams"] if t.get("team_number") == item["team_number"]), None)
        if team is None:
            raise SystemExit(f"ABORT gate 1: team {item['team_number']} missing in match {item['match_id']}")
        if item["name"] not in (team.get("participants") or []):
            todo.append(("add_wrestler", m, item))
    return todo


def apply(todo):
    for kind, m, item in todo:
        if kind == "not_aired":
            m["aired"] = False
        elif kind == "aired_heat":
            m["aired"], m["aired_on"] = False, HEAT
        else:
            team = next(t for t in m["teams"] if t.get("team_number") == item["team_number"])
            team["participants"] = (team.get("participants") or []) + [item["name"]]


def main():
    dry = "--dry-run" in sys.argv
    fixes = json.loads(FIXES.read_text(encoding="utf-8"))
    for kind, window in WINDOWS.items():                       # gate 2
        if len(fixes[kind]) not in window:
            raise SystemExit(f"ABORT gate 2: {len(fixes[kind])} {kind} fixes, expected "
                             f"{window.start} to {window.stop - 1}")
    data = load_existing()
    todo = plan(data["events"], fixes)
    if not todo:
        print("already applied")
        return
    counts = {k: sum(1 for t in todo if t[0] == k) for k in WINDOWS}
    print("applying " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    if dry:
        print("dry run: nothing written")
        return
    apply(todo)
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
