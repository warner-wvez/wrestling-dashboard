"""
Unit tests for fandom_scraper._canonicalize_name.

Run from project root:
    .venv/bin/python -m unittest tests.test_canonicalize_name
or:
    .venv/bin/python tests/test_canonicalize_name.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fandom_scraper import _canonicalize_name  # noqa: E402


class TestExistingPatterns(unittest.TestCase):
    """Phase 1f baseline patterns (paren leaks, accompaniments, outcome prose)."""

    def test_clean_name_passthrough(self):
        self.assertEqual(_canonicalize_name("Chris Benoit"), "Chris Benoit")
        self.assertEqual(_canonicalize_name("Stone Cold Steve Austin"), "Stone Cold Steve Austin")

    def test_title_holder_prefix_stripped(self):
        self.assertEqual(_canonicalize_name("WWE IC Champion Chris Benoit"), "Chris Benoit")
        self.assertEqual(_canonicalize_name("WWE Champion Brock Lesnar"), "Brock Lesnar")
        self.assertEqual(_canonicalize_name("WCW World Champion The Rock"), "The Rock")

    def test_outcome_modifier_stripped(self):
        self.assertEqual(_canonicalize_name("Triple H by Count Out"), "Triple H")
        self.assertEqual(_canonicalize_name("Brock Lesnar by referee's decision"), "Brock Lesnar")
        self.assertEqual(_canonicalize_name("Christian by submission"), "Christian")
        self.assertEqual(_canonicalize_name("Foo by Matchabbruch"), "Foo")

    def test_outcome_prose_stripped(self):
        self.assertEqual(_canonicalize_name("Chris Benoit to retain the WWE Tag Team Championship"), "Chris Benoit")
        self.assertEqual(_canonicalize_name("Christian to win the WWF European Championship"), "Christian")

    def test_trailing_accompaniment_stripped(self):
        self.assertEqual(_canonicalize_name("Triple H (w/ Stephanie McMahon"), "Triple H")
        self.assertEqual(_canonicalize_name("Triple H (w/ Stephanie McMahon)"), "Triple H")
        self.assertEqual(_canonicalize_name("Chris Benoit (w/ Axl Rotten"), "Chris Benoit")

    def test_leading_paren_context_stripped(self):
        self.assertEqual(
            _canonicalize_name("(Special Referee: Jacqueline ): Chris Jericho"),
            "Chris Jericho",
        )
        self.assertEqual(
            _canonicalize_name("Steel Cage Match (Special Referee: Kurt Angle ): Brock Lesnar"),
            "Brock Lesnar",
        )

    def test_directional_paren_strips(self):
        self.assertEqual(_canonicalize_name("The Dudley Boyz ( Bubba Ray Dudley"), "Bubba Ray Dudley")
        self.assertEqual(_canonicalize_name("D-Von Dudley )"), "D-Von Dudley")
        self.assertEqual(_canonicalize_name("Triple H )"), "Triple H")
        self.assertEqual(_canonicalize_name("The Usos ( Jey Uso"), "Jey Uso")
        self.assertEqual(_canonicalize_name("Awesome Truth ( R-Truth"), "R-Truth")

    def test_trailing_bracket_num_stripped(self):
        self.assertEqual(_canonicalize_name("Brock Lesnar [5]"), "Brock Lesnar")
        self.assertEqual(_canonicalize_name("Foo [2:1]"), "Foo")  # 2-char "Fo" survives


class TestRoundARolePrefix(unittest.TestCase):
    """Round A: leading role prefix without parens."""

    def test_special_guest_referee(self):
        self.assertEqual(_canonicalize_name("Special Guest Referee: Triple H"), "Triple H")
        self.assertEqual(_canonicalize_name("special guest referee: foo bar"), "foo bar")

    def test_guest_referee(self):
        self.assertEqual(_canonicalize_name("Guest Referee: John Cena"), "John Cena")

    def test_special_referee(self):
        self.assertEqual(_canonicalize_name("Special Referee: Foo Bar"), "Foo Bar")

    def test_guest_host(self):
        self.assertEqual(_canonicalize_name("Guest Host: John Cena"), "John Cena")

    def test_special_enforcer(self):
        self.assertEqual(_canonicalize_name("Special Enforcer: Foo"), "Foo")

    def test_commentator(self):
        self.assertEqual(_canonicalize_name("Commentator: Joe Smith"), "Joe Smith")

    def test_referee_alone(self):
        self.assertEqual(_canonicalize_name("Referee: Mike Chioda"), "Mike Chioda")


class TestRoundAMatchDescription(unittest.TestCase):
    """Round A: match-description filter."""

    def test_three_way_dropped(self):
        self.assertEqual(
            _canonicalize_name("The Undertaker vs. Triple H vs. Vladimir Kozlov"),
            "",
        )

    def test_two_way_dropped(self):
        self.assertEqual(_canonicalize_name("Foo vs. Bar"), "")
        self.assertEqual(
            _canonicalize_name("CM Punk vs. John Cena"),
            "",
        )

    def test_vs_without_period_NOT_dropped(self):
        # Cagematch sometimes uses "vs" without period; spec requires literal " vs. ".
        # We don't auto-drop these (they could be legitimate ring-name fragments).
        self.assertEqual(_canonicalize_name("Foo vs Bar"), "Foo vs Bar")

    def test_vs_after_strip_also_dropped(self):
        # If a strip exposes " vs. ", the second-pass filter still catches it.
        self.assertEqual(
            _canonicalize_name("Steel Cage Match (Special Referee: Mick Foley ): Triple H vs. Shawn Michaels"),
            "",
        )


class TestRoundAAnnotations(unittest.TestCase):
    """Round A: trailing TITLE CHANGE / ended / DRAFT annotations."""

    def test_title_change_stripped(self):
        self.assertEqual(_canonicalize_name("Triple H - TITLE CHANGE !!!"), "Triple H")
        self.assertEqual(_canonicalize_name("Foo - TITLE CHANGE!!!"), "Foo")
        self.assertEqual(_canonicalize_name("Foo - title change"), "Foo")

    def test_ended_stripped(self):
        self.assertEqual(_canonicalize_name("Triple H ended"), "Triple H")
        self.assertEqual(_canonicalize_name("Booker T ended at 04:32"), "Booker T")

    def test_draft_stripped(self):
        self.assertEqual(_canonicalize_name("Foo - DRAFT"), "Foo")
        self.assertEqual(_canonicalize_name("Foo - DRAFTED to Raw"), "Foo")
        self.assertEqual(_canonicalize_name("Foo (DRAFT"), "Foo")
        self.assertEqual(_canonicalize_name("Foo (DRAFTED to SmackDown"), "Foo")


class TestRoundAParenDigit(unittest.TestCase):
    """Round A side-effect: handle bracket-leak with digits inside paren."""

    def test_paren_digit_stripped(self):
        # Charlotte Flair (10:324 → "Charlotte Flair" not "10:324"
        self.assertEqual(_canonicalize_name("Charlotte Flair (10:324"), "Charlotte Flair")
        self.assertEqual(_canonicalize_name("Foo (5:30"), "Foo")
        self.assertEqual(_canonicalize_name("Foo (5:30)"), "Foo")


class TestRoundBJunkFilter(unittest.TestCase):
    """Round B: pattern junk filter (no-alpha names)."""

    def test_pure_digits_dropped(self):
        self.assertEqual(_canonicalize_name("10"), "")
        self.assertEqual(_canonicalize_name("200"), "")

    def test_digit_with_punct_dropped(self):
        self.assertEqual(_canonicalize_name("10:324"), "")
        self.assertEqual(_canonicalize_name("2:1"), "")
        self.assertEqual(_canonicalize_name("5/"), "")

    def test_pure_punct_dropped(self):
        self.assertEqual(_canonicalize_name("..."), "")
        self.assertEqual(_canonicalize_name("???"), "")  # also filtered later by Phase 1d

    def test_real_ring_names_kept(self):
        self.assertEqual(_canonicalize_name("AJ"), "AJ")           # AJ Lee
        self.assertEqual(_canonicalize_name("B²"), "B²")           # B-2
        self.assertEqual(_canonicalize_name("2 Cold Scorpio"), "2 Cold Scorpio")
        self.assertEqual(_canonicalize_name("3MB"), "3MB")         # alpha char "M"

    def test_single_char_dropped(self):
        self.assertEqual(_canonicalize_name("A"), "")
        self.assertEqual(_canonicalize_name("D"), "")
        self.assertEqual(_canonicalize_name("R"), "")
        self.assertEqual(_canonicalize_name("X"), "")
        self.assertEqual(_canonicalize_name("1"), "")


class TestRoundCNarrative(unittest.TestCase):
    """Round C: narrative result-prose strips (via/when/defeated/applied/etc.)."""

    # _TRAILING_VIA_RE
    def test_via_disqualification(self):
        self.assertEqual(_canonicalize_name("Kurt Angle via disqualification"), "Kurt Angle")

    def test_via_submission(self):
        self.assertEqual(_canonicalize_name("John Cena via submission"), "John Cena")

    def test_via_with_when_clause(self):
        self.assertEqual(
            _canonicalize_name("Kurt Angle via count-out when Angle left ringside to chase Rey Mysterio Jr. backstage"),
            "Kurt Angle",
        )

    def test_via_with_when_chavo(self):
        # Note: trailing "Jr." loses its period via end-punct trim, expected.
        self.assertEqual(
            _canonicalize_name("Chavo Guerrero Jr. via disqualification when Kurt Angle interfered"),
            "Chavo Guerrero Jr",
        )

    # _TRAILING_NARRATIVE_VERBS_RE
    def test_trailing_defeated(self):
        self.assertEqual(_canonicalize_name("Batista defeated D-Von with the Bonzai Drop"), "Batista")

    def test_trailing_applied(self):
        self.assertEqual(_canonicalize_name("Brock Lesnar applied the ankle lock"), "Brock Lesnar")

    def test_trailing_pinned(self):
        self.assertEqual(_canonicalize_name("Stone Cold pinned The Rock"), "Stone Cold")

    def test_trailing_eliminated(self):
        self.assertEqual(_canonicalize_name("Edge eliminated The Undertaker"), "Edge")

    def test_trailing_counted_out(self):
        self.assertEqual(_canonicalize_name("Foo counted out Bar"), "Foo")

    # _LEADING_NARRATIVE_VERB_RE
    def test_leading_applied_dropped(self):
        self.assertEqual(_canonicalize_name("applied the ankle lock on Mysterio"), "")

    def test_leading_defeated_dropped(self):
        self.assertEqual(_canonicalize_name("defeated the champion in 5 minutes"), "")

    def test_leading_pinned_dropped(self):
        self.assertEqual(_canonicalize_name("pinned X with a roll-up"), "")

    # _TRAILING_WHEN_RE
    def test_trailing_when_simple(self):
        self.assertEqual(_canonicalize_name("Foo Bar when something happened"), "Foo Bar")

    def test_trailing_when_batista_compound(self):
        # Combined narrative: " when " strip handles it after " defeated " also strips.
        self.assertEqual(
            _canonicalize_name("Batista when Rikishi defeated D-Von with the Bonzai Drop after Batista hit a spinebuster on his partner"),
            "Batista",
        )

    def test_trailing_when_rejected_for_short_prefix(self):
        # "X when Y" → strip would yield "X" (1 char); strip rejected. Result kept as-is,
        # then later filters apply (no-alpha + len <= 1 don't fire on "X when Y").
        self.assertEqual(_canonicalize_name("X when Y"), "X when Y")


class TestRoundCExactExamples(unittest.TestCase):
    """The 5 specific examples from the spec — must all collapse cleanly."""

    def test_example_1(self):
        self.assertEqual(
            _canonicalize_name("Batista when Rikishi defeated D-Von with the Bonazi Drop after Batista hit a spinebuster on his partner"),
            "Batista",
        )

    def test_example_2(self):
        self.assertEqual(_canonicalize_name("applied the ankle lock on Mysterio"), "")

    def test_example_3(self):
        self.assertEqual(
            _canonicalize_name("Chavo Guerrero Jr. via disqualification when Kurt Angle interfered"),
            "Chavo Guerrero Jr",
        )

    def test_example_4(self):
        self.assertEqual(
            _canonicalize_name("Kurt Angle via count-out when Angle left ringside to chase Rey Mysterio Jr. backstage"),
            "Kurt Angle",
        )

    def test_example_5(self):
        self.assertEqual(_canonicalize_name("Kurt Angle via disqualification"), "Kurt Angle")


class TestRoundDFinishingMoveNarrative(unittest.TestCase):
    """Round D: finishing-move + connector strips + leading pronoun drop."""

    # _TRAILING_WITH_THE_RE
    def test_with_the_finishing_move(self):
        self.assertEqual(_canonicalize_name("Foo with the F5"), "Foo")

    def test_with_the_compound(self):
        self.assertEqual(
            _canonicalize_name("The Hurricane with the Twist of Fate after a low blow"),
            "The Hurricane",
        )

    def test_with_the_long_narrative(self):
        self.assertEqual(
            _canonicalize_name("Nidia with the somersault sit-down splash onto a standing Nidia after knocking Noble off the apron; had Nidia won the title"),
            "Nidia",
        )

    # _TRAILING_WITH_A_RE
    def test_with_a_simple(self):
        self.assertEqual(_canonicalize_name("Foo with a chair"), "Foo")

    def test_with_a_long_narrative(self):
        self.assertEqual(
            _canonicalize_name("Matt Hardy with a roll up as Matt was distracted by Kane 's pyro"),
            "Matt Hardy",
        )

    def test_with_a_rejected_for_short_prefix(self):
        # "X with a move" → strip would yield "X" (1 char); strip rejected.
        self.assertEqual(_canonicalize_name("X with a move"), "X with a move")

    # _TRAILING_AFTER_RE
    def test_after_simple(self):
        self.assertEqual(_canonicalize_name("Foo after Bar"), "Foo")

    def test_after_torrie(self):
        self.assertEqual(
            _canonicalize_name("Torrie Wilson after Noble interfered"),
            "Torrie Wilson",
        )

    def test_after_rejected_for_short_prefix(self):
        # "X after Y" → strip would yield "X" (1 char); strip rejected.
        self.assertEqual(_canonicalize_name("X after Y"), "X after Y")

    # _LEADING_PRONOUN_RE
    def test_leading_she_dropped(self):
        self.assertEqual(
            _canonicalize_name("she would have flashed the crowd; after the match"),
            "",
        )

    def test_leading_he_dropped(self):
        self.assertEqual(_canonicalize_name("he hit the move"), "")

    def test_leading_they_dropped(self):
        self.assertEqual(_canonicalize_name("they ran in"), "")

    def test_leading_uppercase_pronoun_kept(self):
        # Uppercase "She" or "He" could be a stylized name (rare); only lowercase drops.
        # This is a documented edge case; if it surfaces we'll handle separately.
        self.assertEqual(_canonicalize_name("She Wolf"), "She Wolf")


class TestRoundDSurfacedOrphans(unittest.TestCase):
    """The 7 specific orphans surfaced by the Round C suspicious-name scan."""

    def test_orphan_1(self):
        self.assertEqual(_canonicalize_name("Chris Benoit with the Rock Bottom"), "Chris Benoit")

    def test_orphan_2(self):
        self.assertEqual(_canonicalize_name("Rikishi with the F5 as Rikishi prepared to"), "Rikishi")

    def test_orphan_3(self):
        self.assertEqual(
            _canonicalize_name("The Hurricane with the Twist of Fate after a low blow"),
            "The Hurricane",
        )

    def test_orphan_4(self):
        self.assertEqual(
            _canonicalize_name("Nidia with the somersault sit-down splash onto a standing Nidia after knocking Noble off the apron; had Nidia won the title"),
            "Nidia",
        )

    def test_orphan_5(self):
        self.assertEqual(
            _canonicalize_name("Matt Hardy with a roll up as Matt was distracted by Kane 's pyro"),
            "Matt Hardy",
        )

    def test_orphan_6(self):
        self.assertEqual(
            _canonicalize_name("Torrie Wilson after Noble interfered"),
            "Torrie Wilson",
        )

    def test_orphan_7(self):
        self.assertEqual(
            _canonicalize_name("she would have flashed the crowd; after the match"),
            "",
        )


class TestEmptyAndEdgeCases(unittest.TestCase):
    def test_empty_inputs(self):
        self.assertEqual(_canonicalize_name(""), "")
        self.assertEqual(_canonicalize_name("   "), "")
        self.assertEqual(_canonicalize_name(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
