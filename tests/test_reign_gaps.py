"""A title change the corpus never carried must not fuse two reigns into one.

The walk tracks who holds a belt by watching it change hands. When a change
happens on a card the corpus does not have, the belt appears never to have left
and the incumbent's two reigns fuse across the gap. The source already says
otherwise: the (c) marker names who walked in holding it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import build_title_reigns  # noqa: E402

TITLE = "WWE Intercontinental Title"


def _m(order, winner_names, loser_names, champ_side, raw=None, title=TITLE):
    """champ_side: 'winner' | 'loser' | 'both' | None"""
    def team(n, names, is_win):
        side = 'winner' if is_win else 'loser'
        return {"team_number": n, "team_name": " and ".join(names), "participants": list(names),
                "was_winner": is_win,
                "was_champion_entering": champ_side in (side, 'both')}
    return {
        "match_order": order,
        "match_type": f"{title} Match",
        "title_at_stake": title,
        "raw_description": raw or (" and ".join(winner_names) + " defeats " + " and ".join(loser_names) + " (10:00)"),
        "teams": [team(1, winner_names, True), team(2, loser_names, False)],
    }


def _ev(eid, date, matches):
    return {str(eid): {"id": eid, "air_date": date, "title": "Show", "matches": matches}}


def _reigns(events, title=TITLE):
    return build_title_reigns(events)[title]


def test_a_missing_title_change_is_recovered_from_the_champion_marker():
    # Barrett held the IC title from December. The Miz beat him for it at
    # WrestleMania 29 and lost it back the next night, but only the second match
    # is in the corpus, so the walk read "Barrett defeats The Miz (c)" as Barrett
    # retaining and gave him one unbroken reign that swallowed Miz's.
    events = {}
    events.update(_ev(1, "2012-12-29", [_m(1, ["Wade Barrett"], ["Kofi Kingston"], 'loser')]))
    events.update(_ev(2, "2013-04-08", [_m(1, ["Wade Barrett"], ["The Miz"], 'loser')]))
    events.update(_ev(3, "2013-06-16", [_m(1, ["Curtis Axel"], ["Wade Barrett"], 'loser')]))
    rs = _reigns(events)
    champs = [(r["start"], r["end"], r["champion_names"]) for r in rs]
    assert ["The Miz"] in [c[2] for c in champs], f"Miz's reign was swallowed: {champs}"
    barrett = [c for c in champs if c[2] == ["Wade Barrett"]]
    assert len(barrett) == 2, f"Barrett's two reigns must not fuse across the gap: {champs}"


def test_a_multi_man_champion_team_does_not_invent_a_reign():
    # A multi-man title match is stored as two teams, so the (c) side carries the
    # champion AND a challenger: Payback 2013 reads "Curtis Axel defeats The Miz
    # and Wade Barrett (c)". Barrett is the champion and is in there, so the
    # marker agrees with the walk and nothing should be inferred for Miz.
    events = {}
    events.update(_ev(1, "2012-12-29", [_m(1, ["Wade Barrett"], ["Kofi Kingston"], 'loser')]))
    events.update(_ev(2, "2013-06-16", [_m(1, ["Curtis Axel"], ["The Miz", "Wade Barrett"], 'loser')]))
    rs = _reigns(events)
    assert ["The Miz"] not in [r["champion_names"] for r in rs], (
        "the champion was inside the (c) team; nothing was missed")


def test_champion_versus_champion_is_too_ambiguous_to_infer_from():
    # No Mercy 2002: "Triple H (c) [Heavyweight] defeats Kane (c) [Intercontinental]".
    # Both sides are (c), for DIFFERENT belts, and the walk takes the first it
    # finds, so on this chain the marker hands back the other belt's champion.
    events = {}
    events.update(_ev(1, "2002-09-30", [_m(1, ["Kane"], ["Chris Jericho"], 'loser')]))
    events.update(_ev(2, "2002-10-20", [_m(1, ["Triple H"], ["Kane"], 'both')]))
    rs = _reigns(events)
    # Triple H wins the belt here, which is real. What must NOT happen is an
    # extra inferred Triple H reign inserted ahead of his win off the marker.
    th = [r for r in rs if r["champion_names"] == ["Triple H"]]
    assert len(th) == 1, f"champion-vs-champion inferred a phantom reign: {rs}"


def test_a_champion_who_sent_a_stand_in_does_not_lose_the_belt_to_them():
    # "The Undertaker defeats Orlando Jordan [Replacement for John Bradshaw
    # Layfield] (w/ JBL) (c)": the belt is JBL's, the (c) landed on the stand-in.
    events = {}
    events.update(_ev(1, "2004-06-27", [_m(1, ["John Bradshaw Layfield"], ["Eddie Guerrero"], 'loser')]))
    events.update(_ev(2, "2004-08-26", [_m(
        1, ["The Undertaker"], ["Orlando Jordan"], 'loser',
        raw="The Undertaker defeats Orlando Jordan [Replacement for John Bradshaw Layfield] (w/ John Bradshaw Layfield ) (c) (10:00)")]))
    rs = _reigns(events)
    assert ["Orlando Jordan"] not in [r["champion_names"] for r in rs], (
        "the (c) was on the replacement, not the champion")
