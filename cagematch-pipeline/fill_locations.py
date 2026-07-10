#!/usr/bin/env python3
"""Fill venue and location from Cagematch, and backfill the event join key.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_locations.py [--dry-run]

863 of the 3046 events carry no `cagematch_nr`, and they are exactly the ones
with a location problem:

    673 from thesmackdownhotel   no venue, no city, nothing
    114 from wikipedia           venue + city, but city is "Houston, Texas"
     76 from fandom              same, and some read "Hartford, Connecticut , USA"

The other 2183 came from Cagematch and already have venue/city/state/country
split properly. So this is a join problem, not a scraping problem.

## Joining

By date and show type, which resolves 781. Two things break that:

**Cagematch dates the taping, not the broadcast.** parse_raw already routes
SmackDown through the era-aware air-date rule. Raw needs no such rule *except*
in 2020, when WWE taped two episodes in a night at the Performance Center:
Cagematch files RAW #1405 and #1406 both on 2020-04-27, while the dashboard
files them on the 27th and on May 4th. The second episode has no Cagematch row
on its broadcast date at all.

**Episode numbers disagree between sources.** Cagematch calls the 2001-01-04
SmackDown #73; Fandom calls it #72, consistently, for 74 straight events. The
venue (Freeman Coliseum, San Antonio) proves the date join is the correct one,
so episode number cannot be used as a primary key. It can be used as a
*tiebreaker* once the per-source offset is learned from the events the date join
already settled, which is what happens below. Fandom SmackDown is +1;
SmackDownHotel is 0.

Every match is one-to-one: a Cagematch event already claimed cannot be claimed
again. 850 of 863 resolve; the 13 that do not are left alone.

## Writing

Venue is filled when absent and never overwritten. Where both sides have one
they are the same building under two names (`Fleet Center`/`FleetCenter`,
`Bell Centre`/`Molson Centre`), and the shipped name is the more familiar. Those
30 disagreements are written to out/location_conflicts.tsv rather than resolved.

City/state/country are taken from Cagematch wholesale, because the shipped
strings are the dirty ones: they jam the state into the city field, some carry a
stray space (`Hartford, Connecticut , USA`), and at least one is simply wrong
(the 2001-08-16 SmackDown is filed under Salt Lake City; the arena is in West
Valley City). Every change is logged.

Idempotent: a second run finds every event already joined and filled.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from parse_raw import US_STATES  # noqa: E402  (one list of states, not two)
from src.export_to_html import inject  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
# Cagematch's own date can precede the broadcast by a taping gap; anything
# further apart than this is a different show, not the same one dated oddly.
WINDOW_DAYS = 10


def _d(s):
    return date(*map(int, s.split("-")))


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").replace(",", " ").lower()).strip()


def main():
    dry = "--dry-run" in sys.argv
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    bundle = json.loads(re.search(TAG, html, re.S).group(1))
    events = bundle["events"]
    cm = json.loads((OUT / "cm_events.json").read_text(encoding="utf-8"))

    by_ds, by_ep = defaultdict(list), defaultdict(list)
    for e in cm.values():
        by_ds[(e["air_date"], e["show_type"])].append(e)
        if e.get("episode_number"):
            by_ep[(e["show_type"], e["episode_number"])].append(e)

    # Learn the per-source episode offset from every event whose Cagematch
    # counterpart is already known: the ones carrying a cagematch_nr, plus the
    # ones the date join settles on its own. Reading only the latter would make
    # the script useless on a second run, when nothing is left unjoined to learn
    # from, and any event needing the episode tiebreaker would go unresolved.
    off = defaultdict(Counter)
    for e in events.values():
        peer = None
        nr = e.get("cagematch_nr")
        if nr and str(nr) in cm:
            peer = cm[str(nr)]
        else:
            c = by_ds.get((e["air_date"], e["show_type"]), [])
            if len(c) == 1:
                peer = c[0]
        if peer and e.get("episode_number") and peer.get("episode_number"):
            off[(e["primary_source"], e["show_type"])][
                peer["episode_number"] - e["episode_number"]] += 1
    OFFSET = {k: v.most_common(1)[0][0] for k, v in off.items()}

    claimed = {str(e["cagematch_nr"]) for e in events.values() if e.get("cagematch_nr")}
    match, how = {}, Counter()

    def take(eid, x, tag):
        nr = str(x["cagematch_nr"])
        if nr in claimed:
            return False
        claimed.add(nr)
        match[eid] = x
        how[tag] += 1
        return True

    for eid, e in events.items():
        if e.get("cagematch_nr"):
            nr = str(e["cagematch_nr"])
            if nr in cm:                       # already joined: still fill its gaps
                match[eid] = cm[nr]
                how["already-joined"] += 1
            continue
        c = by_ds.get((e["air_date"], e["show_type"]), [])
        if len(c) == 1 and take(eid, c[0], "date"):
            continue
        ep, o = e.get("episode_number"), OFFSET.get((e["primary_source"], e["show_type"]))
        if len(c) > 1 and ep is not None and o is not None:
            m = [x for x in c if x.get("episode_number") == ep + o]
            if len(m) == 1 and take(eid, m[0], "same-date+episode"):
                continue
        # Two PPVs can share a night (WrestleMania Saturday and NXT Stand &
        # Deliver), and a PPV has no episode number. The venue settles it: they
        # are in different buildings, and Cagematch names them the same way the
        # shipped row does. Titles would not settle it, since Cagematch calls
        # WrestleMania XL "Saturday" where the dashboard calls it "Night 1".
        if len(c) > 1 and e.get("venue"):
            m = [x for x in c if x.get("venue") and _norm(x["venue"]) == _norm(e["venue"])]
            if len(m) == 1 and take(eid, m[0], "same-date+venue"):
                continue
        if not c and ep is not None and o is not None:
            m = [x for x in by_ep.get((e["show_type"], ep + o), [])
                 if abs((_d(x["air_date"]) - _d(e["air_date"])).days) <= WINDOW_DAYS
                 and str(x["cagematch_nr"]) not in claimed]
            if len(m) == 1 and take(eid, m[0], "episode+window"):
                continue
        how["unresolved"] += 1

    filled, conflicts, changes = Counter(), [], []
    for eid, x in match.items():
        e = events[eid]
        nr = x["cagematch_nr"]
        if not e.get("cagematch_nr"):
            e["cagematch_nr"] = nr
            e["cagematch_url"] = f"https://www.cagematch.net/?id=1&nr={nr}"
            filled["cagematch_nr"] += 1

        if x.get("venue"):
            if not e.get("venue"):
                e["venue"] = x["venue"]
                filled["venue"] += 1
            elif _norm(e["venue"]) != _norm(x["venue"]):
                conflicts.append((e["air_date"], e["show_type"], e["venue"], x["venue"]))

        if x.get("city"):
            before = (e.get("city"), e.get("state_province"), e.get("country"))
            after = (x["city"], x.get("state_province"), x.get("country"))
            if before != after:
                if before[0] and _norm(" ".join(filter(None, before))) != \
                                 _norm(" ".join(filter(None, after))):
                    changes.append((e["air_date"], e["show_type"],
                                    " / ".join(str(v) for v in before),
                                    " / ".join(str(v) for v in after)))
                e["city"], e["state_province"], e["country"] = after
                filled["city"] += 1

        # SmackDown carries an explicit taping night. A Raw whose Cagematch date
        # precedes its broadcast was taped that night too (the 2020 double
        # tapings), and saying so is the whole point of the "Taped ..." line.
        if not e.get("tape_date"):
            tape = x.get("tape_date")
            if not tape and x["air_date"] < e["air_date"]:
                tape = x["air_date"]
            if tape and tape < e["air_date"]:
                e["tape_date"] = tape
                filled["tape_date"] += 1

    # The events that never join keep whatever the original scrape gave them,
    # which for the Wikipedia and Fandom rows is a jammed string like
    # "Toronto, Ontario , Canada". Split it in place. This invents nothing: the
    # parts are already there, just in the wrong field and with stray spaces.
    for e in events.values():
        if e.get("cagematch_nr") or not e.get("city") or "," not in e["city"]:
            continue
        parts = [p.strip() for p in e["city"].split(",") if p.strip()]
        if len(parts) >= 3:
            e["city"], e["state_province"], e["country"] = parts[0], parts[1], parts[-1]
        elif len(parts) == 2 and parts[1] in US_STATES:
            e["city"], e["state_province"], e["country"] = parts[0], parts[1], "USA"
        else:
            continue
        how["unjoined-city-split"] += 1

    print("join:")
    for k, v in how.most_common():
        print(f"  {v:>5}  {k}")
    print(f"\nlearned episode offsets: {OFFSET}")
    print("\nfilled:")
    for k, v in filled.most_common():
        print(f"  {v:>5}  {k}")
    print(f"\nvenue conflicts (kept the shipped name): {len(conflicts)}")
    print(f"city rewrites that changed the text:     {len(changes)}")

    miss = lambda f: sum(1 for e in events.values() if not e.get(f))  # noqa: E731
    n = len(events)
    print(f"\nafter fill, still empty:  venue {miss('venue')}/{n}  city {miss('city')}/{n}  "
          f"state {miss('state_province')}/{n}  country {miss('country')}/{n}  "
          f"cagematch_nr {miss('cagematch_nr')}/{n}")

    nrs = [e["cagematch_nr"] for e in events.values() if e.get("cagematch_nr")]
    assert len(nrs) == len(set(nrs)), "cagematch_nr is UNIQUE in the schema; duplicates written"

    if dry:
        print("\n--dry-run: nothing written")
        return
    OUT.mkdir(exist_ok=True)
    (OUT / "location_conflicts.tsv").write_text(
        "# date\tshow\tshipped venue (kept)\tcagematch venue\n"
        + "".join("\t".join(r) + "\n" for r in sorted(conflicts)), "utf-8")
    (OUT / "location_rewrites.tsv").write_text(
        "# date\tshow\tbefore (city/state/country)\tafter\n"
        + "".join("\t".join(r) + "\n" for r in sorted(changes)), "utf-8")
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    atomic_write_text(ROOT / "index.html", inject(bundle, template))
    print("\nrewrote index.html; audit trails in out/location_conflicts.tsv, out/location_rewrites.tsv")


if __name__ == "__main__":
    main()
