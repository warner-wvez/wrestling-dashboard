"""
Name the 2001-2003 SmackDowns and Raw #397 as they were billed then.

149 SmackDown episodes from 2001 to 2003 carried the title "Thursday Night
SmackDown", a name the show took in 2014; the ones around them read "WWF
SmackDown #N" and, after WWF became WWE on 2002-05-06, "WWE SmackDown #N".
Each takes that name with its own episode number. One, 2001-05-17, had no
number; it falls between #90 (05-10) and #92 (05-24), so it is #91.

Raw #397 on 2001-01-01 read "WWF RAW #397" while every Raw from 2001-01-08 to
2001-09-10 reads "WWF RAW is WAR"; the show was billed Raw Is War until
September 2001, so #397 is "WWF RAW is WAR #397".

Safety gates: a show is renamed only when it still carries the old title on
its date; at most 150 renames.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0025_name_shows_for_their_era.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.build_update import load_existing  # noqa: E402

OLD = "Thursday Night SmackDown"
RENAME_DAY = "2002-05-06"           # WWF became WWE
CEILING = 150
NUMBERED = {"2001-05-17": 91}       # no number on our card; between #90 and #92
RAW_397 = ("2001-01-01", "WWF RAW #397", "WWF RAW is WAR #397")


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    events = data["events"]
    todo = []
    for e in events.values():
        if e["show_type"] != "SmackDown" or e.get("title") != OLD or e["air_date"] >= "2004-01-01":
            continue
        n = e.get("episode_number") or NUMBERED.get(e["air_date"])
        if n is None:
            raise SystemExit(f"ABORT: SmackDown {e['air_date']} has no episode number")
        prefix = "WWF" if e["air_date"] < RENAME_DAY else "WWE"
        todo.append((e, f"{prefix} SmackDown #{n}", n))
    raw = next((e for e in events.values() if e["show_type"] == "Raw" and e["air_date"] == RAW_397[0]), None)
    if raw is None or raw["title"] not in (RAW_397[1], RAW_397[2]):
        raise SystemExit(f"ABORT: Raw {RAW_397[0]} is {raw and raw['title']!r}")
    raw_todo = raw["title"] == RAW_397[1]
    if len(todo) > CEILING:
        raise SystemExit(f"ABORT: {len(todo)} renames, ceiling {CEILING}")
    if not todo and not raw_todo:
        print("already applied")
        return
    print(f"SmackDown renames {len(todo)}, Raw #397 {'yes' if raw_todo else 'no'}")
    if dry:
        print("dry run: nothing written")
        return
    for e, title, n in todo:
        e["title"] = title
        e["episode_number"] = n
    if raw_todo:
        raw["title"] = RAW_397[2]
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
