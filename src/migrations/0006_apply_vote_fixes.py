"""
Apply the lineup check's hand-verified SmackDown Hotel vote fixes.

lineup-check/lineup_check.py writes these to lineup-check/out/auto-fixes.json
under "fix_result" and "add_match". Each kind is applied because every row it
selects was checked by hand on 2026-10-05:

  fix_result  our card, Cawthon and SmackDown Hotel list the same people, and
              Cawthon and SmackDown Hotel agree on a winner ours lacks or has
              wrong (31 of 31 right). Mostly "No Contest" on our card where
              both say someone won by DQ.
  add_match   a match missing from our card that Cawthon and SmackDown Hotel
              both list with the same people and the same result (14 of 14
              right). It goes in where Cawthon places it, the show's match
              numbers are renumbered in card order, and the show's watch
              links (keyed by match number in shards/media.json) move with
              their matches.

Safety gates:
  1. A result fix is located by event id + match id + stored text, and its
     winners must be exactly one of the match's sides.
  2. A match is never added when the same people already meet on that card
     (a second bout that night is for a person to judge).
  Plus: a corrected winner never moves a belt unless Cawthon says "to win the
  title"; "non-title" clears the match's title tag; DQ and count-out never move
  one. A fix that would otherwise move a belt is skipped.
  3. Ceilings from the 2026-10-05 run: 40 result fixes, 20 added matches.
  Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0006_apply_vote_fixes.py [--dry-run]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

FIXES = PROJECT_ROOT / "lineup-check" / "out" / "auto-fixes.json"
MEDIA = PROJECT_ROOT / "shards" / "media.json"
CEILING = {"fix_result": 40, "add_match": 20}
SOURCE = "Cawthon + SmackDown Hotel (lineup check)"
WIN_LOSS = {"win": ("win", "loss"), "dq": ("dq-win", "dq-loss"),
            "countout": ("countout-win", "countout-loss")}


def outcomes(teams, winners, kind):
    """Set was_winner / match_outcome on teams in place for this result."""
    for t in teams:
        if kind in ("no-contest", "draw"):
            t["was_winner"], t["match_outcome"] = None, kind
        else:
            won = set(t["participants"]) == set(winners)
            t["was_winner"] = won
            t["match_outcome"] = WIN_LOSS.get(kind, WIN_LOSS["win"])[0 if won else 1]


def renumber(matches):
    """Match numbers follow card order; returns {old number: new number}."""
    moved = {}
    for n, m in enumerate(matches, 1):
        if m.get("match_order") is not None and m["match_order"] != n:
            moved[str(m["match_order"])] = str(n)
        m["match_order"] = n
    return moved


def remap_media(entry, moved):
    """Move a show's per-match watch links to the renumbered match numbers.
    Keys that are match ids (never small card positions) are left alone."""
    matches = entry.get("matches") or {}
    entry["matches"] = {moved.get(k, k): v for k, v in matches.items()}
    return entry


def plan_results(events, items):
    todo = []
    for it in items:
        ev = events.get(str(it["event_id"]))
        m = next((x for x in (ev or {}).get("matches") or [] if str(x["id"]) == str(it["match_id"])), None)
        if m is None or (m.get("raw_description") or "") != it["ours"]:
            raise SystemExit(f"ABORT gate 1: match {it['match_id']} not found or its text changed")
        if not any(set(t["participants"]) == set(it["winners"]) for t in m["teams"]):
            raise SystemExit(f"ABORT gate 1: winners {it['winners']} are not a side of match {it['match_id']}")
        won = [t for t in m["teams"] if t.get("was_winner") is True]
        if len(won) == 1 and set(won[0]["participants"]) == set(it["winners"]):
            continue
        # A corrected winner must never move a belt by accident. A DQ or
        # count-out never moves one; "non-title" takes the title tag off
        # (Raw 2011-06-27: R-Truth beat Cena in a non-title tables match);
        # only "to win the title" may move one. Anything else is skipped.
        champ_side = [t for t in m["teams"] if t.get("was_champion_entering")]
        champ_loses = m.get("title_at_stake") and champ_side and \
            not any(set(t["participants"]) == set(it["winners"]) for t in champ_side)
        line = (it.get("cawthon") or "").lower()
        if champ_loses and it["outcome"] not in ("dq", "countout", "no-contest", "draw"):
            if "non-title" in line:
                it = {**it, "clear_title": True}
            elif "to win the title" not in line:
                print(f"  skipped (would move a belt): {it['match_id']} {it['ours'][:70]}")
                continue
        todo.append((m, it))
    return todo


def plan_adds(events, items):
    todo = []
    for it in items:
        ev = events.get(str(it["event_id"]))
        if ev is None:
            raise SystemExit(f"ABORT: event {it['event_id']} not found")
        people = {p for t in it["match"]["teams"] for p in t["participants"]}
        if any({p for t in m["teams"] for p in t["participants"]} == people
               for m in ev["matches"]):
            continue        # gate 2: these people already meet on this card
        todo.append((ev, it))
    return todo


def build_match(new_id, it):
    teams = [{"team_number": n, "team_name": " & ".join(t["participants"]), "accompaniment": None,
              "was_winner": t.get("was_winner"), "match_outcome": None,
              "was_champion_entering": False, "participants": t["participants"]}
             for n, t in enumerate(it["match"]["teams"], 1)]
    outcomes(teams, next((t["participants"] for t in it["match"]["teams"] if t.get("was_winner")), []),
             it["outcome"])
    return {"id": new_id, "match_order": None, "match_type": it["match"].get("match_type"),
            "stipulation": None, "title_at_stake": it["match"].get("title_at_stake"),
            "duration_seconds": it.get("duration_seconds"), "result_method": None,
            "match_guide_rating": None, "raw_description": it["cawthon"], "teams": teams,
            "source": SOURCE}


def main():
    dry = "--dry-run" in sys.argv
    fixes = json.loads(FIXES.read_text(encoding="utf-8"))
    for k, cap in CEILING.items():                                       # gate 3
        if len(fixes.get(k, [])) > cap:
            raise SystemExit(f"ABORT gate 3: {len(fixes[k])} {k}, ceiling {cap}")
    data = load_existing()
    events = data["events"]
    results, adds = plan_results(events, fixes["fix_result"]), plan_adds(events, fixes["add_match"])
    if not results and not adds:
        print("already applied")
        return
    print(f"applying fix_result={len(results)}, add_match={len(adds)}")
    if dry:
        print("dry run: nothing written")
        return
    for m, it in results:
        outcomes(m["teams"], it["winners"], it["outcome"])
        if it.get("clear_title"):
            m["title_at_stake"] = None
        m["result_note"] = f"Result corrected: {SOURCE} agree"
    next_id = max(m["id"] for e in events.values() for m in e["matches"]) + 1
    media = json.loads(MEDIA.read_text(encoding="utf-8"))
    touched = {}
    for ev, it in adds:
        new = build_match(next_id, it)
        next_id += 1
        ids = [m["id"] for m in ev["matches"]]
        at = ids.index(it["after_match_id"]) + 1 if it["after_match_id"] in ids else 0
        ev["matches"].insert(at, new)
        touched[str(ev["id"])] = ev
    for eid, ev in touched.items():
        ev["match_count"] = len(ev["matches"])
        moved = renumber(ev["matches"])
        if eid in media and moved:
            media[eid] = remap_media(media[eid], moved)
    atomic_write_text(MEDIA, json.dumps(media, ensure_ascii=False, separators=(",", ":")))
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
