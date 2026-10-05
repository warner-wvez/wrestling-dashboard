#!/usr/bin/env python3
"""Title changes on shows we don't carry, and on the pre-shows of ones we do.

The NXT Cruiserweight title (2016 to 2022) changed hands on the Cruiserweight
Classic, 205 Live and NXT, none of which we carry, and four times on a
pay-per-view's pre-show, which our cards leave off (the same rule that greys
out a match that aired on Heat). The reign walk saw only the champion's next
defense on a card, so Tony Nese's reign started at Money in the Bank instead
of WrestleMania 35, and Lio Rush, Santos Escobar and Kushida never held it.
This builds data/offshow-title-changes.json, which the walk merges in.

A change goes in when two of three title histories list it:
  Wikipedia      the belt's list of champions (wiki-cache/)
  Duncan & Will  wrestling-titles.com (wiki-cache/wt_*.html)
  WWE.com        the official title history (wwe-cache/)
and no card of ours already carries it. Its date is WWE.com's where it gives
one, since WWE.com dates a taped change by the day it aired, as our cards do.
A change on a pay-per-view we carry goes in only when that show's Wikipedia
results table marks the match as pre-show; it then sorts ahead of the card's
first match. A change on a main card we lack is printed, not applied: the
match belongs on the card.

An interim champion (Escobar, crowned while Jordan Devlin could not travel in
2020) leaves the champion's reign running beside his, to the day the two
histories end it, so neither reign is cut short.

    uv run --with requests --with beautifulsoup4 lineup-check/offshow_titles.py
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from title_247 import _days, _get, align, plain  # noqa: E402
from wiki_titles import _unlink, fetch, reigns  # noqa: E402

OUT = ROOT / "data" / "offshow-title-changes.json"
WIKI = "https://en.wikipedia.org/wiki/"
DW = "https://www.wrestling-titles.com/wwe/"
WWE = "https://www.wwe.com/titlehistory/"
# Our title name -> its lineage key and the three histories' pages.
BELTS = {
    "WWE NXT Cruiserweight Championship": {
        "lineage": "lineage::cruiserweight-2016",
        "wiki": "List of WWE Cruiserweight Champions",
        "dw": "nxt/wwe-nxt-c.html",
        "wwe": "nxt-cruiserweight-championship",
    },
}
# One person under two names across the histories. WWE.com uses today's ring
# name or a short one (JD McDonagh was Jordan Devlin; "TJP", "Angel", "Murphy").
ALIASES = {"jdmcdonagh": "jordandevlin", "tjp": "tjperkins", "angel": "angelgarza",
           "murphy": "buddymurphy", "elhijodelfantasma": "santosescobar"}
INTERIM = re.compile(r"\binterim\b", re.I)


def key(name):
    s = plain(re.sub(r"^.*/", "", name or ""))    # "El Hijo del Fantasma/Santos Escobar"
    return ALIASES.get(s, s)


def same(a, b):
    return key(a) == key(b)


def wikipedia(page):
    rows = [r for r in reigns(fetch(page)["text"]) if r["champion"]]
    for i, r in enumerate(rows):
        r["n"] = i + 1
        for f in ("champion", "event", "notes"):
            r[f] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r[f])).strip()
    return rows


def duncan_will(page):
    from bs4 import BeautifulSoup
    html = _get(DW + page, HERE / "wiki-cache" / f"wt_{page.split('/')[-1]}")
    out = []
    for tr in BeautifulSoup(html, "html.parser").find_all("tr"):
        w, d = tr.find("td", class_="wrestlers"), tr.find("td", class_="date")
        m = d and re.match(r"(\d{4}-\d\d-\d\d)", d.get_text(strip=True))
        if w and m:
            out.append({"date": m.group(1), "champion": re.sub(r"\s*\[\d+\]", "", w.get_text(" ", strip=True))})
    return out


def wwe_com(slug):
    """WWE.com lists newest first: a name line, then "Mon D, YYYY - Mon D, YYYY"."""
    from bs4 import BeautifulSoup
    html = _get(WWE + slug, HERE / "wwe-cache" / f"titlehistory_{slug}.html")
    lines = [ln.strip() for ln in BeautifulSoup(html, "html.parser").get_text("\n").split("\n") if ln.strip()]
    span = re.compile(r"^([A-Z][a-z]{2} \d{1,2}, \d{4})(?: - ([A-Z][a-z]{2} \d{1,2}, \d{4}))?$")

    def iso(s):
        return datetime.strptime(s, "%b %d, %Y").date().isoformat() if s else None

    out = []
    for i in range(len(lines) - 1):
        m = span.match(lines[i + 1])
        if m and not span.match(lines[i]) and lines[i] not in ("day", "days") and not re.match(r"^[<\d|]", lines[i]):
            out.append({"date": iso(m.group(1)), "end": iso(m.group(2)), "champion": lines[i]})
    return sorted(out, key=lambda r: r["date"])


def confirm(name, cfg):
    """Each Wikipedia row, marked with the histories that list it. Duncan and
    Will date a change as Wikipedia does, give or take a day; WWE.com dates a
    taped one by its air date, up to two weeks later."""
    wiki, dw, wwe = wikipedia(cfg["wiki"]), duncan_will(cfg["dw"]), wwe_com(cfg["wwe"])
    for r in wiki:
        r["sources"] = {"Wikipedia": f"{WIKI}{cfg['wiki'].replace(' ', '_')} #{r['n']}"}
    for i, j in align(wiki, dw, lambda w, d: same(w["champion"], d["champion"])
                      and abs(_days(w["date"], d["date"])) <= 1):
        wiki[i]["sources"]["Duncan & Will"] = DW + cfg["dw"]
    for i, j in align(wiki, wwe, lambda w, e: same(w["champion"], e["champion"])
                      and 0 <= _days(w["date"], e["date"]) <= 14):
        wiki[i]["sources"]["WWE.com"] = WWE + cfg["wwe"]
        wiki[i]["wwe"] = wwe[j]
    return wiki


def preshow(event, champion):
    """Does this pay-per-view's Wikipedia results table put the champion's win
    on the pre-show? None when no page or no such match is found."""
    base = re.sub(r'^WWE\s+|\s+-\s+".*"$', "", event["ppv_name"] or event["title"]).strip()
    year = event["air_date"][:4]
    names = [base, re.sub(rf"\s+{year}$", f" ({year})", base), "WWE " + base]
    surname = plain(champion.split()[-1])
    for page in dict.fromkeys(names):
        try:
            text = fetch(page)["text"]
        except (KeyError, IndexError):
            continue
        for m in re.finditer(r"\|\s*match(\d+)\s*=([^\n]*)", text):
            winner = _unlink(m.group(2).split(" defeated ")[0])
            if " defeated " in m.group(2) and surname in plain(winner):
                note = re.search(rf"\|\s*note{m.group(1)}\s*=\s*([^\n|]*)", text)
                return bool(note and note.group(1).strip().lower().startswith("pre"))
    return None


def carried_reigns(events, name):
    """Our reigns that a card's own match starts, from the walk without this file."""
    from src.export_to_html import build_title_reigns, load_offcard_changes
    others = load_offcard_changes(offshow=Path("/nonexistent"))
    return [r for r in build_title_reigns(events, offcard=others).get(name, [])
            if not r["pre_corpus"] and r["start_event_id"]]


def main():
    from src.build_update import load_existing
    data = load_existing()
    events = data["events"]
    # A profile is found by the name itself, never through ALIASES: "Angel"
    # is a wrestler of his own, not Angel Garza.
    by_plain = {}
    for n in data["wrestlers_by_name"]:
        by_plain.setdefault(plain(n), n)
    ppv_by_date = {}
    for e in events.values():
        if e["show_type"] == "PPV":
            ppv_by_date.setdefault(e["air_date"], []).append(e)

    changes = []
    for name, cfg in BELTS.items():
        rows = confirm(name, cfg)
        ours = carried_reigns(events, name)
        for k, r in enumerate(rows):
            day = r["wwe"]["date"] if r.get("wwe") else r["date"]
            if len(r["sources"]) < 2:
                print(f"only {', '.join(r['sources'])} lists it, not applied: {r['date']} {name}: {r['champion']}")
                continue
            if any(same(o["champion_names"][0], r["champion"]) and o["start"] in (r["date"], day) for o in ours):
                continue
            now = re.sub(r"^.*/", "", r["champion"])     # the name he wrestled under later
            champion = by_plain.get(plain(now), now)
            entry = {"lineage": cfg["lineage"], "title_name": name, "date": day, "order": 0,
                     "champions": [champion], "event": r["event"], "place": r["location"],
                     "why": r["notes"][:300], "sources": r["sources"]}
            if day != r["date"]:
                entry["happened"] = r["date"]
            card = next((e for e in ppv_by_date.get(day, [])
                         if plain(r["event"]) and plain(r["event"]) in plain(e["ppv_name"] or e["title"])), None)
            if card:
                pre = preshow(card, champion)
                if pre is None:
                    print(f"on {card['title']}, no results-table row found, not applied: {day} {name}: {champion}")
                    continue
                if not pre:
                    print(f"on {card['title']}'s main card but not ours, not applied: {day} {name}: {champion}"
                          " (add the match to the card)")
                    continue
                entry.update(event_id=card["id"], order=0.5,
                             why=f"Won on the {r['event']} pre-show, which our card does not carry.")
            if INTERIM.search(r["notes"]) and k and rows[k - 1].get("wwe"):
                # The champion the interim title was made for kept his belt
                # until the two histories end his reign.
                held = rows[k - 1]["wwe"]["end"]
                spelled = datetime.fromisoformat(held).strftime("%B %-d, %Y") if held else None
                if held and held > day and spelled and spelled in rows[k - 1]["notes"]:
                    entry.update(interim=True, previous_holds_until=held)
                else:
                    print(f"interim reign without an agreed end for the champion, kept in line: {day} {champion}")
            changes.append(entry)

    changes.sort(key=lambda c: (c["date"], c["title_name"], c["order"]))
    OUT.write_text(json.dumps({
        "about": "Title changes on shows we don't carry (the Cruiserweight Classic, 205 Live, NXT) and on the "
                 "pre-shows of pay-per-views we do. Each is listed by at least two of the belt's Wikipedia list, "
                 "Duncan and Will's title history and WWE.com's. A pre-show change names its event and sorts "
                 "ahead of the card. Built by lineup-check/offshow_titles.py.",
        "changes": changes}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(changes)} changes -> {OUT.relative_to(ROOT)}")
    for c in changes:
        extra = (f", event {c['event_id']}" if "event_id" in c else "") + \
                (f", happened {c['happened']}" if "happened" in c else "") + \
                (f", previous reign runs to {c['previous_holds_until']}" if c.get("interim") else "")
        print(f"  {c['date']} {c['title_name']}: {c['champions'][0]} ({', '.join(c['sources'])}){extra}")


if __name__ == "__main__":
    main()
