"""
Fix match records the title audit found after vacancies went in.

  Raw 2024-04-22, Women's World title (match 30390). Becky Lynch won a
    14-woman battle royal for the title Rhea Ripley had relinquished a week
    earlier (Wikipedia's List of Women's World Champions). The stored belt read
    "Women's World Championship 14-Woman Battle Royal: Winner", a string no
    lineage knows, so the reign was missing: the title sat vacant from Ripley
    to Liv Morgan. The belt string is set to the corpus's name for the title,
    and a ruling names Lynch the champion after the match.

Safety gate: each match is found by event id + match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0017_fix_title_audit_findings.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

WOMENS_WORLD = "https://en.wikipedia.org/wiki/List_of_Women%27s_World_Champions_(WWE)"


def becky(m):
    want = {"title": "Women's World Title", "champions": ["Becky Lynch"],
            "why": "won the battle royal for the vacant title", "source": WOMENS_WORLD}
    if m.get("title_at_stake") == "Women's World Title" and m.get("title_result") == want:
        return False
    m["title_at_stake"] = "Women's World Title"
    m["match_type"] = "Women's World Title Battle Royal"
    m["title_result"] = want
    return True


FIXES = [
    # (event id, match id, start of stored text, fix)
    (None, 30390, "Becky Lynch, Liv Morgan, Nia Jax", becky),
]


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    import copy
    events = copy.deepcopy(data["events"]) if dry else data["events"]
    by_id = {m["id"]: m for e in events.values() for m in e["matches"]}
    changed = 0
    for _, mid, text, fix in FIXES:
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
