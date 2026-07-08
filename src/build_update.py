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

A ship gate guards the run: if any lane fetch fails, or a year comes back under
its episode/PPV floor (src/ship_guard.py), the run exits nonzero BEFORE writing
anything, and every artifact write is atomic (temp file + os.replace), so the
live bundle can never end up truncated or silently incomplete.

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

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.export_to_html import (  # noqa: E402
    build_wrestlers_index, build_title_reigns, build_wrestler_reigns_by_date,
    inject, write_sharded)
from src.ship_guard import atomic_write_text, corpus_floor_problems  # noqa: E402
from src.wikipedia_ppv import WIKILINK_RE, fetch_wikitext, parse_event   # noqa: E402
from src.smackdownhotel import fetch_year, parse_year_html              # noqa: E402
from src.roster_aliases import (                                        # noqa: E402
    SNAPSHOT_PATH, build_canon_map, load_roster_snapshot, save_roster_snapshot,
    scrape_roster)

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
    """Load the prior FULL bundle (events still carrying their matches) so the
    indexes can recompute. index.html is now the sharded core (no match arrays),
    so prefer the single-file dist build, which stays fully inline; fall back to
    index.html for the first sharded build (when it is still the full bundle)."""
    for src in (ROOT / "dist" / "wrestling-dashboard.html", ROOT / "index.html"):
        if not src.exists():
            continue
        m = re.search(r'<script id="wrestling-data"[^>]*>(.*?)</script>',
                      src.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        data = json.loads(m.group(1).replace('<\\/', '</'))
        evs = data.get("events") or {}
        if evs and any("matches" in e for e in evs.values()):   # a full bundle
            return data
    raise RuntimeError("no full inline bundle found in dist/ or index.html")


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


def event_key(ev):
    """An event's identity across rebuilds: one Raw/SmackDown per date, while
    two different PPVs sharing a date stay distinct."""
    return (ev.get("air_date"), ev.get("show_type"), ev.get("title"))


def restore_stable_ids(new, prior_by_key, base_events):
    """Give re-scraped events back the IDs they had in the previous build.

    The present-day range is rebuilt from scratch each run, and IDs used to be
    handed out in scrape-iteration order, so one added episode or a changed
    discovery order renumbered every following event. But users' watched
    history and saved matches live in localStorage keyed by event and match
    IDs, and deep links embed them, so IDs must survive rebuilds.

    Each new event that matches a prior event's identity keeps that event's ID,
    and its matches are paired to the prior matches by table position so saved
    matches stay pointed at the same bout. Genuinely new events (and extra
    matches a better parse found) get fresh IDs above every ID ever used, so
    nothing ever collides with a retired one.
    """
    used_eids = {int(k) for k in base_events}
    used_mids = {m["id"] for e in base_events.values() for m in e["matches"]}
    for ev in prior_by_key.values():
        used_eids.add(int(ev["id"]))
        used_mids.update(m["id"] for m in ev["matches"])
    next_eid = max(used_eids, default=0) + 1
    next_mid = max(used_mids, default=0) + 1

    kept_ids = 0
    for ev in new:
        prior = prior_by_key.get(event_key(ev))
        if prior:
            ev["id"] = prior["id"]
            prior_mids = [m["id"] for m in prior["matches"]]
            for i, m in enumerate(ev["matches"]):
                if i < len(prior_mids):
                    m["id"] = prior_mids[i]
                else:
                    m["id"] = next_mid
                    next_mid += 1
            kept_ids += 1
        else:
            ev["id"] = next_eid
            next_eid += 1
            for m in ev["matches"]:
                m["id"] = next_mid
                next_mid += 1
    print(f"  stable IDs: {kept_ids} events kept their prior IDs, "
          f"{len(new) - kept_ids} new events got fresh IDs", flush=True)
    return new


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

    # Rebuild the present-day range from scratch each run: drop everything from
    # START_YEAR on, keep the clean 2001-2019 Cagematch base, then re-ingest with
    # the current parsers. Without this, a re-run de-dupes the fresh (now cleaner)
    # parse against the prior, dirtier events and keeps the dirt. The pre-2020
    # base keeps its event IDs; the present-day range gets the same ID block back.
    pre = {k: e for k, e in events.items()
           if not ((e.get("air_date") or "")[:4].isdigit()
                   and int(e["air_date"][:4]) >= START_YEAR)}
    # Identity -> prior event for everything being rebuilt, so the re-scrape
    # can hand the same events their old IDs back (see restore_stable_ids).
    prior_present = {event_key(e): e for k, e in events.items() if k not in pre}
    dropped = len(events) - len(pre)
    data["events"] = events = pre
    data["events_by_date"] = {}
    for e in events.values():
        if e.get("air_date"):
            data["events_by_date"].setdefault(e["air_date"], []).append(int(e["id"]))
    print(f"Dropped {dropped} events >= {START_YEAR} (rebuilding present-day range clean); "
          f"{len(events)} pre-{START_YEAR} events kept.", flush=True)

    next_eid = max((int(k) for k in events), default=0) + 1
    next_mid = max((mm["id"] for e in events.values() for mm in e["matches"]), default=0) + 1

    # De-dupe on event_key: one Raw/SmackDown per date, while two different
    # PPVs that share a date both survive. Seed from the existing corpus
    # (ends 2019-12-30) so a re-run can never double-add an event.
    seen = {event_key(e) for e in events.values()}

    def take(evs):
        kept = []
        for ev in evs:
            if event_key(ev) in seen:
                continue
            seen.add(event_key(ev)); kept.append(ev)
        return kept

    new, years = [], range(START_YEAR, END_YEAR + 1)

    # A lane fetch that fails no longer ships a silently thinner corpus: every
    # failure is collected and the run halts at the ship gate below, before any
    # artifact is written.
    fetch_failures, weekly_counts = [], {}

    print("=== Weekly lane: SmackDown Hotel (Raw + SmackDown) ===", flush=True)
    weekly_added = 0
    for show in ("raw", "smackdown"):
        for year in years:
            try:
                eps = parse_year_html(fetch_year(show, year))
            except Exception as ex:
                print(f"  {show}-{year}: FETCH FAILED ({ex})", flush=True)
                fetch_failures.append(f"{show}-{year}: {ex}")
                continue
            weekly_counts[(show, year)] = len(eps)
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
            # An error is not a skip: a candidate that won't fetch or parse
            # needs an operator decision (same halt-don't-default stance as
            # the historical classifier), so it blocks the ship gate below.
            print(f"  {title}: FETCH/PARSE FAILED ({ex})", flush=True)
            fetch_failures.append(f"{title}: {ex}")
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

    # Ship gate: refuse to continue if any lane failed or came back thin.
    # Nothing has been written yet, so a blocked run leaves the live bundle,
    # shards, and dist build exactly as they were; fix the problem and re-run.
    ppv_year_counts = collections.Counter(
        int(ev["air_date"][:4]) for ev in new
        if ev["show_type"] == "PPV" and ev["air_date"])
    problems = ([f"fetch failed: {f}" for f in fetch_failures]
                + corpus_floor_problems(weekly_counts, ppv_year_counts,
                                        START_YEAR, END_YEAR))
    if problems:
        print(f"\n=== SHIP BLOCKED ({len(problems)} problem(s), nothing written) ===",
              flush=True)
        for p in problems:
            print(f"  - {p}", flush=True)
        sys.exit(1)

    # Restore stable IDs before anything is written: same identity -> same ID
    # as the previous build, so watched history, saved matches, and deep links
    # survive the rebuild.
    new = restore_stable_ids(new, prior_present, events)

    # merge new events into the corpus + calendar index
    for ev in new:
        events[str(ev["id"])] = ev
        data["events_by_date"].setdefault(ev["air_date"], []).append(ev["id"])

    print("\nBuilding roster alias map (SmackDown Hotel roster + spelling variants)...", flush=True)
    name_counts = collections.Counter(
        p for e in events.values() for m in e["matches"]
        for t in m["teams"] for p in t.get("participants", []) if p)
    # A failed roster scrape used to silently drop every roster-derived rename,
    # un-merging wrestlers and shipping halved all-time stats. Now: refresh the
    # committed snapshot on success, fall back to it on failure, and refuse to
    # ship if neither is available.
    try:
        roster_pairs = scrape_roster()
        save_roster_snapshot(roster_pairs)
    except Exception as exc:
        roster_pairs = load_roster_snapshot()
        if roster_pairs is None:
            print(f"\n=== SHIP BLOCKED (roster scrape failed: {exc}; no snapshot at "
                  f"{SNAPSHOT_PATH}, nothing written) ===", flush=True)
            sys.exit(1)
        print(f"  roster scrape failed ({exc}); using committed snapshot "
              f"({len(roster_pairs)} pairs)", flush=True)
    canon = build_canon_map(name_counts, roster_pairs=roster_pairs)
    aliased = sum(1 for n in name_counts if canon[n] != n)
    print(f"  {len(name_counts)} distinct names -> {len({canon[n] for n in name_counts})} "
          f"canonical wrestlers ({aliased} names merged)", flush=True)

    print("Recomputing wrestler index + title reigns...", flush=True)
    title_reigns = build_title_reigns(events)
    wrestlers, wrestlers_by_name = build_wrestlers_index(
        events, canon=lambda n: canon.get(n, n), title_reigns=title_reigns)
    wrbd = build_wrestler_reigns_by_date(title_reigns)

    yrs = sorted({e["air_date"][:4] for e in events.values() if e["air_date"]})
    match_count = sum(e.get("match_count", len(e.get("matches") or [])) for e in events.values())
    bundle = {
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(),
                 "event_count": len(events), "match_count": match_count,
                 "year_range": [int(yrs[0]), int(yrs[-1])]},
        "events_by_date": data["events_by_date"], "events": events,
        "wrestlers": wrestlers, "wrestlers_by_name": wrestlers_by_name,
        "title_reigns": title_reigns, "wrestler_reigns_by_date": wrbd,
    }
    template = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    # Live Pages build: lean inline core (event metadata + indexes + search) with
    # the heavy per-match detail in lazy-loaded shards/matches-<era>.json files.
    core, shards = write_sharded(bundle, ROOT, template)
    # Archival single-file build: everything inline, opens offline standalone.
    atomic_write_text(ROOT / "dist" / "wrestling-dashboard.html",
                      inject(bundle, template))

    idx, dist = ROOT / "index.html", ROOT / "dist" / "wrestling-dashboard.html"
    shard_bytes = sum((ROOT / "shards" / f"matches-{e}.json").stat().st_size for e in shards)
    print("\n=== VALIDATION (before -> after) ===")
    print(f"  events:    {old_events} -> {len(events)}  (+{len(new)}: "
          f"{weekly_added} weekly, {ppv_added} PPV from {ppv_ok} events)")
    print(f"  matches:   {old_matches} -> {match_count}  (+{match_count - old_matches})")
    print(f"  year_range: {old_year_range} -> {bundle['meta']['year_range']}")
    print(f"  wrestlers: {old_wrestlers} -> {len(wrestlers)}")
    print(f"  titles:    {old_titles} -> {len(title_reigns)}")
    print(f"  wrote index.html (inline core {idx.stat().st_size/1024/1024:.2f} MB) + "
          f"{len(shards)} era shards ({shard_bytes/1024/1024:.2f} MB) in shards/")
    print(f"  wrote dist/wrestling-dashboard.html (single-file {dist.stat().st_size/1024/1024:.2f} MB)")
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
