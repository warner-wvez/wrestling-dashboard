#!/usr/bin/env python3
"""One-off corpus correction: fix the casing of "SmackDown" in show titles.

The historical fandom lane titled its 2001-2003 SmackDown episodes "Thursday
Night Smackdown" with a lowercase d, against WWE's own spelling and against the
1,168 other titles in the corpus that write it "SmackDown". 149 titles carry the
wrong casing, so the same show reads two ways depending on which week you open.

Only the casing is touched. The numbered-vs-named format ("WWE SmackDown #205"
vs "Friday Night SmackDown") is left alone: that is real era branding, not a
typo, the same call made for the SmackDown episode numbers.

Titles live in the core events, not the match shards, so this rewrites index.html
and dist but leaves the shards byte-identical; no sw cache bump is needed.
Idempotent: a title already spelled correctly is skipped.

Run from repo root:
    uv run --with requests --with beautifulsoup4 python -m src.fix_show_titles [--dry-run]
"""
from __future__ import annotations

import collections
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.build_update import ROOT, load_existing              # noqa: E402
from src.export_to_html import (                              # noqa: E402
    build_title_reigns, build_wrestler_reigns_by_date, build_wrestlers_index,
    inject, split_fused_multiman_sides, strip_phantom_group_labels, write_sharded)
from src.rebuild_indexes import bundle_derived_aliases        # noqa: E402
from src.roster_aliases import CURATED, build_canon_map, load_roster_snapshot  # noqa: E402
from src.ship_guard import atomic_write_text                  # noqa: E402

# Whole-word Smackdown -> SmackDown (never inside another word).
_SMACKDOWN = re.compile(r'\bSmackdown\b')


def apply_corrections(events: dict) -> int:
    fixed = 0
    for e in events.values():
        title = e.get("title")
        if title and _SMACKDOWN.search(title):
            e["title"] = _SMACKDOWN.sub("SmackDown", title)
            fixed += 1
    return fixed


def main() -> None:
    dry = "--dry-run" in sys.argv
    print("Loading existing full bundle...", flush=True)
    data = load_existing()
    events = data["events"]

    would = sum(1 for e in events.values()
                if e.get("title") and _SMACKDOWN.search(e["title"]))
    print(f"\n=== {would} titles with lowercase 'Smackdown' ===")
    for e in list(events.values()):
        if e.get("title") and _SMACKDOWN.search(e["title"]):
            print(f"  {e['air_date']}  {e['title']!r} -> {_SMACKDOWN.sub('SmackDown', e['title'])!r}")
            break  # they are all the same shape; show one
    if dry:
        print("--dry-run: nothing written")
        return
    if not would:
        print("  nothing to do")
        return

    apply_corrections(events)

    name_counts = collections.Counter(
        p for e in events.values() for m in e["matches"]
        for t in m["teams"] for p in t.get("participants", []) if p)
    canon = build_canon_map(name_counts,
                            roster_pairs=load_roster_snapshot() or [],
                            curated={**bundle_derived_aliases(data), **CURATED})
    split_fused_multiman_sides(events)
    strip_phantom_group_labels(events)
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
    print(f"\n=== DONE ===  {would} titles corrected")


if __name__ == "__main__":
    main()
