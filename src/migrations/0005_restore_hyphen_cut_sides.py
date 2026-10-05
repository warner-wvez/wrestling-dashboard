"""
Restore "vs." result sides that a hyphen inside a name cut short.

Both scrapers removed the " - No Contest" tail of a "vs." result with a regex
that stopped at the FIRST hyphen anywhere, so a name with a hyphen took the
rest of its side with it: D-Von Dudley vanished from Dudley Boyz matches,
R-Truth's whole side vanished from "Drew McIntyre vs. R-Truth - No Contest",
The X-Factor became "The X" and Rated-RKO vs D-Generation X became one team
called "Rated". The parsers are fixed (_VS_TAIL_RE); this re-derives the
affected matches from their stored raw_description and rebuilds every index.

Safety gates, in order:
  1. Shape. A match is touched when its stored sides are what the OLD parser
     produced (after the junk cleanup a later pass ran), or when the new parse
     only adds to them: every name it brings is in the match's own stored text.
     It never collapses sides.
  2. No silent removals. A patched match may only lose a name that is the
     front of a hyphenated name in its own text ("The X" of "The X-Factor"),
     or an escort the broken cut leaked onto a side as a wrestler.
  3. Count. Aborts outside the window measured when this was written.

Idempotent: once applied the stored sides match the NEW parser, so gate 1
skips them and the run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0005_restore_hyphen_cut_sides.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bs4 import BeautifulSoup  # noqa: E402

import src.cagematch_scraper as cagematch  # noqa: E402
from src.build_update import load_existing  # noqa: E402

CUTOFF = "2020-01-01"
OLD_TAIL = re.compile(r"\s*-\s*.*$")
EXPECTED = range(20, 27)        # measured 2026-10-05: 23


@contextmanager
def _tail(pattern):
    saved = cagematch._VS_TAIL_RE
    cagematch._VS_TAIL_RE = pattern
    try:
        yield
    finally:
        cagematch._VS_TAIL_RE = saved


def parse(raw, pattern=None):
    div = BeautifulSoup(f'<div><div class="MatchResults">{raw}</div></div>', "html.parser").div
    if pattern is None:
        return cagematch.parse_match_block(div, 1)["teams"]
    with _tail(pattern):
        return cagematch.parse_match_block(div, 1)["teams"]


def _sides(teams, clean=False):
    """Non-empty sides. clean=True applies the junk-name cleanup a later pass
    already ran on the stored data (it dropped the "D" the cut left of
    "D-Von"), so the old parse is compared the way it was actually stored."""
    from src.export_to_html import clean_participant
    out = []
    for t in teams:
        names = t.get("participants") or []
        if clean:
            names = [c for c in map(clean_participant, names) if c]
        if names:
            out.append(names)
    return out


def plan(events):
    patches, already = [], 0
    for ev in events.values():
        if ev["air_date"] >= CUTOFF:
            continue
        for m in ev.get("matches") or []:
            raw = m.get("raw_description") or ""
            if not re.search(r"\s+vs\.?\s+", raw) or not re.search(r"\w-\w", raw):
                continue
            old, new = parse(raw, OLD_TAIL), parse(raw)
            if _sides(old) == _sides(new):
                continue
            stored = _sides(m.get("teams") or [])
            if stored == _sides(new):
                already += 1
                continue
            if stored not in (_sides(old), _sides(old, clean=True)) and \
                    len(stored) > len(_sides(new)):                     # gate 1
                continue
            new_names = [p for side in _sides(new) for p in side]
            if any("match" in p.lower() or re.search(r"\b(?:non-title|ended)\b", p, re.I)
                   for p in new_names):
                continue      # the new parse is not clean for this line either: leave it
            before = {p for s in stored for p in s}
            after = {p for s in _sides(new) for p in s}
            escorts = " ".join(re.findall(r"\(\s*w\s*/[^()]*\)", raw))
            for gone in before - after:                                 # gate 2
                # A hyphen fragment, or an escort the broken cut leaked onto a
                # side (Benoit's "(w/ ... D-Von Dudley ...)" on 2005-06-09).
                fragment = re.search(re.escape(gone) + r"-\w", raw)
                if not (fragment or gone in escorts):
                    raise SystemExit(f"ABORT gate 2: {ev['air_date']} would drop {gone!r}: {raw}")
            patches.append((ev, m, new))
    return patches, already


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    patches, already = plan(data["events"])
    if not patches:
        print(f"already applied ({already} matches carry the full sides)")
        return
    print(f"measured: {len(patches)} to patch, {already} already fixed")
    if len(patches) not in EXPECTED:                                    # gate 3
        raise SystemExit(f"ABORT gate 3: {len(patches)} matches to patch, expected "
                         f"{EXPECTED.start} to {EXPECTED.stop - 1}")
    print(f"patching {len(patches)} matches")
    for ev, m, new in patches[:8]:
        print(f"  e.g. {ev['air_date']} {_sides(m['teams'])} -> {_sides(new)}")
    if dry:
        print("dry run: nothing written")
        return
    for ev, m, new in patches:
        m["teams"] = new
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
