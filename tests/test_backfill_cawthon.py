"""Cawthon's syndicated and special pages give air dates, durations and finishes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lineup-check"))
sys.path.insert(0, str(ROOT))

from cawthon_parse import finish_of, parse_match_line, parse_show_page, parse_special_page  # noqa: E402
from backfill.cawthon_fetch import SLUGS  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "backfill"


def test_finish_of_reads_every_duration_shape():
    assert finish_of("Koko B. Ware pinned Brian Costello at 1:45 with the Ghostbuster") == {"duration_seconds": 105, "method": "pin"}
    assert finish_of("Hercules defeated George South via submission with the full nelson at the 59-second mark") == {"duration_seconds": 59, "method": "submission"}
    assert finish_of("The Big Show pinned Test in 47 seconds") == {"duration_seconds": 47, "method": "pin"}
    assert finish_of("D-Lo Brown defeated Droz via disqualification at 3:16") == {"duration_seconds": 196, "method": "dq"}
    assert finish_of("The Acolytes defeated X via count-out at 3:20") == {"duration_seconds": 200, "method": "countout"}
    assert finish_of("Steve Austin & the Rock fought the Undertaker & Triple H to a no contest at 5:00") == {"duration_seconds": 300, "method": "no-contest"}
    assert finish_of("Ken Shamrock defeated Bradshaw via KO in a streetfight at 4:05") == {"duration_seconds": 245, "method": "ko"}
    assert finish_of("Matt & Jeff Hardy defeated Albert & the Big Bossman") == {"duration_seconds": None, "method": "win"}
    assert finish_of("Shane McMahon pinned Mankind at around the 3:30 mark") == {"duration_seconds": 210, "method": "pin"}


def test_superstars_taping_splits_into_episodes_with_air_dates():
    eps = parse_show_page((FIX / "cawthon-superstars-1988.html").read_text(encoding="utf-8"))
    assert len(eps) >= 2
    assert {e["air_date"] for e in eps} >= {"1988-08-20", "1988-08-27"}
    assert all(e["tape_date"] == "1988-08-03" for e in eps)
    assert eps[0]["city"] == "Wheeling, WV" and eps[0]["venue"] == "Civic Center"
    late = next(e for e in eps if e["air_date"] == "1988-08-27")
    first = parse_match_line(late["lines"][0])
    assert first["winners"] == ["Koko B. Ware"] and first["losers"] == ["Brian Costello"]
    assert all(e["air_date"] > e["tape_date"] for e in eps)


def test_snme_page_gives_taping_and_air_dates():
    shows = parse_special_page((FIX / "cawthon-snme-1985.html").read_text(encoding="utf-8"))
    assert len(shows) == 2
    assert shows[0]["tape_date"] == "1985-05-10" and shows[0]["air_date"] == "1985-05-11"
    assert shows[0]["city"] == "Long Island, NY" and shows[0]["venue"] == "Nassau Coliseum"
    assert shows[0]["label"].startswith("Saturday Night")
    assert any(parse_match_line(ln) for ln in shows[0]["lines"])
    assert shows[1]["tape_date"] == "1985-10-03" and shows[1]["air_date"] == "1985-10-05"


def test_slug_list_covers_every_family_and_year():
    assert "wwf-raw-1993" in SLUGS and "wwf-raw-1994-results" in SLUGS and "wwf-raw-2000" in SLUGS
    assert "wwf-smackdown-1999" in SLUGS and "wwf-superstars-1986" in SLUGS and "wwf-superstars-1997" in SLUGS
    assert "wwf-wrestling-challenge-1995" in SLUGS and "wwf-prime-time-wrestling-1985" in SLUGS
    assert "wwf-all-american-wrestling-1994" in SLUGS and "wwf-sunday-night-heat-1999" in SLUGS
    assert "wwf-shotgun-1997" in SLUGS and "wwf-mania" in SLUGS and "wwf-sunday-night-slam" in SLUGS
    assert "wwf-saturday-nights-main-event" in SLUGS and "wwf-the-main-event" in SLUGS
    assert "wwf-results-1985" in SLUGS and "wwf-results-2000" in SLUGS and "wwf-results-2001" not in SLUGS
    assert len(SLUGS) == len(set(SLUGS))


def test_compilation_page_gives_air_dates_and_lines_without_a_taping():
    from cawthon_parse import parse_compilation_page
    eps = parse_compilation_page((FIX / "cawthon-primetime-1988.html").read_text(encoding="utf-8"))
    assert [e["air_date"] for e in eps][:2] == ["1988-01-04", "1988-01-12"]
    assert eps[0]["tape_date"] is None and eps[0]["venue"] is None
    first = parse_match_line(eps[0]["lines"][0])
    assert first["winners"] == ["Jim Duggan"] and first["losers"] == ["Sika"]
    assert finish_of(eps[0]["lines"][0])["duration_seconds"] == 556
    assert "Madison Square Garden" not in eps[0]["lines"][0]
