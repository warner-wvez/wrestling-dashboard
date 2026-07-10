#!/usr/bin/env python3
"""Parse the Firecrawl scrape of Cagematch's WWE promotion pages into join tables.

Input:  .firecrawl/cagematch-raw/results-*.md   (gitignored, ~74MB)
Output: cagematch-pipeline/out/*.json           (committed, small)

The scrape's results pages are paginated listings, 100 events per page. Every
row is one markdown table cell holding, in order: the show logo (whose filename
encodes the logo's own date range), the event date, the event title linked by
its Cagematch event nr, the Cagematch event type, the venue and location, then
the full match list. Every wrestler in that match list is linked by a stable
Cagematch worker nr.

Those two nrs are the point of this parser. The schema already reserves
`events.cagematch_nr` and `wrestlers.cagematch_id` (see src/db.py), but only
the 2183 cagematch-sourced events carry one and no wrestler does. A worker nr
is immune to ring-name changes, which name-keyed joins are not: the roster
renders JBL, while every Cagematch row for him says Bradshaw or John Bradshaw
Layfield. Keying on the nr is what lets those reconcile.

Three tables come out:
  cm_events.json         cm_nr -> date, title, type, show_type, venue, location, logo
  cm_workers.json        worker_nr -> every ring name seen, with usage counts
  cm_event_workers.json  cm_nr -> [worker_nr]   (participants, for name-free joins)

Show classification and location splitting are imported from the live scraper
rather than reimplemented, so a corpus rule can never drift between the two.

Usage:
    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_raw.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cagematch_scraper import _parse_location, classify_show_type  # noqa: E402
from src.smackdown_schedule import smackdown_air_date  # noqa: E402

RAW_DIR = ROOT / ".firecrawl" / "cagematch-raw"
OUT_DIR = Path(__file__).resolve().parent / "out"

# The scrape was taken without the /en/ prefix, so Cagematch served its German
# locale and ~700 rows carry a German country name. Every distinct non-English
# token in the corpus is listed here; the parse fails loudly on an unmapped one
# rather than writing "Frankreich" into a column that elsewhere says "France".
DE_TO_EN_COUNTRY = {
    "Deutschland": "Germany",
    "Mexiko": "Mexico",
    "Italien": "Italy",
    "Frankreich": "France",
    "Saudi-Arabien": "Saudi Arabia",
    "Spanien": "Spain",
    "Österreich": "Austria",
    "Belgien": "Belgium",
    "Schweiz": "Switzerland",
    "Vereinigte Arabische Emirate": "United Arab Emirates",
    "Philippinen": "Philippines",
    "Niederlande": "Netherlands",
    "Indien": "India",
    "Singapur": "Singapore",
    "Finnland": "Finland",
    "Irak": "Iraq",
    "Polen": "Poland",
    "Argentinien": "Argentina",
    "Südkorea": "South Korea",
    "Katar": "Qatar",
    "Russland": "Russia",
    "Ägypten": "Egypt",
    "Luxemburg": "Luxembourg",
    "Dänemark": "Denmark",
    "Schweden": "Sweden",
    "Ungarn": "Hungary",
    "Türkei": "Turkey",
    "Kolumbien": "Colombia",
    "Norwegen": "Norway",
    "Tschechische Republik": "Czech Republic",
    "Tschechien": "Czech Republic",
    "Brasilien": "Brazil",
    "Rumänien": "Romania",
    "Serbien": "Serbia",
    "Dominikanische Republik": "Dominican Republic",
    "Island": "Iceland",           # not the English word
}
# Already English in the scrape; listed so an unmapped token is a real surprise.
KNOWN_EN_COUNTRY = {
    "USA", "Canada", "UK", "Australia", "Japan", "Ireland", "South Africa",
    "New Zealand", "Portugal", "China", "Chile", "Ecuador", "Peru", "Panama",
    "Taiwan", "Guatemala", "Thailand", "Costa Rica", "El Salvador", "Honduras",
    "Afghanistan", "Malaysia", "Israel", "Kuwait", "Austria", "Bahrain",
    "Oman", "Singapore",
}
# Cagematch drops the country on a handful of US rows ("Target Center in
# Minneapolis, Minnesota"), which _parse_location would read as the country.
# Minnesota is the only such token in the whole corpus; the guard is general so
# a new one surfaces instead of silently becoming a country.
US_STATES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
    "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming",
    "District of Columbia", "Puerto Rico",
}

# One event row. The logo sits in the same cell, ahead of the date.
_EVENT_RE = re.compile(
    r"\((?P<d>\d{2})\.(?P<m>\d{2})\.(?P<y>\d{4})\)\s*"
    r"\[(?P<title>[^\]]+)\]\(https://www\.cagematch\.net/\?id=1&nr=(?P<nr>\d+)\)"
    r"\s*\\?-\s*(?P<ctype>[^@<]+?)\s*@\s*(?P<loc>.+?)(?:<br>|\s*\|\s*$|$)"
)
_LOGO_RE = re.compile(r"img/ligen/normal/([^)\s]+?\.gif)")
# id=2 is a worker. id=28 (tag teams) and id=29 (stables) must not be swept in.
# The link TEXT is the display name; the URL's name= param strips apostrophes
# ("Tony+DAngelo") and pads with '+', so it is the wrong thing to read.
_WORKER_RE = re.compile(
    r"\[([^\]]+)\]\(https://www\.cagematch\.net/\?id=2&nr=(\d+)&name=[^)]*\)"
)
_EPISODE_RE = re.compile(r"#(\d+)\s*$")


def parse_location(loc: str):
    """'Allstate Arena in Rosemont, Illinois, USA' -> venue + city/state/country.

    1205 rows name no venue at all and read 'in Rosemont, Illinois, USA'; those
    yield venue=None rather than swallowing the city as a venue.
    """
    loc = loc.strip().rstrip("|").strip()
    if loc.startswith("in "):                     # venue unknown to Cagematch
        venue, rest = None, loc[3:]
    else:
        venue, sep, rest = loc.partition(" in ")
        if not sep:                               # no split at all: it's a location
            venue, rest = None, loc
    city, state, country = _parse_location(rest)
    if country in DE_TO_EN_COUNTRY:
        country = DE_TO_EN_COUNTRY[country]
    elif country and country not in KNOWN_EN_COUNTRY:
        if state is None and country in US_STATES:
            state, country = country, "USA"       # 'Minneapolis, Minnesota'
        else:
            raise ValueError(f"unmapped country token {country!r} in {loc!r}")
    return (venue or None), city, state, country


def parse():
    files = sorted(RAW_DIR.glob("results-*.md"))
    if not files:
        sys.exit(f"no results-*.md under {RAW_DIR}")

    events: dict[str, dict] = {}
    workers: dict[str, Counter] = defaultdict(Counter)
    event_workers: dict[str, list] = {}
    stats = Counter()
    dupes = []

    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            hits = list(_EVENT_RE.finditer(line))
            if not hits:
                continue
            if len(hits) > 1:
                stats["rows_with_multiple_events"] += 1
            logo_m = _LOGO_RE.search(line)
            for m in hits:
                nr = m.group("nr")
                stats["rows"] += 1
                title = m.group("title").strip()
                ctype = m.group("ctype").strip()
                venue, city, state, country = parse_location(m.group("loc"))
                show_type = classify_show_type(title, ctype)
                ep = _EPISODE_RE.search(title)

                # Cagematch's date is the TAPING night. For taped SmackDown that
                # is not the broadcast date, and the offset is era-dependent
                # (Thursday/Friday/Tuesday-live eras), so the shared era rule
                # converts it. Everything else airs live on its listed date.
                # Without this, ~100 SmackDown rows join to the wrong day or to
                # nothing at all.
                tape = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
                if show_type == "SmackDown":
                    air, derivation = smackdown_air_date(tape)
                else:
                    air, derivation = tape, "live-broadcast"

                rec = {
                    "cagematch_nr": int(nr),
                    "air_date": air.isoformat(),
                    "tape_date": tape.isoformat() if air != tape else None,
                    "date_derivation": derivation,
                    "title": title,
                    "episode_number": int(ep.group(1)) if ep else None,
                    "cm_type": ctype,
                    "show_type": show_type,          # None or "SKIP" = out of corpus
                    "venue": venue,
                    "city": city,
                    "state_province": state,
                    "country": country,
                    "logo": urllib.parse.unquote(logo_m.group(1)) if logo_m else None,
                }
                if nr in events and events[nr] != rec:
                    dupes.append(nr)
                events[nr] = rec

                # Participants: the whole cell, match list included. Store the
                # name each worker used IN THIS EVENT, not just the worker id.
                # 95 ring names are claimed by two different workers ("Kane" is
                # Glenn Jacobs 2719 times and Luke Gallows once, during the 2006
                # impostor angle; "Butch" is a Bushwhacker and also Pete Dunne),
                # so a global name -> worker map silently fuses two people.
                # Pairing the name with the event disambiguates without a
                # heuristic: only one Kane wrestled on any given night.
                seen = {}
                for name, wnr in _WORKER_RE.findall(line):
                    name = name.strip()
                    workers[wnr][name] += 1
                    seen.setdefault(wnr, name)
                event_workers[nr] = seen

    # Events are trimmed to the corpus (Raw/SmackDown/PPV) before writing: the
    # other 24k rows are house shows and NXT/Main Event, which the dashboard
    # does not carry, and keeping them makes the tables 20MB instead of 2MB.
    #
    # Worker name counts are NOT trimmed. Alias evidence gets better the more
    # history it sees, and the table is small either way: JBL's 'Justin
    # Bradshaw' era only ever appears on 1996 house shows.
    corpus = {nr: e for nr, e in events.items()
              if e["show_type"] in ("Raw", "SmackDown", "PPV")}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dump = lambda name, obj: (OUT_DIR / name).write_text(  # noqa: E731
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    dump("cm_events.json", corpus)
    dump("cm_workers.json", {k: dict(v.most_common()) for k, v in workers.items()})
    dump("cm_event_workers.json", {nr: event_workers[nr] for nr in corpus})

    # ---- report ----
    in_corpus = [e for e in events.values()
                 if e["show_type"] in ("Raw", "SmackDown", "PPV")]
    span = sorted(e["air_date"] for e in events.values())
    multi = {k: v for k, v in workers.items() if len(v) > 1}
    print(f"files parsed          {len(files)}")
    print(f"event rows            {stats['rows']}")
    print(f"distinct events       {len(events)}   (conflicting duplicates: {len(set(dupes))})")
    print(f"date span             {span[0]} .. {span[-1]}")
    print(f"in-corpus events      {len(in_corpus)}  (Raw/SmackDown/PPV)")
    print(f"  by show_type        {dict(Counter(e['show_type'] for e in in_corpus))}")
    print(f"out-of-corpus         {len(events) - len(in_corpus)}  "
          f"({dict(Counter(str(e['show_type']) for e in events.values() if e not in in_corpus))})")
    print(f"distinct workers      {len(workers)}")
    print(f"  with >1 ring name   {len(multi)}")
    print(f"venue present         {sum(1 for e in events.values() if e['venue'])}/{len(events)}")
    print(f"country present       {sum(1 for e in events.values() if e['country'])}/{len(events)}")
    print(f"logo present          {sum(1 for e in events.values() if e['logo'])}/{len(events)}")
    print(f"\nwritten (corpus-only events, all workers):")
    for f in sorted(OUT_DIR.glob("*.json")):
        print(f"  {f.name:24} {f.stat().st_size / 1e6:6.2f} MB")


if __name__ == "__main__":
    parse()
