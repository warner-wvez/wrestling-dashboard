"""A belt stays with its champion on a DQ or count-out loss, unless a
stipulation let it change hands that way and the card says so.

Christian won the World Heavyweight title by DQ at Money in the Bank 2011
("Christian defeats Randy Orton (c) by DQ - TITLE CHANGE !!!"), and Sasha Banks
the Raw Women's title by count-out on Raw 2020-07-27. The walk kept both belts
with the champion, so each reign started at the next match on our cards.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.title_lineages import lineage_name  # noqa: E402
from src.export_to_html import build_title_reigns  # noqa: E402

TITLE = "WWE Intercontinental Title"


def _m(order, winner, loser, raw, outcome=None):
    return {
        "match_order": order,
        "match_type": f"{TITLE} Match",
        "title_at_stake": TITLE,
        "raw_description": raw,
        "teams": [
            {"team_number": 1, "team_name": winner, "participants": [winner], "was_winner": True,
             "was_champion_entering": False, "match_outcome": outcome},
            {"team_number": 2, "team_name": loser, "participants": [loser], "was_winner": False,
             "was_champion_entering": True},
        ],
    }


def _reigns(second):
    events = {
        "1": {"id": 1, "air_date": "2011-06-01", "title": "Show",
              "matches": [_m(1, "Randy Orton", "Christian", "Randy Orton defeats Christian (c) - TITLE CHANGE !!!")]},
        "2": {"id": 2, "air_date": "2011-07-17", "title": "Show", "matches": [second]},
    }
    return build_title_reigns(events, offcard=())[lineage_name(TITLE, "2011-06-01")]


def test_a_dq_win_marked_as_a_title_change_moves_the_belt():
    reigns = _reigns(_m(1, "Christian", "Randy Orton",
                        "Christian defeats Randy Orton (c) by DQ (12:22) - TITLE CHANGE !!!", "dq-win"))
    assert [(r["champion_names"], r["start"]) for r in reigns][-1] == (["Christian"], "2011-07-17")


def test_a_count_out_win_that_says_to_win_the_title_moves_the_belt():
    reigns = _reigns(_m(1, "Christian", "Randy Orton",
                        "Christian defeats Randy Orton (c) via Count-out to win the title", "countout-win"))
    assert reigns[-1]["champion_names"] == ["Christian"]


def test_a_plain_dq_win_leaves_the_belt_with_the_champion():
    reigns = _reigns(_m(1, "Christian", "Randy Orton", "Christian defeats Randy Orton (c) by DQ (12:22)", "dq-win"))
    assert reigns[-1]["champion_names"] == ["Randy Orton"]
