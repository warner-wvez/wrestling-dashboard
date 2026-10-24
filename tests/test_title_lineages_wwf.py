import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.title_lineages import lineage_name  # noqa: E402


def test_wwf_era_strings_land_on_the_existing_lineages():
    assert lineage_name("WWF World Heavyweight Title", "1988-03-27") == "WWE Championship"
    assert lineage_name("WWF Championship", "1996-03-31") == "WWE Championship"
    assert lineage_name("WWF World Tag Team Title", "1988-08-24") == "World Tag Team Championship (1971-2010)"
    assert lineage_name("WWF Tag Team Championship", "1997-01-19") == "World Tag Team Championship (1971-2010)"
    assert lineage_name("WWF World Women's Title", "1985-05-11") == "WWE Women's Championship (1956-2010)"
    assert lineage_name("WWF Women's Championship", "1998-09-21") == "WWE Women's Championship (1956-2010)"


def test_million_dollar_belt_has_its_own_lineage():
    assert lineage_name("Million Dollar Title", "1989-02-01") == "Million Dollar Championship"
    assert lineage_name("Million Dollar Championship", "1995-07-23") == "Million Dollar Championship"
