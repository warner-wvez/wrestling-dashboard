"""The Titles shelf names each retired belt the way its history does, and no
two belt pages share an address.

Cagematch titles WCW's belt (page 755) "World Heavyweight Championship", the
words the 2002-13 belt carries too, so the shelf showed WCW's belt as "World
Heavyweight Championship (2001)" and gave the 2002-13 one its years as well.
"""
import json
import re
from pathlib import Path

TITLES = Path(__file__).resolve().parent.parent / "shards" / "titles.json"


def _pages():
    doc = json.loads(TITLES.read_text(encoding="utf-8"))
    return doc["active"] + doc["retired"]


def _by_nr():
    return {int(t["url"].rsplit("=", 1)[1]): t["title"] for t in _pages()}


def test_wcw_belt_carries_its_own_name():
    assert _by_nr()[755] == "WCW World Heavyweight Championship"


def test_the_2002_belt_needs_no_years_once_wcw_is_named():
    assert _by_nr()[17] == "World Heavyweight Championship"


def _slug(name):
    """frontend/index.html jsSlugify, which builds the #title/ address."""
    s = re.sub(r"[^a-z0-9\s-]", "", name.lower())
    return re.sub(r"^-|-$", "", re.sub(r"[\s-]+", "-", s)) or "unknown"


def test_every_belt_page_has_its_own_address():
    slugs = [_slug(t["title"]) for t in _pages()]
    assert len(slugs) == len(set(slugs))
    assert _slug("WWE Women's 24/7 Championship") == "wwe-womens-247-championship"
