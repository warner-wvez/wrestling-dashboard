"""
Fill two calendar gaps the lineup check left: Raw #896 and SmackDown's
"Best of 2006".

Raw #896 (2010-07-26), the show migration 0007 left empty.

Migration 0007 moved the card filed under 2010-07-26 to 2010-08-02, where it
belonged (it was #897), but did not rebuild the real #896 because SmackDown
Hotel's card scored a 46 percent fit with Cawthon's. That score was the
parser's, not the cards': Cawthon writes the 7-on-7 Nexus elimination match
with no "defeated", so the line never parsed. Read side by side, the two cards
list the same six matches in the same order:

  Randy Orton beat Jey Uso; Edge vs The Great Khali, no contest; the Nexus
  beat seven of Raw's roster in an elimination match; Alicia Fox beat Brie
  Bella; Ted DiBiase beat John Morrison; Sheamus & The Miz beat John Cena &
  Chris Jericho.

So the show is built from SmackDown Hotel's card with Cawthon's times and
place (San Antonio, TX, AT&T Center), the way migration 0007 built the other
recovered shows.

SmackDown, 2006-12-29: a "Best of SmackDown! 2006" clip show. Cawthon lists
it, and the Peacock/Netflix air-date list has a Peacock playback page for it
(GMO_00000000373210_01), but our source and SmackDown Hotel never carried it,
so the calendar skipped a week. It is added with no matches, the way Raw #501's
Year in Review sits in the corpus, and no episode number: our numbering runs
#384 on 12-22 to #385 on 2007-01-05.

Safety gate: nothing is added on a date that already holds a show of its type.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0012_fill_calendar_gaps.py [--dry-run]
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "lineup-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.build_update import load_existing  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "m7", Path(__file__).with_name("0007_fix_missing_and_misdated_shows.py"))
m7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m7)

DAY, TYPE, NUMBER = "2010-07-26", "Raw", 896
BEST_OF = {"air_date": "2006-12-29", "show_type": "SmackDown", "like": "2006-12-22",
           "title": "WWE Friday Night SmackDown - Best of SmackDown 2006",
           "source": "Cawthon + Peacock/Netflix air-date list (Peacock GMO_00000000373210_01)"}


def _on(events, day, typ):
    return any(e["air_date"] == day and e["show_type"] == typ for e in events.values())


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    events, by_date = data["events"], data["events_by_date"]
    raw = not _on(events, DAY, TYPE)
    best_of = not _on(events, BEST_OF["air_date"], BEST_OF["show_type"])
    if not raw and not best_of:
        print("already applied")
        return
    print(f"Raw #{NUMBER} {'yes' if raw else 'no'}, Best of SmackDown 2006 {'yes' if best_of else 'no'}")
    if dry:
        print("dry run: nothing written")
        return
    eid = max(int(k) for k in events) + 1
    mid = max(m["id"] for e in events.values() for m in e["matches"]) + 1
    if raw:
        from cawthon_parse import parse_show_page
        from lineup_check import CACHE, load_sdh
        ep = next(e for e in parse_show_page((CACHE / "wwe-raw-2010.html").read_text(encoding="utf-8"))
                  if e["air_date"] == DAY)
        like = next(e for e in events.values() if e["show_type"] == TYPE and e["air_date"] == "2010-08-02")
        ev, mid = m7.weekly_event(eid, mid, TYPE, DAY, NUMBER, ep["tape_date"], ep["city"], ep["venue"],
                                  load_sdh()[(DAY, TYPE)], ep["lines"], like)
        events[str(eid)] = ev
        by_date.setdefault(DAY, []).append(eid)
        eid += 1
    if best_of:
        day, typ = BEST_OF["air_date"], BEST_OF["show_type"]
        like = next(e for e in events.values() if e["show_type"] == typ and e["air_date"] == BEST_OF["like"])
        ev = {k: like.get(k) for k in ("tv_network", "promotion", "promotion_raw", "logo")}
        ev.update(id=eid, air_date=day, tape_date=None, date_derivation=BEST_OF["source"],
                  show_type=typ, episode_number=None, title=BEST_OF["title"], ppv_name=None,
                  venue=None, city=None, state_province=None, country=None, attendance=None,
                  tv_rating=None, broadcast_type="Taped", commentary=None, cagematch_nr=None,
                  cagematch_url=None, fandom_slug=None, fandom_url=None, primary_source="cawthon",
                  verification_status="lineup-check", match_count=0, matches=[],
                  source=BEST_OF["source"])
        events[str(eid)] = ev
        by_date.setdefault(day, []).append(eid)
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
