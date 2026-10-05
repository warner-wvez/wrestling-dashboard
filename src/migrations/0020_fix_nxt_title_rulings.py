"""
Two NXT title rulings the cards cannot express on their own.

Found by laying each NXT belt's reign chain beside its three title histories
(Wikipedia, Duncan and Will's wrestling-titles.com, WWE.com) after the NXT
changes went in through lineup-check/offshow_titles.py.

  SmackDown 2023-06-23, the women's tag unification (match 31748). Ronda
    Rousey and Shayna Baszler beat Alba Fyre and Isla Dawn to unify the NXT
    Women's Tag Team titles into the WWE Women's Tag Team titles, which
    retired the NXT belts. Wikipedia and WWE.com both recognize Fyre and Dawn
    as the final NXT champions, so the walk must not hand the NXT belts to
    Rousey and Baszler for a day. Only Duncan and Will list that reign.
  NXT Halloween Havoc 2025-10-25 (match 33091). Blake Monroe beat Zaria, who
    defended the Women's North American title for the injured Sol Ruca. The
    card marks Zaria "(c)", so the walk gave her a reign of her own. All three
    histories run Sol Ruca straight to Monroe.

Safety gate: each match is found by match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0020_fix_nxt_title_rulings.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

WOMENS_TAG = "https://en.wikipedia.org/wiki/NXT_Women%27s_Tag_Team_Championship"
WOMENS_NA = "https://en.wikipedia.org/wiki/List_of_NXT_Women%27s_North_American_Champions"


def ruling(title, champions, why, source):
    def apply(m):
        want = [{"title": title, "champions": champions, "why": why, "source": source}]
        if m.get("title_result") == want:
            return False
        m["title_result"] = want
        return True
    return apply


FIXES = [
    # (match id, start of stored text (the same before and after the fix), fix)
    (31748, "Ronda Rousey & Shayna Baszler (c) [WWE] defeat Alba Fyre & Isla Dawn (c) [NXT]",
     ruling("NXT Women's Tag Team Title", ["Alba Fyre", "Isla Dawn"],
            "the NXT belts were unified into the WWE Women's Tag Team titles and retired; Wikipedia and "
            "WWE.com recognize Fyre and Dawn as the final champions", WOMENS_TAG)),
    (33091, "[[Blake Monroe]] defeated [[Zaria (wrestler)|Zaria]] (c) (with [[Sol Ruca]])",
     ruling("NXT Women's North American Title", ["Blake Monroe"],
            "Monroe beat Zaria, who defended the title for the injured Sol Ruca", WOMENS_NA)),
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
