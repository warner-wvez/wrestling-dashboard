"""A retrospective's clips must not walk into the title lineage.

Cagematch lists the matches a highlight show aired as that show's card, keeping
their original "TITLE CHANGE !!!" markers, so the reign walk re-crowns the
winner on the replay date. Left alone, the 2001 Year In Review Special hands
Steve Austin the WWF Title on 2001-12-31 and he never loses it again.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import CLIP_SHOWS, build_title_reigns  # noqa: E402


def _event(eid, date, title, matches):
    return {str(eid): {"id": eid, "air_date": date, "title": title, "matches": matches}}


def _title_match(winner, loser, title):
    return {
        "match_order": 1,
        "match_type": f"{title} Match",
        "title_at_stake": title,
        "raw_description": f"{winner} defeats {loser} (c) (18:43) - TITLE CHANGE !!!",
        "teams": [
            {"team_number": 1, "team_name": winner, "participants": [winner],
             "was_winner": True, "was_champion_entering": False},
            {"team_number": 2, "team_name": loser, "participants": [loser],
             "was_winner": False, "was_champion_entering": True},
        ],
    }


def test_a_clip_show_does_not_crown_a_champion():
    events = {}
    # The real title change...
    events.update(_event(9001, "2001-04-01", "WrestleMania X-Seven",
                         [_title_match("Steve Austin", "The Rock", "WWF Title")]))
    # ...and the same match replayed on a retrospective months later.
    clip_id = next(iter(CLIP_SHOWS))
    events.update(_event(clip_id, "2001-12-31", "Year In Review Special",
                         [_title_match("Steve Austin", "The Rock", "WWF Title")]))
    reigns = build_title_reigns(events)["WWF Title"]
    starts = [r["start"] for r in reigns]
    assert "2001-04-01" in starts, "the real title change must still be walked"
    assert "2001-12-31" not in starts, (
        "a replayed title change crowned a champion on the replay date")


def test_clip_show_ids_are_ints_with_a_stated_reason():
    # The list is curated because neither detector is safe on its own, so each
    # entry has to carry the evidence that put it there.
    for eid, why in CLIP_SHOWS.items():
        assert isinstance(eid, int), f"{eid!r} should be an int event id"
        assert len(why) > 20, f"CLIP_SHOWS[{eid}] needs a reason, got {why!r}"


def test_real_anniversary_shows_are_not_excluded():
    # WrestleMania 25 is subtitled "The 25th Anniversary Of WrestleMania" and Raw
    # #759 is a 15th Anniversary show. Both are real cards with real title
    # changes; a title-pattern rule would delete them.
    assert 969 not in CLIP_SHOWS, "WrestleMania 25 is a real PPV"
    assert 825 not in CLIP_SHOWS, "Raw #759 15th Anniversary is a real show"
    # The Eddie Guerrero tributes are real cards too: the roster wrestled that
    # night, they are not a clip reel.
    assert 578 not in CLIP_SHOWS and 579 not in CLIP_SHOWS
