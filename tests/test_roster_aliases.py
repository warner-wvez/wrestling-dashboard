"""Alias resolution: normkey identity rules and build_canon_map precedence.
These encode the invariants behind the 2026-07 roster-accuracy overhaul: a
regression in any of them silently splits or mis-merges wrestler careers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.roster_aliases import (  # noqa: E402
    CURATED, DISPLAY_SPELLING, PROTECTED, build_canon_map, load_roster_snapshot, normkey,
    save_roster_snapshot)


# ---- normkey ---------------------------------------------------------------

def test_normkey_spelling_variants_share_a_key():
    assert normkey("The Big Show") == normkey("Big Show")
    assert normkey("IYO SKY") == normkey("Iyo Sky")
    assert normkey("D'Lo Brown") == normkey("D-Lo Brown")


def test_normkey_transliterates_diacritics():
    assert normkey("Rey Fénix") == normkey("Rey Fenix") == "reyfenix"
    assert normkey("Finn Bálor") == normkey("Finn Balor")


def test_normkey_strips_quoted_nicknames():
    assert normkey('"Dirty" Dominik Mysterio') == normkey("Dominik Mysterio")
    assert normkey('"The Demon" Finn Bálor') == normkey("Finn Balor")
    assert normkey('Ashante "Thee" Adonis') == normkey("Ashante Adonis")
    assert normkey("“Dirty” Dominik Mysterio") == normkey("Dominik Mysterio")  # curly quotes


def test_normkey_fully_quoted_name_keeps_its_key():
    # A name that is nothing but its quoted part must not key on ''.
    assert normkey('"Cowboy"') == "cowboy"
    assert normkey('"???"') != ""


# ---- build_canon_map -------------------------------------------------------

def counts(*names):
    return {n: 10 for n in names}


def test_roster_pairs_slug_encodes_a_rename():
    # SDH page: profile slug keeps the old name, title is the current name.
    canon = build_canon_map(counts("WALTER", "Gunther"),
                            roster_pairs=[("walter", "Gunther")])
    assert canon["WALTER"] == "Gunther"
    assert canon["Gunther"] == "Gunther"


def test_curated_outranks_scrape_and_owns_both_keys():
    # The page lists slug angel-garza under the current name "Angel"; curated
    # says the canonical is "Angel Garza". BOTH raw names must land on it, or
    # the pair stays half-merged.
    canon = build_canon_map(counts("Angel", "Angel Garza"),
                            roster_pairs=[("angel-garza", "Angel")],
                            curated={"Angel": "Angel Garza"})
    assert canon["Angel"] == "Angel Garza"
    assert canon["Angel Garza"] == "Angel Garza"


def test_protected_names_never_alias_away():
    # The live page lists Natalya under a nickname; PROTECTED must win.
    canon = build_canon_map(counts("Natalya"),
                            roster_pairs=[("natalya", "Nattie")])
    assert canon["Natalya"] == "Natalya"


def test_spelling_variant_group_uses_dominant_form():
    canon = build_canon_map({"Big Show": 100, "The Big Show": 3},
                            roster_pairs=[])
    assert canon["The Big Show"] == "Big Show"
    assert canon["Big Show"] == "Big Show"


def test_display_is_the_most_used_ring_name_not_the_curated_target():
    # Curated declares identity ("these are one human"), usage picks the label.
    # The real case: the corpus bills him "Bradshaw" 102 times and "John
    # Bradshaw Layfield" 152, and CURATED points both at "JBL", a string that
    # appears in ZERO matches. Naming the roster entry after the merge target
    # listed a superstar under a name he is never billed under.
    canon = build_canon_map({"Bradshaw": 102, "John Bradshaw Layfield": 152},
                            roster_pairs=[],
                            curated={"Bradshaw": "JBL",
                                     "John Bradshaw Layfield": "JBL"})
    assert canon["Bradshaw"] == "John Bradshaw Layfield"
    assert canon["John Bradshaw Layfield"] == "John Bradshaw Layfield"


def test_a_merge_target_with_no_matches_is_never_displayed():
    canon = build_canon_map({"T-BAR": 29, "Dijak": 5, "Dominik Dijakovic": 1},
                            roster_pairs=[],
                            curated={"T-BAR": "Dijak", "Dominik Dijakovic": "Dijak"})
    # All three are one human...
    assert len({canon["T-BAR"], canon["Dijak"], canon["Dominik Dijakovic"]}) == 1
    # ...labelled by usage, so the 5-match spelling does not win.
    assert canon["Dijak"] == "T-BAR"


def test_tie_defers_to_the_declared_identity():
    # Usage has no opinion at equal counts, but the sources know which name is
    # current. A rename the corpus has barely seen must not lose to the old name
    # on a coin flip.
    canon = build_canon_map(counts("WALTER", "Gunther"),
                            roster_pairs=[("walter", "Gunther")])
    assert canon["WALTER"] == "Gunther"


def test_protected_identity_keeps_its_name_against_usage():
    # PROTECTED exists because the sources try to rename these; frequency is not
    # the authority there. The masks are protected so a rotating gimmick played
    # by several wrestlers never folds into whoever is under it.
    canon = build_canon_map({"Bravo Americano": 8, "Tyler Bate": 40},
                            roster_pairs=[("tyler-bate", "Bravo Americano")])
    assert canon["Tyler Bate"] == "Tyler Bate"
    assert canon["Bravo Americano"] == "Bravo Americano"


def test_display_spelling_corrects_a_dominant_source_typo():
    # Cagematch prints "The Good Father" (10) more than "The Goodfather" (7), so
    # usage alone crowns the typo. The override re-spells the winner without
    # touching who it is.
    canon = build_canon_map({"The Good Father": 10, "The Goodfather": 7},
                            roster_pairs=[])
    assert canon["The Good Father"] == "The Goodfather"
    assert canon["The Goodfather"] == "The Goodfather"


def test_display_spelling_never_changes_identity():
    # An override may re-spell a name, never re-identify it. If a value keys to
    # something else, it would silently move the person into another group.
    for key, spelling in DISPLAY_SPELLING.items():
        assert normkey(spelling) == key, (
            f"DISPLAY_SPELLING[{key!r}] = {spelling!r} keys to "
            f"{normkey(spelling)!r}; a spelling override must not re-identify")


def test_protected_has_no_duplicate_identity_keys():
    # build_canon_map does {normkey(p): p for p in PROTECTED}. PROTECTED is a
    # set, so two entries sharing a key make the winner depend on iteration
    # order and the displayed name non-deterministic across rebuilds. normkey
    # drops quoted nicknames, which makes this easy to trip:
    # '"Original" El Grande Americano' and "El Grande Americano" are one key.
    seen = {}
    for p in PROTECTED:
        k = normkey(p)
        assert k not in seen, (
            f"PROTECTED holds {p!r} and {seen[k]!r}, which share identity key "
            f"{k!r}; keep one, or the display depends on set ordering")
        seen[k] = p


def test_curated_table_has_no_two_step_chains():
    # Every curated canonical must be final: if "Albert" -> "A-Train" and
    # "A-Train" -> "Tensai" both existed, Albert would stay split from Tensai
    # because the map is applied once, not transitively.
    for old, new in CURATED.items():
        assert new not in CURATED, (
            f"CURATED chain: {old!r} -> {new!r} -> {CURATED[new]!r}; "
            f"point {old!r} directly at the final name")


def test_curated_never_renames_a_protected_name():
    protected_keys = {normkey(p) for p in PROTECTED}
    for old in CURATED:
        assert normkey(old) not in protected_keys, (
            f"CURATED renames protected name {old!r}; PROTECTED would win and "
            f"the entry is dead weight at best")


# ---- snapshot --------------------------------------------------------------

def test_snapshot_roundtrip(tmp_path):
    p = tmp_path / "pairs.json"
    pairs = [("walter", "Gunther"), ("mia-yim", "Michin")]
    save_roster_snapshot(pairs, path=p)
    assert load_roster_snapshot(path=p) == pairs


def test_snapshot_missing_returns_none(tmp_path):
    assert load_roster_snapshot(path=tmp_path / "absent.json") is None
