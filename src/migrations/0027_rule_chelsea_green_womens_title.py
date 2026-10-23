"""
Chelsea Green's WWE Women's Championship reign starts at SummerSlam 2026, not
on the SmackDown of September 11.

Rhea Ripley was hurt in July 2026, and Green won a five-way ladder match for
the interim title on SummerSlam night 2 (2026-08-02). On September 11 WWE
amended the title history: Ripley's reign ends on August 2 and Green is
recognized as the champion from that night. WWE.com's title history and
Wikipedia's List of WWE Women's Champions both list it that way (Ripley
2026-04-19 to 2026-08-02, Green 2026-08-02 to present).

Our cards could not say it. The SummerSlam table names the belt but Ripley was
not in the match, so the reign walk kept her champion. The September 11 card
bills Green's defense as the "Interim WWE Women's Championship", so the walk
opened a separate interim belt that night.

  SummerSlam 2026 night 2 (match 33533): Green wins the WWE Women's
    Championship.
  SmackDown 2026-09-11 (match 33593): the stake is the WWE Women's
    Championship, which Green retains.

Found by lineup-check/title_audit.py once it checked a belt still held through
the newest show on file, rather than stopping at the start of our last reign.

Safety gate: each match is found by match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0027_rule_chelsea_green_womens_title.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

WOMENS = "https://en.wikipedia.org/wiki/List_of_WWE_Women%27s_Champions"
WWE_COM = "https://www.wwe.com/titlehistory/raw-womens-championship"


def ruling(*belts, why, source):
    """belts: (title, champions) pairs, one ruling per belt on the match."""
    def apply(m):
        want = [{"title": t, "champions": c, "why": why, "source": source} for t, c in belts]
        if m.get("title_result") == want:
            return False
        m["title_result"] = want
        return True
    return apply


def stake(title):
    def apply(m):
        if m.get("title_at_stake") == title:
            return False
        m["title_at_stake"] = title
        return True
    return apply


FIXES = [
    # (match id, start of stored text (the same before and after the fix), fix)
    (33533, "[[Chelsea Green]] defeated [[Charlotte Flair]], [[Jade Cargill]], [[Lash Legend]]",
     ruling(("WWE Women's Championship", ["Chelsea Green"]),
            why="won the interim title in a ladder match while Rhea Ripley was hurt; on 2026-09-11 WWE "
                "ended Ripley's reign on August 2 and recognized Green as champion from that night",
            source=f"{WOMENS} ; {WWE_COM}")),
    (33593, "Chelsea Green (c) defeats Nia Jax to retain the title", stake("WWE Women's Championship")),
]


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    import copy
    events = copy.deepcopy(data["events"]) if dry else data["events"]
    by_id = {m["id"]: m for e in events.values() for m in e["matches"]}
    changed = 0
    for mid, text, fix in FIXES:
        m = by_id.get(mid)
        if m is None or not (m.get("raw_description") or "").startswith(text):
            raise SystemExit(f"ABORT: match {mid} not found or its text changed")
        changed += fix(m)
    if not changed:
        print("already applied")
        return
    print(f"fixed {changed} matches")
    if dry:
        print("dry run: nothing written")
        return
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
