"""An NXT UK reign runs across the two years our cards carry no NXT UK show.

With no NXT UK show between TakeOver: Cardiff (2019-08-31) and Worlds Collide
2022, the walk read the gap as the belt dying: Kay Lee Ray's UK Women's reign
ended at Cardiff and Meiko Satomura's 2021 win started a new belt.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lineup-check"))
sys.path.insert(0, str(ROOT))

from src.export_to_html import build_title_reigns  # noqa: E402

TITLE = "WWE NXT UK Women's Title"


def _card(eid, day, winner, loser):
    return {"id": eid, "air_date": day, "title": "NXT UK TakeOver",
            "matches": [{"match_order": 1, "match_type": f"{TITLE} Match", "title_at_stake": TITLE,
                         "raw_description": f"{winner} defeats {loser} (c) - TITLE CHANGE !!!",
                         "teams": [{"team_number": 1, "team_name": winner, "participants": [winner],
                                    "was_winner": True, "was_champion_entering": False},
                                   {"team_number": 2, "team_name": loser, "participants": [loser],
                                    "was_winner": False, "was_champion_entering": True}]}]}


def test_a_change_from_the_histories_keeps_the_belt_alive_across_a_long_gap():
    events = {"1": _card(1, "2019-01-12", "Toni Storm", "Rhea Ripley"),
              "2": _card(2, "2019-08-31", "Kay Lee Ray", "Toni Storm")}
    change = {"title": TITLE, "date": "2021-06-10", "order": 0, "champions": ["Meiko Satomura"]}
    reigns = build_title_reigns(events, offcard=[change])[TITLE]
    kay, meiko = reigns[-2], reigns[-1]
    assert (kay["champion_names"], kay["end"]) == (["Kay Lee Ray"], "2021-06-10")
    assert not kay.get("closed_at_retirement")
    assert (meiko["champion_names"], meiko["start"]) == (["Meiko Satomura"], "2021-06-10")
