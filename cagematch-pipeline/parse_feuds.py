#!/usr/bin/env python3
"""Parse the scrape's feud pages into a flat rivalry table.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_feuds.py

Input:  .firecrawl/cagematch-raw/feuds-*.md   (5 pages)
Output: cagematch-pipeline/out/cm_feuds.json

A feud on Cagematch is a rated storyline arc over a span of months:

    | 3 | [The Next Big Thing ...: Brock Lesnar vs. The Undertaker](...nr=695) | 02/2014 - 04/2014 | 5.42 | 37 |

Columns: nr, title, timeframe (MM/YYYY - MM/YYYY), rating, votes. Unlike promos,
there is no workers column, and the title is written in German by Cagematch's
contributors: the `/en/` view translates the page chrome but not these
user-submitted strings, so a language re-scrape does not help. What is
language-neutral is the matchup embedded in the title, since wrestler names are
proper nouns: `Brock Lesnar vs. The Undertaker`.

This step only lifts the rows out of the tables; fill_feuds.py does the matchup
extraction, because pulling `X vs. Y` cleanly out of German prose needs the
roster to tell a wrestler's name from a storyline phrase (`Legend vs. Icon` is
not a match). A feud is dated by a month range, not a single night, so it does
not attach to one event either: fill_feuds ships the list and the event page
shows the feuds whose window covers the show's month.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / ".firecrawl" / "cagematch-raw"
OUT = Path(__file__).resolve().parent / "out"

# nr | [title](id=87&nr=...) | MM/YYYY - MM/YYYY | rating | votes
ROW = re.compile(
    r"^\|\s*\d+\s*\|"
    r"\s*\[(.*?)\]\(https://www\.cagematch\.net/(?:en/)?\?id=87&nr=(\d+)\)\s*\|"
    r"\s*(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{4})\s*\|"
    r"([^|]*)\|([^|]*)\|"
)


def main() -> None:
    files = sorted(RAW.glob("feuds-*.md"))
    if not files:
        sys.exit(f"no feuds-*.md under {RAW}")

    feuds, seen, stats = [], set(), Counter()
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            m = ROW.match(line.strip())
            if not m:
                continue
            title, nr, sm, sy, em, ey, rating, votes = m.groups()
            stats["rows"] += 1
            nr = int(nr)
            if nr in seen:
                stats["dupe nr skipped"] += 1
                continue
            seen.add(nr)
            feuds.append({
                "cagematch_feud_nr": nr,
                "title": title.strip(),
                "start": f"{sy}-{sm}",
                "end": f"{ey}-{em}",
                "rating": float(rating) if rating.strip() else None,
                "votes": int(votes) if votes.strip() else None,
            })

    feuds.sort(key=lambda x: x["start"])
    OUT.mkdir(exist_ok=True)
    (OUT / "cm_feuds.json").write_text(
        json.dumps(feuds, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")

    rated = sum(1 for f in feuds if f["rating"] is not None)
    print(f"pages parsed   {len(files)}")
    print(f"rows           {stats['rows']}   ({stats['dupe nr skipped']} dupe nrs skipped)")
    print(f"unique feuds   {len(feuds)}")
    print(f"  rated        {rated}")
    print(f"\nwrote {OUT / 'cm_feuds.json'}")


if __name__ == "__main__":
    main()
