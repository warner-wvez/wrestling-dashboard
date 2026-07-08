"""SmackDown air-date collision resolver (2026-07 review fixes):
  - #3  every event on an N-way collided date is resolved, not just the first 2
  - #4  respacing only lands on weeks no other SmackDown holds (no new collision)
  - #2  watch-link media is merged bucket-by-bucket (dicts, not flat lists)
  - #10 only a genuine cross-source twin is ever deleted
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fix_smackdown_air_dates import (  # noqa: E402
    _is_cross_source_dup, _merge_media, _next_free_week,
    _smackdowns_by_date, resolve_collisions)


def _ev(eid, date, ep, source, card):
    """card is a list of participant lists, one per match."""
    return {
        "id": eid, "show_type": "SmackDown", "air_date": date,
        "episode_number": ep, "primary_source": source,
        "matches": [{"teams": [{"participants": p}]} for p in card],
    }


def _collides(events):
    return {d: [e["id"] for e in evs]
            for d, evs in _smackdowns_by_date(events).items() if len(evs) > 1}


# ---- #3 + #4: three shows on one date (twin + double-taping) ---------------

def test_three_way_collision_fully_resolved():
    card_x = [["Edge", "Rey Mysterio"], ["Kurt Angle"]]
    card_y = [["Brock Lesnar"], ["The Undertaker"]]
    events = {
        "1": _ev(1, "2003-06-05", 100, "cagematch", card_x),
        "2": _ev(2, "2003-06-05", 100, "fandom", card_x),   # twin of #1 -> dropped
        "3": _ev(3, "2003-06-05", 101, "thesmackdownhotel", card_y),  # respaced
    }
    drop_ids, dups, respaced = resolve_collisions(events, {})

    assert drop_ids == ["2"] and dups == 1 and respaced == 1
    assert "2" not in events                       # the Fandom twin is gone
    assert events["1"]["air_date"] == "2003-06-05"  # earliest keeps the date
    assert events["3"]["air_date"] != "2003-06-05"  # the double-taping moved
    assert events["3"]["date_derivation"] == "air-night-estimate"
    assert _collides(events) == {}                  # nothing left sharing a day


# ---- #4: respace never reuses an occupied week -----------------------------

def test_respace_skips_an_already_taken_week():
    # A distinct show already sits on the week directly after the collision.
    events = {
        "1": _ev(1, "2003-06-05", 100, "cagematch", [["A"]]),
        "2": _ev(2, "2003-06-05", 101, "thesmackdownhotel", [["B"]]),
        "3": _ev(3, "2003-06-12", 102, "thesmackdownhotel", [["C"]]),  # blocks +7
    }
    resolve_collisions(events, {})
    assert events["2"]["air_date"] == "2003-06-19"   # +7 taken, so +14
    assert _collides(events) == {}


# ---- #10: same-source overlap is NOT a deletable twin ----------------------

def test_same_source_overlap_is_respaced_not_deleted():
    same = [["A", "B"], ["C"]]
    events = {
        "1": _ev(1, "2003-06-05", 100, "thesmackdownhotel", same),
        "2": _ev(2, "2003-06-05", 101, "thesmackdownhotel", same),
    }
    drop_ids, dups, respaced = resolve_collisions(events, {})
    assert drop_ids == [] and dups == 0 and respaced == 1   # nothing deleted
    assert "2" in events                                    # real episode kept


def test_cross_source_twin_detection():
    a = _ev(1, "2003-06-05", 100, "cagematch", [["A", "B"], ["C"]])
    b = _ev(2, "2003-06-05", 100, "fandom", [["A", "B"], ["C"]])
    c = _ev(3, "2003-06-05", 100, "thesmackdownhotel", [["A", "B"], ["C"]])
    assert _is_cross_source_dup(a, b) is True     # cagematch + fandom
    assert _is_cross_source_dup(a, c) is True     # cagematch + smackdownhotel
    assert _is_cross_source_dup(b, c) is False    # no cagematch side -> never deleted


# ---- #2: media merge is bucket-wise and does not crash ---------------------

def test_merge_media_combines_buckets_when_survivor_has_links():
    media = {
        "2": {"show": [{"url": "drop-show"}], "matches": {"1": [{"url": "drop-m"}]},
              "moments": [{"url": "drop-mo"}]},
        "1": {"show": [{"url": "keep-show"}], "matches": {}, "moments": []},
    }
    _merge_media(media, "2", "1")   # the old code raised AttributeError here
    assert "2" not in media
    urls = {x["url"] for x in media["1"]["show"]}
    assert urls == {"keep-show", "drop-show"}
    assert media["1"]["matches"]["1"] == [{"url": "drop-m"}]
    assert media["1"]["moments"] == [{"url": "drop-mo"}]


def test_merge_media_dedupes_by_url():
    media = {
        "2": {"show": [{"url": "same"}], "matches": {}, "moments": []},
        "1": {"show": [{"url": "same"}], "matches": {}, "moments": []},
    }
    _merge_media(media, "2", "1")
    assert media["1"]["show"] == [{"url": "same"}]   # not duplicated


def test_next_free_week():
    assert _next_free_week("2003-06-05", set()) == "2003-06-12"
    assert _next_free_week("2003-06-05", {"2003-06-12"}) == "2003-06-19"
    assert _next_free_week("2003-06-05", {"2003-06-12", "2003-06-19"}) == "2003-06-26"
