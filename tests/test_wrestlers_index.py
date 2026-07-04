"""build_wrestlers_index, the title normalizer, and build_title_reigns.
These are the pieces that make the All-time roster numbers true; none of them
had a single test before the 2026-07 accuracy overhaul found bugs in all three."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import (  # noqa: E402
    _get_component_titles, build_title_reigns, build_wrestlers_index,
    is_placeholder_name)


def team(names, winner, outcome=None, champ=False):
    return {
        "team_number": 1, "team_name": " & ".join(names),
        "participants": list(names), "was_winner": winner,
        "match_outcome": outcome if outcome is not None
            else (None if winner is None else ("win" if winner else "loss")),
        "was_champion_entering": champ, "accompaniment": None,
    }


def match(mid, teams, order=1, title=None):
    return {"id": mid, "match_order": order, "match_type": None,
            "stipulation": None, "title_at_stake": title,
            "duration_seconds": None, "raw_description": "", "teams": teams}


def event(eid, date, show, matches):
    return {str(eid): {"id": eid, "air_date": date, "show_type": show,
                       "title": show, "ppv_name": None,
                       "match_count": len(matches), "matches": matches}}


# ---- stat aggregation and alias merging ------------------------------------

def test_totals_satisfy_outcome_invariant():
    events = event(1, "2001-01-01", "Raw", [
        match(1, [team(["A"], True), team(["B"], False)]),
        match(2, [team(["A"], None, "no-contest"), team(["B"], None, "no-contest")], order=2),
    ])
    wrestlers, by_name = build_wrestlers_index(events)
    a = wrestlers[by_name["A"]]
    assert a["total_matches"] == 2
    assert (a["wins"], a["losses"], a["no_contests"]) == (1, 0, 1)


def test_canon_merges_stats_and_maps_alias_to_canonical_slug():
    events = {}
    events.update(event(1, "2001-01-01", "Raw", [match(1, [team(["K-Kwik"], True), team(["X"], False)])]))
    events.update(event(2, "2010-01-01", "Raw", [match(2, [team(["R-Truth"], True), team(["X"], False)])]))
    canon = {"K-Kwik": "R-Truth"}
    wrestlers, by_name = build_wrestlers_index(events, canon=lambda n: canon.get(n, n))
    slug = by_name["R-Truth"]
    assert by_name["K-Kwik"] == slug          # era name links to the merged profile
    w = wrestlers[slug]
    assert w["total_matches"] == 2
    assert w["active_years"] == [2001, 2010]
    assert "K-Kwik" not in {x["name"] for x in wrestlers.values()}


def test_placeholders_stay_out_of_the_index():
    events = event(1, "2001-01-01", "Raw", [
        match(1, [team(["Real Guy"], True), team(["a jobber"], False)]),
    ])
    wrestlers, by_name = build_wrestlers_index(events)
    assert "a jobber" not in by_name
    assert len(wrestlers) == 1
    assert is_placeholder_name("3 local athletes")
    assert not is_placeholder_name("Randy Orton")


# ---- title normalization ---------------------------------------------------

def test_belt_survives_quoted_stipulation_prefix():
    got = _get_component_titles('"If Bryan loses he\'s banned" WWE Universal Championship')
    assert got == ["WWE Universal Title"]


def test_pure_stipulation_is_not_a_belt():
    assert _get_component_titles('"If Hayes wins, he gets a WWE United States Championship Match"') == []
    assert _get_component_titles('"Winner gets a shot" Triple Threat Match') == []


def test_qualifier_and_contender_matches_are_filtered():
    assert _get_component_titles("WWE Championship Elimination Chamber Qualifying Match") == []
    assert _get_component_titles("WWE Cruiserweight Title Match Contendership No # 1") == []


def test_match_type_decoration_is_stripped():
    assert _get_component_titles("WWE Intercontinental Championship Steel Cage Match") == ["WWE Intercontinental Title"]
    assert _get_component_titles("WWE Raw Women's Championship Lumberjack Match") == ["WWE Raw Women's Title"]


def test_spelling_variants_unify():
    assert _get_component_titles("WWE RAW Tag Team Championship") == ["WWE Raw Tag Team Title"]
    assert _get_component_titles("WWE Intercontinental Championship") == _get_component_titles("WWE Intercontinental Title")


def test_composite_and_unification_matches_yield_each_belt():
    assert _get_component_titles("WWE Title / WWE Universal Title") == ["WWE Title", "WWE Universal Title"]
    got = _get_component_titles("WWE Raw Tag Team Championship vs. WWE SmackDown Tag Team Championship Unification Match")
    assert got == ["WWE Raw Tag Team Title", "WWE SmackDown Tag Team Title"]


def test_vacant_marker_is_not_a_belt():
    assert _get_component_titles("vacant / Million Dollar Championship") == ["Million Dollar Title"]


# ---- reign chains and reign-derived title wins ------------------------------

def title_match(mid, champ_names, chall_names, chall_wins, title, outcome=None, order=1):
    champ = team(champ_names, not chall_wins, champ=True)
    chall = team(chall_names, chall_wins, outcome=outcome)
    return match(mid, [champ, chall], order=order, title=title)


def test_dq_win_does_not_move_the_belt():
    events = {}
    events.update(event(1, "2001-01-01", "PPV",
        [title_match(1, ["Champ"], ["Challenger"], True, "WWE Title")]))
    events.update(event(2, "2001-02-01", "PPV",
        [title_match(2, ["Challenger"], ["Other"], True, "WWE Title", outcome="dq-win")]))
    reigns = build_title_reigns(events)["WWE Title"]
    # Challenger won the belt cleanly in Jan; Other's February DQ win must not
    # start a reign.
    assert [r["champion_names"] for r in reigns][-1] == ["Challenger"]


def test_belt_cannot_change_hands_without_its_champion():
    events = {}
    events.update(event(1, "2001-01-01", "PPV",
        [title_match(1, ["Champ"], ["NewChamp"], True, "WWE Title")]))
    # A mislabeled contender match: no team was champion entering.
    events.update(event(2, "2001-02-01", "Raw", [match(2, [
        team(["Corbin"], True), team(["Someone"], False)], title="WWE Title")]))
    reigns = build_title_reigns(events)["WWE Title"]
    assert [r["champion_names"] for r in reigns][-1] == ["NewChamp"]
    assert ["Corbin"] not in [r["champion_names"] for r in reigns]


def test_title_wins_derive_from_reigns_when_provided():
    events = {}
    events.update(event(1, "2001-01-01", "PPV",
        [title_match(1, ["Champ"], ["NewChamp"], True, "WWE Title")]))
    events.update(event(2, "2001-02-01", "Raw", [match(2, [
        team(["Corbin"], True), team(["Someone"], False)], title="WWE Title")]))
    reigns = build_title_reigns(events)
    wrestlers, by_name = build_wrestlers_index(events, title_reigns=reigns)
    assert dict(wrestlers[by_name["NewChamp"]]["title_wins"]) == {"WWE Title": 1}
    assert wrestlers[by_name["Corbin"]]["title_wins"] == []      # phantom win gone
    # Champ held the belt entering the corpus: observing the reign is not a win.
    assert wrestlers[by_name["Champ"]]["title_wins"] == []
