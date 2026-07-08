"""Era-aware SmackDown broadcast schedule.

Cagematch records the TAPING date for taped SmackDown episodes (its "Date"
field), not the night the show aired. The old pipeline estimated the air date
as tape_date + 2 days for every episode, but SmackDown's broadcast night has
changed several times, so a flat +2 is only right in the eras where taping
(usually Tuesday) sits exactly two days before broadcast (the Thursday eras).
In the Friday eras it lands a day early; in the 2016-2019 Tuesday-LIVE era it
lands two days late.

This maps a taping date to the correct broadcast weekday for its era, then
snaps forward to the first occurrence of that weekday on or after the taping
date. Cutover dates (verified):
  - 1999-08-26 debut .. 2005-09-08 : Thursday
  - 2005-09-09 .. 2015-01-09        : Friday   (moved to Fridays 2005-09-09)
  - 2015-01-15 .. 2016-07-18        : Thursday (last Friday ep 2015-01-09,
                                                first Thursday ep 2015-01-15)
  - 2016-07-19 .. 2019-10-03        : Tuesday, LIVE (SmackDown Live premiere,
                                                USA Network, air == tape date)
  - 2019-10-04 .. present           : Friday   (FOX premiere 2019-10-04)

Boundaries are expressed against the taping date (shows tape a few days before
air), so the exact air cutover and the tape cutover differ by a few days; the
gap between eras contains no taping day, so classification is unambiguous.
"""
from datetime import date, timedelta

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

# (tape_date lower bound inclusive, air weekday, is_live). Ordered; the first
# era whose lower bound <= tape_date and next era's bound > tape_date wins.
_ERAS = [
    (date(1900, 1, 1),  THU, False),  # debut era, aired Thursdays
    (date(2005, 9, 7),  FRI, False),  # moved to Fridays 2005-09-09
    (date(2015, 1, 10), THU, False),  # back to Thursdays 2015-01-15
    (date(2016, 7, 19), TUE, True),   # SmackDown Live, Tuesdays, LIVE
    (date(2019, 10, 4), FRI, False),  # FOX, back to Fridays
]


def _era_for(tape_date):
    era = _ERAS[0]
    for e in _ERAS:
        if tape_date >= e[0]:
            era = e
        else:
            break
    return era


def smackdown_air_date(tape_date):
    """Return (air_date, derivation) for a SmackDown taped on tape_date.

    air_date is the first broadcast-weekday occurrence on or after tape_date for
    that date's era. derivation is 'live-broadcast' for the Tuesday-live era
    (air == tape) or 'air-night-estimate' otherwise.
    """
    _, air_weekday, is_live = _era_for(tape_date)
    delta = (air_weekday - tape_date.weekday()) % 7
    air = tape_date + timedelta(days=delta)
    return air, ("live-broadcast" if is_live and delta == 0 else "air-night-estimate")
