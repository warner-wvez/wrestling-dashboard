"""shards/where.json keeps to its contract: every row is one of our shows, every
archive file comes from an item in the feed, every official link is a Peacock
or Netflix page, and every join rule is one the builder documents.
"""
import csv
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WHERE = json.loads((REPO / "shards" / "where.json").read_text(encoding="utf-8"))
HOW = re.compile(r"^(date|name|ordinal|near[+-][123])$")


def _event_ids():
    html = (REPO / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="wrestling-data"[^>]*>(.*?)</script>', html, re.S)
    return set(json.loads(m.group(1))["events"].keys())


def _feed_items():
    with open(REPO / "media-pipeline" / "watch-feed.csv", newline="") as f:
        return {r["identifier"] for r in csv.DictReader(f)}


def test_every_row_is_one_of_our_shows():
    assert set(WHERE) <= _event_ids()


def test_archive_files_come_from_feed_items_and_name_their_join():
    items = _feed_items()
    for row in WHERE.values():
        a = row.get("archive")
        if not a:
            continue
        assert a["item"] in items
        assert a["file"].lower().endswith((".mp4", ".mkv", ".avi"))
        assert HOW.match(a["how"]), a
        assert a["min"] == 0 or 40 <= a["min"] <= 300, a  # 0: the item lists no length


def test_official_links_are_peacock_or_netflix_pages():
    for row in WHERE.values():
        o = row.get("official")
        if not o:
            continue
        host = {"peacock": "https://www.peacocktv.com/", "netflix": "https://www.netflix.com/watch/"}[o["platform"]]
        assert o["url"].startswith(host), o


def test_coverage_holds_for_the_first_three_years():
    html = (REPO / "index.html").read_text(encoding="utf-8")
    events = json.loads(re.search(r'<script id="wrestling-data"[^>]*>(.*?)</script>', html, re.S).group(1))["events"]
    early = [k for k, e in events.items() if "2001" <= e["air_date"][:4] <= "2003" and e["show_type"] in ("Raw", "SmackDown", "PPV")]
    missing = [k for k in early if not WHERE.get(k, {}).get("archive")]
    # Insurrextion 2001 and 2003 are the only 2001-2003 shows the feed lacks.
    assert len(missing) <= 2, missing
