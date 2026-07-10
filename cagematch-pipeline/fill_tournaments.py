#!/usr/bin/env python3
"""Hang each tournament on the show where its final happened: shards/tournaments.json.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_tournaments.py [--dry-run]

parse_tournaments.py flattens the brackets; this attaches each to the event on
its `end` date, the night the final was decided, and writes a lazy sidecar keyed
by event id like media.json. The event page shows a "Tournaments decided here"
shelf, with the winner kept behind the spoiler toggle.

## The join

By the tournament's final date against the event's `tape_date or air_date`. 135
of the 231 land on a unique corpus show; the rest concluded before 2001, or on an
NXT / house show the corpus does not carry. When two shows share that date, the
tie is broken by which card the winner actually wrestled on, since the winner of
a final was in the final. An unresolvable tie is dropped rather than guessed.

Idempotent: the sidecar is rebuilt from scratch each run.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.roster_aliases import normkey  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
TOURNEY_URL = "https://www.cagematch.net/?id=26&nr={}"


def event_participants(shards) -> dict:
    who = defaultdict(set)
    for by_event in shards.values():
        for eid, ms in by_event.items():
            for m in ms:
                for t in m.get("teams", []):
                    for p in t.get("participants", []):
                        if normkey(p):
                            who[eid].add(normkey(p))
    return who


def main() -> None:
    dry = "--dry-run" in sys.argv
    tourneys = json.loads((OUT / "cm_tournaments.json").read_text(encoding="utf-8"))
    bundle = json.loads(re.search(TAG, (ROOT / "index.html").read_text("utf-8"), re.S).group(1))
    events = bundle["events"]
    shards = {p: json.loads(p.read_text(encoding="utf-8"))
              for p in sorted((ROOT / "shards").glob("matches-*.json"))}
    who = event_participants(shards)

    by_date = defaultdict(list)
    for eid, e in events.items():
        by_date[e.get("tape_date") or e.get("air_date")].append(eid)

    attached = defaultdict(list)
    how = Counter()
    for t in tourneys:
        cand = by_date.get(t["end"], [])
        winners = {normkey(w) for w in t["winners"] if normkey(w)}
        if not cand:
            how["no corpus show on the final's date"] += 1
            continue
        if len(cand) == 1:
            eid = cand[0]
            how["unique date"] += 1
        else:
            scored = sorted(cand, key=lambda e: len(winners & who.get(e, set())), reverse=True)
            best = len(winners & who.get(scored[0], set()))
            second = len(winners & who.get(scored[1], set())) if len(scored) > 1 else 0
            if best == 0 or best == second:
                how["ambiguous date, unresolved"] += 1
                continue
            eid = scored[0]
            how["ambiguous date, broken by winner-on-card"] += 1
        attached[eid].append({
            "title": t["title"],
            "winners": t["winners"],
            "rating": t["rating"],
            "votes": t["votes"],
            "url": TOURNEY_URL.format(t["cagematch_tournament_nr"]),
        })

    sidecar = {}
    for eid, lst in attached.items():
        lst.sort(key=lambda x: (x["rating"] is not None, x["rating"] or 0), reverse=True)
        sidecar[eid] = lst

    total = sum(len(v) for v in sidecar.values())
    print("join:")
    for k, v in how.most_common():
        print(f"  {v:>5}  {k}")
    print(f"\nattached {total} tournaments to {len(sidecar)} shows")
    top = sorted(sidecar.items(), key=lambda kv: events[kv[0]]["air_date"], reverse=True)[:8]
    print("\nmost recent:")
    for eid, lst in top:
        e = events[eid]
        for x in lst:
            print(f"  {e['air_date']} {e['show_type']:9} {x['title'][:34]:34} -> {', '.join(x['winners'])}")

    if dry:
        print("\n--dry-run: nothing written")
        return
    atomic_write_text(ROOT / "shards" / "tournaments.json",
                      json.dumps(sidecar, ensure_ascii=False, separators=(",", ":")))
    print("\nwrote shards/tournaments.json")


if __name__ == "__main__":
    main()
