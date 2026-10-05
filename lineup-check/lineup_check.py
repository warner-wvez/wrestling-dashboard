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
YEARS = range(2001, 2014)
AUTO_CLASSES = ("not_aired", "aired_heat", "add_wrestler")
REVIEW_FIELDS = ("class", "vote", "air_date", "show_type", "title", "event_id", "match_id",
                 "match_order", "name", "detail", "ours", "cawthon")


def _org(year):
    return "wwf" if year == 2001 else "wwe"


def _unreadable(lines):
    return sum(1 for line in lines if looks_like_match(line) and not parse_match_line(line))


def _parsed(lines):
    return [p for p in map(parse_match_line, lines) if p]


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
            for ep in parse_show_page((CACHE / f"{slug}.html").read_text(encoding="utf-8")):
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
    id and check its stored text before touching it."""
    out = {k: [] for k in AUTO_CLASSES}
    for r in rows:
        if r["class"] in AUTO_CLASSES:
            item = {"event_id": r["event_id"], "match_id": r["match_id"], "ours": r["ours"]}
            if r["class"] == "add_wrestler":
                item.update(team_number=r["team_number"], name=r["name"])
            out[r["class"]].append(item)
    for k in out:
        out[k].sort(key=lambda i: (i["event_id"], i["match_id"], i.get("name", "")))
    return out


def render(rows, shows, fixes):
    counts = collections.Counter(r["class"] for r in rows)
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
    L += ["", "## For review", "", "| Kind | Count | SmackDown Hotel agrees with ours | with Cawthon | split |",
          "|---|---|---|---|---|"]
    keep = {"keep", "aired"}
    for cls, n in counts.most_common():
        if cls in AUTO_CLASSES:
            continue
        rs = [r for r in rows if r["class"] == cls]
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


def review_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(sorted((r for r in rows if r["class"] not in AUTO_CLASSES),
                       key=lambda r: (r["class"], r["air_date"])))
    return buf.getvalue()


def main():
    from src.build_update import load_existing
    from src.ship_guard import atomic_write_text
    rows, shows = run(load_existing())
    fixes = auto_fixes(rows)
    OUT.mkdir(exist_ok=True)
    atomic_write_text(OUT / "auto-fixes.json", json.dumps(fixes, indent=1))
    atomic_write_text(OUT / "review.csv", review_csv(rows))
    atomic_write_text(OUT / "LINEUP-CHECK.md", render(rows, shows, fixes))
    print(f"{shows} shows compared; auto: " +
          ", ".join(f"{k}={len(v)}" for k, v in fixes.items()) +
          f"; review rows: {sum(1 for r in rows if r['class'] not in AUTO_CLASSES)}")


if __name__ == "__main__":
    main()
