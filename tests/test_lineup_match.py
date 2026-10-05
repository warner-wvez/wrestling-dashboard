"""The lineup matcher only calls a fix automatic when both sources agree.

Each test is a rule that a hand check of the 2001-2013 run proved necessary:
a real Hell in a Cell match was nearly greyed out, 16 of 19 first-draft
additions paired different matches, "Stephanie McMahon" landed on "Shane
McMahon", and a battle royal "aired on Heat" because it shared one entrant.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lineup-check"))

import lineup_match  # noqa: E402
from lineup_match import best_match, compare_show, match_strength  # noqa: E402


def _team(n, people, won=False):
    return {"team_number": n, "participants": people, "was_winner": won}


def _match(mid, raw, teams, match_type="Singles Match"):
    return {"id": mid, "match_order": mid, "match_type": match_type,
            "raw_description": raw, "teams": teams}


def _line(winners, losers, result="win", kind="match"):
    return {"kind": kind, "winners": winners, "losers": losers, "result": result,
            "sub_for": [], "notes": [], "line": " / ".join(winners + losers)}


def _ev(matches):
    return {"id": 1, "air_date": "2002-10-20", "show_type": "PPV", "title": "No Mercy",
            "matches": matches}


def _classes(rows):
    return sorted((r["class"], r.get("name", "")) for r in rows)


def test_dark_label_and_absent_from_his_list_is_not_aired():
    ev = _ev([_match(1, "Rudy Rude defeats Larry Destiny",
                     [_team(1, ["Rudy Rude"], True), _team(2, ["Larry Destiny"])], "Dark Match"),
              _match(2, "Kane defeats The Rock", [_team(1, ["Kane"], True), _team(2, ["The Rock"])])])
    rows = compare_show(ev, [_line(["Kane"], ["the Rock"])], {})
    assert _classes(rows) == [("not_aired", "")]


def test_unlabelled_match_absent_from_his_list_goes_to_review():
    # No Mercy 2002: Lesnar vs Undertaker aired; only a lost line hid it.
    ev = _ev([_match(1, "Brock Lesnar defeats The Undertaker (27:15)",
                     [_team(1, ["Brock Lesnar"], True), _team(2, ["The Undertaker"])])])
    assert _classes(compare_show(ev, [], {})) == [("unpaired", "")]


def test_an_unreadable_line_blocks_not_aired():
    ev = _ev([_match(1, "Rudy Rude defeats Larry Destiny",
                     [_team(1, ["Rudy Rude"], True), _team(2, ["Larry Destiny"])], "Dark Match")])
    assert _classes(compare_show(ev, [], {}, unreadable=1)) == [("unpaired", "")]


def test_escort_credit_is_not_our_source_naming_a_wrestler():
    # SmackDown 2003-05-01: Palumbo escorted Stamboli on our card, wrestled on his.
    ev = _ev([_match(1, "Chris Benoit vs. Johnny Stamboli (w/ Chuck Palumbo & Nunzio ) - No Contest",
                     [_team(1, ["Chris Benoit"]), _team(2, ["Johnny Stamboli"])])])
    rows = compare_show(ev, [_line(["Chuck Palumbo", "Johnny Stamboli"], ["Chris Benoit", "Rhyno"])], {})
    assert ("add_wrestler", "Chuck Palumbo") not in _classes(rows)


def test_name_our_text_lists_but_our_lineup_lost_is_added():
    # Raw 2001-07-09: our own text lists Rhyno on Team ECW, the stored side lost him.
    ev = _ev([_match(1, "Team ECW ( Raven , Rhyno ) defeat Team WWF ( Kane , Test )",
                     [_team(1, ["Raven"], True), _team(2, ["Kane", "Test"])])])
    rows = compare_show(ev, [_line(["Raven", "Rhyno"], ["Kane", "Test"])], {})
    assert ("add_wrestler", "Rhyno") in _classes(rows)


def test_someone_already_on_the_other_side_is_never_added():
    ev = _ev([_match(1, "Chris Jericho vs. Rhyno - No Contest",
                     [_team(1, ["Chris Jericho"]), _team(2, ["Rhyno"])])])
    rows = compare_show(ev, [_line(["Chris Jericho", "Rhyno"], ["Christian", "Tyson Tomko"])], {})
    assert not [r for r in rows if r["class"] == "add_wrestler"]


def test_no_one_in_common_on_a_side_is_a_different_opponent():
    ev = _ev([_match(1, "Kane (c) defeats Kurt Angle",
                     [_team(1, ["Kane"], True), _team(2, ["Kurt Angle"])])])
    rows = compare_show(ev, [_line(["Kane"], ["the Big Show"])], {})
    assert ("different_opponent", "the Big Show") in _classes(rows)


def test_strongest_spelling_wins():
    names = ["Shane McMahon", "Stephanie McMahon-Helmsley"]
    assert best_match("Stephanie McMahon", names) == "Stephanie McMahon-Helmsley"
    assert match_strength("Sho Funaki", "Funaki") == 2
    assert match_strength("K-Kwick", "K-Kwik") == 1
    assert best_match("Bull Buchanon", ["Bull Buchanan", "Val Venis"]) == "Bull Buchanan"


def test_initials_and_alias_map():
    assert match_strength("MVP", "Montel Vontavious Porter") == 3
    lineup_match.CANON = {"King Booker": "Booker T"}
    try:
        assert match_strength("Booker T", "King Booker") == 3
    finally:
        lineup_match.CANON = {}


def test_heat_pairing_needs_overlap_both_ways():
    rumble = _match(1, "Bradshaw defeats twenty others", [
        _team(1, ["Bradshaw"], True), _team(2, ["Kanyon", "Ultimo Dragon", "A", "B", "C", "D"])],
        "Battle Royal")
    ev = _ev([rumble])
    rows = compare_show(ev, [], {}, heat_lines=[_line(["Ultimo Dragon"], ["Kanyon"])])
    assert "aired_heat" not in [r["class"] for r in rows]


def test_fused_multi_team_side_is_never_added_to():
    # Night of Champions 2010 tag turmoil: four teams fused into one losing side.
    ev = _ev([_match(1, "Cody Rhodes & Drew McIntyre defeat Evan Bourne & Mark Henry and "
                        "Santino Marella & Vladimir Kozlov",
                     [_team(1, ["Cody Rhodes", "Drew McIntyre"], True), _team(2, ["Santino Marella"])])])
    rows = compare_show(ev, [_line(["Cody Rhodes", "Drew McIntyre"],
                                   ["Evan Bourne", "Mark Henry", "Santino Marella", "Vladimir Kozlov"])], {})
    assert not [r for r in rows if r["class"] == "add_wrestler"]
