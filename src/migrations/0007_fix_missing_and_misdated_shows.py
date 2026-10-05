"""
Put 2001-2013 shows on their real dates and add the ones the corpus lacks.

lineup-check/missing_shows.py stages lineup-check/out/missing-shows.json from
Cawthon's archive, SmackDown Hotel and the Peacock/Netflix air-date list. This
applies it:

  week_shifts  14 shows hold the NEXT episode's card: a double taping our
               source filed under the taping date (Raw "#767" on 2008-02-04 is
               really #768 from 2008-02-11; SmackDown Hotel numbers it so and
               Cawthon lists that exact card on 02-11). Each moves to its real
               date and number, keeping its taping date, and the real show for
               the date it vacated is rebuilt from SmackDown Hotel when that
               card agrees with Cawthon's (13 of 14). Migration 0006 had
               compared these shows with the wrong week, so its changes to them
               are undone first: 3 added matches come off and 1 result goes
               back to what the corpus had (git ad53061).
  date_fixes   3 shows on a date two other sources agree is wrong.
  weekly       1 SmackDown the corpus lacks (2013-10-04), built the same way.
  ppv          3 PPVs the corpus lacks, built from Wikipedia the way the
               2020-on PPV lane does: One Night Stand 2007 and 2008, Fatal 4-Way.

Safety gates:
  1. Every moved event must still sit on its "from" date with the episode
     number the plan expects, or the run aborts.
  2. No event is created on a date that already holds a show of that type.
  3. Ceilings: 20 shifts, 10 date fixes, 20 new weekly shows, 10 PPVs.
  Idempotent: a second run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0007_fix_missing_and_misdated_shows.py [--dry-run]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "lineup-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.build_update import load_existing, map_match, map_wikipedia  # noqa: E402

PLAN = PROJECT_ROOT / "lineup-check" / "out" / "missing-shows.json"
ADDED_BY_0006 = "Cawthon + SmackDown Hotel (lineup check)"
BEFORE_0006 = "ad53061"
SOURCE = "SmackDown Hotel card, Cawthon dates (lineup check)"
CEILING = {"week_shifts": 20, "date_fixes": 10, "weekly": 20, "ppv": 10}
TITLE = {"Raw": "WWE Monday Night RAW #{n}", "SmackDown": "WWE Friday Night SmackDown #{n}"}
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}


# Wikipedia and SmackDown Hotel name belts "... Championship"; the corpus
# names the same lineages Cagematch-style, and a new show must join the
# existing lineage, not start its own (a "WWE Title" lineage of three PPVs).
TITLE_NAMES = {
    "WWE Championship": "WWE Heavyweight Title",
    "World Heavyweight Championship": "World Heavyweight Title",
    "WWE United States Championship": "WWE United States Title",
    "WWE Intercontinental Championship": "WWE Intercontinental Title",
    "WWE Divas Championship": "WWE Divas Title",
    "Unified WWE Divas Championship": "Unified WWE Divas Title",
    "Unified WWE Tag Team Championship": "Unified WWE Tag Team Title",
    "World Tag Team Championship": "World Tag Team Title",
    "ECW World Championship": "ECW World Heavyweight Title",
    "ECW Championship": "ECW World Heavyweight Title",
    # 2001-02, for the UK PPVs added by migration 0008
    "WWF Championship": "WWF World Heavyweight Title",
    "WCW Championship": "WCW World Heavyweight Title",
    "WCW Tag Team Championship": "WCW World Tag Team Title",
    # The corpus names this belt "World Women's Title" until late 2005, and
    # Insurrextion 2003 is the only added show that defends it.
    "WWE Women's Championship": "World Women's Title",
}


def corpus_titles(title):
    """A new show's title string in the corpus's names; parts that are not a
    belt at all ("/ Night of Champions") are dropped."""
    if not title:
        return title
    parts = [TITLE_NAMES.get(p.strip(), p.strip()) for p in title.split("/")]
    parts = [p for p in parts if re.search(r"(Title|Championship)$", p)]
    return " / ".join(parts) or None


def champion_marks(matches):
    """SmackDown Hotel writes the champion as "Layla ©": the mark comes off the
    name and becomes the team's champion flag."""
    for m in matches:
        m["title_at_stake"] = corpus_titles(m.get("title_at_stake"))
        for t in m["teams"]:
            marked = [p for p in t["participants"] if p.rstrip().endswith("\u00a9")]
            if marked:
                t["was_champion_entering"] = True
                t["participants"] = [p.rstrip().rstrip("\u00a9").rstrip() for p in t["participants"]]
                t["team_name"] = (t.get("team_name") or "").replace(" \u00a9", "").replace("\u00a9", "").strip()


def place(text):
    """'Austin, TX' -> (city, state, country); 'Manchester, England' -> (city, None, 'England')."""
    city, _, rest = (text or "").partition(",")
    rest = rest.strip()
    if rest in STATES:
        return city.strip(), STATES[rest], "USA"
    return city.strip() or None, None, rest or None


def retitle(title, number):
    """Swap the episode number in a title, keeping any subtitle."""
    return re.sub(r"#\d+", f"#{number}", title or "", count=1)


def _era(year):
    return int(year) // 3 * 3


def original_match(event_id, match_id, year):
    """A match as the corpus had it before migration 0006, from git."""
    raw = subprocess.run(["git", "show", f"{BEFORE_0006}:shards/matches-{_era(year)}.json"],
                         cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout
    return next(m for m in json.loads(raw)[str(event_id)] if m["id"] == match_id)


def undo_0006(ev):
    """Take 0006's changes off a show it compared with the wrong week."""
    undone = 0
    kept = []
    for m in ev["matches"]:
        if m.get("source") == ADDED_BY_0006:
            undone += 1
            continue
        if m.get("result_note"):
            orig = original_match(ev["id"], m["id"], ev["air_date"][:4])
            m["teams"], m["title_at_stake"] = orig["teams"], orig.get("title_at_stake")
            del m["result_note"]
            undone += 1
        kept.append(m)
    ev["matches"] = kept
    for n, m in enumerate(kept, 1):
        m["match_order"] = n
    ev["match_count"] = len(kept)
    return undone


def durations(matches, cawthon_lines):
    """Fill missing match times from Cawthon's "at 12:05" by matching people."""
    from cawthon_parse import parse_match_line
    from lineup_match import best_match, duration_of
    lines = [(p, duration_of(p["line"])) for p in map(parse_match_line, cawthon_lines) if p]
    for m in matches:
        if m.get("duration_seconds"):
            continue
        people = {p for t in m["teams"] for p in t["participants"]}
        for p, secs in lines:
            his = {best_match(n, sorted(people)) for n in p["winners"] + p["losers"]} - {None}
            if secs and his and his == people:
                m["duration_seconds"] = secs
                break


def weekly_event(eid, mid, show_type, day, number, tape_date, where, venue, sdh_matches,
                 cawthon_lines, like):
    matches = []
    for m in sdh_matches:
        matches.append(map_match(m, mid))
        mid += 1
    durations(matches, cawthon_lines)
    champion_marks(matches)
    city, state, country = place(where)
    if like.get("city") == city and like.get("venue"):
        # Same arena as its neighbour (a double taping): the corpus spelling
        # wins over Cawthon's ("Frank Erwin Center", not "Frank Irwin").
        venue, state, country = like["venue"], like.get("state_province"), like.get("country")
    ev = {k: like.get(k) for k in ("tv_network", "commentary", "promotion", "promotion_raw", "logo")}
    ev.update(id=eid, air_date=day, tape_date=tape_date,
              date_derivation="Cawthon + SmackDown Hotel dates (lineup check)",
              show_type=show_type, episode_number=number, title=TITLE[show_type].format(n=number),
              ppv_name=None, venue=venue, city=city, state_province=state, country=country,
              attendance=None, tv_rating=None, broadcast_type="Taped" if tape_date != day else "Live",
              cagematch_nr=None, cagematch_url=None, fandom_slug=None, fandom_url=None,
              primary_source="thesmackdownhotel", verification_status="lineup-check",
              match_count=len(matches), matches=matches, source=SOURCE)
    return ev, mid


def main():
    dry = "--dry-run" in sys.argv
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for k, cap in CEILING.items():                                       # gate 3
        if len(plan.get(k, [])) > cap:
            raise SystemExit(f"ABORT gate 3: {len(plan[k])} {k}, ceiling {cap}")
    data = load_existing()
    events, by_date = data["events"], data["events_by_date"]
    on = lambda day, typ: [e for e in events.values() if e["air_date"] == day and e["show_type"] == typ]

    todo = {"shift": [], "fix": [], "new": []}
    for s in plan["week_shifts"]:
        ev = events[str(s["event_id"])]
        if ev["air_date"] == s["to"]:
            continue                                                     # already moved
        if ev["air_date"] != s["from"]:                                  # gate 1
            raise SystemExit(f"ABORT gate 1: event {ev['id']} is on {ev['air_date']}, plan says {s['from']}")
        todo["shift"].append((ev, s))
    for f in plan["date_fixes"]:
        ev = events[str(f["event_id"])]
        if ev["air_date"] == f["from"]:
            todo["fix"].append((ev, f))
    wanted = [(s["show_type"], s["vacated"]) for s in plan["week_shifts"] if s["vacated"]["add"]]
    wanted += [(w["show_type"], {**w, "add": True}) for w in plan["weekly"]]
    for typ, v in wanted:
        moving_off = any(ev["air_date"] == v["air_date"] and ev["show_type"] == typ for ev, _ in todo["shift"])
        if not on(v["air_date"], typ) or moving_off:                     # gate 2
            todo["new"].append((typ, v))
    ppv_todo = [p for p in plan["ppv"] if not on(p["air_date"], "PPV")]
    if not any(todo.values()) and not ppv_todo:
        print("already applied")
        return
    print(f"shifts {len(todo['shift'])}, date fixes {len(todo['fix'])}, new weekly {len(todo['new'])}, "
          f"new ppv {len(ppv_todo)}")
    if dry:
        print("dry run: nothing written")
        return

    def move(ev, to):
        ids = by_date.get(ev["air_date"], [])
        if ev["id"] in ids:
            ids.remove(ev["id"])
        if not ids:
            by_date.pop(ev["air_date"], None)
        ev["air_date"] = to
        by_date.setdefault(to, []).append(ev["id"])

    undone = 0
    for ev, s in todo["shift"]:
        undone += undo_0006(ev)
        move(ev, s["to"])
        ev["episode_number"] = s["number"]
        ev["title"] = retitle(ev["title"], s["number"])
        ev["broadcast_type"] = "Taped"
        ev["date_derivation"] = "air date from Cawthon + SmackDown Hotel; taped the night of an earlier episode"
    for ev, f in todo["fix"]:
        move(ev, f["to"])
        ev["date_derivation"] = "air date from Cawthon + SmackDown Hotel + Peacock list"
    eid = max(int(k) for k in events) + 1
    mid = max(m["id"] for e in events.values() for m in e["matches"]) + 1
    for typ, v in todo["new"]:
        like = min((e for e in events.values() if e["show_type"] == typ),
                   key=lambda e: abs(int(e["air_date"].replace("-", "")) - int(v["air_date"].replace("-", ""))))
        ev, mid = weekly_event(eid, mid, typ, v["air_date"], v["number"], v["tape_date"],
                               v.get("place"), v.get("venue"), v["sdh_matches"], v["cawthon_lines"], like)
        events[str(eid)] = ev
        by_date.setdefault(ev["air_date"], []).append(eid)
        eid += 1
    for p in ppv_todo:
        made, eid, mid = map_wikipedia(p["parsed"], eid, mid)
        for ev in made:
            base = re.sub(r"\s*\(\d{4}\)\s*$", "", p["article"])
            ev["title"] = ev["ppv_name"] = f"WWE {base} {ev['air_date'][:4]}"
            city, _, state = (ev.get("city") or "").partition(",")
            ev.update(tv_network="Pay-Per-View", logo="promotion-20020506",
                      promotion="World Wrestling Entertainment", source="Wikipedia (lineup check)",
                      city=city.strip() or None, state_province=state.strip() or None,
                      country="USA" if state.strip() in STATES.values() else None)
            champion_marks(ev["matches"])
            events[str(ev["id"])] = ev
            by_date.setdefault(ev["air_date"], []).append(ev["id"])
    print(f"undid {undone} migration-0006 changes on shifted shows")
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
