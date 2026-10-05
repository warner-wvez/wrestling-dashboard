#!/usr/bin/env python3
"""Compare every 2001 to 2013 Raw, SmackDown and PPV card with Graham Cawthon's
results archive, with SmackDown Hotel as a third vote on weekly shows.

Reads the shipped bundle (index.html + shards) and the page caches written by
cawthon_fetch.py; never the network. Writes three files to out/:

  auto-fixes.json   the changes both sources agree on, applied by
                    src/migrations/0004_apply_lineup_check.py
  review.csv        every other difference, with SmackDown Hotel's vote as a
                    suggestion (never applied automatically)
  LINEUP-CHECK.md   counts per kind and year, the auto fixes, the show gaps

Run from the repo root:
    uv run --with requests --with beautifulsoup4 lineup-check/lineup_check.py
"""
import collections
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import lineup_match  # noqa: E402
from cawthon_parse import (looks_like_match, parse_match_line,  # noqa: E402
                           parse_ppv_page, parse_show_page)
from lineup_match import compare_show, group_members  # noqa: E402

CACHE, SDH_CACHE, OUT = HERE / "cache", HERE / "sdh-cache", HERE / "out"
# Cawthon entries filed under a date that is not the show's air date, ruled by
# hand from the taping header and the card (2026-10-05): the same taping and
# the same matches as our show on the real date.
CAWTHON_DATES = {
    ("2002-12-28", "Raw"): "2002-12-30",        # Year in Review clip show, Raw #501
    ("2007-07-21", "SmackDown"): "2007-07-20",  # Laredo taping 07-17, SmackDown #413
    ("2010-06-03", "SmackDown"): "2010-06-04",  # Dallas taping 06-01, SmackDown #563
    # Same city and taping as our show, matchups fit 0.8 to 1.0
    ("2007-03-27", "Raw"): "2007-03-26",        # Raw #722, Rosemont (Chicago)
    ("2007-06-19", "Raw"): "2007-06-18",        # Raw #734, Richmond
    ("2008-08-31", "Raw"): "2008-09-01",        # Raw #797, taped Sunday in St. Louis
    ("2008-08-14", "SmackDown"): "2008-08-15",  # SmackDown #469, Norfolk
    ("2008-09-04", "SmackDown"): "2008-09-05",  # SmackDown #472, St. Louis
    ("2008-12-13", "SmackDown"): "2008-12-12",  # SmackDown #486, Bridgeport
    ("2010-09-23", "SmackDown"): "2010-09-24",  # SmackDown #579, Bloomington
    ("2012-09-04", "SmackDown"): "2012-09-07",  # SmackDown #681, taped Tuesday in Moline
    ("2012-11-04", "SmackDown"): "2012-11-02",  # SmackDown #689, Fayetteville
}
# Entries on his Raw and SmackDown pages that are not a show of that brand.
CAWTHON_NOT_SHOWS = {
    ("2007-12-28", "Raw"): "a replay of Michaels vs Cena from Raw 2007-04-23 in London",
    ("2011-01-27", "Raw"): "WWE Superstars (Stanford and Matthews calling it), filed with Raw",
}
YEARS = range(2001, 2014)
AUTO_CLASSES = ("not_aired", "aired_heat", "add_wrestler")
REVIEW_FIELDS = ("class", "vote", "air_date", "show_type", "title", "event_id", "match_id",
                 "match_order", "name", "detail", "ours", "cawthon", "sdh")


def _org(year):
    return "wwf" if year == 2001 else "wwe"


def _unreadable(lines):
    return sum(1 for line in lines if looks_like_match(line) and not parse_match_line(line))


def _parsed(lines):
    return [p for p in map(parse_match_line, lines) if p]


def settle_conflicts(eps):
    """A live show whose italic line gives another week's date (Raw 9/4/06 in
    Atlanta reads "9/11/06") collides with that week's own entry, and the
    night was compared twice. When a flagged episode's date is already taken
    by an unflagged one, its header date is the air date."""
    taken = {e["air_date"] for e in eps if not e["date_conflict"]}
    return [{**e, "air_date": e["header_date"]} if e["date_conflict"] and e["air_date"] in taken else e
            for e in eps]


def load_sdh():
    from src.smackdownhotel import parse_year_html
    out = {}
    for y in YEARS:
        for show, typ in (("raw", "Raw"), ("smackdown", "SmackDown")):
            f = SDH_CACHE / f"{show}-{y}.html"
            if f.exists():
                for e in parse_year_html(f.read_text(encoding="utf-8", errors="replace")):
                    out[(e["date"], typ)] = e["matches"]
    return out


def run(bundle):
    import src.fandom_scraper as fs
    from src.export_to_html import CLIP_SHOWS
    from src.roster_aliases import (CURATED, build_canon_map, bundle_derived_aliases,
                                    load_roster_snapshot)
    events = bundle["events"]
    names = collections.Counter(p for e in events.values() for m in e["matches"]
                                for t in m["teams"] for p in t.get("participants") or [] if p)
    lineup_match.CANON = dict(build_canon_map(
        names, roster_pairs=load_roster_snapshot(),
        curated={**bundle_derived_aliases(bundle), **CURATED}))
    groups = group_members(events, fs._STABLE_RE, fs._split_depth0)
    by_key = {(e["air_date"], e["show_type"]): e for e in events.values()}
    sdh = load_sdh()
    rows, seen = [], set()
    for y in YEARS:
        for typ, slug in (("Raw", f"{_org(y)}-raw-{y}"), ("SmackDown", f"{_org(y)}-smackdown-{y}")):
            for ep in settle_conflicts(parse_show_page((CACHE / f"{slug}.html").read_text(encoding="utf-8"))):
                if (ep["air_date"], typ) in CAWTHON_NOT_SHOWS:
                    continue
                ep = {**ep, "air_date": CAWTHON_DATES.get((ep["air_date"], typ), ep["air_date"])}
                ev = by_key.get((ep["air_date"], typ))
                if ev and ev["id"] in CLIP_SHOWS:
                    seen.add(ev["id"])
                    continue      # a replay special: its matches are clips, not a card
                if not ev:
                    rows.append({"class": "missing_show", "air_date": ep["air_date"],
                                 "show_type": typ, "detail": "Cawthon has it, we do not"})
                    continue
                seen.add(ev["id"])
                rows += compare_show(ev, _parsed(ep["lines"]), groups,
                                     unreadable=_unreadable(ep["lines"]),
                                     sdh_matches=sdh.get((ep["air_date"], typ)))
        page = (CACHE / f"{_org(y)}-results-{y}.html").read_text(encoding="utf-8")
        for d, v in parse_ppv_page(page).items():
            ev = by_key.get((d, "PPV"))
            if not ev:
                rows.append({"class": "missing_show", "air_date": d, "show_type": "PPV",
                             "title": v["title"], "detail": "Cawthon has it, we do not"})
                continue
            seen.add(ev["id"])
            rows += compare_show(ev, _parsed(v["ppv"]), groups, _parsed(v["heat"]),
                                 unreadable=_unreadable(v["ppv"]))
    for e in events.values():
        if e["id"] in CLIP_SHOWS:
            continue
        if str(YEARS.start) <= e["air_date"][:4] <= str(YEARS.stop - 1) and \
                e["show_type"] in ("Raw", "SmackDown", "PPV") and e["id"] not in seen:
            rows.append({"class": "missing_show", "air_date": e["air_date"], "show_type": e["show_type"],
                         "title": e["title"], "event_id": e["id"], "detail": "we have it, Cawthon does not"})
    return rows, len(seen)


def auto_fixes(rows):
    """The machine-applied set, keyed so the migration can find each match by
    id and check its stored text before touching it.

    Besides the both-sources classes, two SmackDown Hotel vote kinds are
    applied, each because every row it selected was checked by hand
    (2026-10-05): a result all three sources describe with the same people
    (31 of 31 right) and a missing match with the same people and winner on
    Cawthon's and SmackDown Hotel's cards (14 of 14 right)."""
    out = {k: [] for k in AUTO_CLASSES}
    out["fix_result"], out["add_match"] = [], []
    for r in rows:
        if r["class"] in AUTO_CLASSES:
            item = {"event_id": r["event_id"], "match_id": r["match_id"], "ours": r["ours"]}
            if r["class"] == "add_wrestler":
                item.update(team_number=r["team_number"], name=r["name"])
            out[r["class"]].append(item)
        elif r.get("vote") == "fix_result_same_people":
            out["fix_result"].append({"event_id": r["event_id"], "match_id": r["match_id"],
                                      "ours": r["ours"], "winners": sorted(r["his_winners"]),
                                      "outcome": r["outcome"], "cawthon": r["cawthon"]})
        elif r.get("vote") == "add_match_same_people":
            out["add_match"].append({"event_id": r["event_id"], "after_match_id": r["after_match_id"],
                                     "cawthon": r["cawthon"], "sdh": r["sdh"],
                                     "outcome": r["outcome"], "duration_seconds": r["duration_seconds"],
                                     "match": r["sdh_match"]})
    for k in out:
        out[k].sort(key=lambda i: (i["event_id"], i.get("match_id") or 0, i.get("name", ""),
                                   i.get("cawthon", "")))
    return out


def render(rows, shows, fixes, review):
    counts = collections.Counter(r["class"] for r in review)
    L = ["# Lineup check, 2001 to 2013", "",
         f"Our {shows} Raw, SmackDown and PPV cards compared with Graham Cawthon's "
         f"thehistoryofwwe.com, run {date.today().isoformat()}. SmackDown Hotel votes on weekly "
         "shows. Only changes both sources agree on are applied; every vote is a suggestion "
         "in review.csv.", "",
         "## Applied automatically", "",
         f"- {len(fixes['not_aired'])} matches marked not on the broadcast: our source labels "
         "them dark matches and Cawthon's televised list does not have them.",
         f"- {len(fixes['add_wrestler'])} wrestlers put back on a side: our own match text "
         "names them, Cawthon lists them, the stored lineup had lost them.",
         f"- {len(fixes['aired_heat'])} match marked as aired on Sunday Night Heat.", ""]
    L += ["### Wrestlers put back", "", "| Event | Match | Name | Our text |", "|---|---|---|---|"]
    for f in fixes["add_wrestler"]:
        L.append(f"| {f['event_id']} | {f['match_id']} | {f['name']} | {f['ours'][:90].replace('|', '/')} |")
    n_ruled = sum(1 for r in rows if r["class"] not in AUTO_CLASSES) - len(review)
    L += ["", "## For review", "",
          f"{len(review)} rows in review.csv; {n_ruled} more were ruled by hand (\"our card is "
          "right\") in rulings.csv and are left out.", "",
          "| Kind | Count | SmackDown Hotel agrees with ours | with Cawthon | split |",
          "|---|---|---|---|---|"]
    keep = {"keep", "aired"}
    for cls, n in counts.most_common():
        if cls in AUTO_CLASSES:
            continue
        rs = [r for r in review if r["class"] == cls]
        L.append(f"| {cls} | {n} | {sum(1 for r in rs if r.get('vote') in keep)} | "
                 f"{sum(1 for r in rs if r.get('vote') in lineup_match_auto())} | "
                 f"{sum(1 for r in rs if r.get('vote') in (None, 'split', '-'))} |")
    gaps = sorted((r["air_date"], r["show_type"], r.get("title") or "") for r in rows
                  if r["class"] == "missing_show" and r["detail"].startswith("Cawthon"))
    L += ["", "## Shows Cawthon has that the dashboard does not", "",
          "| Date | Type | Title |", "|---|---|---|"]
    L += [f"| {d} | {t} | {n} |" for d, t, n in gaps]
    return "\n".join(L) + "\n"


def lineup_match_auto():
    from lineup_vote import AUTO
    return AUTO


APPLIED_VOTES = ("fix_result_same_people", "add_match_same_people")
RULINGS = HERE / "rulings.csv"


def load_rulings(path=RULINGS):
    """Review rows a person ruled "our card is right": (class, event id,
    match id) -> the starts of the Cawthon lines ruled. Rows ruled a data
    change need no entry; once a migration applies them they stop differing."""
    out = collections.defaultdict(list)
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8")):
            out[(r["class"], r["event_id"], r["match_id"])].append(r["cawthon"])
    return out


def ruled(row, rulings):
    starts = rulings.get((row["class"], str(row.get("event_id") or ""), str(row.get("match_id") or "")))
    return bool(starts) and any((row.get("cawthon") or "").startswith(s) for s in starts)


def to_review(rows, rulings):
    return [r for r in rows if r["class"] not in AUTO_CLASSES
            and r.get("vote") not in APPLIED_VOTES and not ruled(r, rulings)]


def review_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(sorted(rows, key=lambda r: (r["class"], r["air_date"])))
    return buf.getvalue()


def main():
    from src.build_update import load_existing
    from src.ship_guard import atomic_write_text
    rows, shows = run(load_existing())
    fixes = auto_fixes(rows)
    rulings = load_rulings()
    review = to_review(rows, rulings)
    OUT.mkdir(exist_ok=True)
    atomic_write_text(OUT / "auto-fixes.json", json.dumps(fixes, indent=1))
    atomic_write_text(OUT / "review.csv", review_csv(review))
    atomic_write_text(OUT / "LINEUP-CHECK.md", render(rows, shows, fixes, review))
    hit = {(r["class"], str(r.get("event_id") or ""), str(r.get("match_id") or ""))
           for r in rows if ruled(r, rulings)}
    stale = sorted(k for k in rulings if k not in hit)
    print(f"{shows} shows compared; auto: " +
          ", ".join(f"{k}={len(v)}" for k, v in fixes.items()) +
          f"; review rows: {len(review)} ({sum(1 for r in rows if ruled(r, rulings))} ruled in rulings.csv)")
    if stale:
        # A ruling whose row no longer appears: the data or the check changed
        # under it. Drop it from rulings.csv once the change is understood.
        print(f"rulings that match no row: {stale}")


if __name__ == "__main__":
    main()
