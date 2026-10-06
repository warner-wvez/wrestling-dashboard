"""
Six pay-per-views the corpus lacks, built from their Wikipedia results tables
the way the 2020-on PPV lane and migrations 0007 and 0008 build them.

Found by laying Wikipedia's List of WWE pay-per-view and livestreaming
supercards beside our events, by date and by name:

  Insurrextion 2001 (2001-05-05, London). The UK-only PPV that 0008's set
    left out; Rebellion 2001 and 2002 and Insurrextion 2002 and 2003 are in.
  Great Balls of Fire 2017 (2017-07-09, Dallas), Raw's July PPV.
  The Horror Show at Extreme Rules (2020-07-19, Orlando).
  Bash in Berlin (2024-08-31).
  Clash in Paris (2025-08-31).
  Clash in Italy (2026-05-31).

Each takes its era's shape. The first two are named the way the Cagematch
lane names a PPV ("WWE Great Balls of Fire 2017") and, like every 2014-2019
card of ours, leave the pre-show off; the title changes on those pre-shows
come in through data/offshow-title-changes.json. The last four are named the
way the Wikipedia lane names them and keep their whole table, as every
2020-on card does.

Insurrextion 2001's main event is a handicap match for Steve Austin's WWF
title that The Undertaker won by pinning Triple H, so Austin kept the belt
(Wikipedia: "Since Undertaker pinned Triple H, he did not win the title"); it
carries that ruling, and Austin's name as the 2001 cards spell it. A result
the table wrote into a side's name comes off it the way migration 0018 does.

Safety gates: nothing is added on a date that already holds a PPV, unless it
is this same show (already applied); a page that parses to no matches aborts.
Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0024_add_missing_ppvs.py [--dry-run]
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "lineup-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.build_update import load_existing, map_wikipedia  # noqa: E402
from src.export_to_html import clean_participant  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "m7", Path(__file__).with_name("0007_fix_missing_and_misdated_shows.py"))
m7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m7)
_spec18 = importlib.util.spec_from_file_location(
    "m18", Path(__file__).with_name("0018_clean_side_names.py"))
m18 = importlib.util.module_from_spec(_spec18)
_spec18.loader.exec_module(m18)

WIKI = "https://en.wikipedia.org/wiki/"
RENAME_DAY = "2002-05-06"           # WWF became WWE
# (air date, Wikipedia article, "classic" = Cagematch-lane shape, "lane" = 2020-on shape)
ADD = [
    ("2001-05-05", "Insurrextion (2001)", "classic"),
    ("2017-07-09", "Great Balls of Fire (2017)", "classic"),
    ("2020-07-19", "The Horror Show at Extreme Rules", "lane"),
    ("2024-08-31", "Bash in Berlin", "lane"),
    ("2025-08-31", "Clash in Paris", "lane"),
    ("2026-05-31", "Clash in Italy", "lane"),
]
# The corpus spells him "Steve Austin" throughout 2001.
NAMES_2001 = {'"Stone Cold" Steve Austin': "Steve Austin"}


def title_of(day, article, shape, info_name):
    if shape == "lane":
        return info_name
    prefix = "WWF" if day < RENAME_DAY else "WWE"
    return f"{prefix} {re.sub(r'\s*\(\d{4}\)\s*$', '', article)} {day[:4]}"


def pre_show_orders(wikitext):
    """The match numbers a results table marks "pre"."""
    from src.wikipedia_ppv import find_blocks, template_params
    out = set()
    for block in find_blocks(wikitext, "Pro wrestling results table"):
        p = template_params(block)
        out |= {int(k[4:]) for k, v in p.items() if re.fullmatch(r"note\d+", k) and v.strip().lower().startswith("pre")}
    return out


def build(day, article, shape, eid, mid, like):
    from wiki_titles import fetch
    from src.wikipedia_ppv import parse_event
    text = fetch(article)["text"]
    parsed = parse_event(text)
    if shape == "classic":
        pre = pre_show_orders(text)
        for tbl in parsed["tables"]:
            tbl["matches"] = [m for m in tbl["matches"] if m["match_order"] not in pre]
            for n, m in enumerate(tbl["matches"], 1):
                m["match_order"] = n
    for tbl in parsed["tables"]:
        tbl["date"] = day
    made, eid, mid = map_wikipedia(parsed, eid, mid)
    if not made or not any(ev["matches"] for ev in made):
        raise SystemExit(f"ABORT: {article} parsed to no matches")
    for ev in made:
        name = title_of(day, article, shape, ev.get("ppv_name"))
        ev.update(title=name, ppv_name=name, source="Wikipedia (missing PPV, lineup check)")
        if shape == "classic":
            city, _, rest = (ev.get("city") or "").partition(",")
            rest = rest.strip()
            state = m7.STATES.get(rest) or (rest if rest in m7.STATES.values() else None)
            ev.update(tv_network="Pay-Per-View" if day < "2014-02-24" else "WWE Network",
                      logo=like.get("logo"), promotion=like.get("promotion"),
                      city=city.strip() or None, state_province=state,
                      country="USA" if state else (rest or None))
            m7.champion_marks(ev["matches"])
        for m in ev["matches"]:
            for t in m["teams"]:
                t["participants"] = [NAMES_2001.get(p, p) if day < "2002-01-01" else p for p in t["participants"]]
                t["participants"] = [c for c in map(clean_participant, t["participants"]) if c]
                # A result the table wrote after the loser ("& no contest")
                # comes off the side's name, as migration 0018 does.
                name = t.get("team_name") or ""
                if m18.clean(name) != name and m18.names_everyone(m18.clean(name), t["participants"]):
                    t["team_name"] = m18.clean(name)
    return made, eid, mid


def austin_keeps_the_title(made):
    m = next(m for ev in made for m in ev["matches"] if "Two Man Power Trip" in (m.get("raw_description") or ""))
    m["title_result"] = [{"title": m.get("title_at_stake"), "champions": ["Steve Austin"],
                          "why": "a handicap match Austin's title could change hands in only if he was "
                                 "pinned; The Undertaker pinned Triple H, so Austin kept the belt",
                          "source": WIKI + "Insurrextion_(2001)"}]


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    events, by_date = data["events"], data["events_by_date"]
    todo = []
    for day, article, shape in ADD:
        here = [e for e in events.values() if e["air_date"] == day and e["show_type"] == "PPV"]
        if here:
            if not any(re.sub(r"\s*\(\d{4}\)$", "", article).split(" (")[0].lower() in e["title"].lower()
                       for e in here):
                raise SystemExit(f"ABORT: {day} already holds a PPV: {[e['title'] for e in here]}")
            continue                                                     # already added
        todo.append((day, article, shape))
    if not todo:
        print("already applied")
        return
    print(f"new ppvs {len(todo)}: {', '.join(a for _, a, _ in todo)}")
    if dry:
        print("dry run: nothing written")
        return
    eid = max(int(k) for k in events) + 1
    mid = max(m["id"] for e in events.values() for m in e["matches"]) + 1
    for day, article, shape in todo:
        like = min((e for e in events.values() if e["show_type"] == "PPV"),
                   key=lambda e: abs(int(e["air_date"].replace("-", "")) - int(day.replace("-", ""))))
        made, eid, mid = build(day, article, shape, eid, mid, like)
        if day == "2001-05-05":
            austin_keeps_the_title(made)
        for ev in made:
            events[str(ev["id"])] = ev
            by_date.setdefault(ev["air_date"], []).append(ev["id"])
            print(f"  {ev['air_date']} {ev['title']}: {len(ev['matches'])} matches")
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
