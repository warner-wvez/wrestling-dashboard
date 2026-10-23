"""Where to watch: the archive feed and the Peacock/Netflix sheet joined to our
shows, one file per show.

The archive items name their files five ways (2002.01.07, 01.07.2002,
07.01.2002, "Jan. 07, 2002", "WrestleMania 26 2010"), one item uses episode
numbers only, and a few holiday-week files sit a day or three off our air
date. Every rule here is one of those cases.
"""
import importlib.util
from datetime import date
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "where_map", Path(__file__).resolve().parent.parent / "media-pipeline" / "where_map.py")
wm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wm)


def _ev(id, show_type, air_date, ppv_name=None):
    return {"id": id, "show_type": show_type, "air_date": air_date, "ppv_name": ppv_name, "title": ppv_name}


def _file(name, length=7000, size=2_000_000_000):
    return {"name": name, "length": str(length), "size": str(size)}


def test_month_name_dates_parse():
    assert wm.date_candidates("SmackDown - 2016 S17 E1 SmackDown - Jan. 07, 2016.mp4") == {"mon": date(2016, 1, 7)}
    assert wm.date_candidates("WWE Friday Night SmackDown_S08E01_January 6, 2006.mkv") == {"mon": date(2006, 1, 6)}


def test_numeric_dates_offer_both_orders():
    c = wm.date_candidates("S26E02 WWE RAW 08.01.2018 720p Web-DL.mp4")
    assert c["mdy"] == date(2018, 8, 1)
    assert c["dmy"] == date(2018, 1, 8)
    assert wm.date_candidates("2002-1-7 - Royal Rumble.mp4")["ymd"] == date(2002, 1, 7)


def test_pick_order_is_decided_by_our_show_dates():
    names = ["08.01.2018.mp4", "15.01.2018.mp4", "22.01.2018.mp4"]
    assert wm.pick_order(names, {"2018-01-08", "2018-01-15", "2018-01-22"}) == "dmy"
    assert wm.pick_order(["01.08.2018.mp4"], {"2018-01-08"}) == "mdy"


def test_ppv_key_normalises_name_year_and_kickoff():
    assert wm.ppv_key("WWE WrestleMania 26 2010.mkv") == ("wrestlemania xxvi", 2010, False)
    assert wm.ppv_key("WWE Hell in a Cell 2012 Kickoff Show.mkv") == ("hell in a cell", 2012, True)
    assert wm.ppv_key("Judgement Day (2007) 720p AAC.mp4") == ("judgment day", 2007, False)
    assert wm.ppv_key("Raw S2019 E01 Raw.mp4") is None


def test_join_keeps_the_main_show_mp4_over_mkv_and_kickoff():
    events = [_ev(1, "PPV", "2012-10-28", "WWE Hell In A Cell 2012")]
    items = [{"col": "PPV", "id": "VPPEWW2012", "files": [
        _file("WWE Hell in a Cell 2012.mkv", 10000, 5_000_000_000),
        _file("WWE Hell in a Cell 2012.mp4", 10000, 3_000_000_000),
        _file("WWE Hell in a Cell 2012 Kickoff Show.mp4", 1800),
    ]}]
    out = wm.join_items(items, events)
    assert out == {"1": {"item": "VPPEWW2012", "file": "WWE Hell in a Cell 2012.mp4", "min": 167, "how": "name"}}


def test_join_accepts_a_near_miss_only_when_it_is_alone_in_its_week():
    # Raw moved to Thursday Feb 16 2006; the file carries the usual Monday.
    events = [_ev(1, "Raw", "2006-02-16"), _ev(2, "Raw", "2006-02-20")]
    items = [{"col": "RAW", "id": "WAR2006", "files": [
        _file("WWE.Monday.Night.Raw.2006.02.13.mp4"), _file("WWE.Monday.Night.Raw.2006.02.20.mp4")]}]
    out = wm.join_items(items, events)
    assert out["1"]["how"] == "near-3"
    assert out["2"]["how"] == "date"
    # Two files near the same show: neither is trusted.
    items = [{"col": "RAW", "id": "WAR2006", "files": [
        _file("WWE.Monday.Night.Raw.2006.02.13.mp4"), _file("WWE.Monday.Night.Raw.2006.02.15.mp4")]}]
    assert wm.join_items(items, events) == {}


def test_join_leaves_files_with_no_show_out():
    # Dec 26 2022 was a recap special; our data has no show that week.
    events = [_ev(1, "Raw", "2022-12-19")]
    items = [{"col": "RAW", "id": "war2022", "files": [_file("WWE.RAW.2022.12.26.1080p.mp4")]}]
    assert wm.join_items(items, events) == {}


def test_ordinal_join_walks_the_weeks_and_skips_shows_we_lack():
    # 2019 Raw files are E01..E52; our data has no Dec 23 show, so E51 goes unused.
    mondays = [date(2019, 1, 7)]
    while len(mondays) < 52:
        mondays.append(date.fromordinal(mondays[-1].toordinal() + 7))
    events = [_ev(i, "Raw", d.isoformat()) for i, d in enumerate(mondays) if d != date(2019, 12, 23)]
    files = [_file(f"Raw S2019 E{n:02d} Raw.mp4") for n in range(1, 53)]
    out = wm.ordinal_join("war2019", files, events, "Raw", 2019)
    assert out["0"] == {"item": "war2019", "file": "Raw S2019 E01 Raw.mp4", "min": 117, "how": "ordinal"}
    assert out[str(events[-1]["id"])]["file"] == "Raw S2019 E52 Raw.mp4"
    assert not any(v["file"] == "Raw S2019 E51 Raw.mp4" for v in out.values())


def test_ordinal_join_refuses_when_the_counts_disagree():
    events = [_ev(1, "Raw", "2019-01-07"), _ev(2, "Raw", "2019-01-14")]
    files = [_file(f"Raw S2019 E{n:02d} Raw.mp4") for n in range(1, 5)]
    assert wm.ordinal_join("war2019", files, events, "Raw", 2019) == {}


def test_official_links_join_by_show_and_date_and_skip_not_yet():
    events = [_ev(1, "Raw", "2001-01-01"), _ev(2, "Raw", "2001-01-08"), _ev(3, "SmackDown", "2002-01-10")]
    rows = [
        ("WWE Raw Vault", date(2001, 1, 1), "https://www.netflix.com/watch/81938084?trackId=1", date(2001, 1, 1)),
        ("WWE Raw Vault", date(2001, 1, 8), "NOT ON NETFLIX YET", date(2001, 1, 8)),
        ("WWE Friday Night Smackdown", date(2002, 1, 10), "https://www.peacocktv.com/watch/playback/vod/GMO_1/abc", date(2002, 1, 10)),
        ("WCW Monday Nitro", date(2001, 1, 1), "https://www.peacocktv.com/watch/playback/vod/GMO_2/def", date(2001, 1, 1)),
    ]
    assert wm.official_links(rows, events) == {
        "1": {"platform": "netflix", "url": "https://www.netflix.com/watch/81938084"},
        "3": {"platform": "peacock", "url": "https://www.peacocktv.com/watch/playback/vod/GMO_1/abc"},
    }


def test_official_ppv_rows_join_by_date_alone():
    events = [_ev(1, "PPV", "2002-01-20", "WWF Royal Rumble 2002")]
    rows = [("Royal Rumble", "Royal Rumble 2002", "https://www.peacocktv.com/watch/playback/vod/GMO_3/x", date(2002, 1, 20))]
    assert wm.official_links(rows, events)["1"]["platform"] == "peacock"
