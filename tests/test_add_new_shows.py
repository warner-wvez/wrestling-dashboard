"""
Unit tests for src.add_new_shows: the window, the already-on-file check, the
weekly gate, the cache bump, and the title-change summary.

Run from project root:
    uv run --with requests --with beautifulsoup4 python -m unittest tests.test_add_new_shows
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.add_new_shows import (  # noqa: E402
    PREEMPTION_ALLOWANCE, aired_dates, already_have, apply_aired_date, bump_cache,
    fix_spellings, list_rows, near_miss, ppv_name_key, title_changes, usual_airings,
    weekly_problems)


def ev(air_date, show_type, title=None, ppv_name=None):
    return {"air_date": air_date, "show_type": show_type, "title": title, "ppv_name": ppv_name}


class TestUsualAirings(unittest.TestCase):
    def test_mondays_and_fridays_in_span(self):
        self.assertEqual(usual_airings("raw", "2026-07-14", "2026-07-31"),
                         ["2026-07-20", "2026-07-27"])
        self.assertEqual(usual_airings("smackdown", "2026-07-14", "2026-07-31"),
                         ["2026-07-17", "2026-07-24", "2026-07-31"])

    def test_bounds_are_inclusive(self):
        self.assertEqual(usual_airings("raw", "2026-07-20", "2026-07-20"), ["2026-07-20"])


class TestAlreadyHave(unittest.TestCase):
    def test_one_weekly_show_per_date(self):
        on_file = [ev("2026-07-13", "Raw", "Monday Night Raw")]
        self.assertTrue(already_have(ev("2026-07-13", "Raw", "Raw"), on_file))
        self.assertFalse(already_have(ev("2026-07-13", "SmackDown"), on_file))

    def test_ppv_matches_by_date_and_name(self):
        on_file = [ev("2026-06-27", "PPV", "Night of Champions", "Night of Champions")]
        self.assertTrue(already_have(ev("2026-06-27", "PPV", "WWE Night of Champions 2026"), on_file))
        # a second event the same night is new, not a duplicate
        self.assertFalse(already_have(ev("2026-06-27", "PPV", "NXT Heatwave", "NXT Heatwave"), on_file))

    def test_ppv_name_key_ignores_prefix_year_and_night(self):
        self.assertEqual(ppv_name_key("WWE SummerSlam 2026 - Night 2"), ppv_name_key("SummerSlam"))


class TestWeeklyGate(unittest.TestCase):
    def test_full_window_passes(self):
        found = {"raw": usual_airings("raw", "2026-07-14", "2026-10-22"),
                 "smackdown": usual_airings("smackdown", "2026-07-14", "2026-10-22")}
        self.assertEqual(weekly_problems(found, "2026-07-14", "2026-10-22"), [])

    def test_allows_preemptions_then_blocks(self):
        raws = usual_airings("raw", "2026-07-14", "2026-10-22")
        sds = usual_airings("smackdown", "2026-07-14", "2026-10-22")
        ok = {"raw": raws[PREEMPTION_ALLOWANCE:], "smackdown": sds}
        self.assertEqual(weekly_problems(ok, "2026-07-14", "2026-10-22"), [])
        thin = {"raw": raws[PREEMPTION_ALLOWANCE + 1:], "smackdown": sds}
        problems = weekly_problems(thin, "2026-07-14", "2026-10-22")
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("raw:"))

    def test_missing_lane_blocks(self):
        found = {"raw": usual_airings("raw", "2026-07-14", "2026-10-22")}
        self.assertTrue(any(p.startswith("smackdown:")
                            for p in weekly_problems(found, "2026-07-14", "2026-10-22")))


class TestBumpCache(unittest.TestCase):
    def test_increments_version(self):
        text, n = bump_cache("x\nconst CACHE = 'wrestling-dashboard-v44';\ny")
        self.assertEqual(n, 45)
        self.assertIn("const CACHE = 'wrestling-dashboard-v45';", text)

    def test_no_cache_line_raises(self):
        with self.assertRaises(RuntimeError):
            bump_cache("const OTHER = 1;")


class TestTitleChanges(unittest.TestCase):
    def test_reports_only_new_reigns_in_window(self):
        old = {"title_reigns": {"WWE Championship": [
            {"start": "2026-07-06", "end": None, "champion_names": ["CM Punk"]}]}}
        new = {"title_reigns": {"WWE Championship": [
            {"start": "2026-07-06", "end": "2026-08-01", "champion_names": ["CM Punk"]},
            {"start": "2026-08-01", "end": None, "champion_names": ["Cody Rhodes"]}]}}
        self.assertEqual(title_changes(old, new, "2026-07-13"),
                         ["2026-08-01: Cody Rhodes won the WWE Championship"])


class TestAiredDates(unittest.TestCase):
    LIST = (
        "|-\n| bgcolor=#B9E2C9 |September 26<br>{{small|(aired September 30)}} "
        "|[[Worlds Collide (2026)|Worlds Collide]] |[[Allstate Arena]]\n"
        "|-\n| |October 10 |[[Money in the Bank (2026)|Money in the Bank]] |[[Smoothie King Center]]\n")

    def test_reads_only_rows_that_aired_later(self):
        self.assertEqual(aired_dates(self.LIST), {"Worlds Collide (2026)": "2026-09-30"})

    def test_moves_air_date_and_keeps_tape_date(self):
        evs = apply_aired_date([{"air_date": "2026-09-26", "tape_date": None}], "2026-09-30")
        self.assertEqual((evs[0]["air_date"], evs[0]["tape_date"]), ("2026-09-30", "2026-09-26"))
        self.assertIn("aired 2026-09-30", evs[0]["date_derivation"])

    def test_leaves_live_and_multi_night_events(self):
        live = [{"air_date": "2026-10-10", "tape_date": None}]
        self.assertEqual(apply_aired_date(live, None)[0]["air_date"], "2026-10-10")
        two = [{"air_date": "2026-08-01"}, {"air_date": "2026-08-02"}]
        self.assertEqual([e["air_date"] for e in apply_aired_date(two, "2026-08-05")],
                         ["2026-08-01", "2026-08-02"])


class TestSpelling(unittest.TestCase):
    KNOWN = {"Damian Priest": 120, "R-Truth": 300, "Tamina": 80, "Jey Uso": 400, "Jimmy Uso": 400,
             "Rare Name": 3}

    def test_one_letter_off_a_regular(self):
        self.assertEqual(near_miss("Damien Priest", self.KNOWN), "Damian Priest")

    def test_short_names_need_a_closer_match(self):
        self.assertIsNone(near_miss("Tama", self.KNOWN))          # Tamina is two letters off

    def test_ambiguous_or_rare_is_left_alone(self):
        two = {**self.KNOWN, "Jay Uso": 50}
        self.assertIsNone(near_miss("Joy Uso", two))              # Jey Uso and Jay Uso both 1 off
        self.assertIsNone(near_miss("Rare Nane", self.KNOWN))     # under 10 cards

    def test_rewrites_card_and_team_name(self):
        ev = {"air_date": "2026-09-11", "show_type": "SmackDown", "episode_number": 1413,
              "matches": [{"teams": [{"team_name": "Damien Priest & R-Truth",
                                      "participants": ["Damien Priest", "R-Truth"]}]}]}
        fixes = fix_spellings([ev], self.KNOWN)
        team = ev["matches"][0]["teams"][0]
        self.assertEqual(team["participants"], ["Damian Priest", "R-Truth"])
        self.assertEqual(team["team_name"], "Damian Priest & R-Truth")
        self.assertEqual(len(fixes), 1)


class TestListRows(unittest.TestCase):
    TEXT = ("\n====2026====\n{| class=wikitable\n|-\n|July 18\n|[[Saturday Night's Main Event XLV|"
            "Saturday Night's Main Event]]\n|-\n|August 1\n|[[SummerSlam (2026)|SummerSlam]]\n|}\n"
            "==Upcoming event schedule==\n|-\n|December 5\n|[[Future Event]]\n")

    def test_dated_rows_of_the_year(self):
        self.assertEqual(list_rows(self.TEXT, [2026]),
                         [("2026-07-18", "Saturday Night's Main Event XLV"),
                          ("2026-08-01", "SummerSlam (2026)")])


if __name__ == "__main__":
    unittest.main()
