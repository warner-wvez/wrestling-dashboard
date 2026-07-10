#!/usr/bin/env python3
"""Fill match durations, ratings, attendance, TV data and commentary from the
Cagematch event pages fetched by fetch_event_pages.py.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/backfill_event_pages.py [--dry-run]

## The desert this waters

fill_locations gave 858 non-Cagematch events a `cagematch_nr`. Their event pages
had never been read, so the SmackDownHotel third of the corpus in particular
carried nothing below the surface:

    source            events  durations  ratings  attendance  tv  commentary
    thesmackdownhotel    671        0%       0%         0%     0%      0%
    fandom                75       96%      ~          0%     0%      0%
    wikipedia            112      100%      ~          0%     0%      0%

The Cagematch-sourced 2183 events already carry all of this. This pass reads the
matching Cagematch page for each of the 858 and fills the gaps.

## Two joins, two rules

**Event fields** (attendance, tv_network, tv_rating, broadcast_type, commentary,
and venue) are written into the bundle's `events`, filled only when the shipped
value is absent. city/state/country and dates are deliberately left alone:
fill_locations owns those, and the event page renders foreign place names in
German (`Saudi-Arabien`).

**Match fields** (duration_seconds, match_guide_rating, and match_type /
stipulation / title_at_stake, which name the gimmick and the belt on the line)
are written into the shards, joined *within the event* by normkeyed, sorted team
members. This is the
match_key from fill_match_ratings.py minus the date, because the event nr already
pins the night. Match order is not used as a key: SmackDownHotel does not always
list matches in the same order the page does. A multi-way match whose sides the
two sources group differently (`A defeats B, C & D` as two teams vs four) simply
does not join, which costs a duration but never scatters one onto the wrong match.
If two matches in one event share a member key, that key is ambiguous and neither
is filled.

## The gate

Where a shard match already has a rating (from the date-keyed matchguide join)
and the event page also carries one, they must agree: same Cagematch community
rating seen at two scrape times, so votes drift a hair but the number does not.
More than 2% disagreeing means the within-event join is wrong, and the run aborts
rather than scatter durations across the corpus.

Idempotent: fill-when-absent means a second run changes nothing.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cagematch_scraper import build_event_from_html, SkipEvent  # noqa: E402
from src.roster_aliases import normkey  # noqa: E402
from src.export_to_html import inject  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

CACHE = ROOT / ".firecrawl" / "cm-events"
OUT = Path(__file__).resolve().parent / "out"
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
EVENT_FIELDS = ("attendance", "tv_network", "tv_rating", "broadcast_type",
                "commentary", "venue")
# A rating on the event page and one from the matchguide table are the same
# Cagematch number at two scrape times; votes drift, so allow a hair of movement.
RATING_TOLERANCE = 0.30
DISAGREE_CEILING = 0.02


def match_key(teams) -> str:
    sides = []
    for t in teams:
        members = [normkey(p) for p in t.get("participants", []) if p]
        sides.append("+".join(sorted(m for m in members if m)))
    return "|".join(sorted(s for s in sides if s))


def page_matches_by_key(matches) -> dict:
    """Index the page's matches by member key, dropping keys that collide within
    the event (a rematch on the same night is unusable as a key) and empties."""
    by_key = defaultdict(list)
    for m in matches:
        k = match_key(m["teams"])
        if k:
            by_key[k].append(m)
    return {k: v[0] for k, v in by_key.items() if len(v) == 1}


def main() -> None:
    dry = "--dry-run" in sys.argv

    html = (ROOT / "index.html").read_text(encoding="utf-8")
    bundle = json.loads(re.search(TAG, html, re.S).group(1))
    events = bundle["events"]

    targets = {eid: e for eid, e in events.items()
               if e.get("primary_source") != "cagematch" and e.get("cagematch_nr")}

    # eid -> (shard_path, [matches]); scan every shard once, as fill_match_ratings does.
    shards = {p: json.loads(p.read_text(encoding="utf-8"))
              for p in sorted((ROOT / "shards").glob("matches-*.json"))}
    matches_of = {}
    for p, by_event in shards.items():
        for eid, ms in by_event.items():
            matches_of[eid] = (p, ms)

    # Parse each target's cached page.
    parsed = {}                       # eid -> (event_dict, page_by_key)
    diag = Counter()
    missing_pages = []
    for eid, e in targets.items():
        nr = e["cagematch_nr"]
        path = CACHE / f"{nr}.html"
        if not path.exists():
            diag["page not fetched"] += 1
            missing_pages.append(nr)
            continue
        try:
            ev, ms = build_event_from_html(nr, path.read_text(encoding="utf-8"),
                                           f"https://www.cagematch.net/?id=1&nr={nr}")
        except SkipEvent:
            diag["page classified as house show / out-of-corpus"] += 1
            continue
        except ValueError as exc:
            diag["page unclassified"] += 1
            print(f"  unclassified nr={nr} eid={eid}: {exc}")
            continue
        parsed[eid] = (ev, page_matches_by_key(ms))

    # --- validation gate: agree with the ratings we already have --------------
    checked = agree = disagree = 0
    worst = []
    for eid, (ev, by_key) in parsed.items():
        _, ms = matches_of.get(eid, (None, []))
        for m in ms:
            r = m.get("match_guide_rating")
            if r is None:
                continue
            hit = by_key.get(match_key(m["teams"]))
            if not hit or hit["match_guide_rating"] is None:
                continue
            checked += 1
            delta = abs(hit["match_guide_rating"] - r)
            if delta <= RATING_TOLERANCE:
                agree += 1
            else:
                disagree += 1
                worst.append((delta, eid, r, hit["match_guide_rating"]))
    print(f"validation: {checked} matches carry a rating on both sides")
    print(f"  agree within {RATING_TOLERANCE}: {agree}   disagree: {disagree}")
    for d, eid, ours, theirs in sorted(worst, reverse=True)[:5]:
        print(f"    delta {d:.2f}  event {eid}  shard {ours} vs page {theirs}")
    if checked and disagree / checked > DISAGREE_CEILING:
        sys.exit(f"FATAL: {disagree}/{checked} ratings disagree. The within-event "
                 f"join is wrong; refusing to write.")

    # --- fill event fields (bundle) -------------------------------------------
    ev_fill = Counter()
    tv_networks, broadcast_types = Counter(), Counter()
    for eid, (ev, _) in parsed.items():
        e = events[eid]
        for f in EVENT_FIELDS:
            val = ev.get(f)
            if val is None or (isinstance(val, str) and not val.strip()):
                continue
            # `is None`, not falsy: attendance 0 is a real value (the 2020
            # empty-arena shows), and treating it as absent would re-fill it
            # every run and break idempotency.
            if e.get(f) is None:
                e[f] = val
                ev_fill[f] += 1
        if ev.get("tv_network"):
            tv_networks[ev["tv_network"]] += 1
        if ev.get("broadcast_type"):
            broadcast_types[ev["broadcast_type"]] += 1

    # --- fill match fields (shards) -------------------------------------------
    m_fill = Counter()
    touched_shards = set()
    for eid, (ev, by_key) in parsed.items():
        p, ms = matches_of.get(eid, (None, []))
        if p is None:
            m_fill["event has no match shard"] += 1
            continue
        for m in ms:
            hit = by_key.get(match_key(m["teams"]))
            if not hit:
                m_fill["match did not join (multi-way / unparsed)"] += 1
                continue
            m_fill["match joined"] += 1
            if m.get("duration_seconds") is None and hit["duration_seconds"] is not None:
                m["duration_seconds"] = hit["duration_seconds"]
                m_fill["+ duration_seconds"] += 1
                touched_shards.add(p)
            if m.get("match_guide_rating") is None and hit["match_guide_rating"] is not None:
                m["match_guide_rating"] = hit["match_guide_rating"]
                m_fill["+ match_guide_rating"] += 1
                touched_shards.add(p)
            # match_type carries the stipulation (Hardcore, Casket, No Holds
            # Barred) and names the title on the line; SmackDownHotel left it
            # blank on 81% of its matches, so a SmackDownHotel match reads
            # "Match" with no title or gimmick. Fill it, the stipulation and the
            # title from the page, only where the shipped value is absent.
            for f in ("match_type", "stipulation", "title_at_stake"):
                if not m.get(f) and hit.get(f):
                    m[f] = hit[f]
                    m_fill[f"+ {f}"] += 1
                    touched_shards.add(p)

    # --- report ---------------------------------------------------------------
    print(f"\ntargets {len(targets)}, pages parsed {len(parsed)}")
    for k, v in diag.most_common():
        print(f"  {v:>5}  {k}")
    print("\nevent fields filled (into the bundle):")
    for f in EVENT_FIELDS:
        print(f"  {ev_fill[f]:>5}  {f}")
    print("\nmatch fields filled (into the shards):")
    for k, v in m_fill.most_common():
        print(f"  {v:>6}  {k}")
    print("\ntv_network values seen (watch for German):")
    for v, c in tv_networks.most_common(12):
        print(f"  {c:>5}  {v!r}")
    print("broadcast_type values seen:", dict(broadcast_types))
    if missing_pages:
        print(f"\n{len(missing_pages)} target pages not yet fetched; run fetch_event_pages.py")

    if dry:
        print("\n--dry-run: nothing written")
        return

    for p in touched_shards:
        atomic_write_text(p, json.dumps(shards[p], ensure_ascii=False, separators=(",", ":")))
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    atomic_write_text(ROOT / "index.html", inject(bundle, template))
    print(f"\nrewrote index.html and {len(touched_shards)} shard(s)")


if __name__ == "__main__":
    main()
