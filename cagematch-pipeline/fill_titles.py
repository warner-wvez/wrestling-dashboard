#!/usr/bin/env python3
"""Build the champions board sidecar from the parsed titles: shards/titles.json.

    uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_titles.py [--dry-run]

parse_titles.py lifts every title on the page, active and retired; this keeps the
active ones (the retired lineages read INACTIVE, with no current champion) and
resolves each champion to a dashboard profile so the Titles view can link to it.
The board is sorted by the title's prestige rating.

The champion is a spoiler, so the sidecar carries it plainly and the Titles view
gates it exactly like a match result: belt and rating always show, the holder
only with spoilers on.

Champions who wrestle only in NXT / EVOLVE / ID are not in the Raw-SmackDown-PPV
corpus, so they resolve to no profile and render as plain text. That is expected,
not an error. Idempotent: the sidecar is rebuilt from scratch each run.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.roster_aliases import normkey  # noqa: E402
from src.ship_guard import atomic_write_text  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
TAG = r'<script id="wrestling-data" type="application/json">(.*?)</script>'
TITLE_URL = "https://www.cagematch.net/?id=5&nr={}"


def main() -> None:
    dry = "--dry-run" in sys.argv
    titles = json.loads((OUT / "cm_titles.json").read_text(encoding="utf-8"))
    bundle = json.loads(re.search(TAG, (ROOT / "index.html").read_text("utf-8"), re.S).group(1))

    # name -> slug, exact then normkeyed, so a champion links to their profile.
    by_name = bundle["wrestlers_by_name"]
    by_norm = {}
    for name, slug in by_name.items():
        by_norm.setdefault(normkey(name), slug)

    def slug_for(name):
        return by_name.get(name) or by_norm.get(normkey(name))

    board, linked, unlinked = [], 0, 0
    for t in titles:
        if not t["champions"]:                       # retired lineage (INACTIVE)
            continue
        champs = []
        for name in t["champions"]:
            slug = slug_for(name)
            champs.append({"name": name, "slug": slug})
            if slug:
                linked += 1
            else:
                unlinked += 1
        board.append({
            "title": t["title"],
            "champions": champs,
            "team_name": t["team_name"],
            "since": t["since"],
            "days_held": t["days_held"],
            "rating": t["rating"],
            "votes": t["votes"],
            "url": TITLE_URL.format(t["cagematch_title_nr"]),
        })

    board.sort(key=lambda t: (t["rating"] is not None, t["rating"] or 0), reverse=True)

    print(f"active titles on the board: {len(board)}")
    print(f"champion links: {linked} resolved, {unlinked} plain text (NXT/EVOLVE/ID off-corpus)")
    print("top belts:")
    for t in board[:8]:
        who = ", ".join(c["name"] for c in t["champions"])
        print(f"  {t['rating']}  {t['title'][:38]:38} {who}")

    if dry:
        print("\n--dry-run: nothing written")
        return
    atomic_write_text(ROOT / "shards" / "titles.json",
                      json.dumps(board, ensure_ascii=False, separators=(",", ":")))
    print("\nwrote shards/titles.json")


if __name__ == "__main__":
    main()
