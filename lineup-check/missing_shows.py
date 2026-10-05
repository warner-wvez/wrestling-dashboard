#!/usr/bin/env python3
"""Find the 2001 to 2013 shows the dashboard lacks or has on the wrong date,
and stage only what independent sources agree on.

Three sources besides our own: Graham Cawthon's pages (cache/), SmackDown
Hotel's year pages (sdh-cache/), and a fan-built list of WWE Network content on
Peacock and Netflix with air dates (passed with --sheet).

  date fix     one of our shows sits on a date two other sources agree is
               wrong, and they agree on the right one. When a source lists
               BOTH dates, they are two different shows and nothing moves.
  weekly add   a Raw or SmackDown that Cawthon lists and SmackDown Hotel or
               the sheet confirms, missing from our corpus. The card comes from
               SmackDown Hotel and must share most of its people with Cawthon's
               list for that night, or it is left out.
  ppv add      a PPV Cawthon lists that we lack, built from its Wikipedia
               article the way the 2020-on PPV lane already does.

Writes out/missing-shows.json for src/migrations/0007_add_missing_shows.py.

    uv run --with requests --with beautifulsoup4 --with openpyxl \\
        lineup-check/missing_shows.py --sheet "~/Downloads/WWE Network Peacock.xlsx"
"""
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from cawthon_parse import parse_match_line, parse_ppv_page, parse_show_page  # noqa: E402
from lineup_check import CACHE, OUT, YEARS, _org  # noqa: E402
from lineup_match import best_match  # noqa: E402

WIKI_CACHE = HERE / "wiki-cache"
# PPVs Cawthon lists that the corpus lacks, by Wikipedia article. The UK-only
# PPVs (Rebellion, Insurrextion) are left out until that scope is decided.
PPV_ARTICLES = {"2007-06-03": "One Night Stand (2007)",
                "2008-06-01": "One Night Stand (2008)",
                "2010-06-20": "Fatal 4-Way (2010)"}
NEAR_DAYS = 10


def sdh_episode_numbers():
    """{(date, show type): episode number} from the cached SmackDown Hotel pages."""
    from lineup_check import SDH_CACHE
    from src.smackdownhotel import parse_year_html
    out = {}
    for y in YEARS:
        for show, typ in (("raw", "Raw"), ("smackdown", "SmackDown")):
            f = SDH_CACHE / f"{show}-{y}.html"
            if f.exists():
                for e in parse_year_html(f.read_text(encoding="utf-8", errors="replace")):
                    out[(e["date"], typ)] = e.get("episode_number")
    return out


def sheet_dates(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    out = {"SmackDown": set(), "Raw": set()}
    for row in wb["Chronological"].iter_rows(min_row=2, values_only=True):
        if row[0] == "WWE Friday Night Smackdown" and isinstance(row[3], dt.datetime):
            out["SmackDown"].add(row[3].date().isoformat())
    for row in wb["Netflix"].iter_rows(min_row=2, values_only=True):
        if row[0] == "WWE Raw Vault" and isinstance(row[3], dt.datetime):
            out["Raw"].add(row[3].date().isoformat())
    return out


def cawthon_shows():
    shows = {}
    for y in YEARS:
        for typ, slug in (("Raw", f"{_org(y)}-raw-{y}"), ("SmackDown", f"{_org(y)}-smackdown-{y}")):
            for ep in parse_show_page((CACHE / f"{slug}.html").read_text(encoding="utf-8")):
                shows[(ep["air_date"], typ)] = ep
        for d in parse_ppv_page((CACHE / f"{_org(y)}-results-{y}.html").read_text(encoding="utf-8")):
            shows.setdefault((d, "PPV"), {"air_date": d})
    return shows


def matchup_fit(our_matches, cawthon_lines):
    """Share of Cawthon's bouts that appear on a card of ours with exactly the
    same people. Rosters repeat week to week; matchups mostly do not, so this
    tells "the same show on another date" from "next week's show"."""
    names = sorted({p for m in our_matches for t in m["teams"] for p in t.get("participants") or []})
    ours = {frozenset(p for t in m["teams"] for p in t.get("participants") or []) for m in our_matches}
    his = [frozenset(best_match(n, names) or n for n in line["winners"] + line["losers"])
           for line in cawthon_lines if line["kind"] == "match"]
    return sum(1 for h in his if h in ours) / max(1, len(his))


def people_fit(sdh_matches, cawthon_lines):
    """Share of SmackDown Hotel's wrestlers that Cawthon's lines for the same
    night also name: the gate for taking a card from SmackDown Hotel."""
    sdh = {p for m in sdh_matches for t in m["teams"] for p in t.get("participants") or []}
    his = [n for line in cawthon_lines for n in line["winners"] + line["losers"]]
    hit = {best_match(n, sorted(sdh)) for n in his} - {None}
    return len(hit) / max(1, len(sdh))


ADDED_BY_0006 = "Cawthon + SmackDown Hotel (lineup check)"


def plan(events, sdh, sheet, sdh_numbers):
    from datetime import date
    D = date.fromisoformat
    ours = {(e["air_date"], e["show_type"]): e for e in events.values()}
    caw = cawthon_shows()
    sdh_dates = {}
    for (d, t) in sdh:
        sdh_dates.setdefault(t, set()).add(d)
    in_years = lambda d: str(YEARS.start) <= d[:4] <= str(YEARS.stop - 1)
    caw_only = [k for k in caw if k not in ours and in_years(k[0])]
    ours_only = [k for k in ours if k not in caw and in_years(k[0]) and k[1] in ("Raw", "SmackDown")]

    def votes(day, typ):
        return (day in sdh_dates.get(typ, set())) + (day in sheet.get(typ, set()))

    date_fixes, used = [], set()
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def our_vote(ev, day):
        """Our record counts as one source for its own date, unless its own
        title names another weekday ("Tuesday Night SmackDown" filed on a
        Friday contradicts itself)."""
        named = [w for w in weekdays if w in (ev.get("title") or "")]
        return 0 if named and weekdays[D(day).weekday()] not in named else 1

    for d, t in ours_only:
        for cd, ct in caw_only:
            if ct != t or (cd, ct) in used or abs((D(cd) - D(d)).days) > NEAR_DAYS:
                continue
            his = 1 + votes(cd, t)                        # Cawthon + the others
            mine = our_vote(ours[(d, t)], d) + votes(d, t)
            # A source listing both dates means two shows: nothing moves.
            both = any(cd in s and d in s for s in (sdh_dates.get(t, set()), sheet.get(t, set())))
            if his > mine and not both:
                date_fixes.append({"event_id": ours[(d, t)]["id"], "show_type": t, "from": d, "to": cd,
                                   "votes": [his, mine]})
                used.add((cd, ct))
                break
    weekly, ppv, skipped, week_shifts = [], [], [], []
    for cd, ct in sorted(caw_only):
        if (cd, ct) in used:
            continue
        if ct == "PPV":
            if cd in PPV_ARTICLES:
                ppv.append({"air_date": cd, "article": PPV_ARTICLES[cd]})
            continue
        if votes(cd, ct) == 0:
            skipped.append({"air_date": cd, "show_type": ct, "why": "only Cawthon lists it"})
            continue
        sdh_matches = sdh.get((cd, ct))
        lines = [p for p in map(parse_match_line, caw[(cd, ct)]["lines"]) if p]
        if not sdh_matches:
            skipped.append({"air_date": cd, "show_type": ct, "why": "no SmackDown Hotel card to build from"})
            continue
        near = [ev for (od, ot), ev in ours.items() if ot == ct and abs((D(od) - D(cd)).days) <= NEAR_DAYS]
        twin = next((ev for ev in near if matchup_fit(ev["matches"], lines) >= 0.5), None)
        if twin is not None:
            # The same card is already ours on another date. If Cawthon's card
            # for OUR date is a different show, our event holds the next
            # week's card (a double taping filed under the taping date) and
            # the real show for our date is missing: a week shift. Otherwise
            # it is a date question (the 2012 Tuesday specials) for a person.
            od = twin["air_date"]
            mine = [m for m in twin["matches"] if m.get("source") != ADDED_BY_0006]
            own = [p for p in map(parse_match_line, caw.get((od, ct), {}).get("lines", [])) if p]
            if own and matchup_fit(mine, own) < 0.5:
                vacated = sdh.get((od, ct))
                fit = people_fit(vacated, own) if vacated else 0.0
                ep_old, ep_new = caw[(od, ct)], caw[(cd, ct)]
                week_shifts.append({
                    "event_id": twin["id"], "show_type": ct, "from": od, "to": cd,
                    "to_tape_date": ep_new["tape_date"], "to_place": ep_new["city"], "to_venue": ep_new["venue"],
                    "number": sdh_numbers.get((cd, ct)),
                    "vacated": {"air_date": od, "number": sdh_numbers.get((od, ct)),
                                "tape_date": ep_old["tape_date"], "place": ep_old["city"],
                                "venue": ep_old["venue"], "fit": round(fit, 2),
                                "add": bool(vacated) and fit >= 0.8,
                                "cawthon_lines": ep_old["lines"]}})
                used.add((cd, ct))
                continue
            skipped.append({"air_date": cd, "show_type": ct,
                            "why": f"same card as our {od}: date question"})
            continue
        fit = people_fit(sdh_matches, lines)
        if fit < 0.6:
            skipped.append({"air_date": cd, "show_type": ct, "why": f"cards disagree (fit {fit:.2f})"})
            continue
        ep = caw[(cd, ct)]
        weekly.append({"air_date": cd, "show_type": ct, "tape_date": ep["tape_date"],
                       "place": ep["city"], "venue": ep["venue"], "fit": round(fit, 2)})
    return date_fixes, weekly, ppv, skipped, week_shifts


def fetch_ppvs(ppv):
    from src.wikipedia_ppv import fetch_wikitext, parse_event
    WIKI_CACHE.mkdir(exist_ok=True)
    for p in ppv:
        f = WIKI_CACHE / (p["article"].replace(" ", "_").replace("/", "-") + ".wiki")
        if not f.exists():
            f.write_text(fetch_wikitext(p["article"]), encoding="utf-8")
        p["parsed"] = parse_event(f.read_text(encoding="utf-8"))
    return ppv


def main():
    from lineup_check import load_sdh
    from src.build_update import load_existing
    from src.ship_guard import atomic_write_text
    sheet_path = Path(sys.argv[sys.argv.index("--sheet") + 1]).expanduser()
    events = load_existing()["events"]
    sdh = load_sdh()
    date_fixes, weekly, ppv, skipped, week_shifts = plan(events, sdh, sheet_dates(sheet_path),
                                                          sdh_episode_numbers())
    for w in weekly:
        w["sdh_matches"] = sdh[(w["air_date"], w["show_type"])]
        w["number"] = sdh_episode_numbers().get((w["air_date"], w["show_type"]))
        w["cawthon_lines"] = cawthon_shows()[(w["air_date"], w["show_type"])]["lines"]
    for w in week_shifts:
        if w["vacated"]["add"]:
            w["vacated"]["sdh_matches"] = sdh[(w["from"], w["show_type"])]
    ppv = fetch_ppvs(ppv)
    OUT.mkdir(exist_ok=True)
    atomic_write_text(OUT / "missing-shows.json", json.dumps(
        {"date_fixes": date_fixes, "week_shifts": week_shifts, "weekly": weekly, "ppv": ppv,
         "skipped": skipped}, indent=1, default=str))
    print(f"date fixes {len(date_fixes)}, week shifts {len(week_shifts)}, weekly adds {len(weekly)}, "
          f"ppv adds {len(ppv)}, skipped {len(skipped)}")
    for x in week_shifts:
        v = x["vacated"]
        print(f"  shift {x['event_id']} {x['show_type']} {x['from']} -> {x['to']} (#{x['number']}); "
              f"recover {v['air_date']} #{v['number']} fit {v['fit']} add={v['add']}")
    for x in date_fixes:
        print("  move", x)
    for x in weekly:
        print("  add", x["air_date"], x["show_type"], x["place"], x["venue"], "fit", x["fit"], len(x["sdh_matches"]), "matches")
    for x in ppv:
        print("  add PPV", x["air_date"], x["article"], [len(t["matches"]) for t in x["parsed"]["tables"]], "matches")
    for x in skipped:
        print("  skip", x)


if __name__ == "__main__":
    main()
