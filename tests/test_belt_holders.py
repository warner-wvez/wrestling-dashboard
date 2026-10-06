"""On a side with more people than the belt has holders, the card names the
one who held it, so the belt and the Champ mark go on him.

Judgment Day 2007: "Shane McMahon, Umaga, Vince McMahon" defended the ECW title
against Bobby Lashley, and the belt sat on Shane, the first name. It was
Vince's.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import mark_belt_holders  # noqa: E402


def _events(stake, people):
    return {"1": {"air_date": "2007-05-20", "matches": [{
        "title_at_stake": stake, "match_type": "Handicap Match",
        "teams": [{"participants": ["Bobby Lashley"], "was_champion_entering": False},
                  {"participants": people, "was_champion_entering": True}]}]}}


REIGNS = {"Vince McMahon": [{"title": "ECW World Heavyweight Title", "start": "2007-04-29", "end": None}],
          "Hardy": [{"title": "World Tag Team Title", "start": "2007-04-02", "end": None}]}


def test_the_holder_is_named():
    events = _events("ECW World Heavyweight Title", ["Shane McMahon", "Umaga", "Vince McMahon"])
    assert mark_belt_holders(events, REIGNS) == 1
    assert events["1"]["matches"][0]["teams"][1]["belt_holders"] == ["Vince McMahon"]


def test_a_tag_belt_is_left_alone():
    events = _events("World Tag Team Title", ["Hardy", "Jeff Hardy"])
    assert mark_belt_holders(events, REIGNS) == 0
    assert "belt_holders" not in events["1"]["matches"][0]["teams"][1]
