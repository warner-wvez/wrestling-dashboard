"""
Settle two title histories the reign walk could not get right from the cards.

  ECW, 2007. Backlash (04-29): Vince McMahon, Shane McMahon and Umaga beat
    Bobby Lashley, and Vince pinned him. The winning side is three men, and
    the walk picked Shane. Judgment Day (05-20): Lashley beat all three by
    pinning Shane, so Vince kept the belt, but the walk crowned Lashley. Both
    matches now carry title_result, the champion after the match, from
    Wikipedia's ECW title history (McMahon 2007-04-29 for 35 days, then
    Lashley at One Night Stand on 2007-06-03). That also removes the one-day
    "Mr. McMahon" reign One Night Stand produced.
  Women's title, Insurrextion 2003. Wikipedia names the belt "WWE Women's
    Championship"; the corpus calls it "World Women's Title" until late 2005,
    so Jazz's defense started a one-night lineage of its own. Renamed, the
    defense joins her reign from Backlash 2003.

Safety gate: each match is found by event id + match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0011_settle_title_lineage_gaps.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

ECW_HISTORY = "https://en.wikipedia.org/wiki/List_of_ECW_World_Heavyweight_Champions"
TITLE_RESULTS = [
    # (event id, match id, stored text, champion after the match, why)
    (751, 9234, "Shane McMahon , Umaga & Vince McMahon defeat Bobby Lashley (c) (15:30) - TITLE CHANGE !!!",
     ["Vince McMahon"], "Vince McMahon pinned Lashley in the handicap match"),
    (758, 9276, "Bobby Lashley defeats Shane McMahon , Umaga & Vince McMahon (c) (1:21)",
     ["Vince McMahon"], "Lashley pinned Shane McMahon, so Vince McMahon kept the title"),
]
RENAMES = [
    # (event id, match id, stored text, from, to)
    (3086, 33421, "[[Jazz (wrestler)|Jazz]] (c) (with [[Theodore Long]]) defeated [[Trish Stratus]]",
     "WWE Women's Championship", "World Women's Title"),
]


def _find(events, eid, mid, text):
    m = next((x for x in (events.get(str(eid)) or {}).get("matches") or [] if x["id"] == mid), None)
    if m is None or m.get("raw_description") != text:
        raise SystemExit(f"ABORT: event {eid} match {mid} not found or its text changed")
    return m


def plan(events):
    results = []
    for eid, mid, text, champs, why in TITLE_RESULTS:
        m = _find(events, eid, mid, text)
        if (m.get("title_result") or {}).get("champions") != champs:
            results.append((m, champs, why))
    renames = []
    for eid, mid, text, old, new in RENAMES:
        m = _find(events, eid, mid, text)
        if m.get("title_at_stake") == old:
            renames.append((m, new))
        elif m.get("title_at_stake") != new:
            raise SystemExit(f"ABORT: match {mid} title is {m.get('title_at_stake')!r}")
    return results, renames


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    results, renames = plan(data["events"])
    if not results and not renames:
        print("already applied")
        return
    print(f"title results {len(results)}, renames {len(renames)}")
    if dry:
        print("dry run: nothing written")
        return
    for m, champs, why in results:
        m["title_result"] = {"champions": champs, "why": why, "source": ECW_HISTORY}
    for m, new in renames:
        m["title_at_stake"] = new
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
