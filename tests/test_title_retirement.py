"""A belt must not keep its last champion forever.

A reign ends when the next title change happens, so the LAST reign of a belt has
nothing to end it. Left alone the corpus insists Rob Van Dam has held the
Hardcore Title since 2002, ECW still crowns a champion, and every one of them
badges its holder as champion on every card thereafter.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import build_title_reigns  # noqa: E402

CORPUS_END = "2026-06-27"


def _title_match(order, winner, loser, title, change):
    tail = " - TITLE CHANGE !!!" if change else ""
    return {
        "match_order": order,
        "match_type": f"{title} Match",
        "title_at_stake": title,
        "raw_description": f"{winner} defeats {loser} (c) (10:00){tail}",
        "teams": [
            {"team_number": 1, "team_name": winner, "participants": [winner],
             "was_winner": True, "was_champion_entering": not change},
            {"team_number": 2, "team_name": loser, "participants": [loser],
             "was_winner": False, "was_champion_entering": change},
        ],
    }


def _events(rows):
    """rows: (eid, date, title, winner, loser, is_change)"""
    out = {}
    for eid, date, title, winner, loser, change in rows:
        out[str(eid)] = {"id": eid, "air_date": date, "title": "Show",
                         "matches": [_title_match(1, winner, loser, title, change)]}
    # anchor the corpus end so "how long since we saw this belt" has a reference
    out["9999"] = {"id": 9999, "air_date": CORPUS_END, "title": "Show", "matches": []}
    return out


def test_a_belt_the_corpus_stops_seeing_closes_its_final_reign():
    reigns = build_title_reigns(_events([
        (1, "2002-01-07", "WWF Hardcore Title", "Rob Van Dam", "Test", True),
        (2, "2002-08-26", "WWF Hardcore Title", "Rob Van Dam", "Jeff Hardy", False),
    ]))["WWF Hardcore Title"]
    final = reigns[-1]
    assert final["end"] == "2002-08-26", (
        "a belt last defended in 2002 must not still be held in 2026")
    assert final["end_event_id"] == 2


def test_a_belt_still_being_defended_keeps_an_open_reign():
    reigns = build_title_reigns(_events([
        (1, "2026-01-05", "WWE Title", "Sami Zayn", "Gunther", True),
        (2, "2026-06-20", "WWE Title", "Sami Zayn", "Bron Breakker", False),
    ]))["WWE Title"]
    assert reigns[-1]["end"] is None, (
        "a belt defended a week before the corpus ends is current, not retired")


def test_a_revived_name_keeps_the_lineage_live():
    # WWE reuses names: the World Heavyweight and World Tag Team titles were both
    # revived years after the originals retired, so one derived lineage holds the
    # dead belt and its modern namesake. Cagematch flags the OLD lineage INACTIVE,
    # and trusting that flag through a name join would end the current champion's
    # reign. Last-seen has to get this right instead.
    reigns = build_title_reigns(_events([
        (1, "2002-09-02", "World Heavyweight Title", "Triple H", "Booker T", True),
        (2, "2013-12-15", "World Heavyweight Title", "Randy Orton", "John Cena", True),
        (3, "2026-04-19", "World Heavyweight Title", "Roman Reigns", "Seth Rollins", True),
    ]))["World Heavyweight Title"]
    assert reigns[-1]["end"] is None, "the revival is current and must stay open"
    assert reigns[-1]["champion_names"] == ["Roman Reigns"]
    # ...and only the final reign is ever open, however old the lineage is
    assert [r["end"] for r in reigns[:-1]].count(None) == 0
