"""
Fix match records that gave the title history reigns that never happened.

Found by laying each title's reign chain beside its Wikipedia title history
(lineup-check/title_audit.py); each fix also rests on the match's own text or
a second record, named below.

  Insurrextion 2002, IC title (match 33402). The Wikipedia import stored
    "disqualification" as a wrestler on Eddie Guerrero's side and the result as
    a clean win, so Rob Van Dam took the belt. Van Dam won by DQ (the stored
    text says so) and Guerrero kept it.
  Raw 2011-06-20, US title (13351). Kofi Kingston won the two-out-of-three
    falls match 2-1, the deciding fall by DQ, so Dolph Ziggler kept the belt
    (Cawthon; SmackDown Hotel: "via DQ; Ziggler retains the title").
  Raw 2017-01-09, US title (24108). Chris Jericho and Kevin Owens beat Roman
    Reigns in a handicap match and Jericho won the title (Wikipedia's list);
    the walk picked Owens off the two-man side.
  Raw 2022-09-05, US title (29870). "Bobby Lashey (c)", a typo, started a
    reign of its own.
  SmackDown 2011-11-25, World Heavyweight title (13729). Daniel Bryan cashed in
    and pinned Mark Henry, but Teddy Long ruled Henry had not been cleared to
    compete and gave the belt back to him (Cawthon). The match stands; the
    title change does not.
  SmackDown 2013-09-06 (16177). Bryan beat WWE Champion Randy Orton by DQ; the
    match was tagged with the World Heavyweight title, so Orton started a reign
    on a belt he did not hold.
  Raw 2010-09-20 and Bragging Rights 2010-10-24, Divas title (33348, 12796).
    LayCool shared the unified Divas title and Layla defended it as "(c)"
    while Michelle McCool held it (Wikipedia: McCool from Night of Champions to
    Survivor Series), so each defense started a Layla reign.

Safety gate: each match is found by event id + match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0015_fix_title_history_errors.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

US_LIST = "https://en.wikipedia.org/wiki/List_of_WWE_United_States_Champions"
DIVAS_LIST = "https://en.wikipedia.org/wiki/List_of_WWE_Divas_Champions"
CAWTHON = "https://thehistoryofwwe.com/"


def _dq(m, winner):
    for t in m["teams"]:
        won = t["participants"] == [winner]
        t["was_winner"], t["match_outcome"] = won, "dq-win" if won else "dq-loss"
    m["result_method"] = "dq"


def fix_insurrextion(m):
    side = next((t for t in m["teams"] if "disqualification" in t["participants"]), None)
    if side is None:
        return False
    side["participants"] = ["Eddie Guerrero"]
    _dq(m, "Rob Van Dam")
    return True


def fix_ziggler(m):
    if m["teams"][0].get("match_outcome") == "dq-win":
        return False
    _dq(m, "Kofi Kingston")
    m["result_note"] = "Kingston won the deciding fall by DQ; Ziggler kept the title (Cawthon, SmackDown Hotel)"
    return True


def ruling(title, champions, why, source):
    def apply(m):
        want = {"title": title, "champions": champions, "why": why, "source": source}
        if m.get("title_result") == want:
            return False
        m["title_result"] = want
        return True
    return apply


def fix_lashley(m):
    if not any("Bobby Lashey" in t["participants"] for t in m["teams"]):
        return False
    for t in m["teams"]:
        t["participants"] = ["Bobby Lashley" if p == "Bobby Lashey" else p for p in t["participants"]]
        t["team_name"] = (t.get("team_name") or "").replace("Bobby Lashey", "Bobby Lashley")
    m["raw_description"] = m["raw_description"].replace("Bobby Lashey", "Bobby Lashley")
    return True


def fix_orton_label(m):
    # Keep the match type's "Dark" (this was a dark match after the taping).
    want = "Dark WWE Heavyweight Title Match"
    if m.get("title_at_stake") == "WWE Heavyweight Title" and m.get("match_type") == want:
        return False
    m["title_at_stake"] = "WWE Heavyweight Title"
    m["match_type"] = want
    return True


FIXES = [
    # (event id, match id, start of stored text (exact before or after the fix), fix)
    (3084, 33402, "[[Rob Van Dam]] defeated [[Eddie Guerrero]] (c) via", fix_insurrextion),
    (1225, 13351, "Kofi Kingston defeats Dolph Ziggler (w/ Vickie Guerrero ) (c) [2:1]", fix_ziggler),
    (1895, 24108, "Chris Jericho & Kevin Owens defeat Roman Reigns (c)",
     ruling("WWE United States Title", ["Chris Jericho"], "Jericho won the handicap match for the title",
            US_LIST)),
    (2410, 29870, "Bobby Lash", fix_lashley),
    (1275, 13729, "Daniel Bryan defeats Mark Henry (c) (0:14)",
     ruling("World Heavyweight Title", ["Mark Henry"],
            "Teddy Long reversed the decision: Henry was not cleared to compete", CAWTHON)),
    (1481, 16177, "Daniel Bryan defeats Randy Orton (c) by DQ", fix_orton_label),
    (3076, 33348, "Layla © defeats Melina",
     ruling("Unified WWE Divas Title", ["Michelle McCool"], "LayCool shared the title; McCool held it",
            DIVAS_LIST)),
    (1148, 12796, "Layla (w/ Michelle McCool ) (c) defeats Natalya",
     ruling("Unified WWE Divas Title", ["Michelle McCool"], "LayCool shared the title; McCool held it",
            DIVAS_LIST)),
]


def plan(events, dry):
    todo = []
    for eid, mid, text, fix in FIXES:
        m = next((x for x in (events.get(str(eid)) or {}).get("matches") or [] if x["id"] == mid), None)
        if m is None or not (m.get("raw_description") or "").startswith(text):
            raise SystemExit(f"ABORT: event {eid} match {mid} not found or its text changed")
        todo.append((m, fix))
    return todo


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    import copy
    probe = copy.deepcopy(data["events"]) if dry else None
    changed = 0
    for m, fix in plan(probe if dry else data["events"], dry):
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
