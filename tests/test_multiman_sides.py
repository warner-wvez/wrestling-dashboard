"""A three-way is three sides, not one man against two.

Cagematch writes a triple threat as "A defeats B and C". The parser splits on the
verb and everything right of it lands in one team, so the landing page billed its
first main event as "Steve Austin vs Kane & The Undertaker": a handicap match
that never happened.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import split_fused_multiman_sides  # noqa: E402


def _team(n, names, win=False, champ=False, label=None):
    return {"team_number": n, "team_name": label or " & ".join(names),
            "participants": list(names), "was_winner": win, "was_champion_entering": champ}


def _events(match_type, teams, raw="A defeats B and C (5:00)"):
    return {"1": {"id": 1, "air_date": "2001-01-04", "title": "Show", "matches": [
        {"match_order": 1, "match_type": match_type, "title_at_stake": None,
         "raw_description": raw, "teams": teams}]}}


def _teams_of(events):
    return events["1"]["matches"][0]["teams"]


def test_a_fused_triple_threat_becomes_three_sides():
    ev = _events("Triple Threat Match", [
        _team(1, ["Steve Austin"], win=True),
        _team(2, ["Kane", "The Undertaker"]),
    ], raw="Steve Austin defeated Kane & The Undertaker in a Triple Threat Match (5:33)")
    assert split_fused_multiman_sides(ev) == 1
    t = _teams_of(ev)
    assert [x["team_name"] for x in t] == ["Steve Austin", "Kane", "The Undertaker"]
    assert [x["was_winner"] for x in t] == [True, False, False]
    assert [x["team_number"] for x in t] == [1, 2, 3]


def test_a_named_tag_team_is_never_cut_into_singles():
    # "The Dudley Boyz" whose members are Bubba Ray and D-Von is a team, not two
    # fused sides, even when the side arithmetic says one-per-side.
    ev = _events("Triple Threat Match", [
        _team(1, ["Lance Storm"], win=True),
        _team(2, ["Bubba Ray Dudley", "D-Von Dudley"], label="The Dudley Boyz"),
    ])
    assert split_fused_multiman_sides(ev) == 0
    assert len(_teams_of(ev)) == 2


def test_the_belt_goes_to_the_one_the_result_marks():
    # "Curtis Axel defeats The Miz and Wade Barrett (c)": splitting naively would
    # hand the belt to BOTH halves and manufacture two champions.
    ev = _events("Triple Threat Match", [
        _team(1, ["Curtis Axel"], win=True),
        _team(2, ["The Miz", "Wade Barrett"], champ=True),
    ], raw="Curtis Axel (w/ Paul Heyman ) defeats The Miz and Wade Barrett (c) (10:35) - TITLE CHANGE !!!")
    assert split_fused_multiman_sides(ev) == 1
    champs = [x["team_name"] for x in _teams_of(ev) if x["was_champion_entering"]]
    assert champs == ["Wade Barrett"], f"the belt was Barrett's, not Miz's: {champs}"


def test_an_unattributable_belt_leaves_the_match_alone():
    # The (c) sits on a team name rather than a person, so which of the two holds
    # it cannot be read off the text. Better fused than wrong.
    ev = _events("Triple Threat Match", [
        _team(1, ["Lance Storm"], win=True),
        _team(2, ["Bubba Ray Dudley", "D-Von Dudley"], champ=True),
    ], raw="Lance Storm defeats The Dudley Boyz ( Bubba Ray Dudley & D-Von Dudley ) (c) (8:00)")
    assert split_fused_multiman_sides(ev) == 0


def test_a_fused_winner_is_left_alone():
    # Only one side wins a three-way, so a fused WINNER means the type or the
    # result is mislabelled; splitting would hand the match two winners.
    ev = _events("Triple Threat Match", [
        _team(1, ["Kane", "The Undertaker"], win=True),
        _team(2, ["Steve Austin"]),
    ])
    assert split_fused_multiman_sides(ev) == 0


def test_it_is_idempotent():
    ev = _events("Triple Threat Match", [
        _team(1, ["Steve Austin"], win=True),
        _team(2, ["Kane", "The Undertaker"]),
    ])
    assert split_fused_multiman_sides(ev) == 1
    assert split_fused_multiman_sides(ev) == 0, "a second pass must not re-split"


def test_a_ladder_matchs_losers_are_each_their_own_side():
    """Money in the Bank 2017: Carmella won the women's ladder match. The four
    she beat were stored as one side, so the card drew a four-on-one handicap
    match and, with spoilers off, the lone side gave the winner away."""
    ev = _events("Money In The Bank Ladder Match", [
        _team(1, ["Carmella"], win=True),
        _team(2, ["Becky Lynch", "Charlotte Flair", "Natalya", "Tamina"],
              label="Becky Lynch and Charlotte Flair and Natalya and Tamina"),
    ], raw="Carmella (w/ James Ellsworth ) defeats Becky Lynch and Charlotte Flair and Natalya and Tamina (8:10)")
    assert split_fused_multiman_sides(ev) == 1
    assert [x["team_name"] for x in _teams_of(ev)] == ["Carmella", "Becky Lynch", "Charlotte Flair",
                                                        "Natalya", "Tamina"]


def test_listed_tag_teams_keep_their_names_corners_and_the_belt():
    """WrestleMania X-Seven, TLC II: Edge and Christian beat the Dudleys, who
    held the titles, and the Hardys. One side held all four."""
    ev = _events("WWF World Tag Team Title Tables, Ladders & Chairs Match", [
        _team(1, ["Christian", "Edge"], win=True),
        _team(2, ["Bubba Ray Dudley", "D-Von Dudley", "Jeff Hardy", "Matt Hardy"], champ=True,
              label="The Dudley Boyz ( Bubba Ray Dudley & D-Von Dudley ) and The Hardy Boyz"),
    ], raw="Christian & Edge defeat The Dudley Boyz ( Bubba Ray Dudley & D-Von Dudley ) (c) (w/ Spike Dudley ) "
           "and The Hardy Boyz ( Jeff Hardy & Matt Hardy ) (w/ Lita ) (15:50) - TITLE CHANGE !!!")
    split_fused_multiman_sides(ev)
    t = _teams_of(ev)
    assert [x["participants"] for x in t] == [["Christian", "Edge"], ["Bubba Ray Dudley", "D-Von Dudley"],
                                             ["Jeff Hardy", "Matt Hardy"]]
    assert [x["was_champion_entering"] for x in t] == [False, True, False]
    assert [x.get("accompaniment") for x in t[1:]] == ["Spike Dudley", "Lita"]


def test_partners_joined_by_and_in_a_tag_match_stay_together():
    for match_type, raw in [
        ("Tag Team Match", "Kanyon & Shawn Stasiak defeated Diamond Dallas Page and Shane McMahon"),
        ("Eight Man Tag Team Match", "Kurt Angle & Shane McMahon & Booker T & Rhyno defeat Chris Jericho and "
                                     "The APA ( Bradshaw & Faarooq ) & The Rock"),
    ]:
        losers = ["Diamond Dallas Page", "Shane McMahon"] if "Page" in raw else \
            ["Chris Jericho", "Bradshaw", "Faarooq", "The Rock"]
        ev = _events(match_type, [_team(1, ["A", "B"], win=True), _team(2, losers, label=" and ".join(losers))],
                     raw=raw)
        assert split_fused_multiman_sides(ev) == 0, match_type


def test_a_side_the_text_does_not_name_exactly_is_left_alone():
    ev = _events("Money In The Bank Ladder Match", [
        _team(1, ["Carmella"], win=True),
        _team(2, ["Becky Lynch", "Natalya"], label="Becky Lynch and Natalya"),
    ], raw="Carmella defeats Becky Lynch and Charlotte Flair and Natalya")
    assert split_fused_multiman_sides(ev) == 0
