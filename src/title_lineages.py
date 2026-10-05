"""
Which belt a title string means, on a given date.

The corpus names belts the way each source billed them that night, and WWE
renamed and swapped its belts often enough that one string can mean three
different belts and one belt can go by nine strings. Keyed by words alone, the
reign walk split the WWE Championship across nine lineages ("WWE Heavyweight
Title" 2002-13 and "WWE Title" 2009-22 even ran side by side), ran the 1956
Women's Championship as two overlapping belts ("World Women's Title" to 2009,
"WWE Women's Title" from 2005), and fused belts that only share a name: the
original World Tag Team Championship (retired 2010) with the Raw tag titles
WWE renamed World Tag Team Championship in 2024.

Each lineage here is one belt's history as Wikipedia's title history tells it
(wiki_list is that list's page title, read by lineup-check/title_audit.py),
with the strings and date ranges the corpus uses for it, and the Cagematch
title page the Titles view shows it on. A string can belong to two lineages
when one match moves both belts (the unified tag titles of 2009-10, the
undisputed tag titles of 2022-24, Roman Reigns's undisputed WWE Universal
title). Strings not listed here keep the word-based lineage key.

Dates are inclusive ISO strings; None is open.
"""
from __future__ import annotations


LINEAGES = [
    {"key": "lineage::wwe-championship", "name": "WWE Championship", "cagematch": 20,
     "wiki_list": "List of WWE Champions",
     "strings": [("WWF World Heavyweight Title", None, "2001-12-31"),
                 ("WWF Title", None, None),
                 ("WWF Undisputed World Heavyweight Title", None, None),
                 ("WWE Undisputed World Heavyweight Title", None, None),
                 ("WWE Heavyweight Title", None, None),
                 ("WWE Title", None, None),
                 ("WWE World Heavyweight Title", "2013-01-01", "2016-12-31"),
                 ("WWE World Title", "2016-01-01", "2016-12-31"),
                 ("Undisputed WWE Universal Title", None, None),
                 ("Undisputed WWE Title", None, None)]},
    {"key": "lineage::universal", "name": "WWE Universal Championship", "cagematch": 3102,
     "wiki_list": "List of WWE Universal Champions",
     "strings": [("WWE Universal Title", None, None),
                 ("Undisputed WWE Universal Title", None, None)]},
    {"key": "lineage::wcw-world", "name": "WCW World Heavyweight Championship", "cagematch": 755,
     "wiki_list": "List of WCW World Heavyweight Champions",
     "strings": [("WCW World Heavyweight Title", None, None),
                 # After Survivor Series 2001 WWF billed it the "World
                 # Championship" until Vengeance unified it.
                 ("World Heavyweight Title", "2001-01-01", "2001-12-31")]},
    {"key": "lineage::world-heavyweight-2002", "name": "World Heavyweight Championship", "cagematch": 17,
     "wiki_list": "List of World Heavyweight Champions (WWE, 2002–2013)",
     "strings": [("World Heavyweight Title", "2002-01-01", "2013-12-31")]},
    {"key": "lineage::world-heavyweight-2023", "name": "WWE World Heavyweight Championship", "cagematch": 6069,
     "wiki_list": "List of World Heavyweight Champions (WWE)",
     "strings": [("World Heavyweight Title", "2023-01-01", None)]},
    {"key": "lineage::womens-1956", "name": "WWE Women's Championship (1956-2010)", "cagematch": 18,
     "wiki_list": "List of WWE Women's Champions (1956–2010)",
     "strings": [("WWF World Women's Title", None, None),
                 ("WWE World Women's Title", None, None),
                 ("World Women's Title", None, None),
                 ("WWE Women's Title", None, "2010-12-31")]},
    # In June 2023 WWE swapped the two women's belts between brands: the
    # Raw lineage (Charlotte's 2016 WWE Women's title, then Raw Women's) went
    # to SmackDown as the WWE Women's Championship, and the SmackDown lineage
    # (Becky Lynch's 2016 title) went to Raw as the Women's World Championship.
    {"key": "lineage::womens-2016", "name": "WWE Women's Championship", "cagematch": 2906,
     "wiki_list": "List of WWE Women's Champions",
     "strings": [("WWE Women's Title", "2016-01-01", "2016-12-31"),
                 ("WWE Raw Women's Title", None, None),
                 ("WWE Women's Title", "2023-01-01", None)]},
    {"key": "lineage::womens-world", "name": "WWE Women's World Championship", "cagematch": 3116,
     "wiki_list": "List of Women's World Champions (WWE)",
     "strings": [("WWE SmackDown Women's Title", None, None),
                 ("Women's World Title", None, None)]},
    {"key": "lineage::divas", "name": "WWE Divas Championship", "cagematch": 904,
     "wiki_list": "List of WWE Divas Champions",
     "strings": [("WWE Divas Title", None, None),
                 ("Unified WWE Divas Title", None, None)]},
    {"key": "lineage::world-tag-1971", "name": "World Tag Team Championship (1971-2010)", "cagematch": 60,
     "wiki_list": "List of World Tag Team Champions (WWE, 1971–2010)",
     "strings": [("WWF World Tag Team Title", None, None),
                 ("WWF Tag Team Title", None, "2001-12-31"),
                 ("WWE World Tag Team Title", None, "2010-12-31"),
                 ("World Tag Team Title", None, "2010-12-31"),
                 ("Unified WWE Tag Team Title", None, None)]},
    {"key": "lineage::wwe-tag-2002", "name": "WWE World Tag Team Championship", "cagematch": 61,
     "wiki_list": "List of World Tag Team Champions (WWE)",
     "strings": [("WWE Tag Team Title", "2002-01-01", "2016-12-31"),
                 ("Unified WWE Tag Team Title", None, None),
                 ("WWE Raw Tag Team Title", None, None),
                 ("Undisputed WWE Tag Team Title", None, None),
                 ("World Tag Team Title", "2024-01-01", None),
                 ("WWE World Tag Team Title", "2024-01-01", None)]},
    {"key": "lineage::smackdown-tag", "name": "WWE Tag Team Championship", "cagematch": 3117,
     "wiki_list": "List of WWE Tag Team Champions",
     "strings": [("WWE SmackDown Tag Team Title", None, None),
                 ("Undisputed WWE Tag Team Title", None, None),
                 ("WWE Tag Team Title", "2024-01-01", None)]},
    {"key": "lineage::cruiserweight-1991", "name": "WWE Cruiserweight Championship", "cagematch": 19,
     "wiki_list": "List of WWE Cruiserweight Champions (1996–2007)",
     "strings": [("WCW Cruiserweight Title", None, None),
                 ("WWF Cruiserweight Title", None, None),
                 ("WWE Cruiserweight Title", None, "2010-12-31")]},
    {"key": "lineage::cruiserweight-2016", "name": "WWE NXT Cruiserweight Championship", "cagematch": 3119,
     "wiki_list": "List of WWE Cruiserweight Champions",
     "strings": [("WWE Cruiserweight Title", "2016-01-01", None),
                 ("NXT Cruiserweight Title", None, None)]},
]

_BY_STRING: dict[str, list[tuple[str | None, str | None, dict]]] = {}
for _lin in LINEAGES:
    for _s, _lo, _hi in _lin["strings"]:
        _BY_STRING.setdefault(_s, []).append((_lo, _hi, _lin))
BY_KEY = {lin["key"]: lin for lin in LINEAGES}


def lineages_for(title: str, day: str) -> list[dict]:
    """The lineages a title string moves on this date; [] when the string is
    not mapped here (the caller falls back to its word-based key)."""
    out = []
    for lo, hi, lin in _BY_STRING.get((title or "").strip(), []):
        if (lo is None or day >= lo) and (hi is None or day <= hi):
            out.append(lin)
    return out


def lineage_name(title: str, day: str) -> str:
    """The name the reign walk files this string's reigns under on this date:
    the lineage's name when mapped, else the string itself."""
    found = lineages_for(title, day)
    return found[0]["name"] if found else title
