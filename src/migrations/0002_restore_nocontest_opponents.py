"""
Restore six 2001 match sides erased by the roster cleanup.

The Phase 1b cleanup dropped junk team entries produced by hyphen/prose
splits ("X" from "X-Pac", "A" from "A-Train", "D" from "D-Lo Brown", and a
result-prose team name) but did not restore the real side they came from,
leaving one-team match cards on the live site. This migration re-adds the
real opponents, then rebuilds the wrestler index so profile stats and
rivalries agree with the cards again, and rewrites every artifact
(index.html, shards, dist) from the patched bundle.

Operates on the live artifacts (index.html core + shards), which are the
data source of truth on machines without data/wrestling.db. Idempotent:
each patch checks current state and skips if already applied.

Safety gates, in order:
  1. Every patched match is located by id AND its raw_description must
     contain the expected text, or the run aborts.
  2. Before any patch, the wrestler index is rebuilt as a no-op (using the
     alias map derived from the bundle itself) and must reproduce the
     committed index exactly. This proves the rebuild is faithful before
     it is trusted with the patched data.
  3. After patching, only an expected set of wrestler slugs may differ,
     and a reign rebuild from the patched events must equal one from the
     unpatched events (no title matches are touched). The committed
     title_reigns themselves are left untouched: they predate the roster
     cleanup's participant relabeling in the 2020+ era, so they no longer
     match ANY fresh rebuild (14 titles differ, e.g. "Andrade Fenix" vs
     "Andrade") - that is the known title-reign canonicalization backlog
     item, out of scope here.

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0002_restore_nocontest_opponents.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.export_to_html import (  # noqa: E402
    build_title_reigns, build_wrestlers_index, era_start, inject, write_sharded)
from src.ship_guard import atomic_write_text  # noqa: E402


def team(number, name, participants, was_winner, outcome, accompaniment=None):
    return {
        "team_number": number, "team_name": name, "accompaniment": accompaniment,
        "was_winner": was_winner, "match_outcome": outcome,
        "was_champion_entering": False, "participants": participants,
    }


# (event_id, match_id, must-appear-in-description, patch kind, payload)
PATCHES = [
    ("163", 977, "vs. X-Pac - No Contest",
     "add_team", team(2, "X-Pac", ["X-Pac"], None, "no-contest")),
    ("164", 983, "vs. X-Pac - No Contest",
     "add_team", team(2, "X-Pac", ["X-Pac"], None, "no-contest")),
    ("259", 1806, "D-Lo Brown vs. Shawn Stasiak - No Contest",
     "add_team", team(1, "D-Lo Brown", ["D-Lo Brown"], None, "no-contest")),
    ("104", 631, "defeated The Big Show to become the #1 Contender",
     "add_team", team(2, "The Big Show", ["The Big Show"], False, "loss")),
    ("147", 2574, "A-Train & John Cena - No Contest",
     "add_team", team(2, "A-Train & John Cena", ["A-Train", "John Cena"], None, "no-contest")),
    # Cleanup stripped only this team's prose-corrupted name; members survived.
    ("86", 530, "D-Von Dudley & Batista",
     "set_team_name", (2, "D-Von Dudley & Batista")),
]

# Slugs whose index entry may legitimately change: restored participants
# gain stats/appearances, and everyone in the six matches can pick up
# rivalry/partner count changes.
EXPECTED_CHANGED = {
    "x-pac", "d-lo-brown", "the-big-show", "a-train", "john-cena",
    "scotty-2-hotty", "eddie-guerrero", "shawn-stasiak",
    "chris-benoit", "kurt-angle", "rikishi", "d-von-dudley", "batista",
}


def jnorm(x):
    """JSON round-trip so freshly built records (which carry tuples) compare
    equal to committed records (which came back from JSON as lists)."""
    return json.loads(json.dumps(x))


def load_bundle(root: Path) -> dict:
    core = json.loads(re.search(
        r'<script id="wrestling-data"[^>]*>(.*?)</script>',
        (root / "index.html").read_text(encoding="utf-8"), re.S
    ).group(1).replace('<\\/', '</'))
    shard_data = {}
    for f in (root / "shards").glob("matches-*.json"):
        shard_data[int(f.stem.split("-")[1])] = json.loads(f.read_text(encoding="utf-8"))
    bundle = dict(core)
    bundle.pop("search_matches", None)
    bundle["meta"] = {k: v for k, v in core["meta"].items() if k != "shards"}
    events = {}
    for eid, ev in core["events"].items():
        year = (ev.get("air_date") or "")[:4]
        era = era_start(year) if year.isdigit() else 0
        matches = shard_data.get(era, {}).get(str(ev["id"]))
        assert matches is not None, f"event {eid} missing from shards"
        events[eid] = dict(ev, matches=matches)
    bundle["events"] = events
    return bundle


def derived_canon(bundle: dict):
    """Alias map recovered from the bundle itself: every name the last real
    build saw maps through wrestlers_by_name to its canonical display name."""
    by_name = bundle["wrestlers_by_name"]
    wrestlers = bundle["wrestlers"]
    table = {name: wrestlers[slug]["name"] for name, slug in by_name.items()
             if slug in wrestlers}
    return lambda n: table.get(n, n)


def apply_patches(events: dict) -> int:
    applied = 0
    for eid, mid, marker, kind, payload in PATCHES:
        match = next((m for m in events[eid]["matches"] if m["id"] == mid), None)
        assert match is not None, f"event {eid}: match {mid} not found"
        desc = match.get("raw_description") or ""
        assert marker in desc, f"event {eid} match {mid}: description mismatch: {desc!r}"
        if kind == "add_team":
            if any(t.get("team_name") == payload["team_name"] for t in match["teams"]):
                print(f"  event {eid} match {mid}: already patched, skipping")
                continue
            match["teams"].append(payload)
            match["teams"].sort(key=lambda t: t["team_number"])
        else:
            number, name = payload
            t = next(t for t in match["teams"] if t["team_number"] == number)
            if t.get("team_name") == name:
                print(f"  event {eid} match {mid}: already patched, skipping")
                continue
            t["team_name"] = name
        applied += 1
        print(f"  event {eid} match {mid}: {kind} -> {payload}")
    return applied


def main() -> None:
    root = PROJECT_ROOT
    bundle = load_bundle(root)
    events = bundle["events"]
    canon = derived_canon(bundle)

    print("Gate: no-op index rebuild must reproduce the committed index...")
    w0, wbn0 = build_wrestlers_index(events, canon=canon)
    assert wbn0 == bundle["wrestlers_by_name"], "derived alias map is not faithful (by_name)"
    w0 = jnorm(w0)
    drift = [s for s in bundle["wrestlers"] if w0.get(s) != bundle["wrestlers"][s]]
    drift += [s for s in w0 if s not in bundle["wrestlers"]]
    assert not drift, f"no-op rebuild drifted for {len(drift)} slugs, e.g. {drift[:5]}"
    print("  faithful.")

    reigns_before = jnorm(build_title_reigns(events))
    applied = apply_patches(events)
    if not applied:
        print("Nothing to do; all patches already applied.")
        return

    print("Rebuilding wrestler index from patched events...")
    wrestlers, wrestlers_by_name = build_wrestlers_index(events, canon=canon)
    wrestlers = jnorm(wrestlers)
    changed = sorted(s for s in wrestlers
                     if wrestlers.get(s) != bundle["wrestlers"].get(s))
    unexpected = set(changed) - EXPECTED_CHANGED
    assert not unexpected, f"unexpected wrestler changes: {sorted(unexpected)}"
    assert wrestlers_by_name == bundle["wrestlers_by_name"]
    print(f"  {len(changed)} wrestler entries changed: {changed}")

    reigns_after = jnorm(build_title_reigns(events))
    assert reigns_after == reigns_before, "patches changed title reigns; none should"

    bundle["wrestlers"] = wrestlers
    bundle["wrestlers_by_name"] = wrestlers_by_name
    template = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    write_sharded(bundle, root, template)
    atomic_write_text(root / "dist" / "wrestling-dashboard.html", inject(bundle, template))
    print(f"Applied {applied} patch(es); rewrote index.html, shards, dist.")


if __name__ == "__main__":
    main()
