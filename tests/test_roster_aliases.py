"""Alias resolution: normkey identity rules and build_canon_map precedence.
These encode the invariants behind the 2026-07 roster-accuracy overhaul: a
regression in any of them silently splits or mis-merges wrestler careers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.roster_aliases import (  # noqa: E402
    CURATED, PROTECTED, build_canon_map, load_roster_snapshot, normkey,
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
