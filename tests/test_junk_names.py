"""clean_junk_participants keeps only people on a card, spelled one way.

Every case below is a real participant found on a shipped card (counts from
the corpus, 2026-10-05): results and prose the parsers glued to a name, words
that are not people at all, and the same person spelled two ways.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import clean_junk_participants, clean_participant  # noqa: E402


def test_result_tails_come_off_the_name():
    assert clean_participant("Jeff Hardy by TKO") == "Jeff Hardy"
    assert clean_participant("Batista by forfeit") == "Batista"
    assert clean_participant("Daniel Bryan by Reverse Decision") == "Daniel Bryan"
    assert clean_participant("Isla Dawn    to unify the titles") == "Isla Dawn"
    assert clean_participant("The Rock Non") == "The Rock"


def test_stray_punctuation_comes_off():
    assert clean_participant(": Solo Sikoa") == "Solo Sikoa"
    assert clean_participant("Johnny Gargano)") == "Johnny Gargano"


def test_words_that_are_not_people_are_dropped():
    for junk in ("countout", "double countout", "no contest", "and", "No Contest"):
        assert clean_participant(junk) is None


def test_a_real_name_with_by_in_it_survives():
    # Ash by Elegance is a wrestler, not a result.
    assert clean_participant("Ash by Elegance") == "Ash by Elegance"


def test_typo_twins_merge_to_one_spelling():
    assert clean_participant("The Good Father") == "The Goodfather"
    assert clean_participant("Grand Master Sexay") == "Grandmaster Sexay"
    assert clean_participant("Lance Anoai") == "Lance Anoa'i"
    assert clean_participant("Walter") == "WALTER"
    assert clean_participant("Je’Von Evans") == "Je'Von Evans"


def test_era_billing_is_left_alone():
    for billed in ("Big Show", "The Big Show", "A-Train", "The A-Train", "Road Dogg", "a jobber"):
        assert clean_participant(billed) == billed


def test_cleanup_runs_over_every_team_in_place():
    events = {"1": {"matches": [{"teams": [
        {"participants": ["Jeff Hardy by TKO", "and"]},
        {"participants": ["The Good Father", "Val Venis"]},
    ]}]}}
    assert clean_junk_participants(events) == 3
    teams = events["1"]["matches"][0]["teams"]
    assert teams[0]["participants"] == ["Jeff Hardy"]
    assert teams[1]["participants"] == ["The Goodfather", "Val Venis"]
    assert clean_junk_participants(events) == 0
