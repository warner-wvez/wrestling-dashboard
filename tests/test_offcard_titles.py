"""The Hardcore title's house-show swaps keep every change two records agree on,
even on a night the first three records tell three different ways.

Columbia, SC, 2002-07-28: Wikipedia has Raven win first, Cawthon has Justin
Credible beat "Eddie Guerrero", Solie has Steven Richards. WWE.com's title
history has Raven, so Raven's reign stands on two records. The source pages
are gitignored caches, so this checks the built file the site reads.
"""
import json
from pathlib import Path

CHANGES = Path(__file__).resolve().parent.parent / "data" / "offcard-title-changes.json"


def _night(day):
    changes = json.loads(CHANGES.read_text(encoding="utf-8"))["changes"]
    return sorted((c for c in changes if c["date"] == day), key=lambda c: c["order"])


def test_columbia_2002_opens_with_raven():
    night = _night("2002-07-28")
    assert [c["champions"] for c in night] == [
        ["Raven"], ["Justin Credible"], ["Shawn Stasiak"], ["Bradshaw"]]
    assert [c["order"] for c in night] == [0, 1, 2, 3]
    assert night[0]["sources"] == ["Wikipedia #201", "WWE.com"]


def test_every_change_rests_on_two_records():
    changes = json.loads(CHANGES.read_text(encoding="utf-8"))["changes"]
    thin = [(c["date"], c["order"], c["sources"]) for c in changes if len(c["sources"]) < 2]
    assert thin == []
