#!/usr/bin/env python3
"""Attach Cagematch promos to the shows they happened on: shards/promos.json.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_promos.py [--dry-run]

parse_promos.py flattens 1236 promos; this hangs each on its event, so the event
page can carry a "Promos from this show" shelf next to the video-clip Moments
shelf. The output is a lazy sidecar keyed by event id, exactly like
shards/media.json and shards/profiles.json, so the page works without it.

## The join

By date, the way fill_match_ratings joins a match: Cagematch dates a promo by its
taping night, so the key is the event's `tape_date or air_date`. 208 promos
predate the 2001 corpus and another ~55 fall on nights with no Raw / SmackDown /
PPV (house shows, other brands); those are left unattached.

When two events share a night (a taping that produced two episodes, a PPV beside
a weekly show), date alone cannot choose, so the tie is broken by which show's
card actually featured the promo's workers. A promo whose talkers appear on
neither, on an ambiguous night, is dropped rather than guessed.

## The check

There is no second promo source to agree with, so correctness is read off the
workers: on a right join, the segment's participants are people who were on that
show. `worker_overlap` reports, across uniquely-dated promos, the share whose
workers touch the event's match card. It is not 100% and should not be, because a
manager or an authority figure cuts a promo without wrestling, but a collapse
would mean the date join is wrong.

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
PROMO_URL = "https://www.cagematch.net/?id=93&nr={}"


def event_participants(shards) -> dict:
    """eid -> set of normkeyed wrestlers who appear in that event's matches."""
    who = defaultdict(set)
    for by_event in shards.values():
        for eid, ms in by_event.items():
            for m in ms:
                for t in m.get("teams", []):
                    for p in t.get("participants", []):
                        k = normkey(p)
                        if k:
                            who[eid].add(k)
    return who


def main() -> None:
    dry = "--dry-run" in sys.argv

    promos = json.loads((OUT / "cm_promos.json").read_text(encoding="utf-8"))
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
    overlap_hits = overlap_seen = 0

    for p in promos:
        cand = by_date.get(p["date"], [])
        keys = {normkey(w) for w in p["workers"] if normkey(w)}
        if not cand:
            how["no event on that date"] += 1
            continue
        if len(cand) == 1:
            eid = cand[0]
            how["unique date"] += 1
            overlap_seen += 1
            if keys & who.get(eid, set()):
                overlap_hits += 1
        else:
            scored = sorted(cand, key=lambda e: len(keys & who.get(e, set())), reverse=True)
            best = len(keys & who.get(scored[0], set()))
            second = len(keys & who.get(scored[1], set())) if len(scored) > 1 else 0
            if best == 0 or best == second:
                how["ambiguous night, unresolved"] += 1
                continue
            eid = scored[0]
            how["ambiguous night, broken by workers"] += 1
        attached[eid].append({
            "title": p["title"],
            "workers": p["workers"],
            "rating": p["rating"],
            "votes": p["votes"],
            "url": PROMO_URL.format(p["cagematch_promo_nr"]),
        })

    # Sort each show's promos best-first; an unrated promo (rating None) sorts last.
    sidecar = {}
    for eid, lst in attached.items():
        lst.sort(key=lambda x: (x["rating"] is not None, x["rating"] or 0, x["votes"] or 0),
                 reverse=True)
        sidecar[eid] = lst

    total = sum(len(v) for v in sidecar.values())
    print("join:")
    for k, v in how.most_common():
        print(f"  {v:>5}  {k}")
    print(f"\nattached {total} promos to {len(sidecar)} events")
    if overlap_seen:
        print(f"worker_overlap: {overlap_hits}/{overlap_seen} "
              f"({overlap_hits/overlap_seen:.0%}) uniquely-dated promos touch the event's card")
    dist = Counter(len(v) for v in sidecar.values())
    print("promos per event:", {k: dist[k] for k in sorted(dist)})
    top = sorted(sidecar.items(), key=lambda kv: max((x["rating"] or 0) for x in kv[1]), reverse=True)[:3]
    print("\nhighest-rated shelves:")
    for eid, lst in top:
        e = events[eid]
        best = lst[0]
        print(f"  {e['air_date']} {e['show_type']}: {best['rating']} \"{best['title'][:50]}\" ({', '.join(best['workers'][:3])})")

    if dry:
        print("\n--dry-run: nothing written")
        return
    atomic_write_text(ROOT / "shards" / "promos.json",
                      json.dumps(sidecar, ensure_ascii=False, separators=(",", ":")))
    print(f"\nwrote shards/promos.json")


if __name__ == "__main__":
    main()
