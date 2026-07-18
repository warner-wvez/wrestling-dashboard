#!/usr/bin/env python3
"""One-off corpus correction: put taped Raws back on the night they aired.

19 Raw episodes are stored on the day they were TAPED, and every one of them is
labelled `date_derivation: "live-broadcast"`, which is the field asserting a
confidence it does not have. Cagematch files a taped show under its taping date,
the scraper copied that into air_date, and nothing noticed because nothing ever
checked the weekday. The result is Raw on a Saturday, and the Eddie Guerrero
tribute filed on 2005-11-13, which is the day Eddie died rather than the night
the show honouring him went out.

For a week-by-week watch companion this is not cosmetic: those shows sit in the
wrong week of the calendar, so a viewer marking a week watched either misses one
or watches it early.

The corpus can correct itself. Raw is weekly and its episode numbers are
sequential, so a misdated episode is pinned by its neighbours: the previous
episode plus seven days, the next episode minus seven. Where both neighbours are
themselves Mondays and agree, the date is simply implied. Where only one side is
usable (two misdated episodes in a row, over a year-end), that side is taken; the
pairs still land on consecutive Mondays, which is the check that they are right.

Spot-checked against the record before trusting the arithmetic:
  #500 lands on 2002-12-23, which is when Raw's 500th episode aired
  #651 lands on 2005-11-14, the Eddie Guerrero tribute, taped nowhere near the
       2005-11-13 the corpus had
  #709 lands on 2006-12-25, Tribute To The Troops, taped 2006-12-07

Not fixable here: the January 1 2001 Raw. It aired inside the corpus but was
taped 2000-12-29, so the same tape-date filing put it outside the 2001 scrape
boundary and it was never ingested at all. There is nothing to re-date. It needs
its card fetched.

Rebuilds events_by_date, because moving an event without it desyncs the calendar
(rebuild_indexes passes that index straight through). Idempotent: a Raw already
on a Monday is left alone, so a second run is a no-op.

Run from repo root:
    uv run --with requests --with beautifulsoup4 python -m src.fix_raw_air_dates [--dry-run]
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.build_update import ROOT, load_existing              # noqa: E402
from src.export_to_html import (                              # noqa: E402
    build_title_reigns, build_wrestler_reigns_by_date, build_wrestlers_index,
    inject, split_fused_multiman_sides, write_sharded)
from src.rebuild_indexes import bundle_derived_aliases        # noqa: E402
from src.roster_aliases import CURATED, build_canon_map, load_roster_snapshot  # noqa: E402
from src.ship_guard import atomic_write_text                  # noqa: E402

MONDAY = 0


def _iso(d: date) -> str:
    return d.isoformat()


def _parse(s: str) -> date:
    return date.fromisoformat(s)


def plan_corrections(events: dict) -> list[dict]:
    """Every Raw sitting on a night Raw does not air, with the date its episode
    number implies. Skips any it cannot pin from a neighbour."""
    raws = sorted(
        (e for e in events.values()
         if e.get("show_type") == "Raw" and e.get("episode_number") is not None
         and e.get("air_date")),
        key=lambda e: e["episode_number"])
    by_num = {e["episode_number"]: e for e in raws}
    occupied = {}
    for e in events.values():
        if e.get("air_date"):
            occupied.setdefault(e["air_date"], []).append(e)

    out = []
    for e in raws:
        if _parse(e["air_date"]).weekday() == MONDAY:
            continue
        prev, nxt = by_num.get(e["episode_number"] - 1), by_num.get(e["episode_number"] + 1)
        from_prev = (_iso(_parse(prev["air_date"]) + timedelta(days=7))
                     if prev and _parse(prev["air_date"]).weekday() == MONDAY else None)
        from_next = (_iso(_parse(nxt["air_date"]) - timedelta(days=7))
                     if nxt and _parse(nxt["air_date"]).weekday() == MONDAY else None)
        if from_prev and from_next and from_prev != from_next:
            continue                     # neighbours disagree: do not guess
        target = from_prev or from_next
        if not target:
            continue                     # both neighbours unusable
        clash = [o for o in occupied.get(target, [])
                 if o["id"] != e["id"] and o.get("show_type") == "Raw"]
        if clash:
            continue                     # never stack two Raws on one night
        out.append({"event": e, "from": e["air_date"], "to": target,
                    "agreed": bool(from_prev and from_next)})
    return out


def apply_corrections(events: dict, plan: list[dict]) -> None:
    for p in plan:
        e = p["event"]
        # tape_date is what the source actually knew; keep it, and stop the
        # record claiming the air date was observed live when it was inferred.
        if not e.get("tape_date"):
            e["tape_date"] = p["from"]
        e["air_date"] = p["to"]
        e["date_derivation"] = "episode-number-implied"


def rebuild_events_by_date(events: dict) -> dict:
    out: dict[str, list[int]] = {}
    for e in events.values():
        if e.get("air_date"):
            out.setdefault(e["air_date"], []).append(int(e["id"]))
    return {d: sorted(ids) for d, ids in sorted(out.items())}


def main() -> None:
    dry = "--dry-run" in sys.argv
    print("Loading existing full bundle...", flush=True)
    data = load_existing()
    events = data["events"]

    plan = plan_corrections(events)
    print(f"\n=== {len(plan)} Raws to move off a taping date ===")
    for p in plan:
        e = p["event"]
        print(f"  #{e['episode_number']:<5} {p['from']} -> {p['to']}   "
              f"{'both neighbours' if p['agreed'] else 'one neighbour '}  {e['title'][:46]}")
    if dry:
        print("\n--dry-run: nothing written")
        return
    if not plan:
        print("  nothing to do")
        return

    apply_corrections(events, plan)
    data["events_by_date"] = rebuild_events_by_date(events)

    import collections
    from datetime import datetime, timezone
    name_counts = collections.Counter(
        p for e in events.values() for m in e["matches"]
        for t in m["teams"] for p in t.get("participants", []) if p)
    # Same alias resolution as rebuild_indexes, or this rewrite would quietly
    # ship a different roster than the one that rebuild produces. Pinned to the
    # committed snapshot rather than a live scrape so the run is reproducible.
    canon = build_canon_map(name_counts,
                            roster_pairs=load_roster_snapshot() or [],
                            curated={**bundle_derived_aliases(data), **CURATED})
    split_fused_multiman_sides(events)
    title_reigns = build_title_reigns(events)
    wrestlers, wrestlers_by_name = build_wrestlers_index(
        events, canon=lambda n: canon.get(n, n), title_reigns=title_reigns)
    yrs = sorted({e["air_date"][:4] for e in events.values() if e["air_date"]})
    bundle = {
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                 "event_count": len(events),
                 "match_count": sum(e.get("match_count", len(e.get("matches") or []))
                                    for e in events.values()),
                 "year_range": [int(yrs[0]), int(yrs[-1])]},
        "events_by_date": data["events_by_date"], "events": events,
        "wrestlers": wrestlers, "wrestlers_by_name": wrestlers_by_name,
        "title_reigns": title_reigns,
        "wrestler_reigns_by_date": build_wrestler_reigns_by_date(title_reigns),
    }
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    write_sharded(bundle, ROOT, template)
    atomic_write_text(ROOT / "dist" / "wrestling-dashboard.html", inject(bundle, template))

    left = [e for e in events.values()
            if e.get("show_type") == "Raw" and e.get("air_date")
            and _parse(e["air_date"]).weekday() != MONDAY]
    print(f"\n=== DONE ===")
    print(f"  moved: {len(plan)}   Raws still off a Monday: {len(left)}")
    for e in left:
        print(f"    #{e.get('episode_number')}  {e['air_date']}  {e['title'][:50]}")


if __name__ == "__main__":
    main()
