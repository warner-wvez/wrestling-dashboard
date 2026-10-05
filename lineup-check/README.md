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

## Title histories

The Titles view walks every title match in order and builds each belt's
reigns. Four tools check that walk against the published histories and feed it
what no card carries:

    uv run --with requests --with beautifulsoup4 lineup-check/title_audit.py [title ...]
    uv run --with requests --with beautifulsoup4 lineup-check/title_vacancies.py
    uv run --with requests --with beautifulsoup4 lineup-check/house_show_titles.py
    uv run --with requests --with beautifulsoup4 lineup-check/offcard_titles.py

- `title_audit.py` lays each belt's reigns beside its Wikipedia list and prints
  every stretch where the champions differ (dates are shown, not compared).
- `title_vacancies.py` writes `data/title-vacancies.json`: vacancies and titles
  awarded without a match, kept only when the list's outgoing champion is who
  we have holding the belt.
- `house_show_titles.py` writes `data/house-show-title-changes.json`: changes
  at house shows, and reigns WWE recognized without a match, that Wikipedia
  and a second record (Cawthon, or Duncan and Will's wrestling-titles.com)
  both list.
- `offcard_titles.py` writes `data/offcard-title-changes.json`: the Hardcore
  title's house-show swaps under the 24/7 rule, two of three records agreeing.
- `title_247.py` writes `data/247-title-changes.json`: the 24/7 title's
  changes outside a match (backstage, ringside, house shows, no show at all),
  two of three title histories agreeing: Wikipedia, Duncan and Will, and
  WWE.com's own history (cached in `wwe-cache/`). A change on a taped show
  takes its air date, and one on a show we carry sits between that show's
  matches in the order the histories give.

As of 2026-10-05 every belt in the lineage map, plus the Intercontinental,
United States, European, ECW, Women's tag and 24/7 titles, matches its list
reign for reign. Two do not: the NXT Cruiserweight title (four reigns won on
NXT TV or a missing Stomping Grounds 2019 match), and the Hardcore title
(Wikipedia lacks two April 2002 house-show nights that Cawthon and Solie both
list). The 24/7 title differs in one place by ruling: Hershey 2019-12-29 runs
Sunil Singh, then Samir, the order Duncan and Will and WWE.com both give;
Wikipedia lists Samir first and calls WWE.com's order a mistake.

## The source's quirks

- A taped show's header carries the taping date, the italic line the air date.
- Raw 2009 labels its 6/29/09 San Jose show 7/6/09; the parser flags pages
  that contradict their own date.
- Some air-date lines drop the colon and run the first match on (Raw 11/2/09).
- A PPV's match list can be interrupted by an italic note (No Mercy 02).
- Group names appear without members ("the Acolytes"); they are expanded from
  the members our own source gives that group nearest the show date.
