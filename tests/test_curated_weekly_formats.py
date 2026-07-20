"""The 2026 SmackDown Hotel editorial pass restructured old match lines, and the
parser read the new labels as wrestlers.

The curated pages now write battle royals as "<desc>: Winner</strong> Asuka.
<strong>Participants:</strong> Asuka, ...", chronicle 2-out-of-3 falls
("0-1: Bayley pins Valkyria"), tag survivors ("- Survivor: Rezar") and special
referees, and introduced fresh typos ("defeas", "#1 Conteder"). Unhandled, a
refresh shipped participants like "Asuka. Asuka" and "CM Punk defeas Sami Zayn",
and real wrestlers vanished behind the garbage.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.smackdownhotel import parse_descriptor, parse_match, parse_side  # noqa: E402


def names(match):
    return [p for t in match["teams"] for p in t["participants"]]


def test_winner_participants_battle_royal_splits_winner_from_field():
    li = ("<strong>#1 Conteder (WWE SmackDown Women's Championship) 15-Women "
          "Battle Royal: Winner</strong> Asuka. <strong>Participants:</strong> "
          "Asuka, Shayna Baszler, Naomi, Liv Morgan")
    m = parse_match(li, 1)
    assert m["teams"][0]["participants"] == ["Asuka"]
    assert m["teams"][0]["was_winner"] is True
    assert "Asuka. Asuka" not in names(m)
    losers = [p for t in m["teams"] if t["was_winner"] is False for p in t["participants"]]
    assert losers == ["Shayna Baszler", "Naomi", "Liv Morgan"]


def test_winner_participants_typo_contendership_is_not_a_belt_at_stake():
    li = ("<strong>#1 Conteder (WWE SmackDown Women's Championship) 15-Women "
          "Battle Royal: Winner</strong> Asuka. <strong>Participants:</strong> "
          "Asuka, Naomi")
    assert parse_match(li, 1)["title_at_stake"] is None


def test_special_referee_on_a_plain_li_is_not_the_descriptor_or_a_wrestler():
    li = "Liv Morgan defeats Ruby Riott (<strong>Special referee:</strong> Sarah Logan)"
    m = parse_match(li, 1)
    assert m["match_type"] is None
    assert names(m) == ["Liv Morgan", "Ruby Riott"]


def test_survivor_note_never_becomes_part_of_a_name():
    li = ("<strong>Elimination Match:</strong> Buddy Murphy &amp; AOP (Akam &amp; "
          "Rezar) defeat Kevin Owens &amp; The Viking Raiders (Erik &amp; Ivar) - "
          "<strong>Survivor:</strong> Rezar")
    m = parse_match(li, 1)
    assert names(m) == ["Buddy Murphy", "Akam", "Rezar", "Kevin Owens", "Erik", "Ivar"]


def test_falls_chronicle_stays_out_of_the_losers_name():
    li = ("<strong>2 out of 3 Falls Match:</strong> Lyra Valkyria defeats Bayley "
          "[2-1]. 0-1: Bayley pins Valkyria; 1-1: Valkyria pins Bayley; "
          "2-1: Valkyria pins Bayley")
    m = parse_match(li, 1)
    assert names(m) == ["Lyra Valkyria", "Bayley"]


def test_defeas_typo_still_splits_winner_from_loser():
    li = ("<strong>Undisputed WWE Championship:</strong> CM Punk defeas "
          "Sami Zayn (c) to win the title")
    m = parse_match(li, 1)
    assert m["result_method"] == "defeated"
    assert names(m) == ["CM Punk", "Sami Zayn"]
    assert m["teams"][1]["was_champion_entering"] is True


def test_turmoil_is_a_multiway_and_eliminations_do_not_shred_the_field():
    li = ("<strong>#1 Contenders (WWE Tag Team Championship) 5-Tag Team Turmoil "
          "Match:</strong> Damian Priest &amp; R-Truth defeat Motor City Machine "
          "Guns (Alex Shelley &amp; Chris Sabin), Fraxiom (Nathan Frazer &amp; "
          "Axiom), Los Garza (Angel &amp; Berto) and The Wyatt Sicks (Dexter "
          "Lumis &amp; Joe Gacy). Fraxiom eliminate Motor City Machine Guns; "
          "Los Garza eliminate Fraxiom and Wyatt Sicks; Priest &amp; R-Truth "
          "eliminate Los Garza")
    m = parse_match(li, 1)
    assert len(m["teams"]) == 5
    assert names(m) == ["Damian Priest", "R-Truth", "Alex Shelley", "Chris Sabin",
                        "Nathan Frazer", "Axiom", "Angel", "Berto",
                        "Dexter Lumis", "Joe Gacy"]


def test_two_labeled_teams_allied_on_one_side_both_expand():
    side = parse_side("The Street Profits (Angelo Dawkins & Montez Ford) & "
                      "The Viking Raiders (Erik & Ivar)")
    assert side["participants"] == ["Angelo Dawkins", "Montez Ford", "Erik", "Ivar"]


def test_conteder_typo_reads_as_contendership_in_the_descriptor():
    title, _, _ = parse_descriptor("#1 Conteder (WWE Raw Women's Championship) Battle Royal")
    assert title is None


def test_a_compound_team_name_is_a_label_not_an_ally_pair():
    for spelling in ("Fire & Desire", "Fire and Desire"):
        side = parse_side(f"{spelling} (Mandy Rose & Sonya Deville)")
        assert side["participants"] == ["Mandy Rose", "Sonya Deville"], spelling
        assert side["team_name"] == spelling


def test_comment_widget_lis_are_not_matches():
    for junk in ("2 Comments", "Login This site", "Facebook", "Google",
                 "Newest Best", "Popular", "Oldest", "1 Up 0 Down"):
        assert parse_match(junk, 1) is None, junk
    # A plain result line and a vs line still parse.
    assert parse_match("Rey Mysterio defeats Ethan Page", 1) is not None
    assert parse_match("Trick Williams vs. Carmelo Hayes", 1) is not None


def test_surname_lend_only_reaches_known_siblings():
    # Jimmy is a listed Uso, so he borrows the surname.
    assert parse_side("Jimmy & Jey Uso")["participants"] == ["Jimmy Uso", "Jey Uso"]
    # Paige is not a Bella; lending would fabricate a person.
    assert parse_side("Paige & Brie Bella")["participants"] == ["Paige", "Brie Bella"]
