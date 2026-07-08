"""split_members surname-lending: it must rejoin genuine shared-surname family
teams ('Jimmy & Jey Uso') without fabricating names when a real mononym is
paired with a two-word wrestler ('Kane & Daniel Bryan' -> NOT 'Kane Bryan').
Regression guard for the 2026-07 review finding."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.smackdownhotel import split_members  # noqa: E402


# ---- the lend must still work for real family teams ------------------------

def test_shared_surname_family_is_rejoined():
    assert split_members("Jimmy & Jey Uso") == ["Jimmy Uso", "Jey Uso"]
    assert split_members("Nikki & Brie Bella") == ["Nikki Bella", "Brie Bella"]
    assert split_members("Matt & Jeff Hardy") == ["Matt Hardy", "Jeff Hardy"]


# ---- the lend must NOT fire on a complete mononym + two-word partner --------

def test_mononym_plus_full_name_is_not_fused():
    # The headline regression: Team Hell No must not become "Kane Bryan".
    assert split_members("Kane & Daniel Bryan") == ["Kane", "Daniel Bryan"]
    assert split_members("Edge & Rey Mysterio") == ["Edge", "Rey Mysterio"]
    assert split_members("Cesaro & Kofi Kingston") == ["Cesaro", "Kofi Kingston"]


def test_two_mononyms_untouched():
    assert split_members("Sheamus & Cesaro") == ["Sheamus", "Cesaro"]


def test_stable_with_parens_still_flattens():
    assert split_members("The Usos (Jimmy & Jey Uso)") == ["Jimmy Uso", "Jey Uso"]
