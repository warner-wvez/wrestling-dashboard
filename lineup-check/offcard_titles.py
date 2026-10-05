#!/usr/bin/env python3
"""Title changes no card of ours carries: house shows, 2001-2002 Hardcore title.

Under the 24/7 rule the Hardcore title changed hands about 150 times at house
shows in 2001 and 2002. No card holds them, so the reign walk never saw them
and the title history ran one reign straight across a week of swaps. This
builds data/offcard-title-changes.json, which the walk merges in by date.

A change goes in only when two of three independent records list the same
night with the same sequence of winners:
  Cawthon       results year pages, every event incl. house shows (cache/)
  Wikipedia     List of WWE Hardcore Champions (wiki-cache/)
  Solie         Solie's Title Histories, WWF Hardcore (wiki-cache/, Wayback 2008)
Each record misses nights the others have (Wikipedia lacks Salt Lake City and
Amarillo, April 2002) and each has a few wrong dates, so no one of them is
the list. Where no two agree, the change is left out and printed.

    uv run --with requests --with beautifulsoup4 lineup-check/offcard_titles.py
"""
import collections
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from cawthon_parse import parse_events  # noqa: E402
from lineup_match import match_strength  # noqa: E402

OUT = ROOT / "data" / "offcard-title-changes.json"
WIKI = HERE / "wiki-cache" / "List_of_WWE_Hardcore_Champions.wiki"
SOLIE = HERE / "wiki-cache" / "solie_whcwwf.html"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_WWE_Hardcore_Champions"
SOLIE_URL = "http://web.archive.org/web/2008/http://www.solie.org/titlehistories/whcwwf.html"
WINDOW = ("2001-01-01", "2002-08-26")        # corpus start to the title's unification
# A TV show or pay-per-view in any of the three records' wording; those changes
# are on our cards (migration 0013), never here.
TV = re.compile(r"Raw is War|\bRAW\b|Monday Night|SmackDown|Smackdown|program\)|WrestleMania|No Way Out|"
                r"SummerSlam|Invasion|Vengeance|Insurrextion|Backlash|Judgment Day|King of the Ring|"
                r"Survivor Series|Armageddon|Unforgiven|No Mercy|Rebellion|Royal Rumble|Heat", re.I)
WIN = re.compile(r"^(.*?)\s+(?:pinned|defeated|won)\b.*?Hardcore.*?to (?:win|regain) the (?:Hardcore )?(?:title|belt)",
                 re.I)


# Cawthon's spelling -> the corpus's, so a reign carries the name the cards use.
CORPUS_NAMES = {"K-Kwick": "K-Kwik", "Chris Nowinski": "Christopher Nowinski"}


def _unlink(s):
    s = re.sub(r"<ref[^>]*/>|<ref.*?</ref>|<ref.*$", "", s)
    return re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s).replace("''", "").strip()


def wikipedia():
    out = []
    for b in re.split(r"\{\{PWtitlereign", WIKI.read_text(encoding="utf-8"))[1:]:
        d = re.search(r"\|date\s*=\s*\{\{dts\|(\d{4})\|(\d+)\|(\d+)\}\}", b)
        c = re.search(r"\|champion\s*=\s*([^\n]+)", b)
        if not d or not c:
            continue
        ev = re.search(r"\|event\s*=\s*([^\n]*)", b)
        loc = re.search(r"\|location\s*=\s*([^\n]*)", b)
        num = re.search(r"\|number\s*=\s*([^\n]*)", b)
        out.append({"date": f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}",
                    "champion": _unlink(c.group(1)), "event": _unlink(ev.group(1) if ev else ""),
                    "place": _unlink(loc.group(1) if loc else ""), "number": _unlink(num.group(1) if num else "")})
    return out


def solie():
    from bs4 import BeautifulSoup
    text = BeautifulSoup(SOLIE.read_text(encoding="utf-8", errors="replace"), "html.parser").get_text("\n")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out = []
    for i, ln in enumerate(lines[:-1]):
        m = re.match(r"^(\d+)\.\s*(.+?)(?:\s*\[\d+\])?\s*$", ln)
        d = re.match(r"^(\d\d)/(\d\d)/(\d{4})\s*-?\s*(.*)$", lines[i + 1])
        if m and d:
            out.append({"date": f"{d.group(3)}-{d.group(1)}-{d.group(2)}", "place": d.group(4),
                        "champion": re.sub(r"\s*\(.*?\)|\"the Bull\" ", "", m.group(2)).strip()})
    return out


def cawthon():
    nights = []
    for f in ("wwf-results-2001.html", "wwe-results-2002.html"):
        for e in parse_events((HERE / "cache" / f).read_text(encoding="utf-8")):
            # His headers do not mark a TV taping ("WWF @ Nashville, TN" is a
            # SmackDown taping), so a TV night is kept here and drops out below:
            # neither Wikipedia nor Solie lists it as a house show.
            if " @ " not in e["head"]:
                continue
            seq = []
            for line in e["lines"]:
                m = WIN.match(line)
                if m:
                    who = re.sub(r"\(w/[^)]*\)", "", m.group(1))
                    who = re.sub(r"^(?:WWF|WWE) [\w' &]+?Champions? ", "", who).strip(" ,")
                    seq.append((who, line))
            if seq:
                nights.append({"date": e["date"], "place": e["head"], "sequence": seq})
    return nights


def tv_dates():
    """Dates we hold a Raw, SmackDown or PPV for, taped or aired. Cawthon files
    a TV taping as "WWF @ Albany, NY" like any house show, and Solie often gives
    it no TV label either, so a night only those two list on one of these dates
    is our card's night, not a house show."""
    from src.build_update import load_existing
    out = set()
    for e in load_existing()["events"].values():
        if e["show_type"] in ("Raw", "SmackDown", "PPV"):
            out |= {e["air_date"], e.get("tape_date") or e["air_date"]}
    return out


def same(a, b):
    a, b = (x.replace("Stevie", "Steven").replace('"', "") for x in (a, b))
    return match_strength(a, b) >= 1 or a.replace("-", "").lower()[:5] == b.replace("-", "").lower()[:5]


def city(place):
    """First word of the town: "WWE (Raw) @ Columbia, SC - ..." and "Columbia,
    South Carolina" are both "columbia"."""
    t = re.sub(r"^.*?@\s*", "", place or "").lower().replace("saint ", "st. ")
    return re.split(r"[\s,(]", t.strip())[0]


def solie_match(sol, used, day, place, names):
    """Solie's night with this exact sequence: on the same date, or a day off
    (his dates slip) only in the same town. Each of his nights is used once."""
    near = {(date.fromisoformat(day) + timedelta(days=k)).isoformat() for k in (-1, 1)}
    for k, v in sol.items():
        if k in used or not same_seq(v, names):
            continue
        if k[0] == day or (k[0] in near and city(k[1]) == city(place)):
            used.add(k)
            return k
    return None


def same_seq(a, b):
    return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))


def build():
    lo, hi = WINDOW
    wiki = collections.defaultdict(list)
    for r in wikipedia():
        if lo <= r["date"] <= hi and r["event"] == "House show":
            wiki[(r["date"], r["place"])].append(r)
    sol = collections.defaultdict(list)
    for r in solie():
        if lo <= r["date"] <= hi and not TV.search(r["place"]):
            sol[(r["date"], r["place"])].append(r["champion"])
    changes, disputed, used_w, used_s = [], [], set(), set()
    tv = tv_dates()
    for n in cawthon():
        if not (lo <= n["date"] <= hi):
            continue
        names = [w for w, _ in n["sequence"]]
        w = next((k for k, v in wiki.items() if k[0] == n["date"] and k not in used_w
                  and same_seq([r["champion"] for r in v], names)), None)
        s = solie_match(sol, used_s, n["date"], n["place"], names)
        if w is None and s is None:
            disputed.append(("cawthon", n["date"], n["place"], names))
            continue
        if w is None and n["date"] in tv:
            continue        # a TV taping: those changes are on our cards
        if w:
            used_w.add(w)
        for i, (who, line) in enumerate(n["sequence"]):
            changes.append({"title": "WWF Hardcore Title" if n["date"] < "2002-05-06" else "WWE Hardcore Title",
                            "date": n["date"], "order": i, "champions": [who], "place": n["place"],
                            "sources": ["Cawthon"] + (["Wikipedia #" + wiki[w][i]["number"]] if w else []) +
                                       (["Solie"] if s else []),
                            "cawthon": line})
    for k, v in wiki.items():
        if k not in used_w:
            # A night Cawthon tells differently: kept where Solie gives
            # Wikipedia's exact sequence, so two records still agree.
            names = [r["champion"] for r in v]
            if solie_match(sol, used_s, k[0], k[1], names):
                for i, r in enumerate(v):
                    changes.append({"title": "WWF Hardcore Title" if k[0] < "2002-05-06" else "WWE Hardcore Title",
                                    "date": k[0], "order": i, "champions": [r["champion"]], "place": k[1],
                                    "sources": ["Wikipedia #" + r["number"], "Solie"], "cawthon": None})
                disputed = [d for d in disputed if not (d[1] == k[0])]
            else:
                disputed.append(("wikipedia", k[0], k[1], names))
    # A night the records tell differently but with the same number of
    # changes: keep each change two of them agree on. Columbia 2002-07-28 has
    # three different first winners (Wikipedia Raven, Cawthon Eddie Guerrero,
    # Solie Steven Richards) and the same three after that.
    caw_nights = {(n["date"], city(n["place"])): n for n in cawthon()}
    for day in sorted({d[1] for d in disputed if d[0] == "wikipedia"}):
        wk = next(k for k in wiki if k[0] == day and k not in used_w)
        seqs = {"Wikipedia": [r["champion"] for r in wiki[wk]]}
        cn = caw_nights.get((day, city(wk[1])))
        if cn:
            seqs["Cawthon"] = [w for w, _ in cn["sequence"]]
        sk = next((k for k in sol if k not in used_s and city(k[1]) == city(wk[1])
                   and abs((date.fromisoformat(k[0]) - date.fromisoformat(day)).days) <= 1), None)
        if sk:
            seqs["Solie"] = sol[sk]
        n = len(seqs["Wikipedia"])
        if len(seqs) < 2 or any(len(v) != n for v in seqs.values()):
            continue
        for i in range(n):
            agree = [src for src, v in seqs.items() if same(v[i], seqs["Wikipedia"][i])]
            if len(agree) < 2:
                print("left out, no two records agree on change", i + 1, "of", day,
                      {src: v[i] for src, v in seqs.items()})
                continue
            changes.append({"title": "WWF Hardcore Title" if day < "2002-05-06" else "WWE Hardcore Title",
                            "date": day, "order": i, "champions": [seqs["Wikipedia"][i]], "place": wk[1],
                            "sources": [src + (" #" + wiki[wk][i]["number"] if src == "Wikipedia" else "")
                                        for src in agree],
                            "cawthon": cn["sequence"][i][1] if cn and "Cawthon" in agree else None})
        disputed = [d for d in disputed if d[1] != day]
    for c in changes:
        c["champions"] = [CORPUS_NAMES.get(n, n) for n in c["champions"]]
    changes.sort(key=lambda c: (c["date"], c["order"]))
    return changes, disputed


def main():
    changes, disputed = build()
    doc = {"about": "Title changes at shows no card of ours carries. Each is listed the same way by at "
                    "least two of: Cawthon's results archive, Wikipedia's List of WWE Hardcore Champions, "
                    "Solie's Title Histories. Built by lineup-check/offcard_titles.py.",
           "sources": {"Wikipedia": WIKI_URL, "Solie": SOLIE_URL, "Cawthon": "https://thehistoryofwwe.com/"},
           "changes": changes}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(changes)} changes on {len({c['date'] for c in changes})} nights -> {OUT.relative_to(ROOT)}")
    for d in disputed:
        print("left out, no two records agree:", d)


if __name__ == "__main__":
    main()
