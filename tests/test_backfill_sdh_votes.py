import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backfill.sdh_votes import PAGES, show_type_of  # noqa: E402


def test_pages_are_raw_1993_on_smackdown_1999_on_heat_1998_on():
    assert ("raw", 1993) in PAGES and ("raw", 2000) in PAGES and ("raw", 1992) not in PAGES
    assert ("smackdown", 1999) in PAGES and ("smackdown", 2000) in PAGES
    assert ("heat", 1998) in PAGES and ("heat", 2000) in PAGES
    assert len(PAGES) == 13


def test_show_type_of_maps_slugs_to_corpus_names():
    assert show_type_of("raw") == "Raw" and show_type_of("smackdown") == "SmackDown" and show_type_of("heat") == "Heat"
