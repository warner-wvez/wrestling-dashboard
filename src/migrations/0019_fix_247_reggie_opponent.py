"""
Raw 2021-11-08: Reggie won the 24/7 title from Drake Maverick, not Byron Saxton.

The night ran Drake Maverick, Akira Tozawa, Corey Graves, Byron Saxton, Drake
Maverick, Reggie. Our card (SmackDown Hotel lane) carries five of the six and
skips Drake pinning Saxton at ringside, so its last line reads "Reggie defeats
Byron Saxton (c)". Wikipedia's List of WWE 24/7 Champions, Duncan and Will's
title history and WWE.com's title history all have the reign Reggie ended as
Drake's second of the night. Drake's ringside win joins the title history from
data/247-title-changes.json; this puts the right champion on Reggie's match.

Safety gate: the match is found by event id + match id + stored text.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0019_fix_247_reggie_opponent.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

EVENT, MATCH = 2367, 29557
OLD = "Reggie defeats Byron Saxton (c) to win the title"
NEW = "Reggie defeats Drake Maverick (c) to win the title"


def plan(events):
    m = next((x for x in (events.get(str(EVENT)) or {}).get("matches") or [] if x["id"] == MATCH), None)
    raw = (m or {}).get("raw_description")
    if raw == NEW:
        return None
    if raw != OLD:
        raise SystemExit(f"ABORT: event {EVENT} match {MATCH} not found or its text changed: {raw!r}")
    return m


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    m = plan(data["events"])
    if m is None:
        print("already applied")
        return
    print(f"Raw 2021-11-08 match {MATCH}: Reggie's opponent Byron Saxton -> Drake Maverick")
    if dry:
        print("dry run: nothing written")
        return
    m["raw_description"] = NEW
    loser = next(t for t in m["teams"] if not t.get("was_winner"))
    loser.update(team_name="Drake Maverick", participants=["Drake Maverick"])
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
