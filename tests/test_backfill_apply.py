"""apply refuses thin or broken runs and gives new shows fresh IDs above every ID ever used."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backfill.common import fresh_event, fresh_match  # noqa: E402
from backfill.apply import gate, index_counts_from, merge  # noqa: E402

OK = {k: {"ok": True} for k in ("cm_results", "cawthon", "wiki", "sdh", "fandom", "join")}


def _card(show_type, day, status="verified"):
    m = fresh_match(1, [{"participants": ["A"], "was_winner": True}, {"participants": ["B"], "was_winner": False}])
    return fresh_event(air_date=day, show_type=show_type, title=f"{show_type} {day}", primary_source="cagematch",
                       verification_status=status, matches=[m])


def test_gate_lists_every_problem():
    cards = [_card("Raw", "1993-01-11")]
    status = dict(OK, cawthon={"ok": False, "detail": "missing wwf-raw-1993"})
    problems = gate(cards, status, {("Raw", 1993): 46})
    assert any("cawthon" in p for p in problems)
    assert any("Raw 1993" in p and "1 of 46" in p for p in problems)


def test_gate_passes_a_full_year_within_ten_percent():
    cards = [_card("Raw", f"1993-{m:02d}-{d:02d}") for m in range(1, 13) for d in (3, 10, 17, 24)][:43]
    assert gate(cards, OK, {("Raw", 1993): 46}) == []


def test_gate_rejects_a_card_without_a_date_family_or_match():
    bad = _card("Raw", "1993-01-11")
    bad["matches"] = []
    assert any("no match" in p for p in gate([bad], OK, {("Raw", 1993): 1}))
    nodate = _card("Raw", "1993-01-11")
    nodate["air_date"] = None
    assert any("no air_date" in p for p in gate([nodate], OK, {}))


def test_index_counts_skip_studio_shows_and_matchless_rows():
    cm = [_card("Challenge", "1988-08-28"), _card("PrimeTime", "1988-01-04"), _card("Challenge", "1988-09-04")]
    cm[2]["matches"] = []
    assert index_counts_from(cm) == {("Challenge", 1988): 1}


def test_merge_gives_fresh_ids_and_sets_family_everywhere():
    old = {"id": 3127, "air_date": "2026-10-19", "show_type": "Raw", "title": "Raw", "matches": [{"id": 19999, "teams": []}]}
    data = {"events": {"3127": old}, "events_by_date": {"2026-10-19": [3127]}}
    added = merge(data, [_card("Challenge", "1988-08-28"), _card("PPV", "1988-03-27")])
    assert [e["id"] for e in added] == [3128, 3129]
    assert added[0]["matches"][0]["id"] == 20000
    assert data["events"]["3127"]["family"] == "main"
    assert data["events"]["3128"]["family"] == "syndicated" and data["events"]["3129"]["family"] == "main"
    assert data["events_by_date"]["1988-08-28"] == [3128]
