"""A stable/tag-team name must not become a roster entry with a win/loss record.

The modern (SmackDown Hotel) source writes "[[The Usos]] ([[Jey Uso]] and
[[Jimmy Uso]])" and the parser flattened the group label into the participant
list ALONGSIDE its members, so The Usos, #DIY, Imperium and ~17 others showed up
in the roster as if they were people.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import (  # noqa: E402
    build_wrestlers_index, collect_group_labels, strip_phantom_group_labels, _label_key)


def _ev(eid, raw, teams):
    return {str(eid): {"id": eid, "air_date": "2022-01-01", "show_type": "Raw",
                       "title": "Show", "matches": [
        {"match_order": 1, "match_type": "Tag Team Match", "title_at_stake": None,
         "duration_seconds": 600, "raw_description": raw, "teams": teams}]}}


def _team(n, names, win):
    return {"team_number": n, "team_name": " & ".join(names), "participants": list(names),
            "was_winner": win, "match_outcome": "win" if win else "loss",
            "was_champion_entering": False}


USOS_RAW = ("[[The Bloodline]] ([[Solo Sikoa]] and [[Jacob Fatu]]) defeated "
            "[[Roman Reigns]] and [[The Usos]] ([[Jey Uso]] and [[Jimmy Uso]])")


def test_group_label_is_detected_from_its_expansion():
    events = _ev(1, USOS_RAW, [
        _team(1, ["Solo Sikoa", "Jacob Fatu"], True),
        _team(2, ["Roman Reigns", "The Usos", "Jey Uso", "Jimmy Uso"], False)])
    labels = collect_group_labels(events)
    assert _label_key("The Usos") in labels
    assert _label_key("The Bloodline") in labels


def test_the_and_case_are_one_label():
    assert _label_key("The New Day") == _label_key("New Day")
    assert _label_key("#DIY") == _label_key("DIY")


def test_a_brand_title_descriptor_is_not_a_group():
    # "[[Cody Rhodes]] ([[SmackDown]]'s [[Undisputed WWE Champion]])": the
    # parenthetical is a brand and a belt, and neither wrestles, so Cody is not a
    # group. Without the competitor test he would be flagged and vanish from the
    # roster.
    raw = ("[[Cody Rhodes]] ([[SmackDown (WWE brand)|SmackDown]]'s [[Undisputed WWE Champion]]) "
           "defeated [[Gunther (wrestler)|Gunther]] ([[Raw (WWE brand)|Raw]]'s [[World Heavyweight Champion]])")
    events = _ev(1, raw, [
        _team(1, ["Cody Rhodes"], True), _team(2, ["Gunther"], False)])
    labels = collect_group_labels(events)
    assert _label_key("Cody Rhodes") not in labels
    assert _label_key("Gunther") not in labels


def test_a_survivor_series_team_label_is_not_a_group():
    # "Team Asuka (Becky Lynch, ..., Asuka, ...)" — the label is plain text, not
    # a wikilink, so it was never a participant; and even the name "Asuka" inside
    # must not be read as the group.
    raw = ("Team Rhea ([[Rhea Ripley]] and [[Iyo Sky]]) defeated "
           "Team Asuka ([[Becky Lynch]], [[Asuka (wrestler)|Asuka]], and [[Kairi Sane]])")
    events = _ev(1, raw, [
        _team(1, ["Rhea Ripley", "Iyo Sky"], True),
        _team(2, ["Becky Lynch", "Asuka", "Kairi Sane"], False)])
    labels = collect_group_labels(events)
    assert _label_key("Asuka") not in labels
    assert _label_key("Team Asuka") not in labels


def test_expandable_label_is_stripped_and_leaves_the_roster():
    events = _ev(1, USOS_RAW, [
        _team(1, ["Solo Sikoa", "Jacob Fatu"], True),
        _team(2, ["Roman Reigns", "The Usos", "Jey Uso", "Jimmy Uso"], False)])
    trimmed = strip_phantom_group_labels(events)
    assert trimmed == 1
    team = events["1"]["matches"][0]["teams"][1]
    assert team["participants"] == ["Roman Reigns", "Jey Uso", "Jimmy Uso"], "The Usos not dropped"
    wrestlers, _ = build_wrestlers_index(events)
    names = {w["name"] for w in wrestlers.values()}
    assert "The Usos" not in names
    assert {"Roman Reigns", "Jey Uso", "Jimmy Uso"} <= names


def test_a_bare_label_leaves_the_roster_but_stays_on_the_card():
    # A gauntlet entry the source never expanded: only "Imperium" appears. It
    # must not be a roster person, but it stays a participant so the card still
    # shows the competitor (as plain text, the frontend's non-indexed path).
    expand = _ev(1, "[[Imperium]] ([[Ludwig Kaiser]] and [[Giovanni Vinci]]) beat x",
                 [_team(1, ["Imperium", "Ludwig Kaiser", "Giovanni Vinci"], True),
                  _team(2, ["Ludwig Kaiser", "Giovanni Vinci"], False)])  # members are competitors
    bare = _ev(2, "[[The Creed Brothers]] ([[Brutus Creed]] and [[Julius Creed]]) beat [[Imperium]]",
               [_team(1, ["Brutus Creed", "Julius Creed"], True),
                _team(2, ["Imperium"], False)])
    events = {**expand, **bare}
    strip_phantom_group_labels(events)
    # bare Imperium is untouched in participants...
    assert events["2"]["matches"][0]["teams"][1]["participants"] == ["Imperium"]
    # ...but never a wrestler
    wrestlers, _ = build_wrestlers_index(events)
    assert "Imperium" not in {w["name"] for w in wrestlers.values()}


def test_a_named_tag_team_with_no_expansion_is_left_alone():
    # "The Creed Brothers (Brutus Creed and Julius Creed)" - here the parser
    # correctly kept only the members, so there is nothing to strip and the
    # members remain wrestlers.
    events = _ev(1, "[[The Creed Brothers]] ([[Brutus Creed]] and [[Julius Creed]]) beat x",
                 [_team(1, ["Brutus Creed", "Julius Creed"], True),
                  _team(2, ["Axiom", "Nathan Frazer"], False)])
    assert strip_phantom_group_labels(events) == 0
    wrestlers, _ = build_wrestlers_index(events)
    assert {"Brutus Creed", "Julius Creed"} <= {w["name"] for w in wrestlers.values()}
