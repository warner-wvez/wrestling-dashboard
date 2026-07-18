#!/usr/bin/env python3
"""One-off corpus correction: fix verified-wrong episode numbers.

Episode numbers are a matter of public record, so each correction here is
required to agree with BOTH the corpus's own chronological sequence (episodes
are weekly and climb by one) AND an independent external source. Only
corrections that pass both go in; a number the sources disagree on is left
alone rather than guessed at.

Corrections:

  Raw, 2024-01-08: #1698 -> #1598. The stored run reads #1595 (Dec 18), #1597
    (Jan 1, Dec 25 skipped), #1698 (Jan 8), #1599 (Jan 15): a single-digit typo,
    a 6 where a 5 belongs, that both duplicates the real #1698 (2025-12-08) and
    leaves #1598 missing. WWE's own site and the Fandom results wiki both state
    the January 8 2024 Raw was episode #1598.
      https://www.wwe.com/shows/raw/2024-01-08
      https://prowrestling.fandom.com/wiki/January_8,_2024_Monday_Night_RAW_results

Deliberately NOT corrected: the five 2002-2003 SmackDown duplicate numbers
(#125, #134, #177, #205, #207). Those are two different shows a week apart
sharing a number, and the air dates are confirmed correct (era-accurate
Thursdays), so the fault is purely the number. But WWE never numbered SmackDown
episodes on-air, and the databases genuinely disagree about the count in this
window (some include the 1999 pilot, some use tape dates), so there is no ground
truth to correct to. Left as a documented data-quality note rather than guessed.

Rebuilds every derived index. Idempotent: a number already correct is skipped.

Run from repo root:
    uv run --with requests --with beautifulsoup4 python -m src.fix_episode_numbers [--dry-run]
"""
from __future__ import annotations

import collections
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

# (show_type, air_date, wrong_number) -> right_number
CORRECTIONS = {
    ("Raw", "2024-01-08", 1698): 1598,
}


def apply_corrections(events: dict) -> list[str]:
    applied = []
    for e in events.values():
        key = (e.get("show_type"), e.get("air_date"), e.get("episode_number"))
        if key in CORRECTIONS:
            e["episode_number"] = CORRECTIONS[key]
            applied.append(f"{key[0]} {key[1]}: #{key[2]} -> #{CORRECTIONS[key]}")
    return applied


def main() -> None:
    dry = "--dry-run" in sys.argv
    print("Loading existing full bundle...", flush=True)
    data = load_existing()
    events = data["events"]

    applied = apply_corrections(events)
    print(f"\n=== {len(applied)} episode-number corrections ===")
    for a in applied:
        print("  " + a)
    if not applied:
        print("  nothing to do (already correct)")
        return
    if dry:
        print("\n--dry-run: nothing written")
        return

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
    print("\n=== DONE ===  rebuilt with corrected episode numbers")


if __name__ == "__main__":
    main()
