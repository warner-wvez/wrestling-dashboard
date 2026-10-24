#!/usr/bin/env python3
"""Who held a belt after a match, where no rule can read it off the card.

The reign walk takes a champion from the winning side. These matches defeat
that: a team won a singles belt and only one of them took it, two belts rode
on one match and went to different men, the champion who walked in was not
the man wearing the belt, or the card leaves a belt off the match. Each ruling
names the show, the people who identify the match on it, and the holder of
each belt afterwards, with the Wikipedia title history that says so. join.py
writes them onto cards.json as the match's title_result, the field the walk
reads, and puts a missing belt on the match's stake.
"""
from __future__ import annotations

WIKI = "https://en.wikipedia.org/wiki/"
WWE_LIST = WIKI + "List_of_WWE_Champions"
IC_LIST = WIKI + "List_of_WWE_Intercontinental_Champions"
EURO_LIST = WIKI + "List_of_WWE_European_Champions"
HC_LIST = WIKI + "List_of_WWE_Hardcore_Champions"

RULINGS = [
    {"night": ("Challenge", "1990-11-18"), "people": {"Marty Jannetty", "Shawn Michaels", "Bret Hart", "Jim Neidhart"},
     "belts": {"WWF World Tag Team Title": ["Bret Hart", "Jim Neidhart"]},
     "why": "the Rockers' two-out-of-three-falls win at the 1990-10-30 taping never aired and WWF never "
            "recognized it (the rope had broken); the Hart Foundation kept the belts",
     "source": WIKI + "List_of_World_Tag_Team_Champions_(WWE,_1971%E2%80%932010)"},
    {"night": ("PPV", "1990-04-01"), "people": {"Ultimate Warrior", "Hulk Hogan"},
     "stake": "WWF Championship / WWF Intercontinental Championship",
     "belts": {"WWF Championship": ["Ultimate Warrior"], "WWF Intercontinental Championship": ["Ultimate Warrior"]},
     "why": "title for title: the Intercontinental Champion pinned Hogan for the WWF Championship and held "
            "both until he gave up the Intercontinental title on 1990-04-03",
     "source": f"{WWE_LIST} ; {IC_LIST}"},
    {"night": ("PrimeTime", "1992-09-14"), "people": {"Ric Flair", "Randy Savage"},
     "stake": "WWF World Heavyweight Title",
     "belts": {"WWF World Heavyweight Title": ["Ric Flair"]},
     "why": "taped 1992-09-01 and first aired on this Prime Time Wrestling; Cawthon's line ends \"to win the "
            "title\"",
     "source": WWE_LIST},
    {"night": ("Raw", "1998-01-26"), "people": {"Owen Hart", "TAFKA Goldust"},
     "belts": {"WWF European Title": ["Owen Hart"]},
     "why": "Owen Hart beat The Artist Formerly Known As Goldust, who was dressed as Triple H and defended "
            "Triple H's belt",
     "source": EURO_LIST},
    {"night": ("PPV", "2000-01-23"), "people": {"Chris Jericho", "Chyna", "Hardcore Holly"},
     "belts": {"Undisputed WWF Intercontinental Championship": ["Chris Jericho"]},
     "why": "Jericho won the triple threat that ended his and Chyna's co-reign and became sole champion",
     "source": IC_LIST},
    {"night": ("PPV", "2000-04-02"), "people": {"Chris Benoit", "Chris Jericho", "Kurt Angle"},
     "belts": {"WWF Intercontinental Championship": ["Chris Benoit"], "WWF European Championship": ["Chris Jericho"]},
     "why": "Kurt Angle defended both belts in a two-fall triple threat: Benoit took the first fall for the "
            "Intercontinental title, Jericho the second for the European",
     "source": f"{IC_LIST} ; {EURO_LIST}"},
    # The Hardcore title under the 24/7 rule, from February 2000: "within"
    # lists who won and lost it inside the match, in order, before the holder
    # it ended with.
    {"night": ("PPV", "2000-04-02"), "people": {"Hardcore Holly"},
     "belts": {"WWF Hardcore Championship": ["Hardcore Holly"]},
     "within": {"WWF Hardcore Championship": ["Tazz", "Viscera", "Funaki", "Rodney", "Joey Abs", "Thrasher",
                                              "Pete Gas", "Tazz", "Crash Holly"]},
     "why": "a 15-minute hardcore battle royal in which every pinfall changed the title; Hardcore Holly held "
            "it at the bell",
     "source": HC_LIST},
    {"night": ("SmackDown", "2000-04-13"), "people": {"Crash Holly", "Tazz"},
     "stake": "WWF Hardcore Title",
     "belts": {"WWF Hardcore Title": ["Crash Holly"]},
     "within": {"WWF Hardcore Title": ["Tazz"]},
     "why": "Tazz took the belt from Perry Saturn after Saturn's win earlier in the night, and Crash Holly "
            "pinned Tazz here to regain it (taped 2000-04-11)",
     "source": HC_LIST},
    {"night": ("SmackDown", "2000-05-11"), "people": {"The British Bulldog", "Hardcore Holly"},
     "belts": {"WWF Hardcore Title": ["Crash Holly"]},
     "why": "Crash Holly pinned the Bulldog during his defense against Hardcore Holly (taped 2000-05-09)",
     "source": HC_LIST},
    {"night": ("Raw", "2000-05-15"), "people": {"Crash Holly", "The Godfather"},
     "belts": {"WWF Hardcore Title": ["Crash Holly"]},
     "within": {"WWF Hardcore Title": ["Godfather's Ho"]},
     "why": "the Godfather's Ho pinned Crash Holly during his defense against the Godfather, and Crash pinned "
            "her 15 seconds later in the same match",
     "source": HC_LIST},
    {"night": ("Raw", "2000-06-19"), "people": {"Gerald Brisco", "Crash Holly"},
     "belts": {"WWF Hardcore Title": ["Pat Patterson"]},
     "within": {"WWF Hardcore Title": ["Gerald Brisco"]},
     "why": "Brisco pinned Crash Holly during his defense against Hardcore Holly, then Pat Patterson pinned "
            "Brisco backstage",
     "source": HC_LIST},
    {"night": ("PPV", "2000-06-25"), "people": {"Pat Patterson", "Gerald Brisco", "Crash Holly"},
     "belts": {"WWF Hardcore Championship": ["Crash Holly"]},
     "why": "Crash Holly pinned Pat Patterson during his defense against Gerald Brisco in the evening gown match",
     "source": HC_LIST},
    {"night": ("SmackDown", "2000-06-29"), "people": {"Crash", "Al Snow"},
     "belts": {"WWF Hardcore Title": ["Steve Blackman"]},
     "why": "Steve Blackman pinned Crash Holly during his defense against Al Snow (taped 2000-06-27)",
     "source": HC_LIST},
    {"night": ("Raw", "2000-12-25"), "people": {"Steve Blackman", "Hardcore Holly", "Raven"},
     "belts": {"WWF Hardcore Title": ["Raven"]},
     "why": "Blackman kept the belt in the triple threat and Raven pinned him after it (taped 2000-12-22)",
     "source": HC_LIST},
    {"night": ("PPV", "2000-09-24"), "people": {"Steve Blackman"},
     "stake": "WWF Hardcore Championship",
     "belts": {"WWF Hardcore Championship": ["Steve Blackman"]},
     "within": {"WWF Hardcore Championship": ["Crash Holly", "Perry Saturn"]},
     "why": "a six-man hardcore battle royal: Crash Holly and then Perry Saturn won the belt from Blackman "
            "before he took it back",
     "source": HC_LIST},
    {"night": ("PPV", "2000-06-25"), "people": {"The Rock", "Mr. McMahon"},
     "belts": {"WWF Championship": ["The Rock"]},
     "why": "a six-man tag in which the belt went to whoever scored the fall; The Rock pinned Vince McMahon",
     "source": WWE_LIST},
    {"night": ("PPV", "2000-08-27"), "people": {"Chyna", "Trish Stratus"},
     "belts": {"WWF Intercontinental Championship": ["Chyna"]},
     "why": "a mixed tag with Eddie Guerrero against Val Venis and Trish Stratus; Chyna pinned Trish to win "
            "Venis's title",
     "source": IC_LIST},
]


# Matches Cagematch bills as title matches that two other records call
# non-title: Cawthon ("in a non-title match") and a third (SmackDown Hotel, KB
# Wrestling Reviews). Checked by web search 2026-10-24. Five more Cawthon
# calls non-title stay title matches: there two records say the belt was on
# the line. Superstars 1987-01-10 (Sheik and Volkoff over the Bulldogs by DQ)
# is one record each and stays as Cagematch bills it.
SDH = "https://www.thesmackdownhotel.com/events-results/wwe/"
CAWTHON = "https://thehistoryofwwe.com/"
NON_TITLE = [
    {"night": ("Superstars", "1997-01-26"), "people": {"Ahmed Johnson", "Hunter Hearst Helmsley"},
     "why": "non-title: Cawthon and KB Wrestling Reviews' recap of the episode",
     "source": f"{CAWTHON}wwf-superstars-1997/ ; https://kbwrestlingreviews.com/2026/02/02/"
               "superstars-january-26-1997-review-superstars-bowl/"},
    {"night": ("Raw", "1997-03-10"), "people": {"Owen Hart", "The British Bulldog"},
     "why": "non-title: Cawthon, SmackDown Hotel's results and KB Wrestling Reviews' recap",
     "source": f"{CAWTHON}wwf-raw-1997/ ; {SDH}raw-is-war-1997 ; https://kbwrestlingreviews.com/2015/01/28/"
               "monday-night-raw-march-10-1997-the-skeleton-of-greatness/"},
    {"night": ("SmackDown", "1999-10-28"), "people": {"Al Snow"},
     "why": "non-title: Cawthon and SmackDown Hotel's results",
     "source": f"{CAWTHON}wwf-smackdown-1999/ ; {SDH}smackdown-1999"},
    {"night": ("SmackDown", "2000-06-01"), "people": {"Kane", "Triple H"},
     "stipulation": "#1 contender for the WWF Championship",
     "why": "a #1 contender match, not a title defense: Cawthon and SmackDown Hotel's results",
     "source": f"{CAWTHON}wwf-smackdown-2000/ ; {SDH}smackdown-2000"},
]


def apply_title_rulings(cards: list[dict]) -> int:
    """Set each ruling's title_result on its match; halt when a ruling finds
    no match or more than one, or names a belt the match does not carry, so a
    changed card never drops one silently."""
    by_night = {}
    for c in cards:
        by_night.setdefault((c["show_type"], c["air_date"]), []).append(c)
    misses = []
    for r in RULINGS:
        hits = [m for c in by_night.get(r["night"], []) for m in c["matches"]
                if (m.get("title_at_stake") or r.get("stake"))
                and r["people"] <= {p for t in m["teams"] for p in t["participants"]}]
        if len(hits) != 1:
            misses.append(f"{r['night']} {sorted(r['people'])}: {len(hits)} matches")
            continue
        m = hits[0]
        if r.get("stake"):
            m["title_at_stake"] = r["stake"]
        parts = [x.strip() for x in m["title_at_stake"].replace(" & ", " / ").split(" / ")]
        gone = [b for b in r["belts"] if b not in parts]
        if gone:
            misses.append(f"{r['night']}: {gone} not in {m['title_at_stake']!r}")
            continue
        m["title_result"] = [{"title": b, "champions": holders, "why": r["why"], "source": r["source"],
                              **({"within": [[n] for n in r["within"][b]]} if b in r.get("within", {}) else {})}
                             for b, holders in r["belts"].items()]
    for r in NON_TITLE:
        hits = [m for c in by_night.get(r["night"], []) for m in c["matches"]
                if m.get("title_at_stake") and r["people"] <= {p for t in m["teams"] for p in t["participants"]}]
        if len(hits) != 1:
            misses.append(f"non-title {r['night']} {sorted(r['people'])}: {len(hits)} matches")
            continue
        m = hits[0]
        m["title_at_stake"] = None
        if r.get("stipulation"):
            m["stipulation"] = r["stipulation"]
        m["stake_ruling"] = {"why": r["why"], "source": r["source"]}
    if misses:
        raise SystemExit("title rulings that found no single match:\n  " + "\n  ".join(misses))
    return len(RULINGS) + len(NON_TITLE)
