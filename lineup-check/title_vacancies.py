#!/usr/bin/env python3
"""Vacancies from the title histories, for the reign walk.

Without them the walk ran a vacated reign on to the match that refilled the
belt: Booker T "held" the US title through a two-month vacancy in 2005-06, and
a champion stripped for injury kept the belt until someone else won it. This
reads each title's Wikipedia list (the lineage map's lists plus EXTRA) and
writes data/title-vacancies.json.

A row counts as a vacancy when the list leaves the champion empty and its note
says the belt was vacated, stripped, relinquished or deactivated (not unified
or retired: those end a lineage, which the walk already handles), and not when
WWE no longer recognizes it (CM Punk, July 2011). A taped vacancy takes the
air date the note gives. And it goes in only when the champion the list says
lost the belt is who our own history has holding it that day; anything else
is printed for a person.

    uv run --with requests --with beautifulsoup4 lineup-check/title_vacancies.py
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

from title_audit import EXTRA  # noqa: E402
from wiki_titles import fetch, reigns  # noqa: E402

OUT = ROOT / "data" / "title-vacancies.json"
MORE = {   # word-keyed titles beyond the audit's, our title string -> list
    "NXT Title": "List of NXT Champions",
    "NXT Women's Title": "List of NXT Women's Champions",
    "NXT North American Title": "List of NXT North American Champions",
    "WWE NXT Tag Team Title": "List of NXT Tag Team Champions",
    "WWE Women's Tag Team Title": "List of WWE Women's Tag Team Champions",
}
AWARDED = re.compile(r"\bawarded\b", re.I)
CORPUS_NAMES = {}   # a list's spelling -> the corpus's, where they differ
VACATED = re.compile(r"vacat|stripped|relinquish|deactivat|left the .*belt in the ring", re.I)
NOT_RECOGNIZED = re.compile(r"no longer recognized", re.I)
AIRED = re.compile(r"[Aa]ired on tape delay on ([A-Z][a-z]+ \d{1,2}, \d{4})")


# Teams a list names where our cards name the members.
TEAMS = {"war raiders": ["Hanson", "Rowe"], "msk": ["Nash Carter", "Wes Lee"]}


def _plain(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def _lost_by(lost, names):
    """Does the list's outgoing champion match one of our holders?"""
    text = _plain(lost)
    for team, members in TEAMS.items():
        if team in text:
            text += " " + " ".join(_plain(m) for m in members)
    return any(_plain(n.split()[-1]) in text for n in names if n)


def main():
    from src.build_update import load_existing
    from src.title_lineages import LINEAGES
    data = load_existing()
    ours = data["title_reigns"]
    sources = [(lin["name"], {"lineage": lin["key"]}, lin["wiki_list"]) for lin in LINEAGES]
    sources += [(name, {"title": name}, page) for name, page in {**EXTRA, **MORE}.items()]
    keep, rejected = [], []
    for name, where, page in sources:
        chain = ours.get(name) or []
        if not chain:
            continue
        lo, hi = chain[0]["start"], max(r["end"] or "9999-12-31" for r in chain)
        rows = reigns(fetch(page)["text"])
        for i, r in enumerate(rows):
            # A title handed to someone, no match, right after a vacancy:
            # Randy Orton at No Mercy 2007, Dolph Ziggler in 2011.
            if r["champion"] and i and not rows[i - 1]["champion"] and AWARDED.search(r["notes"]) \
                    and lo < r["date"] <= hi:
                aired = AIRED.search(r["notes"])
                day = datetime.strptime(aired.group(1), "%B %d, %Y").date().isoformat() if aired else r["date"]
                champs = [CORPUS_NAMES.get(n.strip(), n.strip()) for n in re.split(r" and |, ", r["champion"])]
                keep.append({**where, "date": day, "order": -1, "champions": champs, "awarded": True,
                             "why": r["notes"][:300], "source": page})
                continue
            if r["champion"] or not (lo < r["date"] <= hi) or not VACATED.search(r["notes"]) \
                    or NOT_RECOGNIZED.search(r["notes"]):
                continue
            aired = AIRED.search(r["notes"])
            day = datetime.strptime(aired.group(1), "%B %d, %Y").date().isoformat() if aired else r["date"]
            lost = rows[i - 1]["champion"] if i else ""
            # Every reign that touches the day: a belt can change hands and be
            # deactivated the same night (No Mercy 2002, the IC title).
            holders = [c for c in chain if c["start"] <= day and (c["end"] is None or c["end"] >= day)]
            names = [n for c in holders for n in c["champion_names"]]
            if not _lost_by(lost, names):
                rejected.append((name, day, lost, names, r["notes"][:100]))
                continue
            keep.append({**where, "date": day, "vacate": True, "vacated_by": lost,
                         "why": r["notes"][:300], "source": page})
    keep.sort(key=lambda v: (v["date"], v.get("lineage") or v.get("title"), v.get("order", 0)))
    OUT.write_text(json.dumps({"about": "Title vacancies from Wikipedia's title histories, kept where the "
                                        "champion the list names is who our history has holding the belt. "
                                        "Built by lineup-check/title_vacancies.py.",
                               "vacancies": keep}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(keep)} vacancies -> {OUT.relative_to(ROOT)}")
    for x in rejected:
        print("not applied, our holder differs:", x)


if __name__ == "__main__":
    main()
