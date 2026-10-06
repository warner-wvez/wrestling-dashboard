"""
Valets the Wikipedia results-table parser cut short or counted as wrestlers.

The parser read a side's "(with ...)" group up to the first ")", and a valet's
link can carry brackets of its own: "(with [[Joe Coffey (wrestler)|Joe
Coffey]])". So the ringside line kept a scrap of link code ("[[Joe Coffey
(wrestler"), and the names after the bracket landed among the wrestlers:
Roxanne Perez beside Dominik Mysterio at Survivor Series 2025, Rezar beside
Seth Rollins and Murphy at Elimination Chamber 2020, three of Legado del
Fantasma beside Rey Mysterio and Andrade at WrestleMania XL. The parser now
reads the group to its own closing bracket (src/wikipedia_ppv.with_group).

  Part A, 34 groups on 32 matches (2007 to 2026). Each is found by match id
  and the ringside text the old parser stored; the group is read again from
  the match's own stored text, the ringside line takes every valet in it, and
  any of them standing among that side's wrestlers comes out.
  Part B, two fatal five-ways whose four losers were stored as one team, with
  their valets inside it: NXT Stand & Deliver 2022 (match 32711) and NXT
  Halloween Havoc 2022 (match 32775). Their losing sides are split again from
  the stored text, each with its own valets.
  Part C, the other way round: Worlds Collide 2022's four-way (match 32763)
  split the NXT UK Tag champions, Brooks Jensen and Josh Briggs, into two
  sides of one man each. They are one team again.

Safety gate: each match is found by match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0023_fix_cut_valet_groups.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402
from src.export_to_html import clean_participant  # noqa: E402
from src.wikipedia_ppv import links_in, parse_side, split_top  # noqa: E402

# (match id, the ringside text the old parser stored for the cut group)
CUT_GROUPS = [
    (33370, 'Shane McMahon'),  # 2007-06-03 WWE One Night Stand 2007
    (32526, '[[Akam (wrestler'),  # 2020-03-08 Elimination Chamber
    (33148, '[[Lana (wrestler'),  # 2020-04-05 WrestleMania 36 - Night 2
    (32555, '[[Bayley (wrestler'),  # 2020-08-23 SummerSlam
    (32569, '[[Ricochet (wrestler'),  # 2020-09-27 Clash of Champions
    (32577, '[[John Morrison (wrestler'),  # 2020-10-25 Hell in a Cell
    (32577, '[[Tucker (American wrestler'),  # 2020-10-25 Hell in a Cell
    (32583, '[[Big E (wrestler'),  # 2020-11-22 Survivor Series
    (32595, '[[John Morrison (wrestler'),  # 2020-12-20 TLC: Tables, Ladders & Chairs
    (32596, '[[Reggie (wrestler'),  # 2020-12-20 TLC: Tables, Ladders & Chairs
    (32603, '[[Reggie (wrestler'),  # 2021-01-31 Royal Rumble
    (32607, '[[Mace (wrestler'),  # 2021-02-21 Elimination Chamber
    (32614, '[[Mace (wrestler'),  # 2021-03-21 Fastlane
    (32615, '[[Reggie (wrestler'),  # 2021-03-21 Fastlane
    (32625, '[[John Morrison (wrestler'),  # 2021-05-16 WrestleMania Backlash
    (32629, '[[Robert Stone (wrestler'),  # 2021-06-13 NXT TakeOver: In Your House
    (32631, '[[Boa (wrestler'),  # 2021-06-13 NXT TakeOver: In Your House
    (32638, 'Nia Jax'),  # 2021-06-20 Hell in a Cell
    (32688, '[[Diamond Mine (professional wrestling'),  # 2021-12-05 NXT WarGames
    (32755, '[[Imperium (professional wrestling'),  # 2022-09-03 Clash at the Castle
    (32755, 'The Brawling Brutes, Ridge Holland, Butch'),  # 2022-09-03 Clash at the Castle
    (32763, '[[Joe Coffey (wrestler'),  # 2022-09-04 Worlds Collide
    (32841, '[[Joe Coffey (wrestler'),  # 2023-05-28 NXT Battleground
    (32852, '[[Joe Coffey (wrestler'),  # 2023-07-30 NXT The Great American Bash
    (32865, '[[Bayley (wrestler'),  # 2023-08-05 SummerSlam
    (33203, '[[Carlito (wrestler'),  # 2024-04-06 WrestleMania XL - Night 1
    (32934, '[[Otis (wrestler'),  # 2024-05-25 King and Queen of the Ring
    (32946, '[[Otis (wrestler'),  # 2024-06-15 Clash at the Castle: Scotland
    (32962, '[[Machine Gun Kelly (musician'),  # 2024-08-03 SummerSlam: Cleveland
    (33025, '[[Zaria (wrestler'),  # 2025-05-25 Battleground
    (33043, '[[Zaria (wrestler'),  # 2025-07-12 The Great American Bash
    (33079, '[[Zaria (wrestler'),  # 2025-09-27 NXT No Mercy
    (33096, '[[Raquel Rodriguez (wrestler'),  # 2025-11-29 Survivor Series: WarGames
    (33279, 'Lexis King, Channing "Stacks" Lorenzo'),  # 2026-06-28 NXT The Great American Bash
]

# Fatal five-ways stored with the four losers as one team: (match id, start of
# stored text, that team's stored wrestlers).
FUSED = [
    (32711, "[[Cameron Grimes]] defeated [[Carmelo Hayes]] (c) (with [[Tr",
     ["Carmelo Hayes", "Santos Escobar", "Raul Mendoza", "Joaquin Wilde", "Elektra Lopez", "Solo Sikoa",
      "Grayson Waller", "Sanga"]),
    (32775, "[[Wes Lee]] defeated [[Carmelo Hayes]] (with [[Trick William",
     ["Carmelo Hayes", "Oro Mensah", "Von Wagner", "Mr. Stone", "Nathan Frazer"]),
]


# One team stored as two sides: (match id, start of stored text, the two sides'
# wrestlers, the team's name).
SPLIT_TEAMS = [
    (32763, "[[Pretty Deadly (professional wrestling)|Pretty Deadly]] ([[Elton Prince]] and [[Kit Wilso",
     (["Brooks Jensen"], ["Josh Briggs"]), "Brooks Jensen & Josh Briggs"),
]


def join_team(m, halves, name):
    sides = [next((t for t in m["teams"] if t["participants"] == h), None) for h in halves]
    if any(t is None for t in sides):
        if any(t["participants"] == halves[0] + halves[1] for t in m["teams"]):
            return False                  # already one team
        raise SystemExit(f"ABORT: match {m['id']}'s sides changed")
    first, second = sides
    first["participants"] = halves[0] + halves[1]
    first["team_name"] = name
    first["accompaniment"] = first.get("accompaniment") or second.get("accompaniment")
    m["teams"] = [t for t in m["teams"] if t is not second]
    for n, t in enumerate(m["teams"], 1):
        t["team_number"] = n
    return True


def groups(raw):
    """Each "(with ...)" group in the text as (what the old parser read, the
    whole group)."""
    for m in re.finditer(r"\(with ", raw, re.I):
        depth, j = 1, m.end()
        while j < len(raw) and depth:
            depth += {"(": 1, ")": -1}.get(raw[j], 0)
            j += 1
        yield re.match(r"\(with (.+?)\)", raw[m.start():], re.I).group(1), raw[m.end():j - 1]


def _key(name):
    return (clean_participant(name) or name).lower()


def fix_cut_group(m, old):
    whole = next((full for naive, full in groups(m.get("raw_description") or "")
                  if naive != full and (", ".join(links_in(naive)) or naive.strip()) == old), None)
    if whole is None:
        raise SystemExit(f"ABORT: match {m['id']} has no cut group for {old!r}")
    valets = links_in(whole)
    new = ", ".join(valets)
    team = next((t for t in m["teams"] if (t.get("accompaniment") or "") in (old, new)), None)
    if team is None:
        raise SystemExit(f"ABORT: match {m['id']} has no side with ringside {old!r}")
    out = {_key(v) for v in valets}
    before = team["participants"]
    kept = [p for p in before if _key(p) not in out]
    if team["accompaniment"] == new and kept == before:
        return False
    team["accompaniment"] = new
    team["participants"] = kept
    team["team_name"] = _renamed(team.get("team_name"), before, kept)
    return True


def _renamed(name, before, kept):
    """A side named by joining its wrestlers is named again from the ones left
    ("Seth Rollins & Murphy & Rezar" is "Seth Rollins & Murphy"); a team label
    in front of them is the name ("Gallus & Mark Coffey & Wolfgang" is
    "Gallus"); any other name stays."""
    parts = (name or "").split(" & ")
    keys, was = [_key(p) for p in parts], [_key(p) for p in before]
    if keys == was:
        return " & ".join(kept)
    if len(parts) > 1 and keys[1:] == was:
        return parts[0]
    return name


def split_fused(m, fused):
    loser = [t for t in m["teams"] if t.get("was_winner") is False]
    if len(loser) > 1:
        return False                      # already split
    if not loser or loser[0]["participants"] != fused:
        raise SystemExit(f"ABORT: match {m['id']}'s losing side changed")
    lose_str = re.split(r"\s+defeated\s+", m["raw_description"], maxsplit=1, flags=re.I)[1]
    lose_str = re.sub(r"\s+by\s+(\[\[[^\]]+\]\]|[A-Za-z][\w' \-]*?)\s*$", "", lose_str)
    sides = []
    for side in split_top(lose_str, [" and ", ", "]):
        t = parse_side(side)
        t["participants"] = [clean_participant(p) or p for p in t["participants"]]
        t.update(team_name=t["team_name"] or " & ".join(t["participants"]), was_winner=False,
                 match_outcome="loss")
        sides.append(t)
    names = [p for t in sides for p in t["participants"]]
    valets = {_key(v) for t in sides for v in (t["accompaniment"] or "").split(", ") if v}
    if sorted(names) != sorted(p for p in fused if _key(p) not in valets):
        raise SystemExit(f"ABORT: match {m['id']} split into {names}")
    winners = [t for t in m["teams"] if t.get("was_winner")]
    m["teams"] = winners + sides
    for n, t in enumerate(m["teams"], 1):
        t["team_number"] = n
    return True


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    import copy
    events = copy.deepcopy(data["events"]) if dry else data["events"]
    by_id = {m["id"]: m for e in events.values() for m in e["matches"]}
    changed = 0
    for mid, old in CUT_GROUPS:
        m = by_id.get(mid)
        if m is None:
            raise SystemExit(f"ABORT: match {mid} not found")
        changed += fix_cut_group(m, old)
    for mid, text, fused in FUSED:
        m = by_id.get(mid)
        if m is None or not (m.get("raw_description") or "").startswith(text):
            raise SystemExit(f"ABORT: match {mid} not found or its text changed")
        changed += split_fused(m, fused)
    for mid, text, halves, name in SPLIT_TEAMS:
        m = by_id.get(mid)
        if m is None or not (m.get("raw_description") or "").startswith(text):
            raise SystemExit(f"ABORT: match {mid} not found or its text changed")
        changed += join_team(m, halves, name)
    if not changed:
        print("already applied")
        return
    print(f"fixed {changed} sides")
    if dry:
        print("dry run: nothing written")
        return
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
