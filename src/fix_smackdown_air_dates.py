#!/usr/bin/env python3
"""One-off corpus correction: recompute estimated SmackDown air dates with the
era-aware broadcast schedule, resolve the collisions that surfaces, and rebuild
the bundle.

The corpus stored SmackDown air dates as tape_date + 2 days (derivation
'tape-plus-2-estimate'). That flat offset is only correct in the Thursday eras;
in the Friday eras it lands a day early and in the 2016-2019 Tuesday-live era it
lands two days late. This snaps each estimated date to SmackDown's actual air
night for its era (src/smackdown_schedule.py).

Snapping two nearby dates onto the same broadcast night exposes two pre-existing
data problems, which this also resolves:

  * Cross-source DUPLICATES (~7, pre-2005): the same show ingested from both
    Fandom ("Thursday Night Smackdown", no episode number) and Cagematch
    ("WWF SmackDown #N"), never deduped. Detected by identical match content on
    the same snapped date. We keep the Cagematch record (numbering matches the
    rest of the corpus), drop the Fandom twin, and move any watch links from the
    dropped event to the survivor.

  * DOUBLE-TAPINGS (~10, post-2005): two distinct episodes taped on back-to-back
    nights, the second airing the following week. Detected by disjoint match
    content. We re-space them onto consecutive broadcast weeks anchored to the
    prior episode's air date (ep-1 -> +7, +14), which restores the weekly
    cadence whether the odd episode aired a week earlier (year-end specials) or
    a week later (overseas-tour double-tapings).

Rebuilds the date/wrestler/title indexes and rewrites index.html + shards/ +
dist + shards/media.json. Asserts zero SmackDown collisions remain.

Run from repo root (after restoring pristine pre-fix artifacts):
    uv run src/fix_smackdown_air_dates.py
"""
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.build_update import load_existing                       # noqa: E402
from src.export_to_html import (                                 # noqa: E402
    build_title_reigns, build_wrestlers_index,
    build_wrestler_reigns_by_date, inject, write_sharded, TEMPLATE, OUT)
from src.ship_guard import atomic_write_text                     # noqa: E402
from src.smackdown_schedule import smackdown_air_date            # noqa: E402
from src.roster_aliases import build_canon_map, load_roster_snapshot  # noqa: E402

MEDIA_PATH = ROOT / "shards" / "media.json"


def _match_sig(ev):
    """Sorted set of participant-sets per match, to compare two events' cards."""
    out = []
    for m in ev.get("matches", []):
        ps = sorted(p for t in m.get("teams", []) for p in t.get("participants", []) if p)
        out.append("/".join(ps))
    return out


def _smackdowns_by_date(events):
    byd = {}
    for ev in events.values():
        if ev.get("show_type") == "SmackDown" and ev.get("air_date"):
            byd.setdefault(ev["air_date"], []).append(ev)
    return byd


def main():
    bundle = load_existing()
    events = bundle["events"]

    # 1. Era-aware air-date snap for every flat-estimate SmackDown.
    snapped = 0
    for ev in events.values():
        if ev.get("show_type") != "SmackDown":
            continue
        if ev.get("date_derivation") != "tape-plus-2-estimate":
            continue
        tape = ev.get("tape_date")
        if not tape:
            continue
        new_air, new_deriv = smackdown_air_date(date.fromisoformat(tape))
        ev["air_date"] = new_air.isoformat()
        ev["date_derivation"] = new_deriv
        snapped += 1
    print(f"Snapped {snapped} estimated SmackDown air dates to their era's night.")

    # 2. Resolve collisions created by the snap.
    media = json.loads(MEDIA_PATH.read_text()) if MEDIA_PATH.exists() else {}
    drop_ids = []
    media_moves = []          # (from_id, to_id)
    dups = respaced = 0

    for d, evs in sorted(_smackdowns_by_date(events).items()):
        if len(evs) < 2:
            continue
        evs.sort(key=lambda e: e.get("episode_number") or 0)
        lo, hi = evs[0], evs[1]
        sa, sb = _match_sig(lo), _match_sig(hi)
        shared = len(set(sa) & set(sb))
        is_dup = shared >= max(1, int(min(len(sa), len(sb)) * 0.6))

        if is_dup:
            # Keep the Cagematch record; drop the other (the Fandom twin).
            keep, drop = (lo, hi) if lo.get("primary_source") == "cagematch" else (hi, lo)
            drop_ids.append(str(drop["id"]))
            if str(drop["id"]) in media:
                media_moves.append((str(drop["id"]), str(keep["id"])))
            dups += 1
        else:
            # Double-taping: re-space onto consecutive broadcast weeks anchored
            # to the prior episode's air date (rebuild map fresh each time so
            # earlier fixes are visible; collisions are isolated, not chained).
            ep_map = {e.get("episode_number"): e["air_date"]
                      for e in events.values()
                      if e.get("show_type") == "SmackDown" and e.get("air_date")
                      and str(e["id"]) not in drop_ids}
            anchor = ep_map.get((lo.get("episode_number") or 0) - 1)
            if anchor:
                a = date.fromisoformat(anchor)
                lo["air_date"] = (a + timedelta(days=7)).isoformat()
                hi["air_date"] = (a + timedelta(days=14)).isoformat()
            else:
                hi["air_date"] = (date.fromisoformat(d) + timedelta(days=7)).isoformat()
            respaced += 1

    # Apply media moves, then drop the duplicate events.
    for frm, to in media_moves:
        media.setdefault(to, media.get(to) or media[frm])
        if media.get(to) is not media[frm]:
            # survivor already had media; keep both sets' links (dedupe by url)
            seen = {x.get("url") for x in media[to]}
            media[to] += [x for x in media[frm] if x.get("url") not in seen]
        del media[frm]
    for i in drop_ids:
        events.pop(i, None)
    print(f"Resolved collisions: deduped {dups} cross-source twins "
          f"(dropped events {drop_ids}), re-spaced {respaced} double-tapings.")
    if media_moves:
        print(f"  moved watch links: {media_moves}")

    # 3. Rebuild the date + wrestler + title indexes for consistency.
    events_by_date = {}
    for ev in events.values():
        events_by_date.setdefault(ev["air_date"], []).append(ev["id"])
    bundle["events_by_date"] = events_by_date

    name_counts = Counter(
        p for e in events.values() for m in e.get("matches", [])
        for t in m["teams"] for p in t.get("participants", []) if p)
    canon = build_canon_map(name_counts, roster_pairs=load_roster_snapshot() or [])
    title_reigns = build_title_reigns(events)
    wrestlers, wrestlers_by_name = build_wrestlers_index(
        events, canon=lambda n: canon.get(n, n), title_reigns=title_reigns)
    bundle["title_reigns"] = title_reigns
    bundle["wrestlers"] = wrestlers
    bundle["wrestlers_by_name"] = wrestlers_by_name
    bundle["wrestler_reigns_by_date"] = build_wrestler_reigns_by_date(title_reigns)
    bundle["meta"]["event_count"] = len(events)
    years = sorted({e["air_date"][:4] for e in events.values() if e.get("air_date")})
    if years:
        bundle["meta"]["year_range"] = [int(years[0]), int(years[-1])]

    # 4. Assert no SmackDown lands two shows on one day anymore.
    residual = {d: [e["id"] for e in evs]
                for d, evs in _smackdowns_by_date(events).items() if len(evs) > 1}
    assert not residual, f"unresolved SmackDown collisions: {residual}"
    print("Verified: zero SmackDown date collisions remain.")

    # 5. Write artifacts.
    template = TEMPLATE.read_text(encoding="utf-8")
    write_sharded(bundle, ROOT, template)
    atomic_write_text(OUT, inject(bundle, template))
    atomic_write_text(MEDIA_PATH, json.dumps(media, ensure_ascii=False,
                                             separators=(",", ":")))
    print(f"Wrote index.html + shards/ + {OUT.name} + media.json  "
          f"(events now {len(events)})")


if __name__ == "__main__":
    main()
