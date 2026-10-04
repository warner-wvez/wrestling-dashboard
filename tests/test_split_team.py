"""_split_team keeps everyone on a side, not just the group in parentheses.

The historical parser read "Billy Gunn & The APA ( Bradshaw & Faarooq )" as one
stable label with two members and threw Billy Gunn away, which left the landing
show (Raw 2001-01-01) rendering a six-man tag as three-on-two. The same regex
read a referee note as a member list, so on SmackDown 2001-01-18 the whole team
of Kurt Angle, Rikishi and Kane became Triple H, the special guest referee.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fandom_scraper import _split_team  # noqa: E402


# ---- the bug: a wrestler named before the group was dropped ----------------

def test_partner_named_before_a_stable_is_kept():
    # Raw 2001-01-01, M02
    assert _split_team("Billy Gunn & The APA ( Bradshaw & Faarooq )") == (
        "Billy Gunn & The APA", ["Billy Gunn", "Bradshaw", "Faarooq"])


def test_valet_named_before_a_tag_team_is_kept():
    # SmackDown 2001-01-18, M02, both sides
    assert _split_team("Jacqueline & The APA ( Bradshaw & Faarooq )")[1] == [
        "Jacqueline", "Bradshaw", "Faarooq"]
    assert _split_team("Lita & The Hardy Boyz ( Jeff Hardy & Matt Hardy )")[1] == [
        "Lita", "Jeff Hardy", "Matt Hardy"]


def test_several_names_before_a_stable_are_all_kept():
    assert _split_team("The Rock , Kane & The Dudley Boyz ( Bubba Ray Dudley & D-Von Dudley )")[1] == [
        "The Rock", "Kane", "Bubba Ray Dudley", "D-Von Dudley"]


def test_nested_stables_flatten_to_people():
    assert _split_team("Evolution ( Batista & Ric Flair & Triple H )")[1] == [
        "Batista", "Ric Flair", "Triple H"]
    assert _split_team("Edge & The Brood ( Christian & Gangrel )")[1] == [
        "Edge", "Christian", "Gangrel"]


# ---- the bug: a referee note became the team -------------------------------

def test_special_guest_referee_is_not_a_participant():
    # SmackDown 2001-01-18, M05
    assert _split_team("Kurt Angle , Rikishi & Kane (Special Guest Referee: Triple H )") == (
        "Kurt Angle , Rikishi & Kane", ["Kurt Angle", "Rikishi", "Kane"])


def test_other_officials_are_not_participants():
    assert _split_team("The Rock (Special Guest Enforcer: Mr. T )")[1] == ["The Rock"]
    assert _split_team("Edge & Christian (Special Guest Timekeeper: Shane McMahon )")[1] == [
        "Edge", "Christian"]


# ---- shapes that were already right must not move --------------------------

def test_stable_alone_is_unchanged():
    assert _split_team("The APA ( Bradshaw & Faarooq )") == ("The APA", ["Bradshaw", "Faarooq"])


def test_gimmick_with_one_name_in_parens_is_unchanged():
    assert _split_team("The Hurricane ( Shane Helms )") == ("The Hurricane", ["Shane Helms"])


def test_two_stables_side_by_side_keep_all_four():
    assert _split_team(
        "The Hardy Boyz ( Jeff Hardy & Matt Hardy ) & The Dudley Boyz ( Bubba Ray Dudley & D-Von Dudley )"
    )[1] == ["Jeff Hardy", "Matt Hardy", "Bubba Ray Dudley", "D-Von Dudley"]


def test_plain_teams_are_unchanged():
    assert _split_team("Christian , Edge & Kurt Angle") == (
        "Christian , Edge & Kurt Angle", ["Christian", "Edge", "Kurt Angle"])
    assert _split_team("Val Venis") == ("Val Venis", ["Val Venis"])


def test_referee_note_that_prefixes_the_name_still_yields_the_wrestler():
    # SmackDown 2002-10-17: the source put the match type and referee before
    # the name. Removing the note there left "Singles Match : Jamie Noble".
    assert _split_team("Singles Match (Special Referee: Tajiri ): Jamie Noble")[1] == [
        "Jamie Noble"]


def test_tag_team_with_and_in_its_name_is_one_team():
    # 2019 Raw: "Fire And Desire" is the team, not a wrestler called Fire.
    assert _split_team("Fire And Desire ( Mandy Rose & Sonya Deville )") == (
        "Fire And Desire", ["Mandy Rose", "Sonya Deville"])


def test_lowercase_and_still_separates_people():
    # Raw 2001-09-04
    assert _split_team("Chris Jericho and The APA ( Bradshaw & Faarooq ) & The Rock")[1] == [
        "Chris Jericho", "Bradshaw", "Faarooq", "The Rock"]


def test_match_type_prefix_is_not_part_of_the_first_name():
    # Raw 2001-06-21: the source opens the result with the match type.
    assert _split_team("Six Man Tag Team Match: Kane & The Hardy Boyz ( Jeff Hardy & Matt Hardy )")[1] == [
        "Kane", "Jeff Hardy", "Matt Hardy"]
