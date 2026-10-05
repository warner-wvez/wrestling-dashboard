# lineup-check

Checks that the right wrestlers are on every 2001 to 2013 Raw, SmackDown and
PPV card by comparing each one with an independent record, Graham Cawthon's
results archive at [thehistoryofwwe.com](https://thehistoryofwwe.com/). The
SmackDown Hotel's curated cards cast a third vote on weekly shows.

Only changes **both sources agree on** are applied (by
`src/migrations/0004_apply_lineup_check.py`). Everything else is a suggestion
in `out/review.csv` for a person to rule.

## Run

From the repo root:

    uv run --with requests lineup-check/cawthon_fetch.py      # 39 pages, a few minutes
    uv run --with requests --with beautifulsoup4 lineup-check/lineup_check.py
    uv run --with requests --with beautifulsoup4 src/migrations/0004_apply_lineup_check.py --dry-run

The fetch writes `cache/` (Cawthon) and the check reads `sdh-cache/` (SmackDown
Hotel year pages, `raw-is-war-2001` for 2001); both are gitignored.

## What gets applied automatically

| Kind | Rule | Count (2026-10-05) |
|---|---|---|
| Not on the broadcast | Our source labels it a dark match **and** Cawthon's televised list does not have it | 760 |
| Wrestler put back | Cawthon lists him **and** our own match text names him (not as an escort), but the stored lineup lost him | 13 |
| Aired on Heat | A PPV card's match that pairs both ways with Cawthon's Sunday Night Heat pre-show | 1 |

Hand checks during the build found each rule's failure mode, and each has a
test in `tests/test_lineup_match.py`: a Hell in a Cell match that really aired
was nearly greyed out, escort credits made 16 of 19 draft additions wrong, and
a battle royal "aired on Heat" because it shared one entrant.

## What goes to review

Everything else, about 1,400 rows: matches on one card and not the other,
different opponents, different winners, shows one source lacks. SmackDown
Hotel's vote is attached as a suggestion. It is not applied, because a sample
showed it pairs the wrong matches in elimination tags, gauntlets and
multi-man matches. A vote kind can become automatic only after a hand check
of 20 random rows finds 19 or more right.

## The source's quirks

- A taped show's header carries the taping date, the italic line the air date.
- Raw 2009 labels its 6/29/09 San Jose show 7/6/09; the parser flags pages
  that contradict their own date.
- Some air-date lines drop the colon and run the first match on (Raw 11/2/09).
- A PPV's match list can be interrupted by an italic note (No Mercy 02).
- Group names appear without members ("the Acolytes"); they are expanded from
  the members our own source gives that group nearest the show date.
