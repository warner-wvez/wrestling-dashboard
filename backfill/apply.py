#!/usr/bin/env python3
"""Put the joined 1985 to 2000 cards into the live bundle.

Mirrors src/add_new_shows.py: load the full bundle from index.html + shards,
give the new events IDs above every ID ever used (localStorage keys and deep
links of the 2001 on shows never move), merge, recompute every index with
src.rebuild_indexes.rebuild, refill the belt and titles sidecars, bump the
service worker cache, and write a run report. Sets `family` on every event,
old and new.

The ship gate runs before any write and refuses when: a lane failed or never
ran; a Cagematch-spine family's year count is more than 10% under the number
of Cagematch rows that hold a match, or a year is empty; a card lacks an air
date, show_type, family, primary_source, verification_status or a match; a
PPV or SNME date split is still open on review.csv.

    uv run --with requests --with beautifulsoup4 python backfill/apply.py [--dry-run]
"""
from __future__ import annotations

import collections
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.build_update import load_existing, restore_stable_ids  # noqa: E402
from src.add_new_shows import bump_cache  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402
from backfill.common import FAMILIES, OUT, YEARS, read_json, write_json  # noqa: E402

LANES = ("cm_results", "cawthon", "wiki", "sdh", "fandom", "join")
REQUIRED = ("air_date", "show_type", "family", "primary_source", "verification_status")
CAWTHON_SPINE = {"PrimeTime", "AllAmerican", "Mania"}


def index_counts_from(cm_cards) -> dict:
    """(show_type, year) -> Cagematch rows in range that hold a match, for the
    Cagematch-spine families: the floor the gate measures against."""
    c = collections.Counter()
    for e in cm_cards:
        year = int(e["air_date"][:4])
        if year in YEARS and e["matches"] and e["show_type"] not in CAWTHON_SPINE:
            c[(e["show_type"], year)] += 1
    return dict(c)


def gate(cards, status, index_counts) -> list[str]:
    problems = []
    for lane in LANES:
        s = status.get(lane)
        if not s:
            problems.append(f"lane {lane} never ran")
        elif not s.get("ok"):
            problems.append(f"lane {lane} failed: {s.get('detail', '')}")
    for c in cards:
        label = f"{c.get('show_type')} {c.get('air_date')} {c.get('title')}"
        for k in REQUIRED:
            if not c.get(k):
                problems.append(f"{label}: no {k}")
        if c.get("show_type") not in FAMILIES:
            problems.append(f"{label}: show_type outside the family table")
        if not c.get("matches"):
            problems.append(f"{label}: no match")
    have = collections.Counter((c["show_type"], int(c["air_date"][:4])) for c in cards if c.get("air_date"))
    for key, floor in sorted(index_counts.items()):
        n = have.get(key, 0)
        if n < floor * 0.9:
            problems.append(f"{key[0]} {key[1]}: {n} of {floor} index rows (under 90%)")
    return problems


def merge(data, cards) -> list[dict]:
    events = data["events"]
    for e in events.values():
        e.setdefault("family", FAMILIES.get(e.get("show_type"), "main"))
    new = [dict(c) for c in cards]
    for ev in new:
        ev["family"] = FAMILIES[ev["show_type"]]
    new = restore_stable_ids(new, {}, events)
    for ev in new:
        events[str(ev["id"])] = ev
        data["events_by_date"].setdefault(ev["air_date"], []).append(ev["id"])
    return new


def open_date_splits() -> list[dict]:
    p = OUT / "review.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["class"] == "date_split"]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cards = read_json(OUT / "cards.json")
    status = read_json(OUT / "run_status.json")
    counts = index_counts_from(read_json(OUT / "cm_cards.json"))
    problems = gate(cards, status, counts) + [f"date split open: {r['title']} {r['air_date']}" for r in open_date_splits()]
    if problems:
        print(f"=== SHIP BLOCKED ({len(problems)} problem(s), nothing written) ===")
        for p in problems[:200]:
            print("  - " + p)
        return 1
    by = collections.Counter((c["show_type"], c["verification_status"]) for c in cards)
    print(f"{len(cards)} cards pass the gate:")
    for k in sorted(by):
        print(f"  {k[0]:12s} {k[1]:14s} {by[k]}")
    if "--dry-run" in argv:
        print("--dry-run: nothing written")
        return 0
    data = load_existing()
    before = len(data["events"])
    added = merge(data, cards)
    from src.rebuild_indexes import rebuild
    rebuild(data)
    for script in ("fill_belts.py", "fill_titles.py"):
        res = subprocess.run([sys.executable, str(ROOT / "cagematch-pipeline" / script)],
                             cwd=ROOT, capture_output=True, text=True)
        print(res.stdout[-1200:])
        if res.returncode:
            print(res.stderr)
            raise RuntimeError(f"{script} failed; the bundle is rebuilt but the sidecars are not")
    sw = ROOT / "sw.js"
    text, version = bump_cache(sw.read_text(encoding="utf-8"))
    atomic_write_text(sw, text)
    report = {"added": len(added), "events_before": before, "events_after": len(data["events"]),
              "first_id": added[0]["id"] if added else None, "last_id": added[-1]["id"] if added else None,
              "by_status": {f"{k[0]}|{k[1]}": v for k, v in sorted(by.items())}, "sw_cache": version}
    write_json(OUT / "apply_report.json", report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
