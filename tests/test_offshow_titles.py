"""The off-show title change builder pairs one reign across three histories
that each write a champion their own way, and finds the card match a change
belongs after when our card carries the match but not the title change.

Each case is a row the NXT belts produced.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lineup-check"))
sys.path.insert(0, str(ROOT))

from offshow_titles import event_key, recognized_start, same, won_on_card  # noqa: E402


def test_a_team_pairs_across_all_three_ways_of_writing_it():
    """NXT tag titles, 2013-05-02: Wikipedia writes the team name with its
    members apart, Duncan and Will "Wyatt Family: Erick Rowan & Luke Harper",
    WWE.com "The Wyatt Family"."""
    wiki = {"champion": "The Wyatt Family", "members": ["Luke Harper", "Erick Rowan"]}
    assert same(wiki, {"champion": "Wyatt Family: Erick Rowan & Luke Harper"})
    assert same(wiki, {"champion": "The Wyatt Family"})
    assert same({"champion": "Adrian Neville and Corey Graves", "members": ["Adrian Neville", "Corey Graves"]},
                {"champion": "Adrian Neville & Corey Graves (Sterling James Keenan )"})
    assert not same(wiki, {"champion": "British Ambition: Adrian Neville (Pac) & Oliver Grey"})


def test_a_wrestler_pairs_under_the_name_wwe_uses_today():
    """WWE.com lists Jordan Devlin as JD McDonagh and T. J. Perkins as TJP."""
    assert same({"champion": "Jordan Devlin"}, {"champion": "JD McDonagh"})
    assert same({"champion": "T. J. Perkins"}, {"champion": "TJP"})
    assert same({"champion": "El Hijo del Fantasma/Santos Escobar"}, {"champion": "Santos Escobar"})


def test_an_event_keeps_the_part_after_its_colon():
    """plain() stops at a colon, so every TakeOver read as plain "NXT"."""
    assert event_key("NXT TakeOver: Brooklyn") == "nxttakeoverbrooklyn"
    assert event_key("NXT TakeOver: Brooklyn") in event_key("WWE NXT TakeOver: Brooklyn")
    assert event_key("NXT TakeOver: Brooklyn") not in event_key("WWE NXT TakeOver: Toronto")


def _team(people, won):
    return {"participants": people, "was_winner": won}


def test_the_change_goes_after_the_card_match_its_champion_won():
    """NXT Battleground 2023-05-28: Tiffany Stratton won the vacant women's
    title in match 5, written "vacant / NXT Women's Championship" with no
    TITLE CHANGE marker, so the walk never crowned her."""
    card = {"matches": [
        {"match_order": 3, "title_at_stake": None, "teams": [_team(["Ilja Dragunov"], True), _team(["Dijak"], False)]},
        {"match_order": 5, "title_at_stake": "vacant / NXT Women's Championship",
         "teams": [_team(["Tiffany Stratton"], True), _team(["Lyra Valkyria"], False)]},
    ]}
    assert won_on_card(card, {"champion": "Tiffany Stratton"})["match_order"] == 5
    assert won_on_card(card, {"champion": "Lyra Valkyria"}) is None


def test_two_wins_on_one_card_go_to_the_title_match():
    card = {"matches": [
        {"match_order": 1, "title_at_stake": None, "teams": [_team(["Wes Lee"], True), _team(["Axiom"], False)]},
        {"match_order": 4, "title_at_stake": "vacant / NXT North American Championship",
         "teams": [_team(["Wes Lee"], True), _team(["Carmelo Hayes"], False)]},
    ]}
    assert won_on_card(card, {"champion": "Wes Lee"})["match_order"] == 4


def test_wwe_s_recognized_start_date_is_read_from_the_note():
    """Wikipedia dates Asuka's 2020 Raw Women's reign from the Money in the
    Bank taping; its note gives the day WWE counts, the Raw she was handed
    the belt on."""
    note = ("the title belt was given to Asuka by Becky in exchange for the briefcase on Raw. "
            "WWE recognizes Asuka's reign as beginning on May 11, 2020 (A day after the Money in the "
            "Bank ladder match aired on tape delay)")
    assert recognized_start(note) == "2020-05-11"
    assert recognized_start("Banks won by countout.WWE recognizes Banks' reign as beginning on "
                            "July 27, 2020, when the match aired on tape delay.") == "2020-07-27"
    assert recognized_start("Defeated Iyo Sky to win the vacant title.") is None
