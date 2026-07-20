"""A brand or belt in parentheses describes the wrestler; it is not a team.

Wikipedia writes champion-vs-champion billing as "[[Liv Morgan]] ([[Raw]]'s
[[Women's World Champion]])". Read as a member list, that put "SmackDown" on
cards as a competitor, and once those phantoms existed, the group-label pass
saw "Liv Morgan (two competitors)" and reclassified four real champions as
stables, deleting their profiles from the roster.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import collect_group_labels, _label_key  # noqa: E402
from src.wikipedia_ppv import parse_side  # noqa: E402

CHAMP_VS_CHAMP = ("[[Liv Morgan]] ([[Raw (WWE brand)|Raw]]'s [[Women's World "
                  "Championship (WWE)|Women's World Champion]]) defeated "
                  "[[Nia Jax]] ([[SmackDown (WWE brand)|SmackDown]]'s "
                  "[[WWE Women's Champion]]) by [[pinfall]]")


def test_brand_paren_is_dropped_not_expanded():
    side = parse_side("[[Nia Jax]] ([[SmackDown (WWE brand)|SmackDown]])")
    assert side["participants"] == ["Nia Jax"]
    assert side["team_name"] is None


def test_brand_possessive_belt_paren_is_dropped_not_expanded():
    side = parse_side("[[Liv Morgan]] ([[Raw (WWE brand)|Raw]]'s "
                      "[[Women's World Championship (WWE)|Women's World Champion]])")
    assert side["participants"] == ["Liv Morgan"]
    assert side["team_name"] is None


def test_a_real_team_paren_still_expands():
    side = parse_side("[[The New Day]] ([[Kofi Kingston]] and [[Xavier Woods]])")
    assert side["team_name"] == "The New Day"
    assert side["participants"] == ["Kofi Kingston", "Xavier Woods"]


def test_champion_vs_champion_never_labels_the_champions_as_groups():
    # Even with phantom "competitors" named after brands and belts in the
    # corpus, the descriptor paren must not qualify as a member expansion.
    events = {"1": {"matches": [
        {"raw_description": CHAMP_VS_CHAMP,
         "teams": [{"participants": ["Liv Morgan", "Raw", "Women's World Champion"]},
                   {"participants": ["Nia Jax", "SmackDown", "WWE Women's Champion"]}]},
    ]}}
    labels = collect_group_labels(events)
    assert _label_key("Liv Morgan") not in labels
    assert _label_key("Nia Jax") not in labels
