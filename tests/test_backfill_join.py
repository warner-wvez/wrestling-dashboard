"""Shows pair by date and family, matches by shared people, and every show lands in one bucket."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backfill.common import fresh_event, fresh_match  # noqa: E402
from backfill.join import as_lines, as_matches, bucket, cawthon_match, clean_stakes, join_all, pair_dates, with_ring_names  # noqa: E402


def _cm(show_type, tape, people, nr=1, derivation="cagematch-taping"):
    m = fresh_match(1, [{"participants": [people[0]], "was_winner": True},
                        {"participants": [people[1]], "was_winner": False}],
                    raw_description=f"{people[0]} defeats {people[1]}")
    m["aired"] = True
    ev = fresh_event(air_date=tape, tape_date=tape if derivation == "cagematch-taping" else None,
                     date_derivation=derivation, show_type=show_type, title=f"WWF {show_type} #{nr}",
                     cagematch_nr=nr, cagematch_url=f"https://www.cagematch.net/?id=1&nr={nr}",
                     primary_source="cagematch", logo="1_x.gif", matches=[m])
    ev["workers"] = {people[0]: 10 + nr, people[1]: 20 + nr}
    return ev


def _cawthon_ep(tape, air, winner, loser, method="pin", seconds=100):
    return {"air_date": air, "tape_date": tape, "city": "Hartford, CT", "venue": "Civic Center",
            "matches": [{"kind": "match", "winners": [winner], "losers": [loser], "result": "win",
                         "sub_for": [], "notes": [], "line": f"{winner} pinned {loser} at 1:40",
                         "duration_seconds": seconds, "method": method}]}


def test_three_episodes_on_one_taping_pair_by_people():
    cm = [_cm("Challenge", "1988-08-24", ["Jake Roberts", "Mike Williams"], 1),
          _cm("Challenge", "1988-08-24", ["Demolition", "Jim Powers"], 2),
          _cm("Challenge", "1988-08-24", ["Rick Rude", "Koko B. Ware"], 3)]
    caw = {"wwf-wrestling-challenge-1988": [
        _cawthon_ep("1988-08-24", "1988-09-11", "Rick Rude", "Koko B. Ware"),
        _cawthon_ep("1988-08-24", "1988-08-28", "Jake Roberts", "Mike Williams"),
        _cawthon_ep("1988-08-24", "1988-09-04", "Demolition", "Jim Powers")]}
    paired, unpaired = pair_dates(cm, caw)
    assert unpaired == []
    by_nr = {e["cagematch_nr"]: e for e in paired}
    assert by_nr[1]["air_date"] == "1988-08-28" and by_nr[2]["air_date"] == "1988-09-04" and by_nr[3]["air_date"] == "1988-09-11"
    assert all(e["tape_date"] == "1988-08-24" and e["date_derivation"] == "cawthon-air-date" for e in paired)


def test_unpaired_show_keeps_cagematch_date_and_is_listed():
    cm = [_cm("Superstars", "1990-03-03", ["A", "B"])]
    paired, unpaired = pair_dates(cm, {"wwf-superstars-1990": []})
    assert paired == [] and unpaired[0]["air_date"] == "1990-03-03"
    assert unpaired[0]["date_derivation"] == "cagematch-taping"


def test_studio_show_takes_cawthon_as_spine_and_cagematch_as_vote():
    caw = {"wwf-prime-time-wrestling-1988": [
        {"air_date": "1988-01-04", "tape_date": None, "city": None, "venue": None,
         "matches": [{"kind": "match", "winners": ["Jim Duggan"], "losers": ["Sika"], "result": "win",
                      "sub_for": [], "notes": [], "line": "Jim Duggan pinned Sika at 9:16", "duration_seconds": 556, "method": "pin"}]},
        {"air_date": "1988-01-12", "tape_date": None, "city": None, "venue": None,
         "matches": [{"kind": "match", "winners": ["Bret Hart"], "losers": ["Rene Goulet"], "result": "win",
                      "sub_for": [], "notes": [], "line": "Bret Hart pinned Rene Goulet", "duration_seconds": None, "method": "pin"}]}]}
    cm = [_cm("PrimeTime", "1988-01-04", ["Jim Duggan", "Sika"], 7)]
    cards, review, report = join_all(cm, caw, [], {}, {})
    pt = sorted((c for c in cards if c["show_type"] == "PrimeTime"), key=lambda c: c["air_date"])
    assert [c["air_date"] for c in pt] == ["1988-01-04", "1988-01-12"]
    assert pt[0]["primary_source"] == "cawthon" and pt[0]["verification_status"] == "verified"
    assert pt[0]["cagematch_nr"] == 7 and pt[0]["matches"][0]["duration_seconds"] == 556
    assert pt[0]["matches"][0]["teams"][0]["participants"] == ["Jim Duggan"]
    assert pt[1]["verification_status"] == "single-source" and pt[1]["cagematch_nr"] is None
    assert report["studio_tapings_unpaired"] == 0


def test_as_lines_and_as_matches_round_trip_the_shapes():
    m = fresh_match(1, [{"participants": ["A", "B"], "was_winner": True}, {"participants": ["C"], "was_winner": False}])
    line = as_lines([m])[0]
    assert line["winners"] == ["A", "B"] and line["losers"] == ["C"] and line["result"] == "win" and line["kind"] == "match"
    draw = fresh_match(1, [{"participants": ["A"], "was_winner": None}, {"participants": ["B"], "was_winner": None}], result_method="Time Limit Draw")
    assert as_lines([draw])[0]["result"] == "draw"
    back = as_matches([line])[0]
    assert back["teams"][0]["participants"] == ["A", "B"] and back["teams"][0]["was_winner"] is True


def test_bucket_is_verified_only_when_no_review_rows():
    assert bucket([{"class": "keep"}, {"class": "not_aired"}]) == "verified"
    assert bucket([{"class": "result", "vote": "split"}]) == "flagged"
    assert bucket([{"class": "missing_match", "vote": "keep"}]) == "verified"
    assert bucket([{"class": "missing_match", "vote": "split"}]) == "flagged"


def test_join_all_buckets_fills_durations_and_drops_out_of_range():
    cm = [_cm("Challenge", "1988-08-24", ["Jake Roberts", "Mike Williams"], 1),
          _cm("Jakked", "2000-02-05", ["Essa Rios", "Funaki"], 2),
          _cm("SmackDown", "2001-01-04", ["X", "Y"], 3, derivation="air-night-estimate")]
    caw = {"wwf-wrestling-challenge-1988": [_cawthon_ep("1988-08-24", "1988-08-28", "Jake Roberts", "Mike Williams", seconds=97)]}
    cards, review, report = join_all(cm, caw, wiki=[], sdh={}, fandom={})
    chal = next(c for c in cards if c["show_type"] == "Challenge")
    assert chal["verification_status"] == "verified" and chal["matches"][0]["duration_seconds"] == 97
    assert chal["air_date"] == "1988-08-28" and "aired" not in chal["matches"][0]
    jak = next(c for c in cards if c["show_type"] == "Jakked")
    assert jak["verification_status"] == "single-source"
    assert not any(c["show_type"] == "SmackDown" for c in cards) and report["out_of_range"] == 1
    assert report["by_status"]["verified"] == 1 and report["by_status"]["single-source"] == 1
    assert "workers" not in chal and "cm_type" not in chal and "cawthon" not in chal
    assert any(r["class"] == "date_unconfirmed" for r in review)


def test_wiki_ppv_is_the_spine_and_cagematch_must_share_its_date():
    def wiki_card(day):
        return [{"title": "WrestleMania IV", "show_type": "PPV", "list_date": day,
                 "events": [fresh_event(air_date=day, show_type="PPV", title="WrestleMania IV", ppv_name="WrestleMania IV",
                                        primary_source="wikipedia",
                                        matches=[fresh_match(1, [{"participants": ["Randy Savage"], "was_winner": True},
                                                                 {"participants": ["Ted DiBiase"], "was_winner": False}])])]}]
    cm = [_cm("PPV", "1988-03-27", ["Randy Savage", "Ted DiBiase"], 5, derivation="live-broadcast")]
    cards, review, report = join_all(cm, {}, wiki_card("1988-03-27"), {}, {})
    ppv = cards[0]
    assert ppv["primary_source"] == "wikipedia" and ppv["cagematch_nr"] == 5 and ppv["logo"] == "1_x.gif"
    assert ppv["verification_status"] == "verified"
    cards2, review2, _ = join_all(cm, {}, wiki_card("1988-03-28"), {}, {})
    assert cards2 == [] and any(r["class"] == "date_split" for r in review2)


def test_snme_without_an_article_ships_single_source_from_cagematch():
    cm = [_cm("SNME", "1997-05-23", ["A", "B"], 9, derivation="live-broadcast")]
    cards, review, report = join_all(cm, {}, [], {}, {})
    assert cards[0]["show_type"] == "SNME" and cards[0]["verification_status"] == "single-source"


def test_rulings_remove_rows_a_person_already_settled():
    cm = [_cm("Superstars", "1990-03-03", ["A", "B"], 4)]
    cards, review, report = join_all(cm, {"wwf-superstars-1990": []}, [], {}, {}, rulings={"Superstars|1990-03-03|4"})
    assert review == [] and report["ruled"] == 1


def test_dark_matches_stay_out_of_vote_lines_and_count_as_not_aired():
    dark = fresh_match(1, [{"participants": ["A"], "was_winner": True}, {"participants": ["B"], "was_winner": False}])
    dark["aired"] = False
    assert as_lines([dark]) == []
    cm = [_cm("Superstars", "1991-05-06", ["Mr. Perfect", "Jim Evans"], 11)]
    cm[0]["matches"].append(dict(dark, match_order=2, raw_description="Dark:A defeats B"))
    caw = {"wwf-superstars-1991": [_cawthon_ep("1991-05-06", "1991-05-25", "Mr. Perfect", "Jim Evans")]}
    cards, review, report = join_all(cm, caw, [], {}, {})
    assert cards[0]["verification_status"] == "verified" and review == []


def test_cawthon_match_builds_a_bundle_match():
    m = cawthon_match({"winners": ["A", "B"], "losers": ["C", "D"], "result": "win", "method": "dq",
                       "duration_seconds": 90, "line": "A & B defeated C & D via disqualification at 1:30"}, 3)
    assert m["match_order"] == 3 and m["result_method"] == "by DQ" and m["duration_seconds"] == 90
    assert m["teams"][0]["participants"] == ["A", "B"] and m["teams"][1]["match_outcome"] == "dq-loss"
    nc = cawthon_match({"winners": ["A"], "losers": ["B"], "result": "no contest", "method": "no-contest",
                        "duration_seconds": None, "line": "A fought B to a no contest"}, 1)
    assert all(t["was_winner"] is None for t in nc["teams"]) and nc["result_method"] == "No Contest"


def test_ring_names_swap_only_when_the_card_wears_them():
    lines = [{"winners": ["Davey Boy Smith"], "losers": ["Barry O"], "result": "win"}]
    assert with_ring_names(lines, {"The British Bulldog", "Barry O"})[0]["winners"] == ["The British Bulldog"]
    assert with_ring_names(lines, {"Davey Boy Smith", "Barry O"})[0]["winners"] == ["Davey Boy Smith"]
    assert with_ring_names(lines, {"Bret Hart", "Barry O"})[0]["winners"] == ["Davey Boy Smith"]


def test_show_without_cawthon_is_dated_by_smackdown_hotel_when_people_match():
    cm = [_cm("Heat", "2000-03-07", ["Crash Holly", "Taka Michinoku"], 21)]
    sdh = {"heat-2000": [{"date": "2000-03-12", "episode_number": None, "header": "", "matches": [
        {"match_type": None, "title_at_stake": None, "teams": [{"participants": ["Crash Holly"], "was_winner": True},
                                                               {"participants": ["Taka Michinoku"], "was_winner": False}]}]}]}
    cards, review, report = join_all(cm, {}, [], sdh, {})
    heat = cards[0]
    assert heat["air_date"] == "2000-03-12" and heat["tape_date"] == "2000-03-07" and heat["date_derivation"] == "sdh-air-date"
    assert heat["verification_status"] == "verified" and not any(r["class"] == "date_unconfirmed" for r in review)


def test_clean_stakes_keeps_belts_and_drops_referee_notes():
    def ev(title):
        return {"matches": [fresh_match(1, [{"participants": ["A"], "was_winner": True}, {"participants": ["B"], "was_winner": False}], title_at_stake=title)]}
    assert clean_stakes(ev("WWF Championship / Mr. Perfect / special guest referee"))["matches"][0]["title_at_stake"] == "WWF Championship"
    assert clean_stakes(ev("vacant / WWF Championship"))["matches"][0]["title_at_stake"] == "WWF Championship"
    assert clean_stakes(ev("WWF Intercontinental / WWF European"))["matches"][0]["title_at_stake"] == "WWF Intercontinental Championship / WWF European Championship"
    assert clean_stakes(ev("WWF Championship / WrestleMania XII"))["matches"][0]["title_at_stake"] == "WWF Championship"
    assert clean_stakes(ev("WWF Intercontinental Title"))["matches"][0]["title_at_stake"] == "WWF Intercontinental Title"


def test_result_row_across_two_matches_becomes_a_lineup_difference():
    from backfill.join import _reclass_results
    ev = {"matches": [fresh_match(1, [{"participants": ["Jim Duggan"], "was_winner": True}, {"participants": ["Ron Bass"], "was_winner": False}])]}
    rows = [{"class": "result", "match_order": 1, "cawthon": "Ron Bass defeats Rick Hunter (2:31)"},
            {"class": "result", "match_order": 1, "cawthon": "Ron Bass pinned Jim Duggan at 9:00"}]
    out = _reclass_results(rows, ev)
    assert [r["class"] for r in out] == ["different_opponent", "result"]


def _studio(opponents):
    caw = {"wwf-prime-time-wrestling-1985": [
        {"air_date": "1985-01-15", "tape_date": None, "city": None, "venue": None,
         "matches": [{"kind": "match", "winners": ["Adrian Adonis", "Dick Murdoch"], "losers": ["Afa", "Sika"], "result": "no contest",
                      "sub_for": [], "notes": [], "line": "Adonis & Murdoch fought the Wild Samoans to a double DQ", "duration_seconds": None, "method": "no-contest"}]}]}
    cm = [_cm("PrimeTime", "1985-01-15", ["Adrian Adonis", "Dick Murdoch"], 3)]
    cm[0]["matches"][0]["teams"][0]["participants"] = ["Adrian Adonis", "Dick Murdoch"]
    cm[0]["matches"][0]["teams"][1]["participants"] = opponents
    for t in cm[0]["matches"][0]["teams"]:
        t["was_winner"] = None                      # a double DQ on both records
    cm[0]["matches"][0]["result_method"] = "Double DQ"
    cards, review, report = join_all(cm, caw, [], {}, {})
    return next(c for c in cards if c["show_type"] == "PrimeTime"), review


def test_studio_vote_only_counts_lines_with_the_same_people():
    pt, review = _studio(["Afa", "Sika"])
    assert pt["verification_status"] == "verified" and pt["cagematch_url"] and review == []


def test_a_studio_vote_sharing_no_match_confirms_nothing():
    # Two names in common, no bout in common: no second source, no link.
    pt, review = _studio(["Jack Brisco", "Jerry Brisco"])
    assert pt["verification_status"] == "single-source" and not pt.get("cagematch_url") and review == []


def test_two_sources_against_the_spine_change_the_card():
    from backfill.join import apply_votes
    ev = {"air_date": "1998-12-28", "matches": [fresh_match(1, [{"participants": ["Road Dogg"], "was_winner": True}, {"participants": ["Val Venis"], "was_winner": False}], result_method="by DQ")]}
    rows = [{"class": "result", "vote": "fix_result_same_people", "match_order": 1, "his_winners": ["Val Venis"], "event_key": "k", "cawthon": "Val Venis defeated Road Dogg via disqualification"},
            {"class": "missing_match", "vote": "add_match", "match_order": "", "event_key": "k",
             "cawthon": "Edge pinned Al Snow at 3:00", "sdh_match": None},
            {"class": "unpaired", "vote": "split", "match_order": 1, "event_key": "k"}]
    applied = []
    kept = apply_votes(ev, rows, applied)
    m = ev["matches"][0]
    # The finish comes with the winner: a win by disqualification moves no belt.
    assert [t["was_winner"] for t in m["teams"]] == [False, True] and m["teams"][1]["match_outcome"] == "dq-win"
    assert m["result_method"] == "by DQ"
    assert len(ev["matches"]) == 2 and ev["matches"][1]["teams"][0]["participants"] == ["Edge"] and ev["match_count"] == 2
    assert [r["class"] for r in kept] == ["unpaired"] and len(applied) == 2


def test_other_arenas_of_a_claimed_ppv_night_are_not_second_shows():
    wiki = [{"title": "WrestleMania 2", "show_type": "PPV", "list_date": "1986-04-07",
             "events": [fresh_event(air_date="1986-04-07", show_type="PPV", title="WrestleMania 2", ppv_name="WrestleMania 2", primary_source="wikipedia",
                                    matches=[fresh_match(1, [{"participants": ["Hulk Hogan"], "was_winner": True}, {"participants": ["King Kong Bundy"], "was_winner": False}])])]}]
    cm = [_cm("PPV", "1986-04-07", ["Hulk Hogan", "King Kong Bundy"], 1, derivation="live-broadcast"),
          _cm("PPV", "1986-04-07", ["Davey Boy Smith", "Greg Valentine"], 2, derivation="live-broadcast"),
          _cm("PPV", "1986-04-07", ["Mr. T", "Roddy Piper"], 3, derivation="live-broadcast")]
    cards, review, report = join_all(cm, {}, wiki, {}, {})
    assert len(cards) == 1 and cards[0]["primary_source"] == "wikipedia" and report["same_night_arenas"] == 2


def test_expand_groups_drops_a_team_label_kept_beside_its_members():
    from backfill.join import expand_groups
    ev = {"air_date": "1986-04-07", "matches": [fresh_match(1, [
        {"participants": ["British Bulldogs", "Davey Boy Smith", "Dynamite Kid"], "was_winner": True, "team_name": "British Bulldogs"},
        {"participants": ["Dream Team", "Brutus Beefcake", "Greg Valentine"], "was_winner": False, "team_name": "Dream Team"}])]}
    groups = {"british bulldogs": [("1986-04-07", ["Davey Boy Smith", "Dynamite Kid"])]}
    out = expand_groups(ev, groups)
    assert out["matches"][0]["teams"][0]["participants"] == ["Davey Boy Smith", "Dynamite Kid"]
    assert out["matches"][0]["teams"][1]["participants"] == ["Brutus Beefcake", "Greg Valentine"]
    solo = {"air_date": "1986-04-07", "matches": [fresh_match(1, [{"participants": ["The Rock"], "was_winner": True}, {"participants": ["Mankind"], "was_winner": False}])]}
    assert expand_groups(solo, {})["matches"][0]["teams"][0]["participants"] == ["The Rock"]
