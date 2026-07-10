#!/usr/bin/env python3
"""Parse the scrape's tournament pages into a flat table.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_tournaments.py

Input:  .firecrawl/cagematch-raw/tournaments-*.md   (3 pages)
Output: cagematch-pipeline/out/cm_tournaments.json

A tournament row is a named bracket with a dated final and a winner:

    | 2 | [King Of The Ring 2026](...nr=10191) | 01.06.2026 - 27.06.2026 | [Oba Femi](...id=2&nr=26953) |  |  |

Columns: nr, title, timeframe (single date or DD.MM.YYYY - DD.MM.YYYY), the
winner(s) as wrestler links, rating, votes. Unlike feuds the titles are already
English, and the winners are linked, so their names come clean rather than pulled
out of prose. Cagematch also files the Royal Rumble and the Andre Battle Royal
here, which is right: winning one is the same kind of accolade.

`end` is the last date in the timeframe, the night the final happened;
fill_tournaments hangs each tournament on the show at that date. The winner is a
spoiler, so it never leaves this table for the bundle; the event page reveals it
only when spoilers are on.
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

# nr | [title](id=26&nr=) | timeframe | winner cell | rating | votes
ROW = re.compile(
    r"^\|\s*\d+\s*\|"
    r"\s*\[(.*?)\]\(https://www\.cagematch\.net/(?:en/)?\?id=26&nr=(\d+)\)\s*\|"
    r"([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|"
)
_WINNER = re.compile(r"\[([^\]]+)\]\(https://www\.cagematch\.net/(?:en/)?\?id=2&nr=(\d+)")
_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def main() -> None:
    files = sorted(RAW.glob("tournaments-*.md"))
    if not files:
        sys.exit(f"no tournaments-*.md under {RAW}")

    tourneys, seen, stats = [], set(), Counter()
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            m = ROW.match(line.strip())
            if not m:
                continue
            title, nr, tf, wincell, rating, votes = m.groups()
            stats["rows"] += 1
            nr = int(nr)
            if nr in seen:
                stats["dupe nr skipped"] += 1
                continue
            dates = _DATE.findall(tf)
            if not dates:
                stats["no date skipped"] += 1
                continue
            seen.add(nr)
            winners = _WINNER.findall(wincell)   # [(name, worker_nr), ...]
            tourneys.append({
                "cagematch_tournament_nr": nr,
                "title": title.strip(),
                "start": f"{dates[0][2]}-{dates[0][1]}-{dates[0][0]}",
                "end": f"{dates[-1][2]}-{dates[-1][1]}-{dates[-1][0]}",
                "winners": [w[0].strip() for w in winners],
                "winner_nrs": [int(w[1]) for w in winners],
                "rating": float(rating) if rating.strip() else None,
                "votes": int(votes) if votes.strip() else None,
            })

    tourneys.sort(key=lambda t: t["end"])
    OUT.mkdir(exist_ok=True)
    (OUT / "cm_tournaments.json").write_text(
        json.dumps(tourneys, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")

    with_win = sum(1 for t in tourneys if t["winners"])
    print(f"pages parsed       {len(files)}")
    print(f"rows               {stats['rows']}   ({stats['dupe nr skipped']} dupe, "
          f"{stats['no date skipped']} undated skipped)")
    print(f"unique tournaments {len(tourneys)}")
    print(f"  with a winner    {with_win}")
    print(f"\nwrote {OUT / 'cm_tournaments.json'}")


if __name__ == "__main__":
    main()
