#!/usr/bin/env python3
"""Parse the scrape's matchguide pages into a per-match ratings table.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_matchguide.py

Input:  .firecrawl/cagematch-raw/matchguide-*.md   (178 pages, 100 rows each)
Output: cagematch-pipeline/out/cm_matchguide.json

Each row is: date, the match fixture, a stable Cagematch match nr, a Wrestling
Observer star rating, the Cagematch community rating, and its vote count.

    | 1 | 06.07.2026 | [Chad Gable & Dragon Lee vs. Ethan Page & Rusev](...nr=142697) |  | 6.03 | 63 |

Only matches carrying at least one rating are listed, which is why 17757 rows
cover 68 years: WrestleMania X-Seven has 11, a random 2001 SmackDown has none.
So this cannot fill every gap, only the ones anyone bothered to rate.

The Observer column is the valuable half. Nothing else in the corpus has it, and
`****1/2` is the rating hardcore fans actually argue about. It is stored both as
the string Cagematch prints and as a number, since `1/2*` means half a star and
sorts nowhere near `*1/2`, which means one and a half.

## The join key

Date plus the wrestlers, not date plus the fixture text. A fixture names the
same people the match rows do, but a source can spell them differently
('Finn Balor' / 'Finn Bálor'), so each name goes through `normkey` and each
team's members are sorted. Teams are sorted too, because a fixture lists them in
the event page's order and nothing guarantees ours agrees.

Cagematch dates a match by the night it was *taped*, matching how it dates the
event, so the caller must join on `tape_date or air_date`, never on air_date.
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

from src.roster_aliases import normkey  # noqa: E402

RAW = ROOT / ".firecrawl" / "cagematch-raw"
OUT = Path(__file__).resolve().parent / "out"

ROW = re.compile(
    r"^\|\s*\d+\s*\|\s*(\d{2})\.(\d{2})\.(\d{4})\s*\|"
    r"\s*\[([^\]]+)\]\(https://www\.cagematch\.net/\?id=111&nr=(\d+)\)\s*\|"
    r"([^|]*)\|([^|]*)\|([^|]*)\|"
)
# '***1/2' -> 3.5 | '1/2*' -> 0.5 (half a star, not one and a half) | 'DUD' -> 0
_WON = re.compile(r"^(?:(\d)/(\d))?(\*+)(?:(\d)/(\d))?$")


def won_to_stars(s: str):
    s = s.strip()
    if not s:
        return None
    if s.upper() == "DUD":
        return 0.0
    m = _WON.match(s)
    if not m:
        return None
    if m.group(1):                       # fraction BEFORE the star: '3/4*' = 0.75
        return int(m.group(1)) / int(m.group(2))
    post = int(m.group(4)) / int(m.group(5)) if m.group(4) else 0.0
    return len(m.group(3)) + post


def fixture_key(fixture: str) -> str:
    """'A & B vs. C' -> a normkey-based, order-independent identity for the match."""
    teams = []
    for side in re.split(r"\s+vs\.\s+", fixture):
        members = [normkey(x) for x in re.split(r"\s*&\s*", side) if x.strip()]
        teams.append("+".join(sorted(m for m in members if m)))
    return "|".join(sorted(t for t in teams if t))


def main():
    files = sorted(RAW.glob("matchguide-*.md"))
    if not files:
        sys.exit(f"no matchguide-*.md under {RAW}")

    seen = defaultdict(list)
    stats = Counter()
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            m = ROW.match(line.strip())
            if not m:
                continue
            dd, mo, yy, fixture, nr, won_raw, rating, votes = m.groups()
            stats["rows"] += 1
            won = won_raw.strip().replace("\\", "")          # markdown escapes the stars
            stars = won_to_stars(won)
            if won and stars is None:
                stats["won unparsed"] += 1
            rec = {
                "cagematch_match_nr": int(nr),
                "fixture": fixture.strip(),
                "won_rating": won or None,
                "won_stars": stars,
                "match_guide_rating": float(rating) if rating.strip() else None,
                "match_guide_votes": int(votes) if votes.strip() else None,
            }
            seen[f"{yy}-{mo}-{dd}|{fixture_key(fixture)}"].append(rec)

    table, dupes = {}, 0
    for k, v in seen.items():
        if len(v) > 1:                   # same night, same wrestlers, twice: unusable
            dupes += 1
            continue
        table[k] = v[0]

    OUT.mkdir(exist_ok=True)
    (OUT / "cm_matchguide.json").write_text(
        json.dumps(table, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8")

    with_won = sum(1 for r in table.values() if r["won_stars"] is not None)
    with_rat = sum(1 for r in table.values() if r["match_guide_rating"] is not None)
    print(f"pages parsed        {len(files)}")
    print(f"rows                {stats['rows']}")
    print(f"unique keys         {len(table)}   (dropped {dupes} ambiguous, "
          f"{stats['won unparsed']} unparsed Observer ratings)")
    print(f"  with Observer     {with_won}")
    print(f"  with cm rating    {with_rat}")
    print(f"\nwrote {OUT / 'cm_matchguide.json'}")


if __name__ == "__main__":
    main()
