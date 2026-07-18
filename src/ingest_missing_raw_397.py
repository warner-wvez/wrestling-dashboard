#!/usr/bin/env python3
"""One-off corpus addition: ingest the missing January 1, 2001 Raw (#397).

The first Raw of the corpus is #398 (2001-01-08); the app opens on "start from
the beginning" pointing at the January 4 SmackDown, and the Monday before it is
blank. Raw #397 aired January 1, 2001 but was TAPED December 29, 2000, and
Cagematch files a taped show under its taping date, so the same tape-vs-air fault
behind the SmackDown estimates and the 19 misdated Raws also pushed this whole
episode outside the 2001 scrape boundary. It was never ingested, so unlike the
19 there is nothing to re-date: the card has to be fetched.

It is fetched from the same source the SmackDown lane already uses,
prowrestling.fandom.com, which keys by air date and therefore has it. The card
is parsed by the repo's own fandom parser (parse_episode_page), so the teams,
participants, champion markers, winners and durations come out in exactly the
shape the rest of the corpus uses, rather than being hand-typed. Verified against
the record: 8 matches, Frank Erwin Center in Austin, taped 2000-12-29.

Three corrections the parser cannot make on this particular page:

  * show_type / episode_number / title. parse_episode_page hardcodes SmackDown,
    and this page's external-links list does not carry the number. #397 is
    certain: #398 is the following Monday.

  * two title defenses lose their belt. This page writes results as prose
    ("Raven (c) defeated Tazz to retain the WWF Hardcore Championship") with no
    bold match-type header, so the parser reads no title_at_stake. The (c) is
    captured, and both are retains, so nothing changes hands; but for the Hardcore
    and Intercontinental defenses we set the belt so the title timelines see them.
    Both champions (Raven, Benoit) are already the corpus's first-seen holders of
    those belts, so this only moves their reign floor three days earlier onto the
    night they actually held it.

  * a mangled name. Cagematch-style "(with Stephanie ... as Special guest
    referee)" trailing Steve Austin's name was swallowed into the participant
    field. The referee note stays in raw_description; the wrestler is Steve
    Austin.

The three contendership matches (a WWF Title #1 Contendership tournament ran that
night) are left without a title_at_stake, which is correct: a contendership match
puts no belt on the line, and the reign walk must not treat their winners as
champions. This is the same class the CLIP_SHOWS / _drop_contendership_parts work
guards against.

Run from repo root:
    uv run --with requests --with beautifulsoup4 python -m src.ingest_missing_raw_397 [--dry-run]

Requires the fetched page at .firecrawl/raw-jan1-2001.extracted.html (see the
firecrawl scrape in the commit that adds this file).
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
    inject, split_fused_multiman_sides, write_sharded)
from src.fandom_scraper import parse_episode_page             # noqa: E402
from src.rebuild_indexes import bundle_derived_aliases        # noqa: E402
from src.roster_aliases import CURATED, build_canon_map, load_roster_snapshot  # noqa: E402
from src.ship_guard import atomic_write_text                  # noqa: E402

PAGE = ROOT / ".firecrawl" / "raw-jan1-2001.extracted.html"
FANDOM_URL = "https://prowrestling.fandom.com/wiki/January_1,_2001_Monday_Night_RAW_results"
FANDOM_SLUG = "January_1,_2001_Monday_Night_RAW_results"

# Belt each retain puts on the line, matched to the match by the champion the
# parser already tagged (c). Exact spellings are the ones the era uses in the
# corpus so the lineage keys merge correctly.
RETAIN_BELTS = {
    "Raven": "WWF Hardcore Title",
    "Chris Benoit": "WWF Intercontinental Title",
}

_RETAIN_TAIL = re.compile(r"\s+to retain the .*$", re.I)
_REFEREE_TAIL = re.compile(r"\s*\(?\s*with .*?special guest referee.*$", re.I)


def _clean_name(s: str) -> str:
    s = _RETAIN_TAIL.sub("", s)
    s = _REFEREE_TAIL.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def build_event(next_event_id: int, next_match_id: int) -> dict:
    if not PAGE.exists():
        raise SystemExit(f"missing fetched page: {PAGE}\n"
                         f"  firecrawl scrape \"{FANDOM_URL}\" --format rawHtml -o {PAGE}")
    parsed = parse_episode_page(PAGE.read_text(encoding="utf-8"))
    matches = parsed["matches"]
    if len(matches) != 8:
        raise SystemExit(f"expected 8 matches, parser found {len(matches)}; page shape changed")

    for i, m in enumerate(matches):
        m["id"] = next_match_id + i
        m.pop("parse_confidence", None)
        m.setdefault("match_guide_rating", None)
        # Clean any "to retain the ..." / guest-referee tail the prose-style page
        # left inside a team name or participant.
        for t in m["teams"]:
            t["team_name"] = _clean_name(t.get("team_name") or "")
            t["participants"] = [_clean_name(p) for p in (t.get("participants") or []) if _clean_name(p)]
            # The referee/retain tail can be the whole of a singles participant
            # (M8: Austin's only "participant" was the guest-referee clause). The
            # clean team name is the wrestler, so fall back to it.
            if not t["participants"] and t["team_name"]:
                t["participants"] = [t["team_name"]]
            t.setdefault("accompaniment", None)
        # Tag the belt on the two title defenses the parser could not see.
        champ = next((t["team_name"] for t in m["teams"] if t.get("was_champion_entering")), None)
        belt = RETAIN_BELTS.get(champ)
        if belt and "retain" in (m["raw_description"] or "").lower():
            m["title_at_stake"] = belt
            m["match_type"] = f"{belt} Match"

    event = {
        "id": next_event_id,
        "air_date": "2001-01-01",
        "tape_date": "2000-12-29",             # stated in the page's intro prose
        "date_derivation": "fandom-provided",
        "show_type": "Raw",
        "episode_number": 397,                 # #398 is the following Monday
        "title": "WWF RAW #397",
        "ppv_name": None,
        "venue": parsed.get("venue") or "Frank Erwin Center",
        "city": "Austin",
        "state_province": "Texas",
        "country": "USA",
        "attendance": None,
        "tv_network": "TNN",
        "tv_rating": None,
        "broadcast_type": "Taped",
        "commentary": "Jim Ross & Jerry Lawler",
        "promotion": "World Wrestling Federation",
        "promotion_raw": "World Wrestling Federation",
        "cagematch_nr": None,
        "cagematch_url": None,
        "fandom_slug": FANDOM_SLUG,
        "fandom_url": FANDOM_URL,
        "primary_source": "fandom",
        "verification_status": "unverified",
        "match_count": len(matches),
        "logo": "wwf-raw-is-war-19970310",
        "matches": matches,
    }
    return event


def main() -> None:
    dry = "--dry-run" in sys.argv
    print("Loading existing full bundle...", flush=True)
    data = load_existing()
    events = data["events"]

    if any(e.get("show_type") == "Raw" and e.get("episode_number") == 397 for e in events.values()):
        print("  Raw #397 already present; nothing to do")
        return

    next_event_id = max(int(k) for k in events) + 1
    next_match_id = max((m.get("id", 0)
                         for e in events.values() for m in e.get("matches") or []), default=0) + 1
    event = build_event(next_event_id, next_match_id)

    print(f"\n=== Raw #{event['episode_number']}  {event['air_date']} "
          f"(taped {event['tape_date']})  id={event['id']} ===")
    print(f"  {event['venue']}, {event['city']}, {event['state_province']}  "
          f"source={event['primary_source']}")
    for m in event["matches"]:
        belt = f"  [belt: {m['title_at_stake']}]" if m["title_at_stake"] else ""
        print(f"  M{m['match_order']}: {m['raw_description'][:80]}{belt}")
        for t in m["teams"]:
            flag = "W" if t["was_winner"] else " "
            c = " (c)" if t.get("was_champion_entering") else ""
            print(f"       {flag} {t['team_name']}{c}  {t['participants']}")
    if dry:
        print("\n--dry-run: nothing written")
        return

    events[str(event["id"])] = event
    data["events_by_date"] = {}
    for e in events.values():
        if e.get("air_date"):
            data["events_by_date"].setdefault(e["air_date"], []).append(int(e["id"]))
    data["events_by_date"] = {d: sorted(ids) for d, ids in sorted(data["events_by_date"].items())}

    name_counts = collections.Counter(
        p for e in events.values() for m in e["matches"]
        for t in m["teams"] for p in t.get("participants", []) if p)
    canon = build_canon_map(name_counts,
                            roster_pairs=load_roster_snapshot() or [],
                            curated={**bundle_derived_aliases(data), **CURATED})
    split_fused_multiman_sides(events)
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
    print(f"\n=== DONE ===  events now {len(events)}, matches now {bundle['meta']['match_count']}")


if __name__ == "__main__":
    main()
