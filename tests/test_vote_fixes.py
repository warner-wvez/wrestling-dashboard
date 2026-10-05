"""Migration 0006 corrects results and slots missing matches into place.

A corrected result uses the same outcome labels as every other match, and a
match added mid-card renumbers the show so the M-numbers follow the card,
moving the show's watch links (keyed by match number) with their matches.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "m6", ROOT / "src" / "migrations" / "0006_apply_vote_fixes.py")
m6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m6)


def _teams():
    return [{"participants": ["Chris Jericho"], "was_winner": True, "match_outcome": "dq-win"},
            {"participants": ["The Big Show"], "was_winner": False, "match_outcome": "dq-loss"}]


def test_dq_result_is_flipped_with_the_usual_labels():
    # SmackDown 2001-01-25: Big Show beat Jericho by DQ; our card had it backwards.
    teams = _teams()
    m6.outcomes(teams, ["The Big Show"], "dq")
    assert [(t["was_winner"], t["match_outcome"]) for t in teams] == [
        (False, "dq-loss"), (True, "dq-win")]


def test_no_contest_has_no_winner():
    teams = _teams()
    m6.outcomes(teams, [], "no-contest")
    assert {(t["was_winner"], t["match_outcome"]) for t in teams} == {(None, "no-contest")}


def test_renumber_follows_card_order_and_reports_moves():
    matches = [{"match_order": 1}, {"match_order": None}, {"match_order": 2}, {"match_order": 3}]
    assert m6.renumber(matches) == {"2": "3", "3": "4"}
    assert [m["match_order"] for m in matches] == [1, 2, 3, 4]


def test_watch_links_move_with_their_match():
    entry = {"show": [], "matches": {"2": ["link to the old M02"], "11504": ["keyed by id"]}}
    m6.remap_media(entry, {"2": "3", "3": "4"})
    assert entry["matches"] == {"3": ["link to the old M02"], "11504": ["keyed by id"]}
