"""Wikipedia's title lists write a reign's date both ways round.

The NXT UK lists write the day first ("{{dts|15 January 2017}}"), which the
list reader skipped, so all three belts read as empty, and two NXT lists
lost a vacancy each the same way.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lineup-check"))

from wiki_titles import _date  # noqa: E402


def test_a_day_first_date_reads():
    assert _date("{{dts|15 January 2017}}") == "2017-01-15"
    assert _date("{{dts|12 Jan 2019}}") == "2019-01-12"


def test_the_month_first_dates_still_read():
    assert _date("{{dts|2019|01|12}}") == "2019-01-12"
    assert _date("{{dts|April 6, 2024}}") == "2024-04-06"
    assert _date("March 25–26, 2020") == "2020-03-25"
