# cagematch-pipeline

Turns the Firecrawl scrape of Cagematch's WWE promotion pages into join tables
the rest of the repo can key on.

```
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_raw.py
```

Reads `.firecrawl/cagematch-raw/results-*.md` (gitignored, ~74MB, 280 pages of
100 events each). Writes three tables to `out/`, ~3MB, committed.

## Why

`src/db.py` already reserves `events.cagematch_nr` and `wrestlers.cagematch_id`,
both UNIQUE. Only the 2183 cagematch-sourced events carry an event nr, and no
wrestler carries a worker id at all. Every wrestler link in the scrape supplies
one:

```
[Chad Gable](https://www.cagematch.net/?id=2&nr=15197&name=Chad+Gable)
```

A worker nr survives ring-name changes, which name-keyed joins do not. The
roster renders **JBL**; every Cagematch row for him reads *Bradshaw* or *John
Bradshaw Layfield*. Only the nr reconciles those.

## Tables

| file | key | holds |
|---|---|---|
| `cm_events.json` | event nr | date, title, type, show_type, venue, location, logo |
| `cm_workers.json` | worker nr | every ring name seen, with usage counts |
| `cm_event_workers.json` | event nr | `{worker nr: name used in this event}` |

Events are trimmed to the corpus (Raw / SmackDown / PPV, 3705 of 27987) because
the dashboard carries nothing else and the untrimmed tables are 20MB. Worker
name counts are **not** trimmed: alias evidence improves with more history, and
the table is 120KB regardless.

## Three things the parse has to get right

**Cagematch dates are taping nights.** For taped SmackDown that is not the
broadcast date, and the offset is era-dependent. The parse routes SmackDown
through `src.smackdown_schedule.smackdown_air_date` rather than a flat +2.
Skipping this leaves ~100 SmackDown rows joined to the wrong day or to nothing.

**The scrape is in German.** It was fetched without the `/en/` prefix, so ~700
rows say `Frankreich`, `Saudi-Arabien`, or `Island` (Iceland, not an island).
`DE_TO_EN_COUNTRY` maps every non-English token in the corpus, and an unmapped
one raises rather than landing in a column that elsewhere says `France`.

**A ring name can belong to two people.** 95 names are claimed by more than one
worker. `Kane` is Glenn Jacobs 2719 times and Luke Gallows once, during the 2006
impostor angle. `Butch` is a Bushwhacker and also Pete Dunne. `Chavo Guerrero`
is both Sr and Jr. A global name → worker map therefore fuses two people, so
`cm_event_workers.json` records the name each worker used *in each event*: only
one Kane wrestled on any given night. (At Vengeance 2006 both did — that was the
match. A majority vote across a wrestler's career absorbs it.)

## What the tables resolve

Joining on `cagematch_nr` where present, else `(air_date, show_type)`:

- **781 of the 863** events with no `cagematch_nr` match a unique Cagematch event
- **1199 of 1366** wrestlers resolve to a worker id, 1191 of them unanimously
- **133 split identities**: one person rendered as several on the roster,
  `jbl(102) + john-bradshaw-layfield(152)` among them

Classification and location splitting are imported from `src.cagematch_scraper`
rather than reimplemented, so a corpus rule cannot drift between the two.
