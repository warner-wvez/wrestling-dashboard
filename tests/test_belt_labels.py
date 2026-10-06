"""A match card names the belt alone, spelled one way.

The stored stake is written 284 ways for about 45 belts: stipulations in
quotes, match words after the belt, "vacant / X", "RAW" and "Title" from one
source beside "Raw" and "Championship" from another.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import stake_label  # noqa: E402


def test_match_words_and_spellings_come_off():
    assert stake_label("WWE United States Championship Open Challenge") == ("WWE United States Championship", None)
    assert stake_label("WWE RAW Women's Title / WWE Universal Title") == (
        "WWE Raw Women's Championship / WWE Universal Championship", None)
    assert stake_label("vacant / Women's World Championship") == ("Women's World Championship", None)
    assert stake_label("WWE Women's  Title") == ("WWE Women's Championship", None)


def test_a_quoted_stipulation_becomes_the_note():
    label, note = stake_label('"If Asuka gets DQed or Counted-out Sasha wins the title" WWE Raw Women\'s Championship')
    assert (label, note) == ("WWE Raw Women's Championship", "If Asuka gets DQed or Counted-out Sasha wins the title")
    label, note = stake_label('"If Lashley defeats Owens, Rollins and Big E he gets added to WWE Championship '
                              'Match at Day 1" No DQ Match')
    assert label is None and note.startswith("If Lashley defeats")


def test_a_contender_match_names_no_belt():
    assert stake_label("WWE Undisputed World Heavyweight Title # 1 Contendership Battle Royal")[0] is None
    assert stake_label("WWE Championship Elimination Chamber Qualifying Match")[0] is None


def test_a_tournament_keeps_its_word():
    assert stake_label("WWE Tag Team Title Tournament First Round Match")[0] == "WWE Tag Team Championship Tournament"
