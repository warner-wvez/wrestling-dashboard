import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backfill.fandom_votes import fandom_slug, parse_page  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "backfill"


def test_slugs_follow_fandoms_naming():
    assert fandom_slug("Raw", "1993-01-11") == "January_11,_1993_Monday_Night_RAW_results"
    assert fandom_slug("SmackDown", "1999-08-26") == "August_26,_1999_Smackdown_results"


def test_raw_1993_page_parses_results_list():
    page = parse_page((FIX / "fandom-raw-1993-01-11.html").read_text(encoding="utf-8"))
    ms = page["matches"]
    assert len(ms) >= 4
    first = ms[0]
    assert first["teams"][0]["participants"] == ["Yokozuna"] and first["teams"][0]["was_winner"] is True
    assert first["teams"][1]["participants"] == ["Koko B. Ware"]
    assert first["duration_seconds"] == 225
    ic = next(m for m in ms if m["title_at_stake"] and "Intercontinental" in m["title_at_stake"])
    assert ic["teams"][0]["was_champion_entering"] is True
    dark = [m for m in ms if (m["match_type"] or "").lower().startswith("dark")]
    assert dark and dark[0]["teams"][0]["participants"] == ["Crush"]
