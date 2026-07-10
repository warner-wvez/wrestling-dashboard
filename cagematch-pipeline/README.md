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

---

# fill_locations.py

```
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_locations.py [--dry-run]
```

Fills venue and location, and backfills `events.cagematch_nr`. Idempotent.

| field | empty before | empty after |
|---|---|---|
| venue | 680 | 8 |
| city | 673 | 2 |
| state_province | 877 | 44 |
| country | 863 | 2 |
| cagematch_nr | 863 | 5 |

The 863 events with no `cagematch_nr` were exactly the ones with a location
problem: 673 SmackDownHotel rows had nothing at all, while 114 Wikipedia and 76
Fandom rows jammed the state into the city (`Houston, Texas`, and some with a
stray space: `Hartford, Connecticut , USA`). A join problem, not a scrape.

## Four keys, in order

1. **date + show type** settles 781.
2. **date + episode**, for nights Cagematch files two shows on (see below).
3. **date + venue**, for the two PPVs that share a night. WrestleMania Saturday
   and NXT Stand & Deliver are in different buildings, and a PPV has no episode
   number. Titles cannot settle it: Cagematch calls it "WrestleMania XL -
   Saturday" where the dashboard calls it "Night 1".
4. **episode + date window**, for shows whose broadcast date has no Cagematch
   row at all.

Every match is one-to-one. 3041 of 3046 events join; the 5 that do not are left
alone, beyond splitting their own jammed city string in place.

## Two traps

**Cagematch dates the taping.** parse_raw already handles taped SmackDown. Raw
needs no rule *except* in 2020, when WWE taped two episodes a night at the
Performance Center: Cagematch files RAW #1405 and #1406 both on 2020-04-27,
while they aired a week apart. The second episode has no row on its broadcast
date, which is why key 4 exists.

**Episode numbers disagree between sources.** Cagematch calls the 2001-01-04
SmackDown #73; Fandom calls it #72, consistently, for 74 straight events. The
venue (Freeman Coliseum, San Antonio) proves the *date* join is the right one,
so episode number can only be a tiebreaker, and only once the per-source offset
is learned from events already joined. Fandom SmackDown is +1, everything else 0.

## What it overwrites

Venue is filled when absent and **never** overwritten. Where both sides have
one, they are the same building under two names, and neither source is reliably
better (`Omaha Civic Auditorium` beats `Civic Auditorium`, but `Fort Worth
Convention Center` beats `Convention Center Arena`). The 86 disagreements go to
`out/location_conflicts.tsv` unresolved.

City, state and country are taken from Cagematch wholesale, because the shipped
strings are the dirty ones. This also fixes rows that duplicated the state into
the city (`city="Omaha, Nebraska"`, `state="Nebraska"`), German country names
left by the original scrape (`Irak`, `Italien`), and at least one plain error:
the 2001-08-16 SmackDown was filed under Salt Lake City, but the arena is in
West Valley City. All 243 rewrites are in `out/location_rewrites.tsv`.

Still German, and still wrong, from that original scrape: five foreign *city*
names (`Bagdad`, `Mailand`). The listing spells them the same way, so this pass
cannot fix them.

## Fidelity gate

There is no local `wrestling.db`, so the bundle cannot be regenerated from
source. It does not need to be: `build_wrestlers_index` takes an events dict,
and `events` is recoverable exactly from the bundle's event metadata plus the
match shards. Before changing anything, `apply_merge` rebuilds the index with
the *shipped* canon and asserts it reproduces the shipped index exactly. If the
reconstruction were wrong, every number downstream would shift silently.

---

# fetch_event_pages.py -> backfill_event_pages.py

```
uv run --with requests python cagematch-pipeline/fetch_event_pages.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/backfill_event_pages.py [--dry-run]
```

Once `fill_locations` stamps a `cagematch_nr` onto the 858 events that were not
sourced from Cagematch, their Cagematch event pages can finally be read. Nobody
ever fetched them, so the SmackDownHotel third of the corpus carried no match
durations, no attendance, no TV data and no commentary at all.

`fetch_event_pages` pulls one page per event through Firecrawl (a plain
`requests.get` hits Cagematch's 307 redirect loop) into `.firecrawl/cm-events/`,
skipping anything already on disk so the run is resumable, and writing a page
only if it actually looks like an event page. Firecrawl serves the English
rendering, so `tv_network` comes back `UPN`, not the German `PPV Sender` the
untargeted bulk scrape left behind.

`backfill_event_pages` parses each cached page with the same
`src.cagematch_scraper.build_event_from_html` the live scraper uses, and fills:

| where | fields | rule |
|---|---|---|
| bundle events | attendance, tv_network, tv_rating, broadcast_type, commentary, venue | fill when absent |
| match shards | duration_seconds, match_guide_rating | fill when absent |

City, state, country and dates are left to `fill_locations`; the event page
renders foreign place names in German.

## The match join

Within the event, by normkeyed and sorted team members, never by match order
(SmackDownHotel does not always agree with the page's order). It is
`fill_match_ratings`'s key minus the date, since the event nr already pins the
night. About 84% of SmackDownHotel matches join. The rest are 24/7-title
backstage skits and `a jobber` placeholders Cagematch never lists as matches,
multi-way matches the two sources group into different teams, and a few tag
partners spelled differently across sources. A miss costs a duration; it never
lands one on the wrong match.

## The gate

Where a shard match already has a rating (from the date-keyed matchguide join)
and the page carries one too, they must agree within 0.30. They are the same
Cagematch number seen at two scrape times. More than 2% disagreeing means the
within-event join is wrong, and the run aborts before writing. Idempotent:
fill-when-absent means a second run changes nothing.

---

# parse_promos.py -> fill_promos.py

```
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/parse_promos.py
uv run --with beautifulsoup4 --with requests python cagematch-pipeline/fill_promos.py [--dry-run]
```

A promo on Cagematch is a rated talking segment, the mic work fans argue about
the way they argue about a match. `parse_promos` flattens the 13 promo pages
(1236 rows, 1043 rated) into `out/cm_promos.json`; `fill_promos` hangs each on
its show and writes `shards/promos.json`, a lazy sidecar keyed by event id,
exactly like `shards/media.json`. The event page renders it as a "Promos from
this show" shelf beside the video-clip Moments shelf.

## The join

By date, like a match: Cagematch dates a promo by its taping night, so the key
is the event's `tape_date or air_date`. 208 promos predate the 2001 corpus and
~55 more fall on nights with no Raw / SmackDown / PPV; those stay unattached.
When two events share a night, the tie is broken by which card actually featured
the promo's workers, and an unresolvable tie is dropped rather than guessed. 791
promos attach to 592 shows.

## The check

There is no second promo source to agree with, so correctness is read off the
participants: on a right join, a segment's workers are people who were on that
show. `worker_overlap` reports the share of uniquely-dated promos whose workers
touch the event's match card. It sits around 44%, well above the ~0% a random
date would give, and it is not meant to be higher: Vince McMahon, Paul Heyman
and a commentator cut promos without ever wrestling. A collapse toward zero would
mean the date join is wrong.

Idempotent: the sidecar is rebuilt from scratch each run.
