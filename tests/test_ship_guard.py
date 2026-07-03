"""
Unit tests for src.ship_guard: atomic artifact writes and the pre-write
corpus floor gate.

Run from project root:
    python3 -m unittest tests.test_ship_guard
or:
    python3 tests/test_ship_guard.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ship_guard import (  # noqa: E402
    MIN_PPV_PER_FULL_YEAR, MIN_WEEKLY_PER_FULL_YEAR, WEEKLY_SHOWS,
    atomic_write_text, corpus_floor_problems)


class TestAtomicWriteText(unittest.TestCase):
    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.dir = Path(tmpdir.name)
        self.path = self.dir / "artifact.html"

    def test_writes_content(self):
        atomic_write_text(self.path, "hello")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "hello")

    def test_overwrites_existing(self):
        self.path.write_text("old", encoding="utf-8")
        atomic_write_text(self.path, "new")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "new")

    def test_no_tmp_left_behind(self):
        atomic_write_text(self.path, "x")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["artifact.html"])

    def test_failed_replace_keeps_original_and_cleans_tmp(self):
        self.path.write_text("live", encoding="utf-8")
        with mock.patch("src.ship_guard.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                atomic_write_text(self.path, "half-written")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "live")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["artifact.html"])


class TestCorpusFloorProblems(unittest.TestCase):
    START, END = 2020, 2026

    def healthy(self):
        """Counts shaped like the real corpus: ~52 weeklies per show per full
        year, mid-year partial current year, PPVs only through last year."""
        weekly = {(show, y): 52 for y in range(self.START, self.END + 1)
                  for show in WEEKLY_SHOWS}
        weekly[("raw", self.END)] = 25
        weekly[("smackdown", self.END)] = 26
        ppv = {y: 16 for y in range(self.START, self.END)}
        return weekly, ppv

    def test_healthy_corpus_passes(self):
        weekly, ppv = self.healthy()
        self.assertEqual(corpus_floor_problems(weekly, ppv, self.START, self.END), [])

    def test_thin_full_weekly_year_fails(self):
        weekly, ppv = self.healthy()
        weekly[("raw", 2023)] = MIN_WEEKLY_PER_FULL_YEAR - 1
        problems = corpus_floor_problems(weekly, ppv, self.START, self.END)
        self.assertEqual(len(problems), 1)
        self.assertIn("raw-2023", problems[0])

    def test_missing_weekly_year_counts_as_zero(self):
        weekly, ppv = self.healthy()
        del weekly[("smackdown", 2021)]
        problems = corpus_floor_problems(weekly, ppv, self.START, self.END)
        self.assertEqual(len(problems), 1)
        self.assertIn("smackdown-2021", problems[0])
        self.assertIn("0 episode(s)", problems[0])

    def test_thin_full_ppv_year_fails(self):
        weekly, ppv = self.healthy()
        ppv[2022] = MIN_PPV_PER_FULL_YEAR - 1
        problems = corpus_floor_problems(weekly, ppv, self.START, self.END)
        self.assertEqual(len(problems), 1)
        self.assertIn("PPV 2022", problems[0])

    def test_partial_year_needs_weeklies_but_no_ppvs(self):
        # January build of the current year: no PPV yet is fine, but a show
        # that has aired zero episodes means the weekly fetch broke.
        weekly, ppv = self.healthy()
        weekly[("raw", self.END)] = 0
        problems = corpus_floor_problems(weekly, ppv, self.START, self.END)
        self.assertEqual(len(problems), 1)
        self.assertIn(f"raw-{self.END}", problems[0])

    def test_multiple_problems_all_reported(self):
        weekly, ppv = self.healthy()
        del weekly[("raw", 2020)]
        ppv[2024] = 0
        problems = corpus_floor_problems(weekly, ppv, self.START, self.END)
        self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
