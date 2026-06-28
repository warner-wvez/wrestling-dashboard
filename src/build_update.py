#!/usr/bin/env python3
"""
Merge new SmackDown Hotel (weekly) + Wikipedia (PPV) events into the existing
inlined-JSON corpus and rebuild the bundle, reusing export_to_html's index
builders so wrestler stats + title reigns recompute consistently.

FULL RUN: fills 2020 through the present (2026). The weekly lane pulls every
Raw and SmackDown year from the SmackDown Hotel; the PPV lane pulls every WWE
PPV/PLE in range from Wikipedia, with article titles auto-discovered from the
"List of WWE pay-per-view and livestreaming supercards" page (plus the
WrestleMania editions mapped in by year, since they use an edition number, not
a year disambiguator). New events are de-duped against the existing corpus, the
wrestler + title-reign indexes are recomputed, and the rebuilt bundle is written
to BOTH index.html (the GitHub Pages source) and dist/wrestling-dashboard.html.

Run from repo root:
    uv run --with requests --with beautifulsoup4 src/build_update.py
"""
import collections
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.home() / "wrestling-dashboard"
sys.path.insert(0, str(ROOT))

from src.export_to_html import (  # noqa: E402
    build_wrestlers_index, build_title_reigns, build_wrestler_reigns_by_date, inject)
from src.wikipedia_ppv import WIKILINK_RE, fetch_wikitext, parse_event   # noqa: E402
from src.smackdownhotel import fetch_year, parse_year_html              # noqa: E402

START_YEAR, END_YEAR = 2020, 2026
PPV_LIST_PAGE = "List of WWE pay-per-view and livestreaming supercards"
# WrestleMania articles are titled by edition number, not a (year)
# disambiguator, so they can't be auto-discovered by year off the list page.
WRESTLEMANIA_BY_YEAR = {
    2020: "WrestleMania 36", 2021: "WrestleMania 37", 2022: "WrestleMania 38",
    2023: "WrestleMania 39", 2024: "WrestleMania XL", 2025: "WrestleMania 41",
    2026: "WrestleMania 42",
}


def load_existing():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="wrestling-data"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1).replace('<\\/', '</'))


def _outcome(was_winner, finish, nodecision):
    if nodecision or was_winner is None:
        return nodecision or None
    f = (finish or "").lower()
    kind = "win" if was_winner else "loss"
    if "dq" in f or "disqualif" in f:
        return "dq-" + kind
    if "countout" in f or "count-out" in f or "count out" in f:
        return "countout-" + kind
    return kind


def map_match(m, mid):
    raw = (m.get("raw_description") or "").lower()
    nodecision = None
    if all(t.get("was_winner") is None for t in m["teams"]):
        nodecision = "draw" if "draw" in raw else "no-contest"
    teams = [{
        "team_number": t["team_number"],
        # Existing corpus sets a team_name even for singles (e.g. "Chris Jericho").
        # Default it so the UI never renders a blank where a name should be.
        "team_name": t.get("team_name") or " & ".join(t.get("participants", [])) or None,
        "accompaniment": t.get("accompaniment"), "was_winner": t.get("was_winner"),
        "match_outcome": _outcome(t.get("was_winner"), m.get("finish"), nodecision),
        "was_champion_entering": bool(t.get("was_champion_entering")),
        "participants": t.get("participants", []),
    } for t in m["teams"]]
    return {
        "id": mid, "match_order": m["match_order"], "match_type": m.get("match_type"),
        "stipulation": m.get("stipulation"), "title_at_stake": m.get("title_at_stake"),
        "duration_seconds": m.get("duration_seconds"),
        "result_method": m.get("result_method") or "defeated",
        "match_guide_rating": None, "raw_description": m.get("raw_description", ""),
        "teams": teams,
    }


def blank_event(eid, **kw):
    base = dict(id=eid, air_date=None, tape_date=None, date_derivation="live-broadcast",
                show_type=None, episode_number=None, title=None, ppv_name=None, venue=None,
                city=None, state_province=None, country=None, attendance=None, tv_network=None,
                tv_rating=None, broadcast_type=None, commentary=None, promotion="WWE",
                promotion_raw="WWE", cagematch_nr=None, cagematch_url=None, fandom_slug=None,
                fandom_url=None, primary_source="other", verification_status="unverified",
                match_count=0, matches=[])
    base.update(kw)
    return base


def map_sdh(episodes, show, eid, mid):
    show_type = "Raw" if show == "raw" else "SmackDown"
    title = "Monday Night Raw" if show == "raw" else "Friday Night SmackDown"
    out = []
    for ep in episodes:
        matches = []
        for m in ep["matches"]:
            matches.append(map_match(m, mid)); mid += 1
        out.append(blank_event(eid, air_date=ep["date"], show_type=show_type, title=title,
                               episode_number=ep.get("episode_number"),
                               primary_source="thesmackdownhotel",
                               match_count=len(matches), matches=matches))
        eid += 1
    return out, eid, mid


def map_wikipedia(parsed, eid, mid):
    info = parsed["info"]
    out = []
    multi = len(parsed["tables"]) > 1
    for i, tbl in enumerate(parsed["tables"], 1):
        matches = []
        for m in tbl["matches"]:
            matches.append(map_match(m, mid)); mid += 1
        name = info.get("name")
        title = f"{name} - Night {i}" if multi else name
        out.append(blank_event(eid, air_date=tbl["date"], show_type="PPV", title=title,
                               ppv_name=name, venue=info.get("venue"), city=info.get("city"),
                               attendance=None, primary_source="wikipedia",
                               match_count=len(matches), matches=matches))
        eid += 1
    return out, eid, mid


def discover_ppv_titles(years):
    """Wikipedia article titles for every WWE PPV/PLE held in `years`.

    Scrapes the list page's "Past events" tables for event wikilinks whose
    trailing (YYYY) disambiguator is in range, then adds the WrestleMania
    editions. If the page can't be parsed, seeds a core per-year slate so the
    PPV lane is never empty."""
    yset = set(years)
    titles, seen = [], set()
    try:
        wt = fetch_wikitext(PPV_LIST_PAGE)
        ms = re.search(r"==\s*Past events\s*==", wt)
        me = re.search(r"==\s*Upcoming event schedule\s*==", wt)
        seg = wt[(ms.end() if ms else 0):(me.start() if me else len(wt))]
        for target, _disp in WIKILINK_RE.findall(seg):
            target = target.strip()
            ym = re.search(r"\((20\d{2})\)$", target)
            if "#" in target or not ym or int(ym.group(1)) not in yset:
                continue
            if target not in seen:
                seen.add(target); titles.append(target)
    except Exception as ex:
        print(f"  PPV discovery failed ({ex}); seeding core fallback slate", flush=True)
    for y in sorted(yset):                       # WrestleMania (numbered titles)
        wm = WRESTLEMANIA_BY_YEAR.get(y)
        if wm and wm not in seen:
            seen.add(wm); titles.append(wm)
    if sum("WrestleMania" not in t for t in titles) < 4 * len(yset):   # discovery broke
        for y in sorted(yset):
            for ev in ("Royal Rumble", "Elimination Chamber", "Money in the Bank",
                       "SummerSlam", "Survivor Series", "Backlash", "Crown Jewel"):
                t = f"{ev} ({y})"
                if t not in seen:
                    seen.add(t); titles.append(t)
    return titles


def main():
    data = load_existing()
    events = data["events"]
    old_events, old_matches = len(events), data["meta"]["match_count"]
    old_year_range = list(data["meta"]["year_range"])
    old_wrestlers, old_titles = len(data["wrestlers"]), len(data["title_reigns"])
    next_eid = max(int(k) for k in events) + 1
    next_mid = max((mm["id"] for e in events.values() for mm in e["matches"]), default=0) + 1

    # De-dupe on (air_date, show_type, title): one Raw/SmackDown per date, while
    # two different PPVs that share a date both survive. Seed from the existing
    # corpus (ends 2019-12-30) so a re-run can never double-add an event.
    def key(ev):
        return (ev.get("air_date"), ev.get("show_type"), ev.get("title"))
    seen = {key(e) for e in events.values()}

    def take(evs):
        kept = []
        for ev in evs:
            if key(ev) in seen:
                continue
            seen.add(key(ev)); kept.append(ev)
        return kept

    new, years = [], range(START_YEAR, END_YEAR + 1)

    print("=== Weekly lane: SmackDown Hotel (Raw + SmackDown) ===", flush=True)
    weekly_added = 0
    for show in ("raw", "smackdown"):
        for year in years:
            try:
                eps = parse_year_html(fetch_year(show, year))
            except Exception as ex:
                print(f"  {show}-{year}: FETCH FAILED ({ex})", flush=True)
                continue
            evs, next_eid, next_mid = map_sdh(eps, show, next_eid, next_mid)
            kept = take(evs)
            new += kept; weekly_added += len(kept)
            print(f"  {show}-{year}: {len(eps)} episodes -> {len(kept)} new", flush=True)

    print("\n=== PPV lane: Wikipedia (auto-discovered) ===", flush=True)
    titles = discover_ppv_titles(years)
    print(f"  discovered {len(titles)} candidate PPV/PLE article(s)", flush=True)
    ppv_added, ppv_ok, skipped = 0, 0, []
    for title in titles:
        try:
            parsed = parse_event(fetch_wikitext(title))
        except Exception as ex:
            skipped.append(f"{title} (error: {ex})")
            time.sleep(1)
            continue
        nmatch = sum(len(t["matches"]) for t in parsed["tables"])
        evs, ne, nm = map_wikipedia(parsed, next_eid, next_mid)
        evs = [ev for ev in evs
               if ev["air_date"] and START_YEAR <= int(ev["air_date"][:4]) <= END_YEAR]
        if nmatch == 0 or not evs:
            skipped.append(f"{title} ({nmatch} matches, {len(evs)} in-range night(s))")
            time.sleep(1)
            continue
        next_eid, next_mid = ne, nm                 # only consume IDs when kept
        kept = take(evs)
        new += kept; ppv_added += len(kept); ppv_ok += 1
        print(f"  {title}: {nmatch} matches -> {len(kept)} event(s)", flush=True)
        time.sleep(1)                               # MediaWiki etiquette: serial, >=1s

    # merge new events into the corpus + calendar index
    for ev in new:
        events[str(ev["id"])] = ev
        data["events_by_date"].setdefault(ev["air_date"], []).append(ev["id"])

    print("\nRecomputing wrestler index + title reigns...", flush=True)
    wrestlers, wrestlers_by_name = build_wrestlers_index(events)
    title_reigns = build_title_reigns(events)
    wrbd = build_wrestler_reigns_by_date(title_reigns)

    yrs = sorted({e["air_date"][:4] for e in events.values() if e["air_date"]})
    match_count = sum(e["match_count"] for e in events.values())
    bundle = {
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                 "event_count": len(events), "match_count": match_count,
                 "year_range": [int(yrs[0]), int(yrs[-1])]},
        "events_by_date": data["events_by_date"], "events": events,
        "wrestlers": wrestlers, "wrestlers_by_name": wrestlers_by_name,
        "title_reigns": title_reigns, "wrestler_reigns_by_date": wrbd,
    }
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    html_out = inject(bundle, template)
    dests = (ROOT / "index.html", ROOT / "dist" / "wrestling-dashboard.html")
    for dest in dests:
        dest.write_text(html_out, encoding="utf-8")

    print("\n=== VALIDATION (before -> after) ===")
    print(f"  events:    {old_events} -> {len(events)}  (+{len(new)}: "
          f"{weekly_added} weekly, {ppv_added} PPV from {ppv_ok} events)")
    print(f"  matches:   {old_matches} -> {match_count}  (+{match_count - old_matches})")
    print(f"  year_range: {old_year_range} -> {bundle['meta']['year_range']}")
    print(f"  wrestlers: {old_wrestlers} -> {len(wrestlers)}")
    print(f"  titles:    {old_titles} -> {len(title_reigns)}")
    for dest in dests:
        print(f"  wrote {dest.relative_to(ROOT)} ({dest.stat().st_size / 1024 / 1024:.2f} MB)")
    by_year_show = collections.Counter(
        ((ev["air_date"][:4] if ev["air_date"] else "??"), ev["show_type"]) for ev in new)
    print("\n  New events by year / show:")
    for yr, st in sorted(by_year_show):
        print(f"    {yr} {st:11s} {by_year_show[(yr, st)]}")
    if skipped:
        print(f"\n  Skipped {len(skipped)} PPV candidate(s) (no results table / out of range / error):")
        for s in skipped:
            print(f"    - {s}")


if __name__ == "__main__":
    main()
