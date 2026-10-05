#!/usr/bin/env python3
"""Title changes on house shows, and reigns WWE recognized without a match.

The Hardcore title's house-show swaps have their own builder (offcard_titles.py).
Every other belt changed hands at a house show now and then, and no card of ours
carries those nights, so the reign walk either dated the new reign from the
champion's next TV appearance (La Resistance's World tag reign of January 2005
started fifteen days late, on Raw) or missed it outright (Mickie James won the
Women's title in Paris on 2007-04-24 and lost it back to Melina the same night).
WWE also recognizes a few reigns no match started: Roxanne Perez replacing the
injured Liv Morgan beside Raquel Rodriguez, 2025-06-30.

A change goes in when Wikipedia's title history lists it (a house show, a live
event, or "WWE recognizes this as a separate reign") and a second record lists
the same night with the same new champion: Cawthon's results archive (2001-2013,
house shows included) or Royal Duncan and Gary Will's title histories
(wrestling-titles.com). Writes data/house-show-title-changes.json, which the reign
walk merges in by date. Anything only Wikipedia lists is printed, not applied.

    uv run --with requests --with beautifulsoup4 lineup-check/house_show_titles.py
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from cawthon_parse import parse_events  # noqa: E402
from title_audit import EXTRA  # noqa: E402
from wiki_titles import fetch, reigns  # noqa: E402

OUT = ROOT / "data" / "house-show-title-changes.json"
CACHE = HERE / "wiki-cache"
WT = "https://www.wrestling-titles.com/wwe/"
# Our title name -> Duncan and Will's page for that belt.
WT_PAGES = {
    "World Tag Team Championship (1971-2010)": "wwe-world-t.html",
    "WWE World Tag Team Championship": "wwe-t.html",
    "WWE Tag Team Championship": "wwe-sd-t.html",
    "WWE Women's Championship (1956-2010)": "wwf-wm.html",
    "WWE Cruiserweight Championship": "wwe-c.html",
    "WWE Divas Championship": "wwe-diva.html",
    "WWE Universal Championship": "wwe-univ.html",
    "WWE Intercontinental Title": "ic.html",
    "WWE United States Title": "wwf-us-h.html",
    "WWE Women's Tag Team Title": "wwf-wt.html",
}
HOUSE = re.compile(r"house show|live event|WWE Live|tour", re.I)
RECOGNIZED = re.compile(r"recognizes this as a separate reign", re.I)


def _plain(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def _surnames(names):
    return [_plain(n).split()[-1] for n in names if _plain(n)]


def wrestling_titles(page):
    """The page's text, one space between words (cached)."""
    f = CACHE / f"wt_{page}"
    if not f.exists():
        import requests
        r = requests.get(WT + page, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        f.write_bytes(r.content)
    from bs4 import BeautifulSoup
    text = BeautifulSoup(f.read_bytes().decode("latin-1"), "html.parser").get_text(" ")
    return _plain(text.replace("-", "dash"))


def wt_lists(text, day, names):
    """Does the page list a reign starting this day for one of these names?
    Each row reads "<champion> [n] <YYYY-MM-DD> <place>"."""
    for m in re.finditer(day.replace("-", "dash"), text):
        before = text[max(0, m.start() - 90):m.start()]
        if any(re.search(rf"\b{s}\b", before) for s in _surnames(names)):
            return True
    return False


def cawthon_lists(cawthon, day, names):
    """The house show line where one of these names wins the title, if any."""
    for e in cawthon.get(day, []):
        for line in e["lines"]:
            low = _plain(line)
            if re.search(r"to (?:win|regain) the (?:\w+ )?titles?\b", line, re.I) and \
                    any(re.search(rf"\b{s}\b", low.split(" to win")[0].split(" to regain")[0])
                        for s in _surnames(names)):
                return f"{e['head']}: {line[:200]}"
    return None


def main():
    from src.build_update import load_existing
    from src.title_lineages import LINEAGES
    data = load_existing()
    ours = data["title_reigns"]
    by_plain = {}
    for n in data["wrestlers_by_name"]:
        by_plain.setdefault(_plain(n), n)

    def corpus_name(n):
        return by_plain.get(_plain(n)) or by_plain.get(_plain("The " + n)) or n

    cawthon = {}
    for f in sorted((HERE / "cache").glob("w*-results-*.html")):
        for e in parse_events(f.read_text(encoding="utf-8", errors="ignore")):
            cawthon.setdefault(e["date"], []).append(e)

    sources = [(lin["name"], {"lineage": lin["key"]}, lin["wiki_list"]) for lin in LINEAGES]
    sources += [(name, {"title": name}, page) for name, page in EXTRA.items()
                if "Hardcore" not in name and "24/7" not in name]
    keep, single = [], []
    for name, where, page in sources:
        chain = ours.get(name) or []
        if not chain:
            continue
        lo, hi = chain[0]["start"], max(r["end"] or "9999-12-31" for r in chain)
        wt = wrestling_titles(WT_PAGES[name]) if name in WT_PAGES else ""
        rows = reigns(fetch(page)["text"])
        for i, r in enumerate(rows):
            if not r["champion"] or not (lo < r["date"] <= hi):
                continue
            if not (HOUSE.search(r["event"]) or RECOGNIZED.search(r["notes"])):
                continue
            names = [corpus_name(n) for n in (r["members"] if "Tag" in name else [r["champion"]])]
            order = sum(1 for x in rows[:i] if x["date"] == r["date"])
            seen = {"Wikipedia": f"{page} #{i + 1}: {r['event']}, {r['location']}"}
            line = cawthon_lists(cawthon, r["date"], names)
            if line:
                seen["Cawthon"] = line
            if wt and wt_lists(wt, r["date"], names):
                seen["Duncan & Will"] = WT + WT_PAGES[name]
            entry = {**where, "title_name": name, "date": r["date"], "order": order, "champions": names,
                     "place": r["location"], "why": r["notes"][:300], "sources": seen}
            (keep if len(seen) >= 2 else single).append(entry)
    keep.sort(key=lambda c: (c["date"], c["title_name"], c["order"]))
    OUT.write_text(json.dumps({
        "about": "Title changes at house shows, and reigns WWE recognized without a match, on belts other "
                 "than the Hardcore title. Each is listed by Wikipedia's title history and by Cawthon's "
                 "results or Duncan and Will's title histories. Built by lineup-check/house_show_titles.py.",
        "changes": keep}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(keep)} changes -> {OUT.relative_to(ROOT)}")
    for c in keep:
        print(f"  {c['date']} {c['title_name']}: {' & '.join(c['champions'])} ({', '.join(c['sources'])})")
    for c in single:
        print(f"only Wikipedia lists it, not applied: {c['date']} {c['title_name']}: {' & '.join(c['champions'])}")


if __name__ == "__main__":
    main()
