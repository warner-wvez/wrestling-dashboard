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
- **1203 of 1366** wrestlers resolve to a worker id
- **136 split identities**: one person rendered as several on the roster,
  `jbl(102) + john-bradshaw-layfield(152)` among them

Classification and location splitting are imported from `src.cagematch_scraper`
rather than reimplemented, so a corpus rule cannot drift between the two.

---

# resolve_identities.py -> apply_merge.py

```
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/resolve_identities.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/apply_merge.py [--dry-run]
```

The resolver decides one roster identity per worker and names it. The applier
rewrites `wrestlers` and `wrestlers_by_name` in `index.html`, and copies
headshots onto the canonical slug. Matches, events and title reigns are never
touched, so the shards stay valid. Both are idempotent.

## Naming rule

The name the wrestler is best known by, never a real name, never a one-off
storyline alias. Match cards keep the era-accurate alias and link to the merged
profile; only the roster aggregates under the canonical name.

Trust the corpus window (2001-2026) when it is decisive, meaning the dominant
name is at least `MARGIN` times the runner-up. Otherwise fall back to full WWE
history. Corpus counts are frequently near-ties that carry no signal (Robert
Roode 65, Bobby Roode 62); full history alone would name him Mankind rather than
Mick Foley. Two threshold artifacts are pinned in `OVERRIDES`, keyed by worker nr
so a spelling change cannot unhook them the way the quoted `CURATED` keys did.

The SmackDownHotel roster is deliberately not consulted: it records today's
gimmick, which for Pete Dunne is "Rayo Americano" and for Humberto Carrillo is
"Berto".

## Three guards, each protecting against a merge that looked right

**Resolve inside the event, not globally.** 95 ring names belong to two workers.
`Kane` is Glenn Jacobs 2719 times and Luke Gallows once. Career-wide majority
vote then absorbs the single night both wrestled as Kane.

**Never remap a shared name.** `canon` is a global name -> name function with no
way to say "that night this name meant someone else", so a name worn by more
than one wrestler keeps its own roster entry. `El Grande Americano` is worn by
Chad Gable and Ludwig Kaiser; `Doink` by four workers. Without this the majority
owner swallows the others' matches. The resolver prints every name it refuses.

**Donor headshots come only from unshared names.** Steve Lombardi wrestled once
as "MVP"; the first version of the donor search handed the Brooklyn Brawler
MVP's face.

## Two joins that are easy to get subtly wrong

Names are matched against the night's roster by exact string, then by `normkey`.
The corpora disagree on 329 participations (`Finn Bálor`, `T-Bar` vs `T-BAR`,
`Seth "Freakin" Rollins`, `Big Show`), and exact-only matching strands them.

The applier follows the canon chain one level: a name whose only matches sit in
the 82 events that do not join to Cagematch still has a shipped canonical, and
that canonical may itself be merging away (`T-Bar` -> `Dijak` -> `T-BAR`).
Resolving one level leaves an orphan fragment beside the merged entry.

## Fidelity gate

There is no local `wrestling.db`, so the bundle cannot be regenerated from
source. It does not need to be: `build_wrestlers_index` takes an events dict,
and `events` is recoverable exactly from the bundle's event metadata plus the
match shards. Before changing anything, `apply_merge` rebuilds the index with
the *shipped* canon and asserts it reproduces the shipped index exactly. If the
reconstruction were wrong, every number downstream would shift silently.
