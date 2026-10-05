"""Migration 0007 builds recovered shows in the corpus's own conventions.

A show it moves keeps its taping date but takes its real episode number, and a
show it adds must join existing title lineages (Wikipedia's "WWE Championship"
is the corpus's "WWE Heavyweight Title") and carry champion flags instead of
SmackDown Hotel's "Layla ©" marks inside names.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "m7", ROOT / "src" / "migrations" / "0007_fix_missing_and_misdated_shows.py")
m7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m7)


def test_place_names_follow_the_corpus():
    assert m7.place("Austin, TX") == ("Austin", "Texas", "USA")
    assert m7.place("Manchester, England") == ("Manchester", None, "England")


def test_retitle_swaps_only_the_number():
    assert m7.retitle("WWE Monday Night RAW #767", 768) == "WWE Monday Night RAW #768"
    assert m7.retitle("WWE Monday Night RAW #944 - RAW Roulette 2011", 945) == \
        "WWE Monday Night RAW #945 - RAW Roulette 2011"


def test_title_names_join_existing_lineages():
    assert m7.corpus_titles("WWE Championship") == "WWE Heavyweight Title"
    assert m7.corpus_titles("ECW Championship / Night of Champions") == "ECW World Heavyweight Title"
    assert m7.corpus_titles(None) is None


def test_champion_mark_becomes_a_flag():
    matches = [{"title_at_stake": "Unified WWE Divas Championship", "teams": [
        {"participants": ["Layla ©"], "team_name": "Layla ©"},
        {"participants": ["Melina"], "team_name": "Melina"}]}]
    m7.champion_marks(matches)
    a, b = matches[0]["teams"]
    assert (a["participants"], a["was_champion_entering"], a["team_name"]) == (["Layla"], True, "Layla")
    assert "was_champion_entering" not in b
    assert matches[0]["title_at_stake"] == "Unified WWE Divas Title"


def test_2001_world_titles_join_their_lineages():
    # Rebellion 2001 (Wikipedia) names belts the corpus calls otherwise.
    assert m7.corpus_titles("WWF Championship") == "WWF World Heavyweight Title"
    assert m7.corpus_titles("WCW Tag Team Championship") == "WCW World Tag Team Title"
