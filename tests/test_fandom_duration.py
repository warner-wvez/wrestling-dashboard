"""Fandom duration regex must read hour-long bouts, not just M:SS (2026-07 fix).
A 60-minute Iron Man written '(1:05:23)' used to match nothing -> duration lost."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fandom_scraper import _DURATION_RE  # noqa: E402


def _seconds(text):
    m = _DURATION_RE.search(text)
    if not m:
        return None
    g1, g2, g3 = m.group(1), m.group(2), m.group(3)
    if g3 is not None:
        return int(g1) * 3600 + int(g2) * 60 + int(g3)
    return int(g1) * 60 + int(g2)


def test_minutes_seconds_still_work():
    assert _seconds("Match ends (12:45)") == 12 * 60 + 45


def test_hour_long_match_is_captured():
    assert _seconds("Iron Man Match (1:05:23)") == 3600 + 5 * 60 + 23
    assert _seconds("(1:00:00)") == 3600


def test_no_duration():
    assert _seconds("no time recorded") is None
