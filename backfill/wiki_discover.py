#!/usr/bin/env python3
"""Every WWF pay-per-view and Saturday Night's Main Event of 1985 to 2000 from Wikipedia.

PPVs come from the "List of WWE pay-per-view and livestreaming supercards"
page, whose Past events section has one table per year ("====1985===="), each
row "|March 31" then "|[[WrestleMania I|WrestleMania]]". The existing
discover_ppv_titles reads a (YYYY) suffix off the link, which the early titles
lack (WrestleMania I, In Your House 1), so this walks the year sections instead.
A row whose first cell is not a date (the extra venue rows of a multi-arena
WrestleMania 2) is not an event.

SNME and The Main Event each live in ONE article ("Saturday Night's Main
Event", "WWF The Main Event"; the per-episode titles redirect there). Each
episode is a bold lead sentence, "'''Saturday Night's Main Event III''' took
place on October 31, 1985, from [[Hershey, Pennsylvania]], at the
[[Hersheypark Arena]], and aired on November 2, 1985.", followed by its
results table. special_episodes pairs every table with the lead ahead of it.
The SNME article also carries an Events table (taping, aired, city, venue per
episode), which wins over the sentence when both exist. Friday Night's Main
Event (1997, two shows) has no article and stays on its other sources.

Writes backfill/out/wiki_cards.json: [{title, show_type, list_date, events}]
with events in bundle shape, ids left at None for apply.py.

    uv run --with requests --with beautifulsoup4 python backfill/wiki_discover.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.wikipedia_ppv import (MONTHS, WIKILINK_RE, fetch_wikitext, find_blocks,  # noqa: E402
                               parse_event, parse_table, strip_refs, template_params)
from src.build_update import PPV_LIST_PAGE, map_match, map_wikipedia  # noqa: E402
from backfill.common import CACHE, OUT, YEARS, fresh_event, record_status, write_json  # noqa: E402

WIKI_CACHE = CACHE / "wiki"
_SECTION_RE = re.compile(r"====\s*(\d{4})\s*====")
_DATE_RE = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2})")
_LONG_DATE_RE = re.compile(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})")

SNME_ARTICLES = [("Saturday Night's Main Event", r"Saturday Night's Main Event [IVXL]+"),
                 ("WWF The Main Event", r"The Main Event(?: [IVX]+)?")]


def _iso_long(s: str) -> str | None:
    m = _LONG_DATE_RE.search(s or "")
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"


def ppv_titles(list_wikitext: str, years=YEARS) -> list[tuple[str, str]]:
    out, seen = [], set()
    sections = list(_SECTION_RE.finditer(list_wikitext))
    for i, s in enumerate(sections):
        year = int(s.group(1))
        if year not in years:
            continue
        end = sections[i + 1].start() if i + 1 < len(sections) else len(list_wikitext)
        for row in list_wikitext[s.end():end].split("\n|-")[1:]:
            cells = [c.strip() for c in re.split(r"\n\|", "\n" + row.strip())[1:]]
            if len(cells) < 2:
                continue
            dm = _DATE_RE.search(re.sub(r"\{\{nowrap\|([^}]*)\}\}", r"\1", cells[0]))
            lm = WIKILINK_RE.search(cells[1])
            if not dm or not lm or dm.group(1).lower() not in MONTHS:
                continue
            when = f"{year:04d}-{MONTHS[dm.group(1).lower()]:02d}-{int(dm.group(2)):02d}"
            title = lm.group(1).strip()
            if title not in seen:               # a two-night show lists twice, one article
                seen.add(title)
                out.append((when, title))
    return out


def _events_table(wikitext: str) -> dict:
    """The SNME article's Events table: {title: {tape, air, city, venue}}."""
    out = {}
    for m in re.finditer(r'!\s*scope="row"\s*\|\s*\[\[([^\]|]+)[^\]]*\]\]\s*\n\|([^\n]*)\n\|([^\n]*)\n\|([^\n]*)\n\|([^\n]*)',
                         wikitext):
        title = m.group(1).strip()
        links = lambda s: [t.split("|")[-1].strip() for t in re.findall(r"\[\[([^\]]+)\]\]", s)]  # noqa: E731
        out[title] = {"tape": _iso_long(m.group(2)), "air": _iso_long(m.group(3)),
                      "city": (links(m.group(4)) or [strip_refs(m.group(4)).strip()])[0],
                      "venue": (links(m.group(5)) or [strip_refs(m.group(5)).strip()])[0]}
    return out


def _lead_facts(lead: str) -> dict:
    """Taping, air date, city and venue from one bold lead sentence."""
    lead = strip_refs(lead)
    dates = [_iso_long(x) for x in re.findall(r"[A-Z][a-z]+ \d{1,2}, \d{4}", lead)]
    dates = [d for d in dates if d]
    tape = dates[0] if dates else None
    live = bool(re.search(r"aired live", lead))
    air_m = re.search(r"aired(?: live)?,? on (?:[A-Z][a-z]+ )?([A-Z][a-z]+ \d{1,2}, \d{4})", lead)
    air = _iso_long(air_m.group(1)) if air_m else (tape if live or len(dates) == 1 else None)
    city = venue = None
    for target, disp in WIKILINK_RE.findall(lead):
        shown = (disp or target).strip()
        if "," in shown and city is None:
            city = shown
        elif venue is None and shown.lower() not in ("nbc", "fox"):
            venue = shown
    return {"tape": tape, "air": air, "city": city, "venue": venue}


def special_episodes(wikitext: str, title_re: str, years=YEARS) -> list[dict]:
    """[{title, tape_date, air_date, city, venue, matches}] for every results
    table in an umbrella article, each paired with the bold lead ahead of it."""
    table = _events_table(wikitext)
    bold = re.compile(r"'''(" + title_re + r")'''")
    low = wikitext.lower()
    out, start = [], 0
    for block in find_blocks(wikitext, "Pro wrestling results table"):
        idx = low.find(block.lower(), start)
        start = idx + len(block)
        leads = [m for m in bold.finditer(wikitext, 0, idx)]
        if not leads:
            continue
        lead_m = leads[-1]
        title = lead_m.group(1)
        facts = _lead_facts(wikitext[lead_m.start():idx][:1200])
        row = table.get(title) or {}
        tape = row.get("tape") or facts["tape"]
        air = row.get("air") or facts["air"] or tape
        if not air or int(air[:4]) not in years:
            continue
        matches = [map_match(m, 0) for m in parse_table(block)["matches"]]
        for k, m in enumerate(matches, 1):
            m["match_order"] = k
        out.append({"title": title, "tape_date": tape if tape != air else None, "air_date": air,
                    "city": row.get("city") or facts["city"], "venue": row.get("venue") or facts["venue"],
                    "matches": matches})
    return out


def standalone_episode(wikitext: str, title: str, facts: dict | None = None) -> dict | None:
    """An episode with its own article (Saturday Night's Main Event I): the
    first results table, dated by the umbrella article's Events-table row when
    given (the article's own infobox holds the taping, May 10, 1985, while the
    show aired May 11)."""
    blocks = find_blocks(wikitext, "Pro wrestling results table")
    if not blocks:
        return None
    facts = facts or {}
    info = parse_event(wikitext)["info"]
    tape = facts.get("tape") or ((info.get("dates") or [None])[0])
    air = facts.get("air") or tape
    matches = [map_match(m, 0) for m in parse_table(blocks[0])["matches"]]
    for k, m in enumerate(matches, 1):
        m["match_order"] = k
    return {"title": title, "tape_date": tape if tape != air else None, "air_date": air,
            "city": facts.get("city") or info.get("city"), "venue": facts.get("venue") or info.get("venue"),
            "matches": matches}


_DTS_RE = re.compile(r"\{\{\s*(?:dts|start date)\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", re.I)


def _infobox_dates(wikitext: str) -> list[str]:
    """Every date on the infobox's date line, in order: "May 26, 1996<br />May
    28, 1996" (a two-night show), "{{dts|1995|12|17}}", "{{Start date|...}}".
    parse_event reads only the first plain date, which left nine 1995 to 2000
    articles undated and dated both Beware of Dog nights May 26."""
    boxes = find_blocks(wikitext, "Infobox")
    if not boxes:
        return []
    line = template_params(boxes[0]).get("date", "")
    out = []
    for m in re.finditer(r"\{\{\s*(?:dts|start date)[^}]*\}\}|[A-Z][a-z]+ \d{1,2}, \d{4}", strip_refs(line)):
        t = _DTS_RE.search(m.group(0))
        iso = f"{int(t.group(1)):04d}-{int(t.group(2)):02d}-{int(t.group(3)):02d}" if t else _iso_long(m.group(0))
        if iso and iso not in out:
            out.append(iso)
    return out


def _wikitext(title: str) -> str:
    WIKI_CACHE.mkdir(parents=True, exist_ok=True)
    p = WIKI_CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", title) + ".txt")
    if p.exists():
        return p.read_text(encoding="utf-8")
    wt = fetch_wikitext(title)
    time.sleep(1)
    p.write_text(wt, encoding="utf-8")
    return wt


def _split_city(city: str | None):
    if not city:
        return None, None
    parts = [p.strip() for p in city.split(",")]
    return parts[0], (parts[1] if len(parts) > 1 else None)


def main():
    list_wt = _wikitext(PPV_LIST_PAGE)
    cards, problems = [], []
    for when, title in ppv_titles(list_wt):
        try:
            parsed = parse_event(_wikitext(title))
        except Exception as ex:
            problems.append(f"{title}: {ex}")
            continue
        evs, _, _ = map_wikipedia(parsed, 0, 0)
        for ev in evs:
            ev["id"] = None
            ev["show_type"], ev["family"] = "PPV", "main"
            ev["promotion"] = ev["promotion_raw"] = "WWF"
        if not evs or not any(e["matches"] for e in evs):
            problems.append(f"{title}: no results table parsed")
            continue
        box = _infobox_dates(_wikitext(title))
        if len(box) == len(evs) and (any(e["air_date"] is None for e in evs) or len({e["air_date"] for e in evs}) < len(evs)):
            for ev, d in zip(evs, box):
                ev["air_date"] = d                        # one date per night, in order
        for ev in evs:
            if ev["air_date"] is None:
                ev["air_date"], ev["date_derivation"] = when, "wikipedia-list"
        dated = [e["air_date"] for e in evs]
        if when not in dated:
            problems.append(f"{title}: list says {when}, article says {dated}")
        cards.append({"title": title, "show_type": "PPV", "list_date": when, "events": evs})
        print(f"  {title}: {sum(len(e['matches']) for e in evs)} matches on {[e['air_date'] for e in evs]}")
    for article, title_re in SNME_ARTICLES:
        try:
            umbrella = _wikitext(article)
            eps = special_episodes(umbrella, title_re)
            if article == "Saturday Night's Main Event":
                # Episode I keeps its own article; the umbrella only links it.
                one = standalone_episode(_wikitext("Saturday Night's Main Event I"),
                                         "Saturday Night's Main Event I",
                                         _events_table(umbrella).get("Saturday Night's Main Event I"))
                if one:
                    eps.insert(0, one)
        except Exception as ex:
            problems.append(f"{article}: {ex}")
            continue
        if not eps:
            problems.append(f"{article}: no episodes in range")
            continue
        for ep in eps:
            city, state = _split_city(ep["city"])
            ev = fresh_event(air_date=ep["air_date"], tape_date=ep["tape_date"],
                             date_derivation="wikipedia-aired" if ep["tape_date"] else "live-broadcast",
                             show_type="SNME", family="main", title=ep["title"], venue=ep["venue"],
                             city=city, state_province=state, country="USA" if city else None,
                             primary_source="wikipedia", matches=ep["matches"])
            cards.append({"title": ep["title"], "show_type": "SNME", "list_date": None, "events": [ev]})
            print(f"  {ep['title']}: {len(ev['matches'])} matches on ['{ev['air_date']}']")
    write_json(OUT / "wiki_cards.json", cards)
    ok = not problems
    record_status("wiki", ok, f"{len(cards)} cards; problems: {len(problems)}")
    for p in problems:
        print("  PROBLEM " + p)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
