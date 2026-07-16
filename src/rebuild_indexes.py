#!/usr/bin/env python3
"""Recompute every derived index from the existing full bundle and rewrite
index.html (lean core), shards/, and dist/wrestling-dashboard.html.

Use after changing roster aliases (src/roster_aliases.py) or title
normalization (src/export_to_html.py): the corpus itself (events + matches)
is untouched, so no DB and no scraping are needed. The alias layer prefers
the live SmackDown Hotel roster page, falls back to the committed snapshot,
and finally to alias pairs recovered from the current bundle itself, so the
merges already shipped can never regress just because the network is down.

Run:
    python -m src.rebuild_indexes
"""
from __future__ import annotations

import collections
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.build_update import ROOT, load_existing                        # noqa: E402
from src.export_to_html import (                                        # noqa: E402
    build_title_reigns, build_wrestler_reigns_by_date, build_wrestlers_index,
    inject, split_fused_multiman_sides, write_sharded)
from src.roster_aliases import (                                        # noqa: E402
    CURATED, build_canon_map, load_roster_snapshot, save_roster_snapshot,
    scrape_roster)
from src.ship_guard import atomic_write_text                            # noqa: E402


def resolve_roster_pairs():
    """(pairs, source_label): live scrape > committed snapshot > none."""
    try:
        pairs = scrape_roster()
        if pairs:
            save_roster_snapshot(pairs)
            return pairs, "live scrape"
    except Exception as exc:
        print(f"  roster scrape failed ({exc})", flush=True)
    pairs = load_roster_snapshot()
    if pairs:
        return pairs, "committed snapshot"
    return [], "none (bundle-derived aliases only)"


def bundle_derived_aliases(data):
    """Alias pairs already merged in the shipped bundle (name -> the name of the
    wrestler it merged into). Keeps existing merges alive even with no roster
    source.

    A pair whose target CURATED renames again is re-pointed at the final name,
    not dropped. build_canon_map applies its map once rather than transitively,
    so "Rudy Rude" -> "Robert Roode" alongside CURATED's "Robert Roode" ->
    "Bobby Roode" would strand Rudy Rude one hop short; dropping the pair instead
    orphaned him out of the merge entirely, which is worse.

    This used to be masked. The bundle's canonical was whatever CURATED pointed
    at, and those targets are final (test_curated_table_has_no_two_step_chains),
    so the target was almost never itself a CURATED key. Now that a wrestler is
    displayed under their most-used ring name, the canonical IS a corpus name and
    CURATED keys are corpus names, so the two collide constantly: the first
    rebuild displayed him as "Robert Roode", the second saw that name in CURATED
    and un-merged Rudy Rude. Rebuilds have to be idempotent or the roster rots a
    name at a time."""
    wrestlers = data.get("wrestlers") or {}
    out = {}
    for name, slug in (data.get("wrestlers_by_name") or {}).items():
        canonical = wrestlers.get(slug, {}).get("name")
        if not canonical or canonical == name or name in CURATED:
            continue
        out[name] = CURATED.get(canonical, canonical)   # follow one hop; targets are final
    return out


def main():
    print("Loading existing full bundle...", flush=True)
    data = load_existing()
    events = data["events"]

    name_counts = collections.Counter(
        p for e in events.values() for m in e["matches"]
        for t in m["teams"] for p in t.get("participants", []) if p)

    roster_pairs, source = resolve_roster_pairs()
    print(f"  roster pairs: {len(roster_pairs)} from {source}", flush=True)

    derived = bundle_derived_aliases(data)
    curated = {**derived, **CURATED}
    print(f"  curated aliases: {len(CURATED)} + {len(derived)} recovered from bundle",
          flush=True)

    canon = build_canon_map(name_counts, roster_pairs=roster_pairs, curated=curated)
    aliased = sum(1 for n in name_counts if canon[n] != n)
    print(f"  {len(name_counts)} distinct names -> {len({canon[n] for n in name_counts})} "
          f"canonical wrestlers ({aliased} names merged)", flush=True)

    # Un-fuse multi-man sides before anything reads the teams: the reign walk
    # takes the champion from them, the wrestler index counts rivals and tag
    # partners from them, and write_sharded ships them to the card.
    unfused = split_fused_multiman_sides(events)
    print(f"  un-fused multi-man sides: {unfused} matches", flush=True)

    print("Recomputing wrestler index + title reigns...", flush=True)
    old_wrestlers = len(data.get("wrestlers") or {})
    title_reigns = build_title_reigns(events)
    wrestlers, wrestlers_by_name = build_wrestlers_index(
        events, canon=lambda n: canon.get(n, n), title_reigns=title_reigns)
    wrbd = build_wrestler_reigns_by_date(title_reigns)

    yrs = sorted({e["air_date"][:4] for e in events.values() if e["air_date"]})
    match_count = sum(e.get("match_count", len(e.get("matches") or [])) for e in events.values())
    bundle = {
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                 "event_count": len(events), "match_count": match_count,
                 "year_range": [int(yrs[0]), int(yrs[-1])]},
        "events_by_date": data["events_by_date"], "events": events,
        "wrestlers": wrestlers, "wrestlers_by_name": wrestlers_by_name,
        "title_reigns": title_reigns, "wrestler_reigns_by_date": wrbd,
    }
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    core, shards = write_sharded(bundle, ROOT, template)
    atomic_write_text(ROOT / "dist" / "wrestling-dashboard.html", inject(bundle, template))

    idx, dist = ROOT / "index.html", ROOT / "dist" / "wrestling-dashboard.html"
    print("\n=== REBUILT ===")
    print(f"  events:    {len(events)} (unchanged)  matches: {match_count} (unchanged)")
    print(f"  wrestlers: {old_wrestlers} -> {len(wrestlers)}")
    print(f"  titles:    {len(title_reigns)}")
    print(f"  wrote index.html ({idx.stat().st_size / 1024 / 1024:.2f} MB), "
          f"{len(shards)} shards, dist ({dist.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
