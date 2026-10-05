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

from src.title_lineages import lineage_name  # noqa: E402
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
            for r in build_title_reigns(events, canon=canon, offcard=())[
                lineage_name(title, min(e["air_date"] for e in events.values()))]]


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


# --------------------------------------------------------------------------
# Vacancies and sourced rulings
# --------------------------------------------------------------------------

def test_a_vacant_belt_won_mid_chain_starts_the_new_reign_that_night():
    """Judgment Day 2003: Christian won the reactivated Intercontinental Title
    in a battle royal with no champion in it, and our source marks it TITLE
    CHANGE. The walk skipped it as a contender match, so Triple H "held" the
    belt until Christian first walked out as champion at Insurrextion 2003.
    """
    t = "Intercontinental Title"
    events = {}
    events.update(_ev(1, "2002-09-01", [
        _m(1, ["Triple H"], ["Kane"], "Triple H defeats Kane (c) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2003-05-18", [
        _m(1, ["Christian"], ["Booker T", "Goldust"],
           "Christian defeats Booker T and Goldust (12:00) - TITLE CHANGE !!!", title=t)]))
    events.update(_ev(3, "2003-06-07", [
        _m(1, ["Christian"], ["Booker T"], "Christian (c) defeats Booker T", title=t,
           champ_side="winner")]))
    chain = _chain(events, t)
    assert chain[1:] == [("2002-09-01", "2003-05-18", ["Triple H"]),
                         ("2003-05-18", None, ["Christian"])], chain


def test_a_contender_match_without_the_marker_still_moves_nothing():
    t = "Intercontinental Title"
    events = {}
    events.update(_ev(1, "2002-09-01", [
        _m(1, ["Triple H"], ["Kane"], "Triple H defeats Kane (c) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2002-09-08", [
        _m(1, ["Rob Van Dam"], ["Chris Jericho"], "Rob Van Dam defeats Chris Jericho", title=t)]))
    assert _champs(events, t)[-1] == ["Triple H"]


def test_a_sourced_title_result_names_who_holds_the_belt():
    """ECW, 2007. Backlash: Vince McMahon, Shane McMahon and Umaga beat Bobby
    Lashley and Vince pinned him, but the walk picked Shane off the three-man
    side. Judgment Day: Lashley beat all three by pinning Shane, so Vince kept
    the belt, but the walk crowned Lashley. A match can carry the champion
    after it, from a cited source, and the walk takes it.
    """
    t = "ECW World Heavyweight Title"
    trio = ["Shane McMahon", "Umaga", "Vince McMahon"]
    events = {}
    events.update(_ev(1, "2006-12-03", [
        _m(1, ["Bobby Lashley"], ["The Big Show"],
           "Bobby Lashley defeats The Big Show (c) - TITLE CHANGE !!!", title=t, champ_side="loser")]))
    backlash = _m(1, trio, ["Bobby Lashley"], "... defeat Bobby Lashley (c) - TITLE CHANGE !!!",
                  title=t, champ_side="loser")
    backlash["title_result"] = {"champions": ["Vince McMahon"], "source": "Wikipedia"}
    events.update(_ev(2, "2007-04-29", [backlash]))
    jd = _m(1, ["Bobby Lashley"], trio, "Bobby Lashley defeats ... (c)", title=t, champ_side="loser")
    jd["title_result"] = {"champions": ["Vince McMahon"], "source": "Wikipedia"}
    events.update(_ev(3, "2007-05-20", [jd]))
    events.update(_ev(4, "2007-06-03", [
        _m(1, ["Bobby Lashley"], ["Mr. McMahon"], "Bobby Lashley defeated Mr. McMahon (c)",
           title=t, champ_side="loser")]))
    chain = _chain(events, t, canon={"Mr. McMahon": "Vince McMahon"})
    assert chain[1:] == [("2006-12-03", "2007-04-29", ["Bobby Lashley"]),
                         ("2007-04-29", "2007-06-03", ["Vince McMahon"]),
                         ("2007-06-03", None, ["Bobby Lashley"])], chain


def test_title_changes_inside_one_match_are_reigns_of_their_own():
    """No Way Out 2001: inside Raven's defense against the Big Show, Billy
    Gunn pinned Raven for the title at 2:27 and Raven pinned Gunn back at 3:28
    before Show won it at 4:20. The card holds one match; the history holds
    three changes. title_result's "within" lists the holders before the last.
    """
    t = "WWF Hardcore Title"
    events = {}
    events.update(_ev(1, "2001-02-08", [
        _m(1, ["Raven"], ["Hardcore Holly"], "Raven defeats Hardcore Holly (c) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    nwo = _m(1, ["The Big Show"], ["Raven"], "The Big Show defeats Raven (c) (4:20) - TITLE CHANGE !!!",
             title=t, champ_side="loser")
    nwo["title_result"] = {"champions": ["The Big Show"], "within": [["Billy Gunn"], ["Raven"]]}
    events.update(_ev(2, "2001-02-25", [nwo]))
    chain = _chain(events, t)
    assert chain[1:] == [("2001-02-08", "2001-02-25", ["Raven"]),
                         ("2001-02-25", "2001-02-25", ["Billy Gunn"]),
                         ("2001-02-25", "2001-02-25", ["Raven"]),
                         ("2001-02-25", None, ["The Big Show"])], chain


def test_a_title_result_for_one_belt_leaves_the_other_belt_alone():
    """Raw 2002-05-13: Bubba Ray Dudley & Trish Stratus beat Jazz (Women's)
    and Steven Richards (Hardcore). Trish pinned Jazz and took the Women's
    title; Richards was never pinned and kept the Hardcore title. The ruling
    names its belt, so the Women's chain still moves."""
    hc, wo = "WWE Hardcore Title", "WWE World Women's Title"
    events = {}
    events.update(_ev(1, "2002-05-06", [
        _m(1, ["Steven Richards"], ["Trish Stratus"], "Steven Richards defeats Trish Stratus (c) - TITLE CHANGE !!!",
           title=hc, champ_side="loser"),
        _m(2, ["Jazz"], ["Trish Stratus"], "Jazz (c) defeats Trish Stratus", title=wo, champ_side="winner")]))
    tag = _m(1, ["Bubba Ray Dudley", "Trish Stratus"], ["Jazz", "Steven Richards"],
             "Bubba Ray Dudley & Trish Stratus defeat Jazz (c) & Steven Richards (c) - TITLE CHANGE !!!",
             title=f"{wo} / {hc}", champ_side="loser")
    tag["title_result"] = {"title": hc, "champions": ["Steven Richards"]}
    events.update(_ev(2, "2002-05-13", [tag]))
    assert _champs(events, hc)[-1] == ["Steven Richards"], _chain(events, hc)
    assert _champs(events, wo)[-1] == ["Trish Stratus"], _chain(events, wo)


def test_house_show_changes_join_the_chain_by_date():
    """Raw 2001-01-22 ends with Raven champion; three nights of house shows
    later (2001-02-03, Greensboro) K-Kwik, Crash Holly and Raven traded it, and
    Hardcore Holly won it on SmackDown 2001-02-08. No card carries the house
    show, so the change list does."""
    t = "WWF Hardcore Title"
    events = {}
    events.update(_ev(1, "2001-01-22", [
        _m(1, ["Raven"], ["Al Snow"], "Raven defeats Al Snow (c) - TITLE CHANGE !!!", title=t, champ_side="loser")]))
    events.update(_ev(2, "2001-02-08", [
        _m(1, ["Hardcore Holly"], ["Raven"], "Hardcore Holly defeated Raven (c)", title=t, champ_side="loser")]))
    house = [{"title": t, "date": "2001-02-03", "order": i, "champions": [c]}
             for i, c in enumerate(["K-Kwik", "Crash Holly", "Raven"])]
    chain = [(s, e, c) for s, e, c in
             [(r["start"], r["end"], r["champion_names"]) for r in build_title_reigns(events, offcard=house)[t]]]
    assert chain[1:] == [("2001-01-22", "2001-02-03", ["Raven"]),
                         ("2001-02-03", "2001-02-03", ["K-Kwik"]),
                         ("2001-02-03", "2001-02-03", ["Crash Holly"]),
                         ("2001-02-03", "2001-02-08", ["Raven"]),
                         ("2001-02-08", None, ["Hardcore Holly"])], chain


def test_an_off_card_change_on_a_carried_show_sorts_between_its_matches():
    """Raw 2021-11-08: the 24/7 title went Drake Maverick, Akira Tozawa, Corey
    Graves, Byron Saxton, Drake Maverick, Reggie. The card carries five of the
    six as matches; Drake pinning Saxton at ringside is a change the card does
    not list, so the change list places it inside that night's show, after
    Saxton's win and before Reggie's."""
    t = "WWE 24/7 Title"
    events = {}
    events.update(_ev(1, "2021-07-19", [
        _m(4, ["Reggie"], ["Akira Tozawa"], "Reggie defeats Akira Tozawa (c) to win the title",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2021-11-08", [
        _m(4, ["Drake Maverick"], ["Reggie"], "Drake Maverick defeats Reggie (c) to win the title",
           title=t, champ_side="loser"),
        _m(5, ["Akira Tozawa"], ["Drake Maverick"], "Akira Tozawa defeats Drake Maverick (c) to win the title",
           title=t, champ_side="loser"),
        _m(6, ["Corey Graves"], ["Akira Tozawa"], "Corey Graves defeats Akira Tozawa (c) to win the title",
           title=t, champ_side="loser"),
        _m(7, ["Byron Saxton"], ["Corey Graves"], "Byron Saxton defeats Corey Graves (c) to win the title",
           title=t, champ_side="loser"),
        _m(8, ["Reggie"], ["Drake Maverick"], "Reggie defeats Drake Maverick (c) to win the title",
           title=t, champ_side="loser")]))
    ringside = [{"title": t, "date": "2021-11-08", "event_id": 2, "order": 7.5,
                 "champions": ["Drake Maverick"]}]
    chain = [r["champion_names"] for r in build_title_reigns(events, offcard=ringside)[t]]
    assert chain == [["Akira Tozawa"], ["Reggie"], ["Drake Maverick"], ["Akira Tozawa"], ["Corey Graves"],
                     ["Byron Saxton"], ["Drake Maverick"], ["Reggie"]], chain


def test_a_pre_show_change_starts_the_reign_on_its_pay_per_view():
    """WrestleMania 35, 2019-04-07: Tony Nese beat Buddy Murphy for the
    Cruiserweight title on the pre-show, which our card leaves off. Without the
    change list the walk first saw Nese as "(c)" at Money in the Bank six weeks
    later and started his reign there."""
    t = "WWE Cruiserweight Title"
    events = {}
    events.update(_ev(1, "2018-10-06", [
        _m(1, ["Buddy Murphy"], ["Cedric Alexander"], "Buddy Murphy defeats Cedric Alexander (c) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2019-04-07", []))
    events.update(_ev(3, "2019-05-19", [
        _m(4, ["Tony Nese"], ["Ariya Daivari"], "Tony Nese (c) defeats Ariya Daivari", title=t,
           champ_side="winner")]))
    preshow = [{"lineage": "lineage::cruiserweight-2016", "date": "2019-04-07", "event_id": 2, "order": 0.5,
                "champions": ["Tony Nese"]}]
    reigns = build_title_reigns(events, offcard=preshow)[lineage_name(t, "2019-01-01")]
    assert [(r["champion_names"], r["start"], r["start_event_id"], r["pre_corpus"]) for r in reigns[1:]] == [
        (["Buddy Murphy"], "2018-10-06", 1, False),
        (["Tony Nese"], "2019-04-07", 2, False)], reigns


def test_a_reign_runs_on_beside_an_interim_champion():
    """Jordan Devlin won the Cruiserweight title at Worlds Collide 2020-01-25.
    Unable to travel, he kept it while Santos Escobar was crowned interim
    champion (aired 2020-06-03), until Escobar beat him on 2021-04-08. Kushida
    took it from Escobar on 2021-04-13. Both reigns run their full length."""
    t = "NXT Cruiserweight Title"
    events = _ev(1, "2020-01-25", [
        _m(1, ["Jordan Devlin"], ["Angel Garza"], "Jordan Devlin defeats Angel Garza (c) - TITLE CHANGE !!!",
           title=t, champ_side="loser")])
    nxt = [{"lineage": "lineage::cruiserweight-2016", "date": "2020-06-03", "champions": ["Santos Escobar"],
            "interim": True, "previous_holds_until": "2021-04-08"},
           {"lineage": "lineage::cruiserweight-2016", "date": "2021-04-13", "champions": ["Kushida"]}]
    reigns = build_title_reigns(events, offcard=nxt)[lineage_name(t, "2020-01-25")]
    assert [(r["champion_names"], r["start"], r["end"]) for r in reigns[1:]] == [
        (["Jordan Devlin"], "2020-01-25", "2021-04-08"),
        (["Santos Escobar"], "2020-06-03", "2021-04-13"),
        (["Kushida"], "2021-04-13", None)], reigns
    assert reigns[1].get("beside_interim") and not reigns[2].get("beside_interim")


def test_a_stand_in_wins_the_belt_for_the_man_he_replaced():
    """SmackDown 2006-01-13: Randy Orton, "[Replacement for Booker T]", won the
    deciding match of the best-of-seven series for the vacant US title. The
    belt went to Booker T, and Orton's defense a week later was Booker's too."""
    t = "WWE United States Title"
    events = {}
    events.update(_ev(1, "2006-01-13", [
        _m(1, ["Randy Orton"], ["Chris Benoit"],
           "Randy Orton [Replacement for Booker T] (w/ Booker T & Sharmell ) [4] defeats Chris Benoit [3] "
           "(28:05) - TITLE CHANGE !!!", title=t)]))
    events.update(_ev(2, "2006-01-20", [
        _m(1, ["Randy Orton"], ["Orlando Jordan"],
           "Randy Orton [Replacement for Booker T] (c) defeats Orlando Jordan (12:57)", title=t,
           champ_side="winner")]))
    assert _champs(events, t) == [["Booker T"]], _chain(events, t)


def test_a_ruling_on_a_mapped_belt_overrides_a_co_holders_c_marker():
    """LayCool, 2010: Michelle McCool held the unified Divas title and Layla
    defended it as "(c)" under the Freebird rule. With a ruling naming McCool,
    Layla's defense is not a reign of her own."""
    t = "Unified WWE Divas Title"
    events = {}
    events.update(_ev(1, "2010-09-19", [
        _m(1, ["Michelle McCool"], ["Melina"], "Michelle McCool defeats Melina (c) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    defense = _m(1, ["Layla"], ["Natalya"], "Layla (w/ Michelle McCool ) (c) defeats Natalya", title=t,
                 champ_side="winner")
    defense["title_result"] = {"title": t, "champions": ["Michelle McCool"]}
    events.update(_ev(2, "2010-10-24", [defense]))
    assert _champs(events, t)[-1] == ["Michelle McCool"], _chain(events, t)
    assert ["Layla"] not in _champs(events, t)


def test_a_vacancy_ends_the_reign_and_holds_the_belt_empty():
    """US title, 2005: Booker T's defense against Chris Benoit ended in a
    double pin on 2005-11-25 and the title was vacated; a contender match during
    the vacancy crowns nobody, and the series decider on 2006-01-13 fills it."""
    t = "WWE United States Title"
    events = {}
    events.update(_ev(1, "2005-10-21", [
        _m(1, ["Booker T"], ["Chris Benoit"], "Booker T defeats Chris Benoit (c) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2005-12-09", [
        _m(1, ["Randy Orton"], ["Matt Hardy"], "Randy Orton defeats Matt Hardy", title=t)]))
    events.update(_ev(3, "2006-01-13", [
        _m(1, ["Booker T"], ["Chris Benoit"], "Booker T [4] defeats Chris Benoit [3] - TITLE CHANGE !!!", title=t)]))
    vacancy = [{"title": t, "date": "2005-11-25", "vacate": True}]
    reigns = build_title_reigns(events, offcard=vacancy)[t]
    assert [(r["start"], r["end"], r["champion_names"]) for r in reigns][1:] == [
        ("2005-10-21", "2005-11-25", ["Booker T"]),
        ("2006-01-13", None, ["Booker T"])], reigns


def test_a_champions_defense_the_night_he_is_stripped_does_not_recrown_him():
    """SmackDown 2004-07-08: John Cena defended the US title as "(c)" on the
    show where Kurt Angle then stripped him. The vacancy sorts ahead of that
    night's card, so Cena's own (c) must not hand him the belt back."""
    t = "WWE United States Title"
    events = {}
    events.update(_ev(1, "2004-03-14", [
        _m(1, ["John Cena"], ["The Big Show"], "John Cena defeats The Big Show (c) - TITLE CHANGE !!!",
           title=t, champ_side="loser")]))
    events.update(_ev(2, "2004-07-08", [
        _m(1, ["John Cena"], ["Rene Dupree"], "John Cena (c) defeats Rene Dupree", title=t, champ_side="winner")]))
    events.update(_ev(3, "2004-07-29", [
        _m(1, ["Booker T"], ["John Cena"], "Booker T defeats John Cena - TITLE CHANGE !!!", title=t)]))
    vacancy = [{"title": t, "date": "2004-07-08", "vacate": True, "vacated_by": "John Cena"}]
    reigns = build_title_reigns(events, offcard=vacancy)[t]
    assert [(r["start"], r["end"], r["champion_names"]) for r in reigns][1:] == [
        ("2004-03-14", "2004-07-08", ["John Cena"]),
        ("2004-07-29", None, ["Booker T"])], reigns


def test_a_no_disqualification_title_match_is_not_a_qualifier():
    """SmackDown 2001-04-19: Kane and The Undertaker won the WWF tag titles
    from Edge and Christian in a "No Disqualification Match". The belt filter
    for qualifiers matched inside "Disqualification" and dropped the belt, so
    the reign was missing."""
    t = "WWF World Tag Team Title"
    events = {}
    events.update(_ev(1, "2001-04-01", [
        _m(1, ["Christian", "Edge"], ["Bubba Ray Dudley", "D-Von Dudley"],
           "Christian & Edge defeat The Dudley Boyz (c) - TITLE CHANGE !!!", title=t, champ_side="loser")]))
    events.update(_ev(2, "2001-04-19", [
        _m(1, ["Kane", "The Undertaker"], ["Christian", "Edge"],
           "Kane & The Undertaker defeated Christian & Edge (w/ Rhyno ) (c) (8:14)",
           title=f"{t} No Disqualification Match", champ_side="loser")]))
    assert _champs(events, t)[-1] == ["Kane", "The Undertaker"], _chain(events, t)


def test_one_ruling_per_belt_when_a_match_splits_two_belts():
    """WrestleMania XL: the six-pack ladder match for the undisputed tag
    titles ended with A-Town Down Under taking the SmackDown belts and The
    Awesome Truth the Raw belts. Each belt's ruling moves only its own chain,
    written in Wikipedia's "Championship" spelling."""
    t = "Undisputed WWE Tag Team Title"
    m = _m(1, ["Austin Theory", "Grayson Waller"], ["Finn Balor", "Damian Priest"],
           "A-Town Down Under defeat The Judgment Day (c) ... to win the titles", title=t, champ_side="loser")
    m["title_result"] = [
        {"title": "World Tag Team Championship", "champions": ["The Miz", "R-Truth"]},
        {"title": "WWE Tag Team Championship", "champions": ["Austin Theory", "Grayson Waller"]}]
    events = _ev(1, "2024-04-06", [m])
    reigns = build_title_reigns(events, offcard=())
    assert reigns["WWE World Tag Team Championship"][-1]["champion_names"] == ["The Miz", "R-Truth"]
    assert reigns["WWE Tag Team Championship"][-1]["champion_names"] == ["Austin Theory", "Grayson Waller"]


def test_a_three_man_champion_team_defending_with_any_two_is_one_reign():
    """The New Day won the Raw tag titles at SummerSlam 2015 as Big E and Kofi
    Kingston and defended them as Big E and Xavier Woods under the Freebird
    rule; Wikipedia lists one reign to Roadblock 2016. Each swap of partners
    read as a title change."""
    t = "WWE Tag Team Title"
    new_day = ["Big E", "Kofi Kingston"]
    events = {}
    events.update(_ev(1, "2015-08-23", [
        _m(1, new_day, ["Darren Young", "Titus O'Neil"], "The New Day defeat The Prime Time Players (c) "
           "- TITLE CHANGE !!!", title=t, champ_side="loser")]))
    events.update(_ev(2, "2016-03-14", [
        _m(1, ["Big E", "Xavier Woods"], ["Goldust", "R-Truth"], "The New Day (Big E & Xavier Woods) (c) "
           "defeat Golden Truth", title=t, champ_side="winner")]))
    events.update(_ev(3, "2016-04-04", [
        _m(1, new_day, ["Sheamus", "Rusev"], "The New Day (c) defeat The League Of Nations", title=t,
           champ_side="winner")]))
    assert _champs(events, t)[1:] == [new_day], _chain(events, t)


def test_a_partner_swap_with_a_title_change_marker_is_still_a_new_reign():
    """The Freebird merge needs the champions defending with no marker: a
    marked change between overlapping teams stays a change."""
    t = "WWE Tag Team Title"
    events = {}
    events.update(_ev(1, "2009-06-28", [
        _m(1, ["Chris Jericho", "Edge"], ["Carlito", "Primo"], "Chris Jericho & Edge defeat Carlito & Primo "
           "(c) - TITLE CHANGE !!!", title=t, champ_side="loser")]))
    events.update(_ev(2, "2009-07-26", [
        _m(1, ["Chris Jericho", "The Big Show"], ["Cody Rhodes", "Ted DiBiase"],
           "Chris Jericho & The Big Show (c) defeat Cody Rhodes & Ted DiBiase - TITLE CHANGE !!!", title=t,
           champ_side="winner")]))
    assert _champs(events, t)[-1] == ["Chris Jericho", "The Big Show"], _chain(events, t)


def test_a_tournament_final_named_in_the_belt_string_fills_the_vacant_belt():
    """SmackDown 2020-06-12: AJ Styles won the vacant Intercontinental title in
    the final of a tournament, written "WWE Intercontinental Championship
    Tournament - Final". The earlier rounds move nothing."""
    events = {}
    events.update(_ev(1, "2020-05-15", [
        _m(1, ["AJ Styles"], ["Shinsuke Nakamura"], "AJ Styles defeats Shinsuke Nakamura",
           title="WWE Intercontinental Championship Tournament - Round 1", match_type="Tournament")]))
    events.update(_ev(2, "2020-06-12", [
        _m(1, ["AJ Styles"], ["Daniel Bryan"], "AJ Styles defeats Daniel Bryan to win the vacant title",
           title="WWE Intercontinental Championship Tournament - Final", match_type="Tournament")]))
    reigns = build_title_reigns(events, offcard=())["WWE Intercontinental Title"]
    assert [(r["start"], r["champion_names"]) for r in reigns] == [("2020-06-12", ["AJ Styles"])], reigns


def test_a_freebird_defense_with_the_holders_in_the_corner_is_one_reign():
    """Raw 2006-05-15: the Spirit Squad defended the World tag titles as Johnny
    and Nicky with Mikey and Mitch at ringside; Kenny and Mikey had won them.
    Wikipedia lists one Spirit Squad reign, so the corner counts as the team."""
    t = "World Tag Team Title"
    events = {}
    events.update(_ev(1, "2006-04-03", [
        _m(1, ["Kenny", "Mikey"], ["Kane", "The Big Show"], "The Spirit Squad (Kenny & Mikey) defeat Kane & "
           "The Big Show (c) - TITLE CHANGE !!!", title=t, champ_side="loser")]))
    defense = _m(1, ["Johnny", "Nicky"], ["Goldust", "Snitsky"], "The Spirit Squad (Johnny & Nicky) "
                 "(w/ Mikey & Mitch ) (c) defeat Goldust & Snitsky", title=t, champ_side="winner")
    defense["teams"][0]["accompaniment"] = "Mikey & Mitch"
    events.update(_ev(2, "2006-05-15", [defense]))
    assert _champs(events, t)[1:] == [["Kenny", "Mikey"]], _chain(events, t)
