"""PPV discovery walks the list page's year sections; SNME episodes come out of the umbrella articles."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backfill.wiki_discover import SNME_ARTICLES, ppv_titles, special_episodes  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "backfill"


def test_every_1985_to_1995_event_is_found_with_its_date():
    rows = ppv_titles((FIX / "wiki-ppv-list-1985-1995.txt").read_text(encoding="utf-8"), range(1985, 1996))
    assert ("1985-03-31", "WrestleMania I") in rows
    assert ("1985-11-07", "The Wrestling Classic") in rows
    assert ("1995-01-22", "Royal Rumble (1995)") in rows
    assert ("1995-05-14", "In Your House 1") in rows
    years = {d[:4] for d, _ in rows}
    assert years == {str(y) for y in range(1985, 1996)}
    assert len(rows) == len(set(rows)) == len({t for _, t in rows})
    # WrestleMania 2 ran in three arenas: the two extra venue rows are not events.
    assert [t for d, t in rows if d.startswith("1986")] == ["WrestleMania 2"]


def test_year_filter_drops_out_of_range_sections():
    rows = ppv_titles((FIX / "wiki-ppv-list-1985-1995.txt").read_text(encoding="utf-8"), range(1988, 1989))
    assert all(d.startswith("1988") for d, _ in rows) and len(rows) == 3
    assert ("1988-03-27", "WrestleMania IV") in rows


def test_snme_episodes_take_dates_from_the_events_table_and_leads():
    # The umbrella article holds episodes II on; I keeps its own article.
    eps = special_episodes((FIX / "wiki-snme-excerpt.txt").read_text(encoding="utf-8"), SNME_ARTICLES[0][1])
    assert [e["title"] for e in eps] == ["Saturday Night's Main Event II", "Saturday Night's Main Event III",
                                         "Saturday Night's Main Event IV"]
    two = eps[0]
    assert two["tape_date"] == "1985-10-03" and two["air_date"] == "1985-10-05"
    assert two["city"] == "East Rutherford, New Jersey" and two["venue"] == "Brendan Byrne Arena"
    assert two["matches"] and two["matches"][0]["match_order"] == 1
    assert any("Hulk Hogan" in t["participants"] for m in two["matches"] for t in m["teams"])
    three = eps[1]
    assert three["tape_date"] == "1985-10-31" and three["air_date"] == "1985-11-02"
    # Episode IV is past the Events-table excerpt, so its dates come from the lead sentence.
    assert eps[2]["tape_date"] == "1985-12-19" and eps[2]["air_date"] == "1986-01-04"


def test_snme_one_comes_from_its_own_article_dated_by_the_events_row():
    from backfill.wiki_discover import _events_table, standalone_episode
    table = _events_table((FIX / "wiki-snme-excerpt.txt").read_text(encoding="utf-8"))
    one = standalone_episode((FIX / "wiki-snme-one.txt").read_text(encoding="utf-8"),
                             "Saturday Night's Main Event I", table["Saturday Night's Main Event I"])
    assert one["tape_date"] == "1985-05-10" and one["air_date"] == "1985-05-11"
    assert one["city"] == "Uniondale, New York" and one["venue"] == "Nassau Veterans Memorial Coliseum"
    assert len(one["matches"]) == 4 and one["matches"][1]["teams"][0]["participants"] == ["Hulk Hogan"]


def test_main_event_episodes_read_the_lead_sentence_when_there_is_no_table():
    eps = special_episodes((FIX / "wiki-main-event-excerpt.txt").read_text(encoding="utf-8"), SNME_ARTICLES[1][1])
    assert [e["title"] for e in eps] == ["The Main Event", "The Main Event II"]
    first = eps[0]
    assert first["air_date"] == "1988-02-05" and first["tape_date"] is None       # aired live
    assert first["venue"] == "Market Square Arena" and first["city"] == "Indianapolis, Indiana"
    assert any("Hulk Hogan" in t["participants"] for m in first["matches"] for t in m["teams"])


def test_articles_are_the_two_umbrella_pages():
    assert [a for a, _ in SNME_ARTICLES] == ["Saturday Night's Main Event", "WWF The Main Event"]


def test_infobox_dates_read_two_nights_and_templates():
    from backfill.wiki_discover import _infobox_dates
    two = "{{Infobox wrestling event\n|name = In Your House 8\n|date       = May 26, 1996<br />May 28, 1996\n|venue = X\n}}"
    assert _infobox_dates(two) == ["1996-05-26", "1996-05-28"]
    dts = "{{Infobox wrestling event\n|date       = {{dts|1995|12|17}}<ref>x</ref>\n}}"
    assert _infobox_dates(dts) == ["1995-12-17"]
    assert _infobox_dates("no box here") == []
