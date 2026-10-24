"""WWF's own archived write-ups settle review rows by who is named on the page."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backfill.wayback_tv import check, parse_page  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "backfill"


def test_write_up_page_parses_show_date_part_and_text():
    rec = parse_page((FIX / "wwf-tv-1999-06-24ac.html").read_text(encoding="utf-8", errors="replace"),
                     "/tv/archives/1999/06/24ac.html")
    assert rec["show_type"] == "Raw" and rec["air_date"] == "1999-06-21" and rec["part"] == 3
    assert "Big Show" in rec["text"] and "Hardcore Holly" in rec["text"]
    assert "ShopZone" not in rec["text"][-200:]


def test_index_page_is_not_a_write_up():
    assert parse_page((FIX / "wwf-tv-indexjune99.html").read_text(encoding="utf-8", errors="replace"),
                      "/tv/archives/indexjune99.html") is None


def test_rows_are_ruled_by_name_presence():
    texts = {"Raw|1999-06-21": {"text": "The Big Show and Hardcore Holly battled out of the arena. The Big Show got the pin. "
                                        "Mr. Ass teamed with the Acolytes to take on X-Pac, Kane and the Road Dogg.",
                                "urls": ["http://web.archive.org/web/*/http://www.wwf.com/tv/archives/1999/06/24ac.html"], "parts": 1}}
    rows = [
        {"event_key": "Raw|1999-06-21|1", "show_type": "Raw", "air_date": "1999-06-21", "class": "different_opponent", "match_order": "2",
         "ours": "The Big Show defeats Hardcore Holly (4:00)", "cawthon": "The Big Show pinned Bob Holly at 4:00"},
        {"event_key": "Raw|1999-06-21|1", "show_type": "Raw", "air_date": "1999-06-21", "class": "unpaired", "match_order": "3",
         "ours": "Dark:Mideon defeats Gillberg", "cawthon": ""},
        {"event_key": "Raw|1999-06-21|1", "show_type": "Raw", "air_date": "1999-06-21", "class": "missing_match", "match_order": "",
         "ours": "", "cawthon": "Mr. Ass & the Acolytes defeated X-Pac, Kane, & the Road Dogg when Mr. Ass pinned X-Pac"},
        {"event_key": "Raw|1999-06-21|1", "show_type": "Raw", "air_date": "1999-06-21", "class": "result", "match_order": "2",
         "ours": "The Big Show defeats Hardcore Holly (4:00)", "cawthon": "Hardcore Holly fought the Big Show to a no contest"},
        {"event_key": "Heat|1999-06-20|2", "show_type": "Heat", "air_date": "1999-06-20", "class": "date_unconfirmed", "match_order": "",
         "ours": "", "cawthon": ""},
    ]
    out = {(r["class"], r["match_order"]): r for r in check(rows, texts)}
    assert out[("different_opponent", "2")]["ruling"] == "keep"
    assert ("unpaired", "3") not in out                      # Mideon and Gillberg are not on WWF's page
    assert out[("missing_match", "")]["ruling"] == "add_match"
    assert out[("result", "2")]["ruling"] == "evidence" and "got the pin" in out[("result", "2")]["evidence"]
    assert ("date_unconfirmed", "") not in out               # no WWF write-up for that Heat
    assert out[("different_opponent", "2")]["source_url"].startswith("http://web.archive.org/")
