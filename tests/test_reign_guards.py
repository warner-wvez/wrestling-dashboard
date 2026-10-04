"""Reign-walk guards against fabricated title changes.

Every case here is a real match in the corpus that produced a championship
reign that never happened. Each is verified against the published title
history, cited in the test.

Three guard families:
  1. Ambiguous stake. A belt only moves when the source is unambiguous about
     THIS belt moving: not on a multi-man win, not off a TITLE CHANGE marker
     that could belong to either half of a composite stake, not in a
     tournament round or a mid-series match, and not on a DQ win by someone
     who does not hold the belt.
  2. Spelling. A champion re-spelled is not a new champion.
  3. Retirement. A belt that goes quiet for years and comes back is two
     lineages, not one reign spanning the gap.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import build_title_reigns  # noqa: E402


def _team(n, names, is_win, champ=False, outcome=None):
    return {
        "team_number": n,
        "team_name": " & ".join(names),
        "participants": list(names),
        "was_winner": is_win,
        "was_champion_entering": champ,
        "match_outcome": outcome or ("win" if is_win else "loss"),
    }


def _m(order, winners, losers, raw, *, title, match_type=None,
       champ_side=None, win_outcome=None, lose_outcome=None):
    """champ_side: 'winner' | 'loser' | 'both' | None"""
    return {
        "match_order": order,
        "match_type": match_type or f"{title} Match",
        "title_at_stake": title,
        "raw_description": raw,
        "teams": [
            _team(1, winners, True, champ_side in ("winner", "both"), win_outcome),
            _team(2, losers, False, champ_side in ("loser", "both"), lose_outcome),
        ],
    }


def _ev(eid, date, matches):
    return {str(eid): {"id": eid, "air_date": date, "title": "Show", "matches": matches}}


def _chain(events, title, canon=None):
    return [(r["start"], r["end"], r["champion_names"])
            for r in build_title_reigns(events, canon=canon)[title]]


def _champs(events, title, canon=None):
    return [c[2] for c in _chain(events, title, canon=canon)]


# --------------------------------------------------------------------------
# Guard 1: ambiguous stake
# --------------------------------------------------------------------------

WHT = "World Heavyweight Title"


def test_a_singles_belt_does_not_move_on_a_multi_man_win_without_a_marker():
    """Raw 2004-11-29: Benoit and Edge both pinned Triple H at once, so the
    title was held up and Triple H regained it in the Elimination Chamber.
    The corpus stores the two challengers as one winning team, which crowned
    Edge as World Heavyweight Champion for two months. Edge's first World
    Heavyweight reign was May 2007.
    """
    events = {}
    events.update(_ev(1, "2004-09-12", [
        _m(1, ["Triple H"], ["Randy Orton"], "Triple H defeats Randy Orton (c) (20:00) - TITLE CHANGE !!!",
           title=WHT, champ_side="loser")]))
    events.update(_ev(2, "2004-11-29", [
        _m(1, ["Chris Benoit", "Edge"], ["Triple H"],
           "Chris Benoit and Edge defeat Triple H (c) (14:44)",
           title=WHT, match_type=f"{WHT} Triple Threat Match", champ_side="loser")]))
    chain = _chain(events, WHT)
    assert ["Edge"] not in [c[2] for c in chain], \
        f"a held-up finish must not crown a challenger: {chain}"
    assert chain[-1][2] == ["Triple H"], f"Triple H still holds it: {chain}"


def test_a_title_change_marker_on_a_composite_stake_does_not_crown_a_multi_man_winner():
    """Raw 2006-05-15: a three-on-two handicap tagged
    'WWE Heavyweight Title / Intercontinental Title'. The marker belongs to the
    Intercontinental half. John Cena held the WWE Championship from the 2006
    Royal Rumble to ECW One Night Stand; Triple H never held it in that window.
    """
    t = "WWE Heavyweight Title / Intercontinental Title"
    events = {}
    events.update(_ev(1, "2006-01-29", [
        _m(1, ["John Cena"], ["Edge"], "John Cena defeats Edge (c) (15:00) - TITLE CHANGE !!!",
           title="WWE Heavyweight Title", champ_side="loser")]))
    events.update(_ev(2, "2006-05-15", [
        _m(1, ["Chris Masters", "Shelton Benjamin", "Triple H"], ["John Cena", "Rob Van Dam"],
           "Chris Masters , Shelton Benjamin & Triple H defeat John Cena (c) [WWE] & "
           "Rob Van Dam (c) [Intercontinental] (12:57) - TITLE CHANGE !!!",
           title=t, match_type=f"{t} Texas Tornado Three On Two Handicap Match",
           champ_side="loser")]))
    chain = _chain(events, "WWE Heavyweight Title")
    assert ["Triple H"] not in [c[2] for c in chain], \
        f"the marker belongs to the other belt on the line: {chain}"
    assert chain[-1][2] == ["John Cena"], f"Cena held it through this night: {chain}"


def test_a_clean_winners_take_all_swap_still_crowns_both_belts():
    """SummerSlam 2008: Beth Phoenix and Santino Marella beat Kofi Kingston and
    Mickie James in a winners-take-all mixed tag, and each walked out with one
    of the two belts. Two winners, two belts, two champions entering, so the
    marker maps cleanly and the multi-man guard must not swallow it.
    """
    t = "Intercontinental Title / WWE Women's Title"
    events = {}
    # Each challenger has chased their own belt first, which is what tells
    # _pick_singles_champion who wrestles for which title on the night.
    events.update(_ev(1, "2008-07-28", [
        _m(1, ["Kofi Kingston"], ["Santino Marella"],
           "Kofi Kingston (c) defeats Santino Marella (8:00)",
           title="Intercontinental Title", champ_side="winner")]))
    events.update(_ev(2, "2008-08-04", [
        _m(1, ["Mickie James"], ["Beth Phoenix"],
           "Mickie James (c) defeats Beth Phoenix (7:00)",
           title="WWE Women's Title", champ_side="winner")]))
    events.update(_ev(3, "2008-08-17", [
        _m(1, ["Beth Phoenix", "Santino Marella"], ["Kofi Kingston", "Mickie James"],
           "Beth Phoenix & Santino Marella defeat Kofi Kingston (c) & Mickie James (c) "
           "(5:25) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    womens = _chain(events, "WWE Women's Title")
    ic = _chain(events, "Intercontinental Title")
    assert womens[-1] == ("2008-08-17", None, ["Beth Phoenix"]), \
        f"Beth left SummerSlam with the Women's Title: {womens}"
    assert ic[-1] == ("2008-08-17", None, ["Santino Marella"]), \
        f"Santino left SummerSlam with the IC Title: {ic}"


def test_a_single_winner_still_takes_both_halves_of_a_composite_stake():
    """SummerSlam 2015: Seth Rollins beat John Cena in a title-for-title match
    and left with both belts. One winner, so the stake is unambiguous.
    """
    t = "WWE World Heavyweight Title / WWE United States Title"
    events = _ev(1, "2015-08-23", [
        _m(1, ["Seth Rollins"], ["John Cena"],
           "Seth Rollins (c) [WWE] defeats John Cena (c) [United States] (19:25) - TITLE CHANGE !!!",
           title=t, champ_side="both")])
    assert _champs(events, "WWE United States Title") == [["Seth Rollins"]], \
        f"Rollins really did win the US title here: {_chain(events, 'WWE United States Title')}"


def test_a_challenger_dq_win_does_not_take_a_belt_they_do_not_hold():
    """Raw 2019-04-08: 'Kofi Kingston (c) [WWE] defeats Seth Rollins (c)
    [Universal] by DQ'. Kofi is champion of the OTHER belt, so the existing
    challenger-DQ guard did not fire on the Universal chain. Kofi Kingston has
    never been Universal Champion.
    """
    t = "WWE Title / WWE Universal Title"
    events = {}
    events.update(_ev(1, "2019-04-07", [
        _m(1, ["Seth Rollins"], ["Brock Lesnar"],
           "Seth Rollins defeats Brock Lesnar (c) (2:30) - TITLE CHANGE !!!",
           title="WWE Universal Title", champ_side="loser")]))
    events.update(_ev(2, "2019-04-08", [
        _m(1, ["Kofi Kingston"], ["Seth Rollins"],
           "Kofi Kingston (c) [WWE] defeats Seth Rollins (c) [Universal] by DQ (7:50)",
           title=t, champ_side="both", win_outcome="dq-win", lose_outcome="dq-loss")]))
    chain = _chain(events, "WWE Universal Title")
    assert ["Kofi Kingston"] not in [c[2] for c in chain], \
        f"a DQ win cannot take a belt: {chain}"
    assert chain[-1][2] == ["Seth Rollins"], f"Rollins keeps it: {chain}"


def test_a_tournament_round_does_not_crown_a_champion():
    """SmackDown 2003-06-19 'WWE United States Title Tournament First Round
    Match': Chris Benoit beat Rhyno. That seeded the revived US title lineage
    with Benoit as inaugural champion. Eddie Guerrero won the tournament final
    at Vengeance 2003.
    """
    t = "WWE United States Title"
    events = {}
    events.update(_ev(1, "2003-06-19", [
        _m(1, ["Chris Benoit"], ["Rhyno"], "Chris Benoit defeats Rhyno (16:22)",
           title=t, match_type=f"{t} Tournament First Round Match")]))
    events.update(_ev(2, "2003-10-19", [
        _m(1, ["The Big Show"], ["Eddie Guerrero"],
           "The Big Show defeats Eddie Guerrero (c) (10:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    assert ["Chris Benoit"] not in _champs(events, t), \
        f"a first-round win is not a title win: {_chain(events, t)}"


def test_a_tournament_final_for_a_vacant_belt_still_crowns():
    t = "WWE United States Title"
    events = _ev(1, "2003-07-27", [
        _m(1, ["Eddie Guerrero"], ["Chris Benoit"],
           "Eddie Guerrero defeats Chris Benoit (20:00)",
           title=t, match_type=f"{t} Tournament Final Match (vakant)")])
    assert _champs(events, t) == [["Eddie Guerrero"]], \
        f"the final does crown the inaugural champion: {_chain(events, t)}"


def test_a_qualifying_match_does_not_crown_a_champion():
    """Raw 2019-01-28 'Women's Tag Team Title Elimination Chamber Qualifying
    Match'. Sasha Banks and Bayley were the inaugural champions, at Elimination
    Chamber on 2019-02-17.
    """
    t = "WWE Women's Tag Team Title"
    events = {}
    events.update(_ev(1, "2019-01-28", [
        _m(1, ["Nia Jax", "Tamina"], ["Alexa Bliss", "Mickie James"],
           "Nia Jax & Tamina defeat Alexa Bliss & Mickie James (9:54)",
           title=t, match_type=f"{t} Elimination Chamber Qualifying Match")]))
    events.update(_ev(2, "2019-04-07", [
        _m(1, ["Billie Kay", "Peyton Royce"], ["Bayley", "Sasha Banks"],
           "The IIconics defeat Bayley & Sasha Banks (c) (8:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    assert ["Nia Jax", "Tamina"] not in _champs(events, t), \
        f"a qualifier is not a title win: {_chain(events, t)}"


def test_a_best_of_five_series_only_crowns_on_the_decider():
    """Cena and Booker T, 2004. Each of the five matches is tagged with the US
    title and the running series score, so four of them read as title changes.
    Only match five carries the TITLE CHANGE marker.
    """
    t = "WWE United States Title"
    events = {}
    events.update(_ev(1, "2004-08-15", [
        _m(1, ["John Cena"], ["Booker T"], "John Cena [1] defeats Booker T (c) [0] (6:20)",
           title=t, match_type=f"{t} Best Of Five Series Match #1", champ_side="loser")]))
    events.update(_ev(2, "2004-08-26", [
        _m(1, ["Booker T"], ["John Cena"], "Booker T (c) [1] defeats John Cena [1] (9:45)",
           title=t, match_type=f"{t} Best Of Five Series Match #2", champ_side="winner")]))
    events.update(_ev(3, "2004-10-03", [
        _m(1, ["John Cena"], ["Booker T"],
           "John Cena [3] defeats Booker T (c) [2] (10:20) - TITLE CHANGE !!!",
           title=t, match_type=f"{t} Best Of Five Series Match #5", champ_side="loser")]))
    chain = _chain(events, t)
    assert [c[2] for c in chain] == [["Booker T"], ["John Cena"]], \
        f"only the decider moves the belt: {chain}"
    assert chain[1][0] == "2004-10-03", f"and it moves on the decider's night: {chain}"


# --------------------------------------------------------------------------
# Guard 2: a champion re-spelled is not a new champion
# --------------------------------------------------------------------------

def test_a_spelling_change_is_not_a_title_change():
    """Seth Rollins won the revived World Heavyweight Championship on
    2023-05-27 and held it until WrestleMania XL. The source alternates
    between 'Seth Rollins' and 'Seth "Freakin" Rollins', which split one reign
    into four.
    """
    canon = {'Seth "Freakin" Rollins': "Seth Rollins"}
    events = {}
    events.update(_ev(1, "2023-05-27", [
        _m(1, ["Seth Rollins"], ["AJ Styles"], "Seth Rollins defeats AJ Styles (25:00)",
           title=WHT)]))
    events.update(_ev(2, "2023-07-01", [
        _m(1, ['Seth "Freakin" Rollins'], ["Finn Balor"],
           'Seth "Freakin" Rollins (c) defeats Finn Balor (20:00)',
           title=WHT, champ_side="winner")]))
    events.update(_ev(3, "2023-11-04", [
        _m(1, ["Seth Rollins"], ["Drew McIntyre"],
           "Seth Rollins (c) defeats Drew McIntyre (22:00)",
           title=WHT, champ_side="winner")]))
    assert _champs(events, WHT, canon=canon) == [["Seth Rollins"]], \
        f"one reign, not three: {_chain(events, WHT, canon=canon)}"


def test_a_tag_team_spelling_change_is_not_a_title_change():
    """The Dudleys 'lose and regain' the tag titles on 2001-02-25 purely
    because the source flips from 'Buh Buh Ray Dudley' to 'Bubba Ray Dudley'.
    """
    t = "WWF World Tag Team Title"
    canon = {"Buh Buh Ray Dudley": "Bubba Ray Dudley"}
    events = {}
    events.update(_ev(1, "2001-01-21", [
        _m(1, ["Buh Buh Ray Dudley", "D-Von Dudley"], ["Edge", "Christian"],
           "The Dudley Boyz defeat Edge & Christian (c) (12:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2001-02-25", [
        _m(1, ["Bubba Ray Dudley", "D-Von Dudley"], ["Kane", "The Undertaker"],
           "The Dudley Boyz ( Bubba Ray Dudley & D-Von Dudley ) (c) defeat "
           "Kane & The Undertaker (12:04)",
           title=t, champ_side="winner")]))
    chain = _chain(events, t, canon=canon)
    dudleys = [c for c in chain if "D-Von Dudley" in c[2]]
    assert len(dudleys) == 1, f"one unbroken Dudley reign, not two: {chain}"


def test_canon_does_not_merge_genuinely_different_champions():
    t = "WWF World Tag Team Title"
    canon = {"Buh Buh Ray Dudley": "Bubba Ray Dudley"}
    events = {}
    events.update(_ev(1, "2001-01-21", [
        _m(1, ["Bubba Ray Dudley", "D-Von Dudley"], ["Edge", "Christian"],
           "The Dudley Boyz defeat Edge & Christian (c) (12:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2001-04-01", [
        _m(1, ["Edge", "Christian"], ["Bubba Ray Dudley", "D-Von Dudley"],
           "Edge & Christian defeat The Dudley Boyz (c) (12:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    assert len(_champs(events, t, canon=canon)) == 3, \
        f"a real change still registers: {_chain(events, t, canon=canon)}"


# --------------------------------------------------------------------------
# Guard 3: a revived belt is a new lineage
# --------------------------------------------------------------------------

def test_a_revived_belt_does_not_extend_the_retired_belts_final_reign():
    """The World Tag Team Championship was retired in August 2010 with the
    Hart Dynasty as the last champions. WWE revived the name in 2024. One
    lineage across that gap gives the Hart Dynasty a fourteen-year reign.
    """
    t = "World Tag Team Title"
    events = {}
    events.update(_ev(1, "2010-04-26", [
        _m(1, ["David Hart Smith", "Tyson Kidd"], ["The Big Show", "The Miz"],
           "The Hart Dynasty defeat ShoMiz (c) (10:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2024-04-22", [
        _m(1, ["Finn Balor", "Damian Priest"], ["Jey Uso", "Jimmy Uso"],
           "Finn Balor & Damian Priest defeat The Usos (c) (12:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    chain = _chain(events, t)
    hart = [c for c in chain if c[2] == ["David Hart Smith", "Tyson Kidd"]]
    assert hart, f"the Hart Dynasty reign must survive: {chain}"
    assert hart[0][1] == "2010-04-26", \
        f"and must close at the retired belt's last match, not bridge to 2024: {chain}"


def test_a_belt_the_corpus_loses_sight_of_is_not_a_retirement():
    """Pete Dunne held the United Kingdom Championship from May 2017 to April
    2019, 685 days. The corpus carries almost no NXT UK, so there is a
    twenty-month hole in the middle of it. He walks back in as champion, which
    is the belt saying plainly that it never died: a gap is only a retirement
    when somebody else is holding it on the far side.
    """
    t = "WWE United Kingdom Title"
    events = {}
    events.update(_ev(1, "2017-05-20", [
        _m(1, ["Pete Dunne"], ["Tyler Bate"],
           "Pete Dunne defeats Tyler Bate (c) (15:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2019-01-12", [
        _m(1, ["Pete Dunne"], ["Joe Coffey"], "Pete Dunne (c) defeats Joe Coffey (20:00)",
           title=t, champ_side="winner")]))
    events.update(_ev(3, "2019-04-05", [
        _m(1, ["WALTER"], ["Pete Dunne"], "WALTER defeats Pete Dunne (c) (18:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    chain = _chain(events, t)
    dunne = [c for c in chain if c[2] == ["Pete Dunne"]]
    assert len(dunne) == 1, f"one reign across the corpus hole, not two: {chain}"
    assert dunne[0] == ("2017-05-20", "2019-04-05", ["Pete Dunne"]), \
        f"and it runs the full length: {chain}"


def test_an_active_belt_defended_across_a_normal_gap_stays_one_reign():
    t = "WWE Intercontinental Title"
    events = {}
    events.update(_ev(1, "2022-06-10", [
        _m(1, ["Gunther"], ["Ricochet"], "Gunther defeats Ricochet (c) (10:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2023-04-01", [
        _m(1, ["Gunther"], ["Drew McIntyre"], "Gunther (c) defeats Drew McIntyre (15:00)",
           title=t, champ_side="winner")]))
    events.update(_ev(3, "2024-04-06", [
        _m(1, ["Sami Zayn"], ["Gunther"], "Sami Zayn defeats Gunther (c) (12:00) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    chain = _chain(events, t)
    gunther = [c for c in chain if c[2] == ["Gunther"]]
    assert len(gunther) == 1 and gunther[0][1] == "2024-04-06", \
        f"a belt defended all along is one reign: {chain}"
