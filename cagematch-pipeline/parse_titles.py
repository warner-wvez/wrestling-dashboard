#!/usr/bin/env python3
"""Parse the scrape's active-titles page into a champions table.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_titles.py

Input:  .firecrawl/cagematch-raw/titles-*.md
Output: cagematch-pipeline/out/cm_titles.json

The page is a snapshot of every active WWE championship and who holds it as of
the scrape:

    | 1 | [Undisputed WWE Championship](...id=5&nr=20) | [CM Punk](...id=2&nr=80) (3) | 06.07.2026  (4 Tage) | 9.13 | 820 |

Columns: nr, title, the current champion(s) (linked; a tag title lists the team
and its members), since when ("Tage" is German for days), the title's prestige
rating, and its vote count. Titles are English; the only German is the word
"Tage", which is dropped for the day count.

fill_titles.py joins the champions to the dashboard roster for internal links and
ships the board. The holder is a spoiler, so the event page's rule applies on the
Titles view too: the belt and its rating always show, the champion only with
spoilers on.
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

# nr | [title](id=5&nr=) | champion cell | since cell | rating | votes
ROW = re.compile(
    r"^\|\s*\d+\s*\|"
    r"\s*\[(.*?)\]\(https://www\.cagematch\.net/(?:en/)?\?id=5&nr=(\d+)\)\s*\|"
    r"(.*?)\|"                                  # champion cell (may hold many links)
    r"\s*(\d{2})\.(\d{2})\.(\d{4})\s*(?:\(\s*(\d+)\s*Tage?\s*\))?\s*\|"
    r"([^|]*)\|([^|]*)\|"
)
_PERSON = re.compile(r"\[([^\]]+)\]\(https://www\.cagematch\.net/(?:en/)?\?id=2&nr=(\d+)")
_TEAM = re.compile(r"\[([^\]]+)\]\(https://www\.cagematch\.net/(?:en/)?\?id=29&nr=(\d+)")


def main() -> None:
    files = sorted(RAW.glob("titles-*.md"))
    if not files:
        sys.exit(f"no titles-*.md under {RAW}")

    titles, seen, stats = [], set(), Counter()
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            m = ROW.match(line.strip())
            if not m:
                continue
            name, nr, champ_cell, dd, mo, yy, days, rating, votes = m.groups()
            stats["rows"] += 1
            nr = int(nr)
            if nr in seen:
                stats["dupe nr skipped"] += 1
                continue
            seen.add(nr)
            people = _PERSON.findall(champ_cell)
            team = _TEAM.search(champ_cell)
            titles.append({
                "cagematch_title_nr": nr,
                "title": name.strip(),
                "champions": [p[0].strip() for p in people],
                "team_name": team.group(1).strip() if team else None,
                "since": f"{yy}-{mo}-{dd}",
                "days_held": int(days) if days else None,
                "rating": float(rating) if rating.strip() else None,
                "votes": int(votes) if votes.strip() else None,
            })

    titles.sort(key=lambda t: (t["rating"] is not None, t["rating"] or 0), reverse=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "cm_titles.json").write_text(
        json.dumps(titles, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")

    rated = sum(1 for t in titles if t["rating"] is not None)
    vacant = sum(1 for t in titles if not t["champions"])
    print(f"pages parsed   {len(files)}")
    print(f"rows           {stats['rows']}   ({stats['dupe nr skipped']} dupe nrs skipped)")
    print(f"unique titles  {len(titles)}")
    print(f"  rated        {rated}")
    print(f"  vacant       {vacant}")
    print(f"\nwrote {OUT / 'cm_titles.json'}")


if __name__ == "__main__":
    main()
