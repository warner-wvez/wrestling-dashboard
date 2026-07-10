#!/usr/bin/env python3
"""Parse the scrape's promo pages into a flat promo table.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_promos.py

Input:  .firecrawl/cagematch-raw/promos-*.md   (13 pages, 100 rows each)
Output: cagematch-pipeline/out/cm_promos.json

A promo on Cagematch is a rated talking segment, the mic work the crowd argues
about the way it argues about a match. Each row is a memorable line, the workers
in the segment, its date, and a community rating:

    | 3 | 06.04.2026 | ["Being hated by losers is the price I pay ..."](...nr=1930) | CM Punk | 7.64 | 82 |

Columns: nr, date (DD.MM.YYYY), the quote (linked to the promo's id=93 page), the
workers (comma-separated), the community rating, and its vote count. Only rated
or notable promos are listed, so 1236 rows span sixty years and most weekly shows
carry none.

Like a match, Cagematch dates a promo by the night it was *taped*, so the caller
must join on `tape_date or air_date`, never on air_date. fill_promos.py does the
join and the per-show attach.
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

# nr | DD.MM.YYYY | [quote](id=93&nr=...) | workers | rating | votes
# The quote is captured non-greedily up to its own id=93 link, so a stray ] in
# the line cannot end it early.
ROW = re.compile(
    r"^\|\s*\d+\s*\|\s*(\d{2})\.(\d{2})\.(\d{4})\s*\|"
    r"\s*\[(.*?)\]\(https://www\.cagematch\.net/\?id=93&nr=(\d+)\)\s*\|"
    r"([^|]*)\|([^|]*)\|([^|]*)\|"
)


def main() -> None:
    files = sorted(RAW.glob("promos-*.md"))
    if not files:
        sys.exit(f"no promos-*.md under {RAW}")

    promos, seen_nr, stats = [], set(), Counter()
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            m = ROW.match(line.strip())
            if not m:
                continue
            dd, mo, yy, title, nr, workers, rating, votes = m.groups()
            stats["rows"] += 1
            nr = int(nr)
            if nr in seen_nr:                      # pages overlap at the edges
                stats["dupe nr skipped"] += 1
                continue
            seen_nr.add(nr)
            promos.append({
                "cagematch_promo_nr": nr,
                "date": f"{yy}-{mo}-{dd}",
                "title": title.strip(),
                "workers": [w.strip() for w in workers.split(",") if w.strip()],
                "rating": float(rating) if rating.strip() else None,
                "votes": int(votes) if votes.strip() else None,
            })

    promos.sort(key=lambda p: (p["date"], p["cagematch_promo_nr"]))
    OUT.mkdir(exist_ok=True)
    (OUT / "cm_promos.json").write_text(
        json.dumps(promos, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")

    rated = sum(1 for p in promos if p["rating"] is not None)
    print(f"pages parsed   {len(files)}")
    print(f"rows           {stats['rows']}   ({stats['dupe nr skipped']} dupe nrs skipped)")
    print(f"unique promos  {len(promos)}")
    print(f"  rated        {rated}")
    print(f"\nwrote {OUT / 'cm_promos.json'}")


if __name__ == "__main__":
    main()
