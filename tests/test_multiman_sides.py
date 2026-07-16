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
