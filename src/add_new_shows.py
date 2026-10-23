#!/usr/bin/env python3
"""
Add the shows that aired since the newest one in the bundle, and nothing else.

build_update.py rebuilds 2020 on from scratch. That was right while the
parsers were the only source for the present-day range, but since the July 2026
refresh the migrations in src/migrations/ have corrected that range inside the
bundle itself: missing PPVs added, title changes ruled, names fixed. A re-fetch
throws those corrections away. This script never touches an event already in
the bundle. It fetches what aired after the newest show, gives it fresh IDs,
and rebuilds the derived indexes the same way a migration does
(src/rebuild_indexes.rebuild), so every correction made so far carries through.

Each step is a gate; a blocked run writes nothing:
  1. Weekly lane (SmackDown Hotel) and PPV lane (Wikipedia) for the years the
     window touches. The window starts 14 days before the newest show, so a
     show whose results were not posted yet on one run is picked up on the
     next, and anything already in the bundle (same date and show, or same
     date and PPV name) is skipped. A card with no matches is left out and
     reported, never added empty.
  2. Ship gate: any fetch or parse failure, PPV discovery finding nothing, or
     fewer Raws or SmackDowns than their usual nights in the window (allowing
     two pre-emptions per show) stops the run.
  3. rebuild(): roster aliases, title reigns, wrestler index, shards, dist.
  4. Sidecars that read the rebuilt bundle: shards/belts.json (belt image per
     title-match wording) and shards/titles.json (the champions board, which
     takes a newer champion from our own reigns; see fill_titles.py).
  5. Service worker cache bump, so returning visitors load the new shards
     instead of their cached copies.
  6. A plain-words summary for the pull request (--summary FILE).

Run from repo root:
    uv run --with requests --with beautifulsoup4 src/add_new_shows.py [--dry-run] [--through YYYY-MM-DD] [--summary FILE]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.build_update import (  # noqa: E402
    _inline_bundle, discover_ppv_titles, load_existing, map_sdh, map_wikipedia,
    restore_stable_ids)
from src.ship_guard import atomic_write_text  # noqa: E402
from src.smackdownhotel import fetch_year, parse_year_html  # noqa: E402
from src.wikipedia_ppv import fetch_wikitext, parse_event   # noqa: E402

LOOKBACK_DAYS = 14
AIR_WEEKDAY = {"raw": 0, "smackdown": 4}       # Monday, Friday
SHOW_TYPE = {"raw": "Raw", "smackdown": "SmackDown"}
PREEMPTION_ALLOWANCE = 2
CACHE_RE = re.compile(r"const CACHE = 'wrestling-dashboard-v(\d+)';")
PPV_LIST_PAGE = "List of WWE pay-per-view and livestreaming supercards"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
AIRED_RE = re.compile(r"aired\s+(" + "|".join(MONTHS) + r")\s+(\d{1,2})")


def usual_airings(show: str, start: str, through: str) -> list[str]:
    """Dates in [start, through] that fall on the show's usual night."""
    d, end, out = date.fromisoformat(start), date.fromisoformat(through), []
    while d <= end:
        if d.weekday() == AIR_WEEKDAY[show]:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def ppv_name_key(name: str | None) -> str:
    """'WWE SummerSlam 2026 - Night 1' and 'SummerSlam' compare equal."""
    n = (name or "").lower()
    n = re.sub(r"\s+-\s+night\s+\d+$", "", n)
    n = re.sub(r"^(wwe|wwf)\s+", "", n)
    n = re.sub(r"\b(19|20)\d{2}\b", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def already_have(ev: dict, existing: list[dict]) -> bool:
    """One Raw or SmackDown per date; a PPV matches by date and name, so a
    second event on the same night (an NXT special beside a PLE) still counts
    as new."""
    same_day = [e for e in existing if e.get("air_date") == ev["air_date"]]
    if ev["show_type"] != "PPV":
        return any(e.get("show_type") == ev["show_type"] for e in same_day)
    key = ppv_name_key(ev.get("ppv_name") or ev.get("title"))
    return any(e.get("show_type") == "PPV"
               and ppv_name_key(e.get("ppv_name") or e.get("title")) == key for e in same_day)


def weekly_problems(found: dict, start: str, through: str) -> list[str]:
    """found maps show -> air dates kept or already on file inside the window."""
    problems = []
    for show in AIR_WEEKDAY:
        usual = usual_airings(show, start, through)
        got = len(found.get(show, []))
        if got < len(usual) - PREEMPTION_ALLOWANCE:
            problems.append(f"{show}: {got} episode(s) from {start} to {through}, "
                            f"{len(usual)} {SHOW_TYPE[show]} nights in that span")
    return problems


def bump_cache(sw_text: str) -> tuple[str, int]:
    m = CACHE_RE.search(sw_text)
    if not m:
        raise RuntimeError("sw.js: no `const CACHE = 'wrestling-dashboard-vN';` line to bump")
    n = int(m.group(1)) + 1
    return sw_text[:m.start()] + f"const CACHE = 'wrestling-dashboard-v{n}';" + sw_text[m.end():], n


def aired_dates(list_wikitext: str) -> dict[str, str]:
    """Article title -> broadcast date, for list-page rows that say the event
    aired after it was held ("September 26 (aired September 30)"). The calendar
    orders shows by when they aired, the way taped Raws and SmackDowns already
    carry a tape_date beside their air_date."""
    out = {}
    for row in list_wikitext.split("\n|-"):
        m = AIRED_RE.search(row)
        link = re.search(r"\[\[([^\]|#]+?\((\d{4})\))(?:\|[^\]]*)?\]\]", row)
        if m and link:
            month = MONTHS.index(m.group(1)) + 1
            out[link.group(1).strip()] = f"{link.group(2)}-{month:02d}-{int(m.group(2)):02d}"
    return out


def apply_aired_date(evs: list[dict], aired: str | None) -> list[dict]:
    """Move a single-night event held on one date and aired on another."""
    if aired and len(evs) == 1 and evs[0]["air_date"] and evs[0]["air_date"] != aired:
        held = evs[0]["air_date"]
        evs[0].update(air_date=aired, tape_date=held,
                      date_derivation=f"held {held}, aired {aired} (Wikipedia, {PPV_LIST_PAGE})")
    return evs


def show_label(ev: dict) -> str:
    if ev["show_type"] == "PPV":
        return ev.get("title") or ev.get("ppv_name") or "PPV"
    num = ev.get("episode_number")
    return f"{SHOW_TYPE.get(ev['show_type'].lower(), ev['show_type'])}{f' #{num}' if num else ''}"


def title_changes(before: dict, after: dict, start: str) -> list[str]:
    """Reigns that begin on or after `start` and were not in the prior bundle."""
    def sigs(reigns):
        return {(t, r["start"], tuple(r.get("champion_names") or [])) for t, rs in reigns.items() for r in rs}
    old = sigs(before.get("title_reigns") or {})
    out = []
    for t, rs in (after.get("title_reigns") or {}).items():
        for r in rs:
            s = (t, r["start"], tuple(r.get("champion_names") or []))
            if r["start"] >= start and s not in old:
                out.append((r["start"], f"{r['start']}: {' & '.join(r.get('champion_names') or ['vacant'])} won the {t}"))
    return [line for _, line in sorted(out)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    ap.add_argument("--through", default=date.today().isoformat(),
                    help="last air date to take (default: today)")
    ap.add_argument("--summary", type=Path, help="write a plain-words summary here")
    args = ap.parse_args(argv)

    data = load_existing()
    events = data["events"]
    existing = list(events.values())
    newest = max(e["air_date"] for e in existing if e.get("air_date"))
    start = (date.fromisoformat(newest) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    through = args.through
    years = range(int(start[:4]), int(through[:4]) + 1)
    print(f"Newest show on file: {newest}. Looking at {start} to {through}.", flush=True)

    failures, empty, new = [], [], []
    found = {show: [e["air_date"] for e in existing
                    if e.get("show_type") == SHOW_TYPE[show] and start <= (e.get("air_date") or "") <= through]
             for show in AIR_WEEKDAY}

    def consider(ev):
        if not (start <= (ev.get("air_date") or "") <= through):
            return
        if already_have(ev, existing + new):
            return
        if not ev["matches"]:
            empty.append(f"{ev['air_date']} {show_label(ev)}")
            return
        new.append(ev)

    print("=== Weekly lane: SmackDown Hotel ===", flush=True)
    for show in AIR_WEEKDAY:
        for year in years:
            try:
                eps = parse_year_html(fetch_year(show, year))
            except Exception as ex:
                failures.append(f"{show}-{year}: {ex}")
                print(f"  {show}-{year}: FETCH FAILED ({ex})", flush=True)
                continue
            evs, _, _ = map_sdh(eps, show, 0, 0)
            before = len(new)
            for ev in evs:
                consider(ev)
            found[show] += [ev["air_date"] for ev in new[before:]]
            print(f"  {show}-{year}: {len(eps)} episodes listed, {len(new) - before} new", flush=True)

    print("=== PPV lane: Wikipedia ===", flush=True)
    titles = discover_ppv_titles(years, fallback=False)
    if not any("WrestleMania" not in t for t in titles):
        failures.append("PPV discovery found no events on the list page")
    try:
        time.sleep(1)                       # discovery just fetched this page
        aired = aired_dates(fetch_wikitext(PPV_LIST_PAGE))
    except Exception as ex:
        aired = {}
        failures.append(f"{PPV_LIST_PAGE} (aired dates): {ex}")
    for title in titles:
        try:
            parsed = parse_event(fetch_wikitext(title))
        except Exception as ex:
            failures.append(f"{title}: {ex}")
            print(f"  {title}: FETCH/PARSE FAILED ({ex})", flush=True)
            time.sleep(1)
            continue
        evs, _, _ = map_wikipedia(parsed, 0, 0)
        evs = apply_aired_date(evs, aired.get(title))
        before = len(new)
        for ev in evs:
            consider(ev)
        if len(new) > before:
            print(f"  {title}: {len(new) - before} new night(s)", flush=True)
        time.sleep(1)                       # MediaWiki etiquette: serial, >=1s

    new.sort(key=lambda e: (e["air_date"], e["show_type"]))
    problems = [f"fetch failed: {f}" for f in failures] + weekly_problems(found, start, through)
    print(f"\n{len(new)} new show(s); {len(empty)} listed without results yet", flush=True)
    for ev in new:
        print(f"  + {ev['air_date']} {show_label(ev)} ({len(ev['matches'])} matches)", flush=True)
    for e in empty:
        print(f"  - {e}: no results posted, left for the next run", flush=True)
    if problems:
        print(f"\n=== SHIP BLOCKED ({len(problems)} problem(s), nothing written) ===", flush=True)
        for p in problems:
            print(f"  - {p}", flush=True)
        return 1
    if not new:
        print("Nothing new to add.", flush=True)
        return 0
    if args.dry_run:
        print("\n--dry-run: nothing written", flush=True)
        return 0

    before_core = _inline_bundle(ROOT / "index.html")
    new = restore_stable_ids(new, {}, events)
    for ev in new:
        events[str(ev["id"])] = ev
        data["events_by_date"].setdefault(ev["air_date"], []).append(ev["id"])

    from src.rebuild_indexes import rebuild
    rebuild(data)

    board_lines = []
    for script in ("fill_belts.py", "fill_titles.py"):
        res = subprocess.run([sys.executable, str(ROOT / "cagematch-pipeline" / script)],
                             cwd=ROOT, capture_output=True, text=True)
        print(res.stdout[-1500:], flush=True)
        if res.returncode:
            print(res.stderr, flush=True)
            raise RuntimeError(f"{script} failed; the bundle is rebuilt but the sidecars are not")
        if script == "fill_titles.py":
            board_lines = [ln.strip() for ln in res.stdout.splitlines()
                           if ln.strip().startswith(("newer champion", "holders:"))
                           or "keep the snapshot holder" in ln]

    sw = ROOT / "sw.js"
    text, version = bump_cache(sw.read_text(encoding="utf-8"))
    atomic_write_text(sw, text)
    print(f"sw.js cache -> v{version}", flush=True)

    after_core = _inline_bundle(ROOT / "index.html")
    changes = title_changes(before_core, after_core, newest)
    new_names = sorted(set(after_core["wrestlers_by_name"]) - set(before_core["wrestlers_by_name"]))
    counts = {k: sum(e["show_type"] == k for e in new) for k in ("Raw", "SmackDown", "PPV")}
    lines = [
        f"Adds {len(new)} shows that aired {new[0]['air_date']} to {new[-1]['air_date']}: "
        f"{counts['Raw']} Raw, {counts['SmackDown']} SmackDown, {counts['PPV']} PPV.",
        "",
        "Shows:",
        *[f"- {ev['air_date']} {show_label(ev)}, {len(ev['matches'])} matches" for ev in new],
        "",
        "Title changes on these shows:" if changes else "No title changes on these shows.",
        *[f"- {c}" for c in changes],
        "",
        f"Names new to the roster ({len(new_names)}): {', '.join(new_names) or 'none'}.",
    ]
    if board_lines:
        lines += ["", "Titles page:", *[f"- {b}" for b in board_lines]]
    if empty:
        lines += ["", "Listed without results yet (next run picks them up):", *[f"- {e}" for e in empty]]
    lines += ["", f"Service worker cache v{version}. Every show already on file is unchanged."]
    summary = "\n".join(lines) + "\n"
    print("\n" + summary, flush=True)
    if args.summary:
        args.summary.write_text(summary, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
