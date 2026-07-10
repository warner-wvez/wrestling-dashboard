#!/usr/bin/env python3
"""Attach Cagematch and Wrestling Observer ratings to the match shards.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_match_ratings.py [--dry-run]

84% of the corpus's 19521 matches carry no rating. The matchguide table only
lists matches somebody rated, so this cannot fix that: it reaches the ~7000
matches that have one. What it does add, for the first time, is the Wrestling
Observer star rating.

Adds four fields to a match:
    match_guide_votes    how many people voted (a 9.13 from 12 is not a 9.13)
    won_rating           '****1/2' as Cagematch prints it
    won_stars            4.5, because '1/2*' is half a star and sorts nowhere
                         near '*1/2', which is one and a half
    cagematch_match_nr   stable id, so a match can be linked back to its source
and fills `match_guide_rating` where it is null.

## The join, and how it is checked

Key is the Cagematch event date (which is the *taping* night, so `tape_date or
air_date`) plus the wrestlers, normkeyed and sorted. Names alone are not enough:
two matches on one night can share a fixture, and 31 such rows are dropped by
the parser rather than guessed at.

Before writing anything, the script re-derives ratings for the 3208 matches that
already have one and asserts they agree. If the join were wrong, it would be
scattering other matches' ratings across the corpus, and a rating is exactly the
kind of number nobody would notice was wrong.

Idempotent. Only shards/matches-*.json change; the bundle does not carry matches.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from parse_matchguide import fixture_key  # noqa: E402  (one key function, not two)
from src.roster_aliases import normkey  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
# A rating scraped from the event page and one printed in the matchguide are the
# same number seen at different times; votes drift, so allow a hair of movement.
RATING_TOLERANCE = 0.30


def match_key(cm_date, teams):
    sides = []
    for t in teams:
        members = [normkey(p) for p in t.get("participants", []) if p]
        sides.append("+".join(sorted(m for m in members if m)))
    return f"{cm_date}|" + "|".join(sorted(s for s in sides if s))


def main():
    dry = "--dry-run" in sys.argv
    mg = json.loads((OUT / "cm_matchguide.json").read_text(encoding="utf-8"))
    cm = json.loads((OUT / "cm_events.json").read_text(encoding="utf-8"))
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    events = json.loads(re.search(TAG, html, re.S).group(1))["events"]

    # Cagematch dates a match by its taping night, exactly as it dates the event.
    cm_date_of = {}
    for eid, e in events.items():
        nr = e.get("cagematch_nr")
        if nr and str(nr) in cm:
            x = cm[str(nr)]
            cm_date_of[eid] = x.get("tape_date") or x["air_date"]

    shards = {p: json.loads(p.read_text(encoding="utf-8"))
              for p in sorted((ROOT / "shards").glob("matches-*.json"))}

    # --- validation gate: agree with the ratings we already have --------------
    agree = disagree = checked = 0
    worst = []
    for by_event in shards.values():
        for eid, ms in by_event.items():
            d = cm_date_of.get(eid)
            if not d:
                continue
            for m in ms:
                if m.get("match_guide_rating") is None:
                    continue
                hit = mg.get(match_key(d, m["teams"]))
                if not hit or hit["match_guide_rating"] is None:
                    continue
                checked += 1
                delta = abs(hit["match_guide_rating"] - m["match_guide_rating"])
                if delta <= RATING_TOLERANCE:
                    agree += 1
                else:
                    disagree += 1
                    worst.append((delta, eid, m["match_guide_rating"],
                                  hit["match_guide_rating"], hit["fixture"][:48]))
    print(f"validation: {checked} matches have a rating on both sides")
    print(f"  agree within {RATING_TOLERANCE}: {agree}   disagree: {disagree}")
    for w in sorted(worst, reverse=True)[:5]:
        print(f"    delta {w[0]:.2f}  event {w[1]}  ours {w[2]} vs matchguide {w[3]}  {w[4]!r}")
    if checked and disagree / checked > 0.02:
        sys.exit(f"FATAL: {disagree}/{checked} ratings disagree. The join is wrong; "
                 f"refusing to scatter ratings across the corpus.")

    # --- fill ----------------------------------------------------------------
    add = Counter()
    for by_event in shards.values():
        for eid, ms in by_event.items():
            d = cm_date_of.get(eid)
            if not d:
                add["event not joined to cagematch"] += len(ms)
                continue
            for m in ms:
                hit = mg.get(match_key(d, m["teams"]))
                if not hit:
                    add["no matchguide row (unrated match)"] += 1
                    continue
                add["matched"] += 1
                if m.get("match_guide_rating") is None and hit["match_guide_rating"] is not None:
                    m["match_guide_rating"] = hit["match_guide_rating"]
                    add["+ cagematch rating"] += 1
                for src, dst in (("match_guide_votes", "match_guide_votes"),
                                 ("won_rating", "won_rating"),
                                 ("won_stars", "won_stars"),
                                 ("cagematch_match_nr", "cagematch_match_nr")):
                    if hit[src] is not None and m.get(dst) != hit[src]:
                        m[dst] = hit[src]
                        add[f"+ {dst}"] += 1

    for k, v in add.most_common():
        print(f"  {v:>6}  {k}")

    if dry:
        print("\n--dry-run: nothing written")
        return
    for p, by_event in shards.items():
        atomic_write_text(p, json.dumps(by_event, ensure_ascii=False, separators=(",", ":")))
    print(f"\nrewrote {len(shards)} shards")


if __name__ == "__main__":
    main()
