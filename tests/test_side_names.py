"""Side names keep the side, not the result the source wrote after it.

Cases are real names from the corpus (migration 0018)."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "m18", Path(__file__).resolve().parent.parent / "src" / "migrations" / "0018_clean_side_names.py")
m18 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m18)


def test_result_tails_come_off():
    cases = {
        "The Big Show by Count Out": "The Big Show",
        "The Usos ( Jey Uso & Jimmy Uso ) by Count Out": "The Usos ( Jey Uso & Jimmy Uso )",
        "Christian to retain the WWE European Championship": "Christian",
        "Triple H - TITLE CHANGE !!!": "Triple H",
        "Eddie Guerrero & Chavo Guerrero Jr. via disqualification when Kurt Angle interfered":
            "Eddie Guerrero & Chavo Guerrero Jr.",
        "Matt Hardy with a roll up as Matt was distracted by Kane 's pyro": "Matt Hardy",
        "Bianca Belair & no contest": "Bianca Belair",
        "Asuka & Charlotte Flair (10:324": "Asuka & Charlotte Flair",
        "Chris Jericho by Matchabbruch": "Chris Jericho",
    }
    for raw, want in cases.items():
        assert m18.clean(raw) == want, raw


def test_a_champion_label_in_front_comes_off():
    assert m18.clean("WWE IC Champion Chris Benoit with the Rock Bottom") == "Chris Benoit"
    assert m18.clean("WWE Cruiserweight Champion Jamie Noble & Tajiri when Moore defeated Noble") == \
        "Jamie Noble & Tajiri"


def test_real_team_names_are_left_alone():
    for name in ["The Dudley Boyz", "Team Rhodes Scholars ( Cody Rhodes & Damien Sandow )",
                 "Too Cool", "Rated-RKO", "Hardcore Holly & The Big Valbowski", "The Brothers Of Destruction"]:
        assert m18.clean(name) == name


def test_a_cut_that_loses_a_wrestler_is_not_kept():
    assert not m18.names_everyone("Jamie Noble", ["Jamie Noble", "Tajiri"])
    assert m18.names_everyone("Jamie Noble & Tajiri", ["Jamie Noble", "Tajiri"])
