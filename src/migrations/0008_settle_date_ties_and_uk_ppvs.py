"""
Settle the lineup check's date ties from published sources, and add the UK PPVs.

The lineup check left 8 shows where two sources said one date and two said
another. Each is settled here from WWE's own archived site or Wikipedia's
episode lists, and every decision carries its source:

  SmackDown, 6 shows filed on a Friday that aired live on the Tuesday before.
    Wikipedia, List of WWE SmackDown special episodes, lists each as a Tuesday
    special (SuperSmackDown Live and Tuesday Night SmackDown), and the episode
    numbers run on without a Friday show between them (#653 is 2012-02-21,
    #654 is 2012-03-02).
  Raw #664, 2006-02-13 to 2006-02-16. USA aired the Westminster Kennel Club
    Dog Show that Monday; WWE's own Raw archive has a page for 02162006 and none
    for the 13th (Wayback capture 20060413105955), and our own title already
    says "Thursday Night RAW".
  Raw #716, 2007-02-12 to 2007-02-15, taped 2007-02-12. WWE's Raw archive page
    is 02152007, and Wikipedia's list of Raw special episodes has it airing
    Thursday, February 15, taped February 12.

It also adds what the scope decisions of 2026-10-05 asked for:
  SmackDown 2005-11-29, a one-hour live Tuesday special that Wikipedia says
    aired in addition to the regular Friday show, built from SmackDown Hotel's
    card and Cawthon's place for it.
  The UK-only PPVs, from Wikipedia the way the 2020-on PPV lane does: Rebellion
    2001 and 2002, Insurrextion 2002 and 2003.

Safety gates: a show is moved only if it still sits on its "from" date with
the expected episode number and nothing of its type already sits on the "to"
date; nothing is added on a date that already holds a show of that type.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0008_settle_date_ties_and_uk_ppvs.py [--dry-run]
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "lineup-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.build_update import load_existing, map_wikipedia  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "m7", Path(__file__).with_name("0007_fix_missing_and_misdated_shows.py"))
m7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m7)

SD_SPECIALS = "https://en.wikipedia.org/wiki/List_of_WWE_SmackDown_special_episodes"
RAW_SPECIALS = "https://en.wikipedia.org/wiki/List_of_WWE_Raw_special_episodes"
MOVES = [
    # (show type, episode number, from, to, tape date or None, source)
    ("SmackDown", 641, "2011-12-02", "2011-11-29", None, SD_SPECIALS),
    ("SmackDown", 653, "2012-02-24", "2012-02-21", None, SD_SPECIALS),
    ("SmackDown", 660, "2012-04-13", "2012-04-10", None, SD_SPECIALS),
    ("SmackDown", 672, "2012-07-06", "2012-07-03", None, SD_SPECIALS),
    ("SmackDown", 690, "2012-11-09", "2012-11-06", None, SD_SPECIALS),
    ("SmackDown", 696, "2012-12-21", "2012-12-18", None, SD_SPECIALS),
    ("Raw", 664, "2006-02-13", "2006-02-16", None,
     "https://web.archive.org/web/20060413105955/http://www.wwe.com/shows/raw/archive/02162006/"),
    ("Raw", 716, "2007-02-12", "2007-02-15", "2007-02-12", "https://www.wwe.com/shows/raw/archive/02152007"),
]
WIKI = PROJECT_ROOT / "lineup-check" / "wiki-cache"
UK_PPVS = {"2001-11-03": "Rebellion (2001)", "2002-05-04": "Insurrextion (2002)",
           "2002-10-26": "Rebellion (2002)", "2003-06-07": "Insurrextion (2003)"}
SPECIAL_2005 = {"show_type": "SmackDown", "air_date": "2005-11-29", "source": SD_SPECIALS}
RENAME_DAY = "2002-05-06"      # WWF became WWE


def plan(events):
    on = lambda day, typ: [e for e in events.values() if e["air_date"] == day and e["show_type"] == typ]
    moves = []
    for typ, num, frm, to, tape, src in MOVES:
        here = [e for e in on(frm, typ) if e.get("episode_number") == num]
        if not here:
            if any(e.get("episode_number") == num for e in on(to, typ)):
                continue                                                 # already moved
            raise SystemExit(f"ABORT: {typ} #{num} not on {frm}")
        if on(to, typ):
            raise SystemExit(f"ABORT: {to} already holds a {typ}")
        moves.append((here[0], to, tape, src))
    special = None if on(SPECIAL_2005["air_date"], "SmackDown") else SPECIAL_2005
    ppvs = [(d, a) for d, a in UK_PPVS.items() if not on(d, "PPV")]
    return moves, special, ppvs


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    events, by_date = data["events"], data["events_by_date"]
    moves, special, ppvs = plan(events)
    if not moves and not special and not ppvs:
        print("already applied")
        return
    print(f"moves {len(moves)}, 2005 special {'yes' if special else 'no'}, uk ppvs {len(ppvs)}")
    if dry:
        print("dry run: nothing written")
        return
    for ev, to, tape, src in moves:
        by_date[ev["air_date"]].remove(ev["id"])
        if not by_date[ev["air_date"]]:
            del by_date[ev["air_date"]]
        ev["air_date"] = to
        if tape:
            ev["tape_date"], ev["broadcast_type"] = tape, "Taped"
        ev["date_derivation"] = f"air date settled from {src}"
        by_date.setdefault(to, []).append(ev["id"])
    eid = max(int(k) for k in events) + 1
    mid = max(m["id"] for e in events.values() for m in e["matches"]) + 1
    if special:
        from cawthon_parse import parse_show_page
        from lineup_check import CACHE, load_sdh
        from missing_shows import sdh_episode_numbers
        typ, day = special["show_type"], special["air_date"]
        ep = next(e for e in parse_show_page((CACHE / "wwe-smackdown-2005.html").read_text(encoding="utf-8"))
                  if e["air_date"] == day)
        like = min((e for e in events.values() if e["show_type"] == typ),
                   key=lambda e: abs(int(e["air_date"].replace("-", "")) - int(day.replace("-", ""))))
        ev, mid = m7.weekly_event(eid, mid, typ, day, sdh_episode_numbers().get((day, typ)), ep["tape_date"],
                                  ep["city"], ep["venue"], load_sdh()[(day, typ)], ep["lines"], like)
        if ev["episode_number"] is None:
            ev["title"] = "WWE Friday Night SmackDown - Tuesday Special"
        ev["date_derivation"] = f"Tuesday special, aired in addition to Friday ({special['source']})"
        events[str(eid)] = ev
        by_date.setdefault(day, []).append(eid)
        eid += 1
    from src.wikipedia_ppv import parse_event
    for day, article in ppvs:
        parsed = parse_event((WIKI / (article.replace(" ", "_") + ".wiki")).read_text(encoding="utf-8"))
        made, eid, mid = map_wikipedia(parsed, eid, mid)
        like = min((e for e in events.values() if e["show_type"] == "PPV"),
                   key=lambda e: abs(int(e["air_date"].replace("-", "")) - int(day.replace("-", ""))))
        for ev in made:
            prefix = "WWF" if ev["air_date"] < RENAME_DAY else "WWE"
            base = article.split(" (")[0]
            city, _, rest = (ev.get("city") or "").partition(",")
            ev.update(title=f"{prefix} {base} {ev['air_date'][:4]}", ppv_name=f"{prefix} {base} {ev['air_date'][:4]}",
                      tv_network="Pay-Per-View", logo=like.get("logo"), promotion=like.get("promotion"),
                      city=city.strip() or None, state_province=None, country=rest.strip() or None,
                      source="Wikipedia (UK PPV, lineup check)")
            m7.champion_marks(ev["matches"])
            events[str(ev["id"])] = ev
            by_date.setdefault(ev["air_date"], []).append(ev["id"])
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
