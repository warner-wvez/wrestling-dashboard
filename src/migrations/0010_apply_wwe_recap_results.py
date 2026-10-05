"""
Correct match results where WWE's own same-night recap settles a split.

Each row here is a lineup check "result" row: our card gave someone a DQ or
count-out win, and Cawthon and SmackDown Hotel did not agree with it. WWE's
results list for that night, read from the Wayback Machine with
lineup-check/wwe_recap.py, calls each of these a no contest:

  SmackDown 2006-03-10  Kurt Angle & Rey Mysterio vs Randy Orton & Mark Henry
  SmackDown 2006-11-24  The Boogeyman vs The Miz
  SmackDown 2007-09-21  Batista vs Mark Henry
  SmackDown 2009-03-27  Maryse vs Michelle McCool (Divas title, Maryse keeps it)
  SmackDown 2009-09-04  Matt Hardy vs CM Punk
  Raw 2009-12-07        D-Generation X vs Chris Jericho
  Raw 2013-08-05        CM Punk vs Curtis Axel
  Raw 2013-09-23        Randy Orton vs Rob Van Dam

The same check found our DQ or count-out win right five times against both
other sources (Raw 2008-01-07, 2008-03-03, 2008-03-10 and 2011-11-14,
SmackDown 2008-06-20). Those are ruled in lineup-check/rulings.csv, and they
are why this kind of row is never applied without WWE's page.

A no contest never moves a belt. The stored match text is left as our source
wrote it; the result note says what changed and where the proof is.

Safety gate: each match is found by event id + match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0010_apply_wwe_recap_results.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

WB = "http://web.archive.org/web/"
NO_CONTESTS = [
    # (event id, match id, stored text, WWE's recap page)
    (616, 8352, "Kurt Angle & Rey Mysterio defeat Mark Henry & Randy Orton (w/ Daivari ) by DQ (0:13)",
     WB + "20060412102216/http://www.wwe.com:80/shows/smackdown/archive/03102006/"),
    (700, 8906, "The Boogeyman defeats The Miz by Count Out (3:00)",
     WB + "20061206004311/http://www.wwe.com:80/shows/smackdown/archive/11242006/"),
    (798, 9555, "Batista defeats Mark Henry by DQ (3:20)",
     WB + "20071012231959/http://www.wwe.com:80/shows/smackdown/archive/09212007/"),
    (965, 11530, "Maryse (c) defeats Michelle McCool by DQ (3:00)",
     WB + "20090408025422/http://www.wwe.com:80/shows/smackdown/archive/03272009/"),
    (1018, 11900, "Matt Hardy defeats CM Punk by DQ (17:24)",
     WB + "20090915185518/http://www.wwe.com:80/shows/smackdown/archive/09042009/"),
    (1049, 12099, "D-Generation X ( Shawn Michaels & Triple H ) defeat Chris Jericho by DQ (2:00)",
     WB + "20091219211753/http://www.wwe.com:80/shows/raw/archive/12072009/"),
    (1471, 16100, "Curtis Axel (w/ Paul Heyman ) defeats CM Punk by DQ (10:20)",
     WB + "2013/http://www.wwe.com/shows/raw/2013-08-05/wwe-raw-results-26137732/page-9"),
    (1487, 16217, "Rob Van Dam defeats Randy Orton by Count Out (10:40)",
     WB + "20130927085350/http://www.wwe.com:80/shows/raw/2013-09-23/wwe-raw-results-26150716/page-5"),
]


def plan(events):
    todo = []
    for eid, mid, text, proof in NO_CONTESTS:
        m = next((x for x in (events.get(str(eid)) or {}).get("matches") or [] if x["id"] == mid), None)
        if m is None or m.get("raw_description") != text:
            raise SystemExit(f"ABORT: event {eid} match {mid} not found or its text changed")
        if all(t.get("match_outcome") == "no-contest" for t in m["teams"]):
            continue                                                 # already applied
        todo.append((m, proof))
    return todo


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    todo = plan(data["events"])
    if not todo:
        print("already applied")
        return
    print(f"no contests {len(todo)}")
    if dry:
        print("dry run: nothing written")
        return
    for m, proof in todo:
        for t in m["teams"]:
            t["was_winner"], t["match_outcome"] = None, "no-contest"
        m["result_method"] = "no contest"
        m["result_note"] = f"Result corrected to a no contest from WWE's own recap: {proof}"
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
