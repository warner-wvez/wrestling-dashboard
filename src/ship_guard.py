"""
Ship-safety helpers for the bundle build: atomic artifact writes and the
pre-write corpus floor gate.

Stdlib-only on purpose, so tests (and any future tooling) can import it
without pulling in the scraper dependency chain (requests, bs4).
"""

from __future__ import annotations

import os
from pathlib import Path

# Floors sit well under the observed per-year counts in the shipped corpus
# (weekly: 51-53 episodes per show per full year; PPV/PLE: 14-21 per full
# year, 2020-2025), so a legitimately odd year still passes but a
# half-fetched source page or a broken discovery run cannot ship. The final
# year in range is the current year at build time, so it is only required to
# have started airing; PPV counts there can legitimately be zero in January.
MIN_WEEKLY_PER_FULL_YEAR = 45
MIN_WEEKLY_PER_PARTIAL_YEAR = 1
MIN_PPV_PER_FULL_YEAR = 10
WEEKLY_SHOWS = ("raw", "smackdown")


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` via a same-directory temp file + os.replace, so
    a crash mid-write can never leave a truncated live artifact in place."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def corpus_floor_problems(weekly_counts: dict, ppv_year_counts: dict,
                          start_year: int, end_year: int) -> list:
    """Return human-readable problems for any lane that came back thin.

    weekly_counts maps (show, year) -> parsed episode count; a (show, year)
    that never fetched simply has no key and counts as zero. ppv_year_counts
    maps year -> kept PPV event count. Empty list means the corpus clears
    every floor and is safe to ship.
    """
    problems = []
    for year in range(start_year, end_year + 1):
        partial = year == end_year
        wfloor = MIN_WEEKLY_PER_PARTIAL_YEAR if partial else MIN_WEEKLY_PER_FULL_YEAR
        for show in WEEKLY_SHOWS:
            got = weekly_counts.get((show, year), 0)
            if got < wfloor:
                problems.append(
                    f"{show}-{year}: {got} episode(s) parsed, floor is {wfloor}")
        if not partial:
            got = ppv_year_counts.get(year, 0)
            if got < MIN_PPV_PER_FULL_YEAR:
                problems.append(
                    f"PPV {year}: {got} event(s) kept, floor is {MIN_PPV_PER_FULL_YEAR}")
    return problems
