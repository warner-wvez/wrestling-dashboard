"""The footer credits the data's own sources, most used first.

It said "Data: Cagematch + Fandom" long after SmackDown Hotel and Wikipedia
became the weekly and PPV lanes, and the belt histories cite Duncan and Will,
WWE.com, Cawthon and Solie besides.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export_to_html import data_sources  # noqa: E402


def test_cards_and_belt_histories_count_their_sources():
    events = {"1": {"primary_source": "cagematch"}, "2": {"primary_source": "cagematch"},
              "3": {"primary_source": "thesmackdownhotel"}, "4": {"primary_source": "wikipedia"}}
    changes = [{"sources": ["Wikipedia #201", "WWE.com"]},
               {"sources": {"Wikipedia": "https://...", "Duncan & Will": "https://..."}},
               {"source": "List of WWE Champions"}, {"source": "NXT UK Tag Team Championship"}]
    got = data_sources(events, offcard=changes)
    assert got["cards"] == [("Cagematch", 2), ("SmackDown Hotel", 1), ("Wikipedia", 1)]
    assert got["belt_histories"][0] == ("Wikipedia", 4)
    assert dict(got["belt_histories"]) == {"Wikipedia": 4, "WWE.com": 1, "Duncan & Will": 1}
