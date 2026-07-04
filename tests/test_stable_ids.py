"""restore_stable_ids: rebuilt events must keep the IDs users' localStorage
(watched history, saved matches) and deep links already point at."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.build_update import event_key, restore_stable_ids  # noqa: E402


def ev(eid, date, show, title, mids):
    return {
        "id": eid, "air_date": date, "show_type": show, "title": title,
        "matches": [{"id": m, "match_order": i + 1} for i, m in enumerate(mids)],
    }


def base_corpus():
    """Pre-2020 events whose IDs must never be handed out again."""
    return {"1": ev(1, "2019-12-30", "Raw", "Monday Night Raw", [10, 11])}


def test_same_identity_keeps_event_and_match_ids():
    prior = ev(100, "2020-01-06", "Raw", "Monday Night Raw", [500, 501])
    prior_by_key = {event_key(prior): prior}
    # Re-scrape assigned different provisional IDs (an episode was added
    # earlier in the iteration, shifting everything).
    new = [ev(342, "2020-01-06", "Raw", "Monday Night Raw", [900, 901])]
    out = restore_stable_ids(new, prior_by_key, base_corpus())
    assert out[0]["id"] == 100
    assert [m["id"] for m in out[0]["matches"]] == [500, 501]


def test_new_event_gets_fresh_id_above_everything_ever_used():
    prior = ev(100, "2020-01-06", "Raw", "Monday Night Raw", [500, 501])
    prior_by_key = {event_key(prior): prior}
    new = [
        ev(342, "2020-01-06", "Raw", "Monday Night Raw", [900, 901]),
        ev(343, "2020-01-10", "SmackDown", "Friday Night SmackDown", [902]),
    ]
    out = restore_stable_ids(new, prior_by_key, base_corpus())
    fresh = out[1]
    assert fresh["id"] > 100                      # above every prior event ID
    assert fresh["id"] != out[0]["id"]
    assert fresh["matches"][0]["id"] > 501        # above every prior match ID


def test_better_parse_with_extra_match_keeps_old_ids_and_extends():
    prior = ev(100, "2020-01-06", "Raw", "Monday Night Raw", [500, 501])
    prior_by_key = {event_key(prior): prior}
    new = [ev(342, "2020-01-06", "Raw", "Monday Night Raw", [900, 901, 902])]
    out = restore_stable_ids(new, prior_by_key, base_corpus())
    mids = [m["id"] for m in out[0]["matches"]]
    assert mids[:2] == [500, 501]                 # existing bouts keep their IDs
    assert mids[2] > 501                          # the newly-found bout is fresh
    assert len(set(mids)) == 3


def test_shrunken_parse_does_not_crash_or_collide():
    prior = ev(100, "2020-01-06", "Raw", "Monday Night Raw", [500, 501, 502])
    prior_by_key = {event_key(prior): prior}
    new = [ev(342, "2020-01-06", "Raw", "Monday Night Raw", [900])]
    out = restore_stable_ids(new, prior_by_key, base_corpus())
    assert out[0]["id"] == 100
    assert [m["id"] for m in out[0]["matches"]] == [500]


def test_no_id_collisions_across_a_realistic_shuffle():
    # Three prior events; the re-scrape discovers one brand-new episode that
    # lands between them, shifting every provisional ID by one.
    prior_events = [
        ev(100, "2020-01-06", "Raw", "Monday Night Raw", [500]),
        ev(101, "2020-01-10", "SmackDown", "Friday Night SmackDown", [501]),
        ev(102, "2020-01-13", "Raw", "Monday Night Raw", [502]),
    ]
    prior_by_key = {event_key(e): e for e in prior_events}
    new = [
        ev(100, "2020-01-06", "Raw", "Monday Night Raw", [900]),
        ev(101, "2020-01-08", "Raw", "Monday Night Raw", [901]),   # new episode
        ev(102, "2020-01-10", "SmackDown", "Friday Night SmackDown", [902]),
        ev(103, "2020-01-13", "Raw", "Monday Night Raw", [903]),
    ]
    out = restore_stable_ids(new, prior_by_key, base_corpus())
    by_key = {event_key(e): e["id"] for e in out}
    assert by_key[("2020-01-06", "Raw", "Monday Night Raw")] == 100
    assert by_key[("2020-01-10", "SmackDown", "Friday Night SmackDown")] == 101
    assert by_key[("2020-01-13", "Raw", "Monday Night Raw")] == 102
    all_eids = [e["id"] for e in out]
    assert len(set(all_eids)) == len(all_eids)
    assert by_key[("2020-01-08", "Raw", "Monday Night Raw")] > 102
    all_mids = [m["id"] for e in out for m in e["matches"]]
    assert len(set(all_mids)) == len(all_mids)
