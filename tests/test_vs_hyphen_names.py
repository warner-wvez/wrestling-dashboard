"""A "vs." result keeps names that contain a hyphen.

To cut off the " - No Contest" tail, both scrapers removed everything from the
first hyphen, so a hyphen inside a name took the rest of the side with it:
D-Von Dudley vanished from Dudley Boyz matches, R-Truth's whole side vanished
from "Drew McIntyre vs. R-Truth - No Contest", and Rated-RKO vs D-Generation X
became one team called "Rated".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup  # noqa: E402

from src.cagematch_scraper import parse_match_block  # noqa: E402


def _teams(raw):
    div = BeautifulSoup(f'<div><div class="MatchResults">{raw}</div></div>', "html.parser").div
    return [t["participants"] for t in parse_match_block(div, 1)["teams"]]


def test_hyphen_inside_a_name_keeps_the_whole_side():
    assert _teams("Drew McIntyre vs. R-Truth - No Contest") == [["Drew McIntyre"], ["R-Truth"]]
    assert _teams("Spike Dudley & Trish Stratus vs. The Dudley Boyz ( Bubba Ray Dudley & "
                  "D-Von Dudley ) - No Contest") == [
        ["Spike Dudley", "Trish Stratus"], ["Bubba Ray Dudley", "D-Von Dudley"]]


def test_hyphenated_team_names_survive():
    assert _teams("Rated-RKO ( Edge & Randy Orton ) (c) vs. D-Generation X ( Shawn Michaels & "
                  "Triple H ) - No Contest (20:00)") == [
        ["Edge", "Randy Orton"], ["Shawn Michaels", "Triple H"]]
    assert _teams("Booker T & Goldust vs. The Un-Americans ( Test & William Regal ) - Double DQ (5:50)") == [
        ["Booker T", "Goldust"], ["Test", "William Regal"]]


def test_spaced_dash_tail_still_comes_off():
    assert _teams("Batista vs. R-Truth - Time Limit Draw (7:19)") == [["Batista"], ["R-Truth"]]
    assert _teams("Eddie Guerrero vs. X-Pac - No Contest (4:36)") == [["Eddie Guerrero"], ["X-Pac"]]


def test_ended_in_tail_comes_off_too():
    assert _teams("The Undertaker vs. Triple H ended in a No Contest (10:00)") == [
        ["The Undertaker"], ["Triple H"]]
