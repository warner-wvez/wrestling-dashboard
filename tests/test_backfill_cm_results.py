"""The cached Cagematch results rows parse into dated events and full matches.

Fixture rows are verbatim lines from .firecrawl/cagematch-raw/results-*.md,
one event per table cell, matches separated by "<br>- ".
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backfill.cm_results import classify, parse_line, parse_rows  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "backfill"


def _rows():
    return (FIX / "cm-rows.md").read_text(encoding="utf-8").splitlines()


def _w(name, nr):
    return f"[{name}](https://www.cagematch.net/?id=2&nr={nr}&name={name.replace(' ', '+')})"


def test_classify_by_logo_then_type():
    assert classify("1_WWF Wrestling Challenge.gif", "WWF Wrestling Challenge #106", "TV-Show") == ("Challenge", "syndicated")
    assert classify("1_WWF RAW is WAR_19970310-20010910.gif", "WWF RAW is WAR #201", "TV-Show") == ("Raw", "main")
    assert classify("1_WWF In Your House.gif", "WWF In Your House #1", "Pay Per View") == ("PPV", "main")
    assert classify("1__1985-199503.gif", "WWF WrestleMania IV", "Pay Per View") == ("PPV", "main")
    assert classify("1_WWF The Main Event.gif", "WWF The Main Event", "TV-Show") == ("SNME", "main")
    assert classify("1__1985-199503.gif", "WWF Superstars #12", "TV-Show") == ("Superstars", "syndicated")
    assert classify("1__1985-199503.gif", "WWF @ Boston Garden", "House Show") == ("SKIP", None)
    assert classify("1__1985-199503.gif", "WWF TV Taping", "Event") == ("SKIP", None)
    assert classify("1__1985-199503.gif", "WWF on MSG Network", "TV-Show") == ("SKIP", None)
    assert classify("1__1985-199503.gif", "WWF All-Star Wrestling #12", "TV-Show") == ("SKIP", None)
    assert classify("1__1985-199503.gif", "WWF Royal Rumble 1988", "TV-Show") == ("PPV", "main")
    with pytest.raises(ValueError):
        classify("1__1985-199503.gif", "WWF Mystery Show", "TV-Show")


def test_simple_win_line_with_duration_and_worker_numbers():
    m = parse_line(f"{_w('Jake Roberts', 36)} defeats {_w('Mike Williams', 11799)} (1:37)", 1)
    assert m["duration_seconds"] == 97 and m["result_method"] == "defeated"
    assert [t["participants"] for t in m["teams"]] == [["Jake Roberts"], ["Mike Williams"]]
    assert [t["was_winner"] for t in m["teams"]] == [True, False]
    assert m["workers"] == {"Jake Roberts": 36, "Mike Williams": 11799}
    assert m["aired"] is True and m["title_at_stake"] is None and m["match_type"] is None
    assert m["raw_description"] == "Jake Roberts defeats Mike Williams (1:37)"


def test_title_line_with_champion_mark_manager_and_dq():
    line = ("[WWF Intercontinental Title](https://www.cagematch.net/?id=5&nr=2):"
            f"{_w('Brutus Beefcake', 100)} defeats {_w('The Honky Tonk Man', 101)} "
            f"(w/ {_w('Jimmy Hart', 102)} & {_w('Peggy Sue', 103)}) (c) by DQ (6:30)")
    m = parse_line(line, 3)
    assert m["title_at_stake"] == "WWF Intercontinental Title"
    assert m["result_method"] == "by DQ" and m["duration_seconds"] == 390
    loser = m["teams"][1]
    assert loser["was_champion_entering"] is True and loser["participants"] == ["The Honky Tonk Man"]
    assert loser["accompaniment"] == "Jimmy Hart & Peggy Sue"
    assert loser["match_outcome"] == "dq-loss" and m["teams"][0]["match_outcome"] == "dq-win"
    assert "Jimmy Hart" in m["workers"]


def test_title_change_marker_and_duration_are_kept():
    line = (f"[WWF Women's Title](https://www.cagematch.net/?id=5&nr=18):{_w('Sensational Sherri', 1050)} "
            f"defeats {_w('The Fabulous Moolah', 55)} (c) (12:32) - TITLE CHANGE !!!")
    m = parse_line(line, 1)
    assert m["duration_seconds"] == 752 and m["teams"][1]["was_champion_entering"] is True
    # The marker stays in the text: the corpus's reign walk crowns on it.
    assert "TITLE CHANGE" in m["raw_description"]


def test_match_type_prefix_tag_team_with_group_members():
    line = ("Tag Team:[Demolition](https://www.cagematch.net/?id=28&nr=23&name=Demolition) "
            f"( {_w('Ax', 201)} & {_w('Smash', 202)} ) defeat {_w('Jim Powers', 203)} & {_w('Paul Roma', 204)} (4:10)")
    m = parse_line(line, 2)
    assert m["match_type"] == "Tag Team"
    assert m["teams"][0]["team_name"] == "Demolition"
    assert m["teams"][0]["participants"] == ["Ax", "Smash"]
    assert m["teams"][1]["participants"] == ["Jim Powers", "Paul Roma"]
    assert m["teams"][1]["team_name"] == "Jim Powers & Paul Roma"


def test_time_limit_draw_has_no_winner():
    line = ("[WWF World Heavyweight Title](https://www.cagematch.net/?id=5&nr=1) Tournament First Round:"
            f"{_w('Jake Roberts', 36)} vs. {_w('Rick Rude', 630)} (w/ {_w('Bobby Heenan', 7)}) \\- Time Limit Draw (15:00)")
    m = parse_line(line, 7)
    assert m["match_type"] == "Tournament First Round" and m["title_at_stake"] == "WWF World Heavyweight Title"
    assert m["result_method"] == "Time Limit Draw" and m["duration_seconds"] == 900
    assert all(t["was_winner"] is None for t in m["teams"])
    assert all(t["match_outcome"] == "no-contest" for t in m["teams"])


def test_dark_prefix_marks_not_aired_and_keeps_type():
    m = parse_line(f"Dark Tag Team:{_w('A', 1)} & {_w('B', 2)} defeat {_w('C', 3)} & {_w('D', 4)} (3:00)", 1)
    assert m["aired"] is False and m["match_type"] == "Tag Team"
    plain = parse_line(f"Dark:{_w('A', 1)} defeats {_w('B', 2)} (3:00)", 1)
    assert plain["aired"] is False and plain["match_type"] is None


def test_multi_way_losers_each_get_a_side_and_unlinked_jobber_kept():
    m = parse_line(f"Battle Royal:{_w('Bad News Brown', 9)} defeats {_w('B. Brian Blair', 10)} and "
                   f"Antonio Chapotlin and {_w('Bret Hart', 11)}", 1)
    assert m["match_type"] == "Battle Royal"
    assert [t["participants"] for t in m["teams"]] == [["Bad News Brown"], ["B. Brian Blair"], ["Antonio Chapotlin"], ["Bret Hart"]]
    assert "Antonio Chapotlin" not in m["workers"]


def test_winner_only_battle_royal_is_one_winning_side():
    m = parse_line(f"Bunkhouse Battle Royal:Winner: {_w('Jim Duggan', 1107)}", 1)
    assert m["match_type"] == "Bunkhouse Battle Royal"
    assert len(m["teams"]) == 1 and m["teams"][0]["was_winner"] is True
    tag = parse_line(f"Tag Team Battle Royal:Winner: {_w('Nikolai Volkoff', 1)} & {_w('The Iron Sheik', 2)}", 1)
    assert tag["teams"][0]["participants"] == ["Nikolai Volkoff", "The Iron Sheik"]


def test_rows_become_events_with_tape_dates_and_shows_skipped():
    events, unparsed = parse_rows(_rows())
    kinds = {(e["show_type"], e["tape_date"] or e["air_date"]) for e in events}
    assert ("Challenge", "1988-08-24") in kinds
    assert ("PPV", "1988-03-27") in kinds
    assert ("SNME", "1985-10-31") in kinds
    assert not any(e["show_type"] in ("SKIP", None) for e in events)
    assert not any("House Show" in (e["title"] or "") or "TV Taping" in (e["title"] or "") for e in events)
    chal = next(e for e in events if e["show_type"] == "Challenge")
    assert chal["air_date"] == "1988-08-24" and chal["date_derivation"] == "cagematch-taping"
    assert chal["episode_number"] == 106 and chal["cagematch_nr"] == 16600
    assert chal["city"] == "Hartford" and chal["state_province"] == "Connecticut" and chal["country"] == "USA"
    assert chal["logo"] == "1_WWF Wrestling Challenge.gif"
    assert chal["match_count"] == len(chal["matches"]) >= 2
    assert chal["primary_source"] == "cagematch" and chal["family"] == "syndicated"
    assert all(isinstance(nr, int) for nr in chal["workers"].values())
    ppv = next(e for e in events if e["show_type"] == "PPV")
    assert ppv["tape_date"] is None and ppv["date_derivation"] == "live-broadcast"
    assert ppv["ppv_name"].startswith("WWF WrestleMania IV")
    assert unparsed == []


def test_smackdown_row_takes_the_thursday_air_night():
    events, _ = parse_rows(_rows())
    sd = next(e for e in events if e["show_type"] == "SmackDown")
    assert sd["tape_date"] == "1999-08-24" and sd["air_date"] == "1999-08-26"
    assert sd["date_derivation"] == "air-night-estimate"


def test_plain_text_team_with_members_and_alias_in_parens():
    line = (f"Survivor Series Elimination:The Dream Team ( {_w('Brutus Beefcake', 1)}, {_w('Dusty Rhodes', 2)} & "
            f"{_w('Tito Santana', 3)} ) defeat The Machines ( {_w('Big Machine', 4)} & Hulk Machine ( {_w('Hulk Hogan', 5)} ) ) (20:00)")
    m = parse_line(line, 1)
    assert m["teams"][0]["team_name"] == "The Dream Team"
    assert m["teams"][0]["participants"] == ["Brutus Beefcake", "Dusty Rhodes", "Tito Santana"]
    assert m["teams"][1]["participants"] == ["Big Machine", "Hulk Machine"]


def test_unknown_opponent_keeps_the_match_with_an_unnamed_side():
    m = parse_line(f"Dark:{_w('Gillberg', 9)} defeats ???", 1)
    assert m["teams"][0]["participants"] == ["Gillberg"] and m["teams"][1]["participants"] == []
    assert m["teams"][1]["team_name"] == "Unknown"
    assert parse_line("??? defeats ???", 1) is None


def test_duration_before_a_no_decision_tail_and_one_digit_seconds():
    m = parse_line(f"{_w('A', 1)} vs. {_w('B', 2)} (11:37) \\- Double DQ", 1)
    assert m["duration_seconds"] == 697 and m["result_method"] == "Double DQ"
    assert parse_line(f"{_w('A', 1)} defeats {_w('B', 2)} (1:0)", 1)["duration_seconds"] == 60
    bare = parse_line(f"{_w('Dave DiMegglio', 1)} vs. {_w('Duke Droese', 2)}", 1)
    assert bare["result_method"] == "No Result" and all(t["was_winner"] is None for t in bare["teams"])


def test_first_match_of_every_event_is_kept():
    events, _ = parse_rows(_rows())
    chal = next(e for e in events if e["show_type"] == "Challenge")
    assert chal["matches"][0]["teams"][0]["participants"] == ["Jake Roberts"]
    assert chal["matches"][0]["match_order"] == 1
