#!/usr/bin/env python3
"""Title changes on shows we don't carry, and on the pre-shows of ones we do.

The NXT Cruiserweight title (2016 to 2022) changed hands on the Cruiserweight
Classic, 205 Live and NXT, none of which we carry, and four times on a
pay-per-view's pre-show, which our cards leave off (the same rule that greys
out a match that aired on Heat). The reign walk saw only the champion's next
defense on a card, so Tony Nese's reign started at Money in the Bank instead
of WrestleMania 35, and Lio Rush, Santos Escobar and Kushida never held it.
The main-roster belts had the same gaps: Nunzio's Cruiserweight title won on
Velocity, Kofi Kingston's Intercontinental title on Main Event, three ECW
titles on ECW's own show, The Miz's at the WrestleMania 29 pre-show, and the
belts Becky Lynch and Charlotte Flair swapped on SmackDown after the 2021
draft. This builds data/offshow-title-changes.json, which the walk merges in.

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
import unicodedata
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
WWE = "https://www.wwe.com/"
# Our title name -> its lineage key (for a belt in src/title_lineages.py) and
# the three histories' pages.
BELTS = {
    "WWE NXT Cruiserweight Championship": {
        "lineage": "lineage::cruiserweight-2016",
        "wiki": "List of WWE Cruiserweight Champions",
        "dw": "nxt/wwe-nxt-c.html",
        "wwe": "titlehistory/nxt-cruiserweight-championship",
    },
    "NXT Title": {
        "wiki": "List of NXT Champions",
        "dw": "nxt/wwe-nxt.html",
        "wwe": "titlehistory/nxt-championship",
    },
    "NXT Women's Title": {
        "wiki": "List of NXT Women's Champions",
        "dw": "nxt/wwe-nxt-wm.html",
        "wwe": "titlehistory/nxt-womens-championship",
    },
    "NXT North American Title": {
        "wiki": "List of NXT North American Champions",
        "dw": "nxt/wwe-nxt-na.html",
        "wwe": "titlehistory/nxt-north-american-championship",
    },
    "WWE NXT Tag Team Title": {
        "wiki": "List of NXT Tag Team Champions",
        "dw": "nxt/wwe-nxt-t.html",
        "wwe": "titlehistory/nxt-tag-team-championship",
    },
    "NXT Women's Tag Team Title": {
        "wiki": "List of NXT Women's Tag Team Champions",
        "dw": "nxt/wwe-nxt-wt.html",
        "wwe": "titlehistory/nxt-womens-tag-team-championship",
    },
    "NXT Women's North American Title": {
        "wiki": "List of NXT Women's North American Champions",
        "dw": "nxt/wwe-nxt-na-wm.html",
        "wwe": "classics/titlehistory/nxt-womens-north-american-championship",
    },
    # The NXT UK belts (2017 to 2022). Wikipedia keeps their histories on the
    # belts' own pages, not a "List of" page. NXT UK taped its shows up to
    # three months ahead in 2018 and 2019, so WWE.com's air date can sit that
    # far after the taping Wikipedia gives.
    "WWE United Kingdom Title": {
        "wiki": "NXT United Kingdom Championship", "dw": "nxt-uk/wwe-uk-h.html",
        "wwe": "classics/titlehistory/nxt-united-kingdom-championship", "taped_within": 100,
    },
    "WWE NXT UK Women's Title": {
        "wiki": "NXT UK Women's Championship", "dw": "nxt-uk/wwe-nxt-uk-wm.html",
        "wwe": "titlehistory/nxt-uk-womens-championship", "taped_within": 100,
    },
    "WWE NXT UK Tag Team Title": {
        "wiki": "NXT UK Tag Team Championship", "dw": "nxt-uk/wwe-nxt-uk-t.html",
        "wwe": "titlehistory/nxt-uk-tag-team-championship", "taped_within": 100,
    },
    # The main-roster belts. Their changes on shows we don't carry (Velocity,
    # Main Event, ECW's own show, a Saturday Night's Main Event) and on
    # pre-shows started late the same way. WWE.com keeps the 2016 brand names
    # in its addresses: the Raw Women's page is today's WWE Women's
    # Championship. Duncan and Will have no page for the 2002-13 World
    # Heavyweight or the ECW title, so there WWE.com is the second record.
    "WWE Championship": {"lineage": "lineage::wwe-championship", "wiki": "List of WWE Champions",
                         "dw": "wwe-h.html", "wwe": "titlehistory/wwe-championship"},
    "WWE Universal Championship": {"lineage": "lineage::universal", "wiki": "List of WWE Universal Champions",
                                   "dw": "wwe-univ.html", "wwe": "titlehistory/universal-championship"},
    "World Heavyweight Championship": {
        "lineage": "lineage::world-heavyweight-2002",
        "wiki": "List of World Heavyweight Champions (WWE, 2002–2013)",
        "wwe": "titlehistory/world-heavyweight-championship"},
    "WWE Women's Championship": {"lineage": "lineage::womens-2016", "wiki": "List of WWE Women's Champions",
                                 "dw": "wwe-raw-wm.html", "wwe": "titlehistory/raw-womens-championship"},
    "WWE Women's World Championship": {
        "lineage": "lineage::womens-world", "wiki": "List of Women's World Champions (WWE)",
        "dw": "wwe-sd-wm.html", "wwe": "titlehistory/smackdown-womens-championship"},
    "WWE Divas Championship": {"lineage": "lineage::divas", "wiki": "List of WWE Divas Champions",
                               "dw": "wwe-diva.html", "wwe": "titlehistory/divas-championship"},
    "World Tag Team Championship (1971-2010)": {
        "lineage": "lineage::world-tag-1971", "wiki": "List of World Tag Team Champions (WWE, 1971–2010)",
        "dw": "wwe-world-t.html", "wwe": "titlehistory/world-tag-team-championship"},
    "WWE World Tag Team Championship": {
        "lineage": "lineage::wwe-tag-2002", "wiki": "List of World Tag Team Champions (WWE)",
        "dw": "wwe-t.html", "wwe": "titlehistory/raw-tag-team-championship"},
    "WWE Tag Team Championship": {"lineage": "lineage::smackdown-tag", "wiki": "List of WWE Tag Team Champions",
                                  "dw": "wwe-sd-t.html", "wwe": "titlehistory/smackdown-tag-team-championship"},
    "WWE Cruiserweight Championship": {
        "lineage": "lineage::cruiserweight-1991", "wiki": "List of WWE Cruiserweight Champions (1996–2007)",
        "dw": "wwe-c.html", "wwe": "titlehistory/cruiserweight-championship"},
    "WWE Intercontinental Title": {"wiki": "List of WWE Intercontinental Champions",
                                   "dw": "ic.html", "wwe": "titlehistory/intercontinental-championship"},
    "WWE United States Title": {"wiki": "List of WWE United States Champions",
                                "dw": "wwf-us-h.html", "wwe": "titlehistory/united-states-championship"},
    "WWF European Title": {"wiki": "List of WWE European Champions",
                           "dw": "wwf-eu-h.html", "wwe": "titlehistory/european-championship"},
    "ECW World Heavyweight Title": {"wiki": "List of ECW World Heavyweight Champions",
                                    "wwe": "titlehistory/ecw-championship"},
    "WWE Women's Tag Team Title": {"wiki": "List of WWE Women's Tag Team Champions",
                                   "dw": "wwf-wt.html", "wwe": "classics/titlehistory/wwe-womens-tag-team-championship"},
}
# Our cards carry nearly every main-roster change already, so on those belts
# a change is skipped when a card of ours crowns the same champion within a
# week of it: a day or two between a history's date and our card (a time
# zone, a taping) is our card being right.
NXT_FAMILY = {"WWE NXT Cruiserweight Championship", "NXT Title", "NXT Women's Title", "NXT North American Title",
              "WWE NXT Tag Team Title", "NXT Women's Tag Team Title", "NXT Women's North American Title",
              "WWE United Kingdom Title", "WWE NXT UK Women's Title", "WWE NXT UK Tag Team Title"}
MAIN_ROSTER = set(BELTS) - NXT_FAMILY
SLACK = 7
# Wikipedia's note when WWE dates a reign from another day than the list
# does: "WWE recognizes Asuka's reign as beginning on May 11, 2020".
RECOGNIZED_START = re.compile(r"WWE recognizes [^.]*?reign as beginning on ([A-Z][a-z]+ \d{1,2}, \d{4})")
# One person under two names across the histories. WWE.com uses today's ring
# name or a short one (JD McDonagh was Jordan Devlin; "TJP", "Angel", "Murphy").
ALIASES = {"jdmcdonagh": "jordandevlin", "tjp": "tjperkins", "angel": "angelgarza",
           "murphy": "buddymurphy", "elhijodelfantasma": "santosescobar",
           "andradecienalmas": "andradealmas"}
INTERIM = re.compile(r"\binterim\b", re.I)
# A history's event for a weekly show, never one of our pay-per-view cards.
WEEKLY = {"nxt", "nxt20", "nxtlevelup", "nxtuk", "205live", "raw", "smackdown", "mainevent"}


def key(name):
    s = plain(re.sub(r"^.*/", "", name or ""))    # "El Hijo del Fantasma/Santos Escobar"
    return ALIASES.get(s, s)


def keys(r):
    """Every name a history gives a reign: the champion, and for a team its
    name and each member. Duncan and Will write "Wyatt Family: Erick Rowan &
    Luke Harper", WWE.com "The Wyatt Family" or "Adrian Neville & Corey Graves",
    Wikipedia the team name with its members apart."""
    out = set()
    for part in re.split(r":|&| and ", re.sub(r"\(.*?\)", "", r["champion"])):
        if key(part):
            out.add(key(part))
    out.add(key(r["champion"]))
    out |= {key(m) for m in r.get("members") or [] if key(m)}
    return out


def same(a, b):
    return bool(keys(a) & keys(b))


def event_key(s):
    """"NXT TakeOver: Brooklyn" and "WWE NXT TakeOver: Brooklyn" alike, which
    plain() cannot do: it stops at the colon."""
    s = unicodedata.normalize("NFKD", re.sub(r"<[^>]+>|\(.*?\)", " ", s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


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


def wwe_com(path):
    """WWE.com lists newest first: a name line, then "Mon D, YYYY - Mon D, YYYY"."""
    from bs4 import BeautifulSoup
    html = _get(WWE + path, HERE / "wwe-cache" / f"titlehistory_{path.split('/')[-1]}.html")
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
    taped one by its air date, up to five weeks later (NXT taped a month of
    shows at a time at Full Sail until 2019), or the belt's own "taped_within"
    days (NXT UK, three months)."""
    wiki, wwe = wikipedia(cfg["wiki"]), wwe_com(cfg["wwe"])
    dw = duncan_will(cfg["dw"]) if cfg.get("dw") else []
    for r in wiki:
        r["sources"] = {"Wikipedia": f"{WIKI}{cfg['wiki'].replace(' ', '_')} #{r['n']}"}
    for i, j in align(wiki, dw, lambda w, d: same(w, d) and abs(_days(w["date"], d["date"])) <= 1):
        wiki[i]["sources"]["Duncan & Will"] = DW + cfg["dw"]
    window = cfg.get("taped_within", 35)
    for i, j in align(wiki, wwe, lambda w, e: same(w, e) and 0 <= _days(w["date"], e["date"]) <= window):
        wiki[i]["sources"]["WWE.com"] = WWE + cfg["wwe"]
        wiki[i]["wwe"] = wwe[j]
    return wiki


def preshow(event, champion):
    """Does this pay-per-view's Wikipedia results table put the champion's win
    on the pre-show? None when no page or no such match is found."""
    base = re.sub(r'^WWE\s+|\s+-\s+".*"$', "", event["ppv_name"] or event["title"]).strip()
    year = event["air_date"][:4]
    names = [base, re.sub(rf"\s+{year}$", f" ({year})", base), f"{base} ({year})", "WWE " + base]
    surname = plain(champion.split()[-1])
    for page in dict.fromkeys(names):
        try:
            text = fetch(page)["text"]
        except (KeyError, IndexError):
            continue
        for m in re.finditer(r"\|\s*match(\d+)\s*=([^\n]*)", text):
            winner = _unlink(m.group(2).split(" defeated ")[0])
            # plain() drops brackets, and a team's members sit in them: "New
            # Age Outlaws (Billy Gunn and Road Dogg)".
            spelled = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", winner).lower())
            if " defeated " in m.group(2) and (surname in plain(winner) or surname in spelled):
                note = re.search(rf"\|\s*note{m.group(1)}\s*=\s*([^\n|]*)", text)
                return bool(note and note.group(1).strip().lower().startswith("pre"))
    return None


def won_on_card(card, r):
    """The match on our card the new champion won, when exactly one fits. The
    cards from Wikipedia's results tables (2020 on) write a vacant belt as
    "vacant / NXT Women's Championship" with no TITLE CHANGE marker, and one
    (Worlds Collide 2022) leaves the belt off, so the walk never crowns the
    winner there."""
    won = [m for m in card["matches"] for t in m["teams"]
           if t.get("was_winner") and same({"champion": " & ".join(p for p in t["participants"] if p)}, r)]
    if len(won) > 1:
        won = [m for m in won if m.get("title_at_stake")]
    return won[0] if len(won) == 1 else None


def walk_without_this_file(events):
    """Every belt's reigns from the walk without data/offshow-title-changes.json."""
    from src.export_to_html import build_title_reigns, load_offcard_changes
    others = load_offcard_changes(offshow=Path("/nonexistent"))
    return build_title_reigns(events, offcard=others)


def carried(reigns):
    """The reigns that a card's own match starts."""
    return [r for r in reigns if not r["pre_corpus"] and r["start_event_id"]]


def recognized_start(notes):
    m = RECOGNIZED_START.search(notes or "")
    return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat() if m else None


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

    # Nothing past our last show: the title pages stay where the site ends.
    corpus_end = max(e["air_date"] for e in events.values())
    changes = []
    walk = walk_without_this_file(events)
    # A main-roster belt pairs a history's champion with ours through the
    # dashboard's profiles: "The Hurricane" is our "Hurricane Helms", MNM our
    # "Mercury" and "Nitro".
    from title_audit import name_key
    profile = name_key(data["wrestlers_by_name"])

    def profiles(r):
        names = [r["champion"]] + list(r.get("members") or [])
        names += [p for n in names for p in re.split(r":|&| and ", re.sub(r"\(.*?\)", "", n))]
        return {profile(n.strip()) for n in names if n.strip()}
    cards_by_date = {}
    for e in events.values():
        cards_by_date.setdefault(e["air_date"], []).append(e)
    for name, cfg in BELTS.items():
        rows = confirm(name, cfg)
        reigns = walk.get(name, [])
        ours = carried(reigns)
        main_roster = name in MAIN_ROSTER
        for k, r in enumerate(rows):
            day = r["wwe"]["date"] if r.get("wwe") else r["date"]
            if main_roster:
                day = recognized_start(r["notes"]) or day
                # Ours from the reign in force when our history of the belt
                # starts; anything before it is outside the corpus.
                if not reigns or day <= reigns[0]["start"]:
                    continue
            if day > corpus_end:
                continue
            if len(r["sources"]) < 2:
                print(f"only {', '.join(r['sources'])} lists it, not applied: {r['date']} {name}: {r['champion']}")
                continue

            def held_by(o):
                if same({"champion": " & ".join(o["champion_names"]), "members": o["champion_names"]}, r):
                    return True
                return main_roster and bool({profile(n) for n in o["champion_names"]} & profiles(r))
            if any(o["start"] in (r["date"], day) and held_by(o) for o in (reigns if main_roster else ours)):
                continue
            if main_roster and any(held_by(o) and min(abs(_days(o["start"], d)) for d in (r["date"], day)) <= SLACK
                                   for o in ours):
                continue
            # A team by its members; a wrestler by the name he wrestled under
            # later ("El Hijo del Fantasma/Santos Escobar").
            names = r["members"] if "Tag" in name and len(r["members"]) > 1 else [r["champion"]]
            champions = [by_plain.get(plain(re.sub(r"^.*/", "", n)), re.sub(r"^.*/", "", n)) for n in names]
            if main_roster:
                # The reign we have, started late: the change takes its names,
                # spelled as our cards spell them and without a partner the
                # team added later (Naomi joined Belair and Cargill in 2025).
                late = next((o for o in reigns if held_by(o) and 0 < _days(day, o["start"]) <= 120), None)
                if late:
                    champions = list(late["champion_names"])
            champion = champions[0]
            where = {"lineage": cfg["lineage"]} if "lineage" in cfg else {"title": name}
            entry = {**where, "title_name": name, "date": day, "order": 0,
                     "champions": champions, "event": r["event"], "place": r["location"],
                     "why": r["notes"][:300], "sources": r["sources"]}
            if day != r["date"]:
                entry["happened"] = r["date"]
            ek = event_key(r["event"])
            card = next((e for e in ppv_by_date.get(day, [])
                         if ek and ek not in WEEKLY and ek in event_key(e["ppv_name"] or e["title"])), None)
            weekly = None
            if main_roster and card is None and ek in WEEKLY:
                # A Raw or SmackDown we carry: the change goes on that show.
                weekly = next((e for e in cards_by_date.get(day, []) if ek in event_key(e["title"])), None)
            won = (card or weekly) and won_on_card(card or weekly, r)
            if won and main_roster:
                print(f"won on our card without the walk seeing it, rule the match instead: {day} {name}: "
                      f"{champion}, match {won['id']}")
                continue
            if weekly and not won:
                entry.update(event_id=weekly["id"], order=0,
                             why=(r["notes"][:300] or f"Changed hands on {weekly['title']} outside a match."))
            elif won:
                entry.update(event_id=card["id"], order=won["match_order"] + 0.5,
                             why=f"Won in match {won['match_order']} of {card['title']}, which our card does not "
                                 "mark as a title change.")
            elif card:
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
        "about": "Title changes on shows we don't carry (the Cruiserweight Classic, 205 Live, NXT, Velocity, "
                 "Main Event, ECW) and on the pre-shows of pay-per-views we do, and changes outside a match on a "
                 "Raw or SmackDown we carry. Each is listed by at least two of the belt's Wikipedia list, "
                 "Duncan and Will's title history and WWE.com's. A pre-show change names its event and sorts "
                 "ahead of the card. Built by lineup-check/offshow_titles.py.",
        "changes": changes}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(changes)} changes -> {OUT.relative_to(ROOT)}")
    for c in changes:
        extra = (f", event {c['event_id']}" if "event_id" in c else "") + \
                (f", happened {c['happened']}" if "happened" in c else "") + \
                (f", previous reign runs to {c['previous_holds_until']}" if c.get("interim") else "")
        print(f"  {c['date']} {c['title_name']}: {' & '.join(c['champions'])} ({', '.join(c['sources'])}){extra}")


if __name__ == "__main__":
    main()
