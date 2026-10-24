"""The shared builders give every backfilled event and match the exact bundle shape."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backfill.common import FAMILIES, fresh_event, fresh_match  # noqa: E402


def test_fresh_event_has_every_bundle_field_and_family():
    ev = fresh_event(air_date="1988-08-27", show_type="Superstars", title="WWF Superstars #106")
    for key in ("id", "air_date", "tape_date", "date_derivation", "show_type", "family",
                "episode_number", "title", "ppv_name", "venue", "city", "state_province",
                "country", "attendance", "tv_network", "tv_rating", "broadcast_type",
                "commentary", "promotion", "promotion_raw", "cagematch_nr", "cagematch_url",
                "fandom_slug", "fandom_url", "primary_source", "verification_status",
                "match_count", "matches", "logo"):
        assert key in ev, key
    assert ev["family"] == "syndicated"
    assert ev["promotion"] == "WWF" and ev["promotion_raw"] == "WWF"
    assert ev["id"] is None and ev["matches"] == []


def test_fresh_match_defaults_and_team_shape():
    m = fresh_match(2, teams=[{"participants": ["Jake Roberts"], "was_winner": True},
                              {"participants": ["Mike Williams"], "was_winner": False}])
    assert m["match_order"] == 2 and m["id"] is None
    assert m["result_method"] == "defeated" and m["match_guide_rating"] is None
    t0, t1 = m["teams"]
    assert t0 == {"team_number": 1, "team_name": "Jake Roberts", "accompaniment": None,
                  "was_winner": True, "match_outcome": "win", "was_champion_entering": False,
                  "participants": ["Jake Roberts"]}
    assert t1["match_outcome"] == "loss" and t1["team_number"] == 2


def test_families_cover_the_fourteen_show_types():
    assert FAMILIES["Raw"] == "main" and FAMILIES["SNME"] == "main"
    assert FAMILIES["Challenge"] == "syndicated" and len(FAMILIES) == 14
