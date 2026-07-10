#!/usr/bin/env python3
"""Apply the resolved identities to the shipped bundle.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/apply_merge.py

There is no local wrestling.db, so the bundle cannot be regenerated from source.
It does not need to be: `build_wrestlers_index` takes an events dict and a canon
callable, and `events` is recoverable exactly from the bundle's own event
metadata plus the match shards. Feeding it the shipped canon reproduces the
shipped index byte for byte (asserted below), so swapping in the corrected canon
changes only what the canon changes.

Only `wrestlers` and `wrestlers_by_name` are rewritten. Matches, events, title
reigns and the search index are untouched, so the shards stay valid.

Idempotent: running twice is a no-op.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_to_html import build_wrestlers_index, inject  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
TAG_RE = r'<script id="wrestling-data" type="application/json">(.*?)</script>'

# Names the roster should answer to that appear nowhere in the match data, so
# `build_wrestlers_index` cannot learn them from participants. "JBL" is the
# obvious one: Cagematch never records it, but it is what a viewer types.
# Without this the merge would make him unsearchable, since today the standalone
# 'JBL' entry is what search matches on.
EDITORIAL_ALIASES = {"JBL": "Bradshaw"}


def load_events(bundle):
    events = {eid: dict(ev, matches=[]) for eid, ev in bundle["events"].items()}
    for f in sorted((ROOT / "shards").glob("matches-*.json")):
        for eid, ms in json.loads(f.read_text(encoding="utf-8")).items():
            if eid in events:
                events[eid]["matches"] = ms
    return events


def rekey_assets(pairs, dry=False):
    """Copy an existing headshot (and its era/gimmick strips, and its profile)
    onto the canonical slug. Copies, never moves: the donor slug may still be
    referenced, and a move would make this non-idempotent."""
    moved = []
    for canon_slug, src in pairs:
        for d in ("roster-img",):
            s, t = ROOT / d / f"{src}.webp", ROOT / d / f"{canon_slug}.webp"
            if s.exists() and not t.exists():
                if not dry:
                    shutil.copy2(s, t)
                moved.append(f"{d}/{canon_slug}.webp")
        for d in ("era-img", "gimmick-img"):
            for s in sorted((ROOT / d).glob(f"{src}-*.webp")):
                idx = s.stem[len(src):]                       # '-0', '-11'
                t = ROOT / d / f"{canon_slug}{idx}.webp"
                if not t.exists():
                    if not dry:
                        shutil.copy2(s, t)
                    moved.append(f"{d}/{t.name}")
    # profiles shard is keyed by slug
    pf = ROOT / "shards" / "profiles.json"
    profiles = json.loads(pf.read_text(encoding="utf-8"))
    added = 0
    for canon_slug, src in pairs:
        if src in profiles and canon_slug not in profiles:
            profiles[canon_slug] = profiles[src]
            added += 1
    if added and not dry:
        atomic_write_text(pf, json.dumps(profiles, ensure_ascii=False,
                                         separators=(",", ":"), sort_keys=True) + "\n")
    return moved, added


def main():
    dry = "--dry-run" in sys.argv
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    bundle = json.loads(re.search(TAG_RE, html, re.S).group(1))
    old_w, old_bn = bundle["wrestlers"], bundle["wrestlers_by_name"]
    canon_map = json.loads((OUT / "canon_map.json").read_text(encoding="utf-8"))
    events = load_events(bundle)

    # Fidelity gate: the shipped canon must reproduce the shipped index from the
    # reconstructed events. If it does not, `events` is wrong and every number
    # downstream would silently shift.
    #
    # Only `wrestlers` is compared. `wrestlers_by_name` legitimately differs by
    # the editorial aliases, which are injected after the build and cannot be
    # relearned from participants.
    shipped_canon = lambda n: (old_w[old_bn[n]]["name"] if n in old_bn else n)  # noqa: E731
    check_w, _ = build_wrestlers_index(events, canon=shipped_canon,
                                       title_reigns=bundle["title_reigns"])
    norm = lambda o: json.loads(json.dumps(o))  # noqa: E731
    assert norm(check_w) == norm(old_w), "event reconstruction does not reproduce the shipped index"
    print("fidelity gate passed: reconstructed events reproduce the shipped index exactly")

    # Follow the chain. A name the resolver never saw (its only matches sit in
    # the 82 events that do not join to Cagematch) still has a shipped canonical,
    # and that canonical may itself be merging away: 'T-Bar' currently canons to
    # 'Dijak', and 'Dijak' becomes 'T-BAR'. Resolving one level leaves a 2-match
    # 'dijak' orphan beside the 35-match 'T-BAR'. This also makes the merge a
    # fixed point, so re-running is a genuine no-op.
    def new_canon(n):
        c = canon_map.get(n)
        if c:
            return c
        s = shipped_canon(n)
        return canon_map.get(s) or s
    wrestlers, by_name = build_wrestlers_index(events, canon=new_canon,
                                              title_reigns=bundle["title_reigns"])
    for alias, target in EDITORIAL_ALIASES.items():
        slug = next((s for s, w in wrestlers.items() if w["name"] == target), None)
        assert slug, f"editorial alias {alias!r} points at unknown wrestler {target!r}"
        by_name.setdefault(alias, slug)

    # Conservation: merging redistributes matches, it never creates or destroys.
    before = sum(w["total_matches"] for w in old_w.values())
    after = sum(w["total_matches"] for w in wrestlers.values())
    assert before == after, f"match total changed {before} -> {after}"
    for w in wrestlers.values():
        assert w["total_matches"] == w["wins"] + w["losses"] + w["draws"] + w["no_contests"]

    b = wrestlers.get("bradshaw")
    assert b and b["total_matches"] == 254, f"bradshaw merge wrong: {b and b['total_matches']}"
    assert "jbl" not in wrestlers and "john-bradshaw-layfield" not in wrestlers
    assert by_name["JBL"] == by_name["Bradshaw"] == "bradshaw"
    assert wrestlers["kane"]["total_matches"] == old_w["kane"]["total_matches"]
    assert wrestlers["luke-gallows"]["total_matches"] == old_w["luke-gallows"]["total_matches"]

    pairs = [tuple(l.split("\t")) for l in
             (OUT / "asset_rekey.tsv").read_text().splitlines() if l and not l.startswith("#")]
    moved, profiles_added = rekey_assets(pairs, dry=dry)

    print(f"wrestlers {len(old_w)} -> {len(wrestlers)}   "
          f"({len(old_w) - len(wrestlers)} duplicate identities removed)")
    print(f"wrestlers_by_name {len(old_bn)} -> {len(by_name)}   (aliases now route to the merged slug)")
    print(f"matches conserved: {before}")
    print(f"assets copied: {len(moved)}   profiles re-keyed: {profiles_added}")

    if dry:
        print("\n--dry-run: nothing written")
        return
    bundle["wrestlers"], bundle["wrestlers_by_name"] = wrestlers, by_name
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    atomic_write_text(ROOT / "index.html", inject(bundle, template))
    print(f"\nrewrote index.html")


if __name__ == "__main__":
    main()
