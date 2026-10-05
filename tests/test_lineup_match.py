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


def test_one_word_billing_is_never_added_as_a_second_person():
    # Cawthon writes "Eve" where our card has "Eve Torres" (about 60 matches).
    ev = _ev([_match(1, "Eve Torres defeats Layla (3:10)",
                     [_team(1, ["Eve Torres"], True), _team(2, ["Layla"])])])
    assert not [r for r in compare_show(ev, [_line(["Eve"], ["Layla"])], {})
                if r["class"] in ("add_wrestler", "cawthon_only_name", "extra_name")]


def test_gimmick_label_in_our_text_is_not_a_missing_wrestler():
    ev = _ev([_match(1, "Calgary Kid ( The Miz ) defeats Eugene (1:21)",
                     [_team(1, ["The Miz"], True), _team(2, ["Eugene"])])])
    rows = compare_show(ev, [_line(["The Calgary Kid"], ["Eugene"])], {})
    assert not [r for r in rows if r["class"] == "add_wrestler"]


def test_junk_on_our_side_is_replaced_by_the_real_wrestlers():
    # SmackDown 2001-03-15: our X-Factor side was the junk "The X".
    ev = _ev([_match(1, "Billy Gunn & The Hardy Boyz ( Jeff Hardy & Matt Hardy ) vs. The X-Factor "
                        "( Albert , Justin Credible & X-Pac ) - Double DQ (5:05)",
                     [_team(1, ["Billy Gunn", "Jeff Hardy", "Matt Hardy"]), _team(2, ["The X"])])])
    rows = compare_show(ev, [_line(["Billy Gunn", "Matt Hardy", "Jeff Hardy"],
                                   ["X-Pac", "Justin Credible", "Albert"], result="double disqualification")], {})
    assert sorted(r["name"] for r in rows if r["class"] == "add_wrestler") == [
        "Albert", "Justin Credible", "X-Pac"]


def _sd(matches):
    return {"id": 2, "air_date": "2006-06-16", "show_type": "SmackDown", "title": "SmackDown",
            "matches": matches}


def test_attack_before_the_bell_does_not_steal_the_real_bout():
    # SmackDown 2006-06-16: Cawthon logs Lashley vs Booker as a no contest
    # when Finlay and Regal jumped Lashley on his way out, then the real
    # match later. The no contest came first on his list and used to pair
    # with our win, reporting a wrong result and a "second bout".
    ev = _sd([_match(1, "Bobby Lashley defeats King Booker (16:02)",
                     [_team(1, ["Bobby Lashley"], True), _team(2, ["King Booker"])])])
    lines = [_line(["Bobby Lashley"], ["King Booker"], result="no contest"),
             _line(["Bobby Lashley"], ["King Booker"])]
    assert _classes(compare_show(ev, lines, {})) == []


def test_unplaceable_name_does_not_steal_the_pairing():
    # Raw 2011-08-08: "Rey Mysterio Jr. fought Mike Mizanin to a no contest"
    # (Rey not on our card) scored as high as Miz vs Kofi once Rey dropped out.
    ev = _sd([_match(1, "The Miz defeats Kofi Kingston (10:42)",
                     [_team(1, ["The Miz"], True), _team(2, ["Kofi Kingston"])])])
    lines = [_line(["Rey Mysterio Jr."], ["Mike Mizanin"], result="no contest"),
             _line(["Mike Mizanin"], ["Kofi Kingston"])]
    lineup_match.CANON = {"Mike Mizanin": "The Miz"}
    try:
        assert _classes(compare_show(ev, lines, {})) == [("missing_match", "")]
    finally:
        lineup_match.CANON = {}


def test_title_changing_hands_twice_is_still_a_second_bout():
    # Raw 2001-01-22: Al Snow won the Hardcore title from Raven, then Raven
    # took it back the same night. Both are real; a person adds the second.
    ev = _sd([_match(1, "Al Snow defeats Raven (c) (3:35)",
                     [_team(1, ["Al Snow"], True), _team(2, ["Raven"])])])
    lines = [_line(["Al Snow"], ["Raven"]), _line(["Raven"], ["Al Snow"])]
    assert _classes(compare_show(ev, lines, {})) == [("possible_second_bout", "")]


def test_a_ruled_row_leaves_the_review_list(tmp_path):
    import lineup_check
    f = tmp_path / "rulings.csv"
    f.write_text("class,event_id,match_id,cawthon,ruling,why\n"
                 "possible_second_bout,782,,Matt Hardy defeated WWE US Champion MVP,no change,arm wrestling\n")
    rulings = lineup_check.load_rulings(f)
    row = {"class": "possible_second_bout", "event_id": 782, "match_id": None,
           "cawthon": "Matt Hardy defeated WWE US Champion MVP via count-out ..."}
    other = {**row, "event_id": 783}
    assert lineup_check.to_review([row, other], rulings) == [other]


def test_dark_rematch_never_takes_a_televised_line():
    # SmackDown 2009-08-07: Hardy beat Punk on TV and again after the show.
    # Cawthon also logs a no contest earlier that night; it paired with the
    # dark rematch, which then escaped the dark rule.
    ev = _sd([_match(6, "Jeff Hardy (c) defeats CM Punk (11:10)",
                     [_team(1, ["Jeff Hardy"], True), _team(2, ["CM Punk"])]),
              _match(7, "Jeff Hardy (c) defeats CM Punk",
                     [_team(1, ["Jeff Hardy"], True), _team(2, ["CM Punk"])], "Dark Match")])
    lines = [_line(["Jeff Hardy"], ["CM Punk"], result="no contest"),
             _line(["Jeff Hardy"], ["CM Punk"])]
    rows = compare_show(ev, lines, {})
    assert _classes(rows) == [("not_aired", "")] and rows[0]["match_id"] == 7


def test_dark_main_event_never_pairs_with_a_different_match():
    # Raw 2008-12-15: our dark Cena vs Jericho took Cawthon's line for
    # Jericho refusing to face Jim Duggan, a man not on our card.
    ev = _sd([_match(7, "John Cena (c) defeats Chris Jericho",
                     [_team(1, ["John Cena"], True), _team(2, ["Chris Jericho"])], "Dark Match")])
    lines = [_line(["Chris Jericho"], ["Jim Duggan"], result="no contest")]
    assert _classes(compare_show(ev, lines, {})) == [("missing_match", ""), ("not_aired", "")]


def test_his_not_televised_note_is_his_dark_label():
    # SmackDown 2004-02-05: "Ernest Miller pinned Tajiri ... (match not televised)".
    ev = _sd([_match(2, "Ernest Miller defeats Tajiri",
                     [_team(1, ["Ernest Miller"], True), _team(2, ["Tajiri"])], "Dark Match"),
              _match(3, "Kane defeats Simon Dean (2:30)",
                     [_team(1, ["Kane"], True), _team(2, ["Simon Dean"])])])
    miller, kane = _line(["Ernest Miller"], ["Tajiri"]), _line(["Kane"], ["Simon Dean"])
    miller["line"] += " (match not televised)"
    kane["line"] += " (this bout took place during the commercial break and was not mentioned on TV)"
    assert _classes(compare_show(ev, [miller, kane], {})) == [("cawthon_says_dark", ""), ("not_aired", "")]


def test_a_contest_is_never_added_automatically():
    # SmackDown 2013-05-03: Cawthon and SmackDown Hotel both list Mark Henry
    # beating Sheamus "in an arm wrestling contest". Not a match.
    ev = _sd([_match(8, "Randy Orton & Sheamus defeat Mark Henry & The Big Show",
                     [_team(1, ["Randy Orton", "Sheamus"], True),
                      _team(2, ["Mark Henry", "The Big Show"])], "Dark Tag Team Match")])
    line = _line(["Mark Henry"], ["Sheamus"])
    line["line"] = "Mark Henry defeated Sheamus in an arm wrestling contest"
    sdh = [{"teams": [{"participants": ["Mark Henry"], "was_winner": True},
                      {"participants": ["Sheamus"], "was_winner": False}]}]
    rows = compare_show(ev, [line], {}, sdh_matches=sdh)
    assert [(r["class"], r["vote"]) for r in rows if r["class"] == "missing_match"] == [
        ("missing_match", "add_match")]
    assert lineup_match.CONTEST.search("fought Raven to a no contest") is None
