"""Cawthon's results pages parse into episodes, PPVs and match sides.

Fixtures are verbatim excerpts of thehistoryofwwe.com pages, each chosen for a
shape that broke an earlier version: a taped header, a titled air-date line
("Smackdown! Xtreme"), a page that contradicts its own date (Raw 2009), a
header with no colon after it, and a PPV whose list is interrupted by an
italic note (No Mercy 02).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lineup-check"))

from cawthon_parse import (looks_like_match, parse_match_line,  # noqa: E402
                           parse_ppv_page, parse_show_page, split_side)

FIX = Path(__file__).resolve().parent / "fixtures" / "cawthon"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_taped_header_gives_tape_and_air_dates():
    eps = parse_show_page(_read("raw-2001-jan.html"))
    assert [e["air_date"] for e in eps] == ["2001-01-01", "2001-01-08", "2001-01-15"]
    assert (eps[0]["tape_date"], eps[0]["city"], eps[0]["venue"]) == (
        "2000-12-29", "Austin, TX", "Frank Erwin Center")
    assert len(eps[1]["lines"]) == 6


def test_titled_air_date_line_is_still_an_episode():
    eps = parse_show_page(_read("smackdown-2001-xtreme.html"))
    assert [(e["tape_date"], e["air_date"]) for e in eps] == [("2001-01-30", "2001-02-01")]


def test_page_that_contradicts_its_own_date_is_flagged():
    eps = parse_show_page(_read("raw-2009-summer.html"))
    conflicts = [(e["header_date"], e["air_date"]) for e in eps if e["date_conflict"]]
    assert conflicts == [("2009-06-29", "2009-07-06")]


def test_header_without_a_colon_does_not_swallow_the_next_week():
    eps = parse_show_page(_read("raw-2009-november.html"))
    assert [e["air_date"] for e in eps] == ["2009-10-26", "2009-11-02", "2009-11-09"]


def test_rumble_ppv_has_heat_and_ppv_sections():
    ppv = parse_ppv_page(_read("results-2001-rumble.html"))
    rr = ppv["2001-01-21"]
    assert rr["title"].startswith("Royal Rumble 01")
    assert len(rr["heat"]) == 1 and len(rr["ppv"]) == 6


def test_italic_note_mid_show_does_not_end_the_ppv_list():
    nm = parse_ppv_page(_read("results-2002-nomercy.html"))["2002-10-20"]
    assert len(nm["ppv"]) == 8


def test_defeated_line_with_escorts_titles_and_finish():
    p = parse_match_line(
        "The Acolytes (w/ Jackie) & Billy Gunn defeated the Goodfather, Val Venis, & Bull "
        "Buchanon (w/ Steven Richards & WWF Women's Champion Ivory) when Gunn pinned Venis")
    assert (p["winners"], p["losers"], p["result"]) == (
        ["The Acolytes", "Billy Gunn"], ["the Goodfather", "Val Venis", "Bull Buchanon"], "win")


def test_no_contest_and_substitution_note():
    p = parse_match_line(
        "Steve Austin fought WWF World Champion Kurt Angle to a no contest at around 12:20 when "
        "Triple H came ringside")
    assert (p["winners"], p["losers"], p["result"]) == (["Steve Austin"], ["Kurt Angle"], "no contest")
    s = parse_match_line(
        "WWF Tag Team Champions the Dudley Boyz defeated Sho Funaki & Taka Michinoku (sub. for "
        "Edge & Christian) after hitting the 3D")
    assert s["winners"] == ["the Dudley Boyz"] and s["sub_for"] == ["Edge & Christian"]


def test_three_way_no_contest_is_one_list():
    p = parse_match_line(
        "Naomi (w/ Cameron & JoJo), Brie Bella (w/ Nikki Bella), and Natalya Neidhart fought to "
        "a no contest at 1:47 when AJ interfered; after the contest, the other women beat AJ down")
    assert p["all_sides"] and p["winners"] == ["Naomi", "Brie Bella", "Natalya Neidhart"]


def test_match_type_prefix_and_mystery_note():
    p = parse_match_line("Gauntlet Match : Mark Henry (mystery opponent) pinned WWE World "
                         "Champion Randy Orton in a non-title match at 3:20")
    assert (p["winners"], p["losers"]) == (["Mark Henry"], ["Randy Orton"])
    assert p["notes"] == ["mystery opponent"]


def test_title_billing_never_eats_a_partner():
    assert split_side("Steve Austin & WWF World Champion the Rock (w/ Debra)") == [
        "Steve Austin", "the Rock"]
    assert split_side("WWF Tag Team Champions - WWF World Champion Steve Austin & WWF IC "
                      "Champion Triple H") == ["Steve Austin", "Triple H"]


def test_non_match_lines():
    assert parse_match_line("Featured a 3-hour special titled Best of the WWF 2001") is None
    assert looks_like_match("Kane pinned the Rock with the chokeslam")
    assert not looks_like_match("Copyright 2026 The History of WWE.")


def test_generational_suffix_stays_on_the_name():
    assert split_side("Chavo Guerrero, Sr. & Eddie Guerrero") == ["Chavo Guerrero Sr.", "Eddie Guerrero"]


def test_ppv_list_ends_at_the_next_nights_bold_header():
    # WrestleMania X-Seven is followed by "WWF @ Ft. Worth, TX - April 2,
    # 2001", one dash only; its Raw card once ran on into the PPV list.
    wm = parse_ppv_page(_read("results-2001-wm17.html"))["2001-04-01"]
    assert len(wm["ppv"]) == 11
    assert not any("Dave Taylor" in line or "steel cage" in line for line in wm["ppv"] + wm["heat"])


def test_header_whose_note_has_no_date_is_its_own_episode():
    # Raw 11/3/08's italic line is a note ("3-hour episode celebrating ...").
    eps = parse_show_page(_read("raw-2008-november.html"))
    assert [e["air_date"] for e in eps] == ["2008-10-27", "2008-11-03"]
    assert len(eps[0]["lines"]) == 5
    assert eps[1]["lines"][0].startswith("ECW World Champion Matt Hardy")


def test_header_with_no_italic_line_is_its_own_episode():
    eps = parse_show_page(_read("raw-2004-august.html"))
    assert [(e["air_date"], len(e["lines"])) for e in eps] == [
        ("2004-08-23", 2), ("2004-08-30", 6), ("2004-09-06", 0)]


def test_air_date_after_text_or_an_entity_is_found():
    # "Raw SuperShow 9/5/11 - Labor Day" and a taped special whose air date
    # follows a quoted title: "&#8220;Holiday with the Troops&#8221; - 12/19/05".
    eps = parse_show_page(_read("raw-2011-labor-day.html"))
    assert [e["air_date"] for e in eps] == ["2011-09-05", "2011-09-19"]
    assert eps[0]["lines"] and not eps[0]["lines"][0].startswith("Raw SuperShow")
    eps = parse_show_page(_read("raw-2005-december.html"))
    assert [(e["tape_date"], e["air_date"]) for e in eps] == [
        ("2005-12-09", "2005-12-19"), ("2005-12-26", "2005-12-26")]


def test_house_show_after_an_episode_is_not_part_of_it():
    # SmackDown 1/9/03 is followed by "WWE (Smackdown!) @ Trenton, NJ - ...
    # January 11, 2003", a house show with a second DeMott vs Moore.
    eps = parse_show_page(_read("smackdown-2003-trenton.html"))
    assert [(e["air_date"], len(e["lines"])) for e in eps] == [("2003-01-09", 9)]
