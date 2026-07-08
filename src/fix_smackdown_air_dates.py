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


def _is_cross_source_dup(a, b):
    """True only when a and b look like the SAME show ingested from two sources
    (one Cagematch, one not) with near-identical cards. The cross-source
    precondition guards the destructive drop path: two same-source episodes on
    one date are far more likely genuine back-to-back tapings than a twin, so
    they must never be silently deleted on card overlap alone."""
    sa, sb = _match_sig(a), _match_sig(b)
    if not sa or not sb:
        return False
    sources = {a.get("primary_source"), b.get("primary_source")}
    cross = "cagematch" in sources and any(s != "cagematch" for s in sources)
    shared = len(set(sa) & set(sb))
    return cross and shared >= max(1, int(min(len(sa), len(sb)) * 0.6))


def _occupied_smackdown_dates(events, exclude_ids):
    """Every date currently held by a SmackDown, minus the ids being dropped."""
    return {e["air_date"] for e in events.values()
            if e.get("show_type") == "SmackDown" and e.get("air_date")
            and str(e["id"]) not in exclude_ids}


def _next_free_week(after_iso, occupied):
    """First weekly broadcast slot strictly after after_iso that no other
    SmackDown already holds, so respacing can never manufacture a new collision."""
    d = date.fromisoformat(after_iso)
    for _ in range(520):                       # 10 years of weeks: a hard stop
        d = d + timedelta(days=7)
        if d.isoformat() not in occupied:
            return d.isoformat()
    raise RuntimeError(f"no free SmackDown week within 10 years after {after_iso}")


def _merge_media(media, frm, to):
    """Move frm's watch links into to, bucket by bucket (show / matches /
    moments), de-duping by url. media entries are dicts of those three buckets,
    NOT flat lists -- treating them as lists corrupts/ crashes the merge."""
    src = media.get(frm)
    if src is None:
        return
    dst = media.setdefault(to, {"show": [], "matches": {}, "moments": []})
    for bucket in ("show", "moments"):
        existing = dst.setdefault(bucket, [])
        seen = {x.get("url") for x in existing}
        existing.extend(x for x in src.get(bucket, []) if x.get("url") not in seen)
    dst_matches = dst.setdefault("matches", {})
    for key, links in src.get("matches", {}).items():
        existing = dst_matches.setdefault(key, [])
        seen = {x.get("url") for x in existing}
        existing.extend(x for x in links if x.get("url") not in seen)
    del media[frm]


def resolve_collisions(events, media):
    """Resolve every SmackDown date that carries 2+ shows after the snap, in
    place. Returns (drop_ids, dups, respaced).

    A collided date can carry a cross-source twin AND a double-taping at once
    (3+ shows), so it folds EVERY event on the date against the survivors kept
    so far -- not just the first two. A cross-source twin is dropped (its watch
    links merged into the survivor); everything distinct is kept; the extra
    survivors are respaced onto later broadcast weeks that no other SmackDown
    holds, so respacing can never manufacture a fresh collision.
    """
    drop_ids = []
    media_moves = []          # (from_id, to_id)
    dups = respaced = 0

    for d, evs in sorted(_smackdowns_by_date(events).items()):
        if len(evs) < 2:
            continue
        evs.sort(key=lambda e: e.get("episode_number") or 0)

        survivors = []
        for ev in evs:
            twin = next((s for s in survivors if _is_cross_source_dup(s, ev)), None)
            if twin is None:
                survivors.append(ev)
                continue
            # Keep the Cagematch record; drop the other (usually the Fandom twin).
            if twin.get("primary_source") == "cagematch":
                keep, drop = twin, ev
            else:
                keep, drop = ev, twin
                survivors[survivors.index(twin)] = ev
            drop_ids.append(str(drop["id"]))
            if str(drop["id"]) in media:
                media_moves.append((str(drop["id"]), str(keep["id"])))
            # Audit trail: log the card that justified a destructive drop.
            print(f"  dedup {d}: dropping event {drop['id']} "
                  f"(source={drop.get('primary_source')}, {len(_match_sig(drop))} matches) "
                  f"into {keep['id']} (source={keep.get('primary_source')})")
            dups += 1

        # Distinct survivors sharing the date are double-tapings: the earliest
        # (lowest episode number) keeps the date; each later one moves to the
        # next broadcast week that no other SmackDown holds. Reserving as we go
        # (occupied is recomputed live) means two extras never land together.
        for ev in survivors[1:]:
            occupied = _occupied_smackdown_dates(events, drop_ids)
            ev["air_date"] = _next_free_week(d, occupied)
            ev["date_derivation"] = "air-night-estimate"
            respaced += 1

    # Apply media moves (bucket-wise merge), then drop the duplicate events.
    for frm, to in media_moves:
        _merge_media(media, frm, to)
    for i in drop_ids:
        events.pop(i, None)
    if media_moves:
        print(f"  moved watch links: {media_moves}")
    return drop_ids, dups, respaced


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
    media = json.loads(MEDIA_PATH.read_text(encoding="utf-8")) if MEDIA_PATH.exists() else {}
    drop_ids, dups, respaced = resolve_collisions(events, media)
    print(f"Resolved collisions: deduped {dups} cross-source twins "
          f"(dropped events {drop_ids}), re-spaced {respaced} double-tapings.")

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
