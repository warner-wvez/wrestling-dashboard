# Data audit, August 2026

A pass over the corpus and the running app from the point of view of the person
this is built for: someone rewatching the Attitude and Ruthless Aggression eras
in order, who knows the period well enough to notice when the data is wrong.

**Method.** Read the full corpus (3,053 events, 19,563 matches, 58 title
lineages) directly, then drove the app in Chrome DevTools through a new user's
path: landing show, event cards, spoiler toggle, a wrestler profile, the Titles
pages, search. Every championship claim below was checked against the published
title history rather than from memory. Counts are from the corpus, not
estimates.

Everything in "Fixed" is done and on this branch. Everything in "Open" is
reproducible against the current build.

---

## Fixed in this branch

Three guards in the reign walk (`build_title_reigns` in `src/export_to_html.py`),
covered by 15 tests in `tests/test_reign_guards.py`. Each test cites the real
match and the published history it contradicts.

**Reigns: 1,226 to 1,182.** Fifty-three removed, nine added. Reigns longer than
1,400 days: seven, now zero.

### Guard 1: ambiguous stake

A belt only moves when the source is unambiguous about *this* belt moving.

| Was showing | Truth |
|---|---|
| Triple H, WWE Championship, 2006-05-15 to 06-11 | John Cena held it Jan 29 to Jun 11 2006 |
| Edge, World Heavyweight, 2004-11-29 to 2005-01-30 | Triple H. Edge's first was May 2007 |
| Kofi Kingston, Universal, 2019-04-08 to 05-13 | Seth Rollins. Kofi has never held it |
| Chris Benoit, inaugural US Champion, 2003-06-19 | Eddie Guerrero, Vengeance 2003 |
| The Usos, inaugural SmackDown Tag, 2016-08-23 | Heath Slater and Rhyno, Backlash 2016 |
| Nia Jax and Tamina, inaugural Women's Tag, 2019-01-28 | Sasha Banks and Bayley, Elimination Chamber 2019 |
| Six US title changes, Aug to Oct 2004 | One. Cena won the best-of-five decider |

Causes and rules added:

- **A singles belt does not change hands on a multi-man win.** The source fuses
  held-up finishes, handicap matches and tornado tags into one winning side.
  Raw 2004-11-29 reads "Chris Benoit and Edge defeat Triple H (c)", which is
  both men pinning him at once and the title being held up.
- **A `TITLE CHANGE` marker on a composite `A / B` stake is not evidence for
  either half.** Raw 2006-05-15 is a three-on-two handicap tagged "WWE
  Heavyweight Title / Intercontinental Title" whose marker belongs to the
  Intercontinental half.
- **Exception, so real unifications survive:** a clean winners-take-all swap,
  where winners equals belts equals champions defending, maps one belt to one
  winner. SummerSlam 2008's mixed tag is the shape.
- **The DQ/countout retain check now asks about this belt's champion**, not the
  match-level `(c)` flag, which was true for the *other* belt's holder the night
  after WrestleMania 35.
- **Tournament rounds, qualifiers and mid-series nights never move a belt.**
  Finals still do. Only the decider of a best-of-N carries the marker.

### Guard 2: a champion respelled is not a new champion

Compared through the alias map, stored verbatim, so a reign keeps the ring name
it was won under (King Booker stays King Booker).

| Was showing | Truth |
|---|---|
| Seth Rollins' 2023 World Heavyweight reign as four reigns | One, 2023-05-27 to 2024-04-07. Split on `Seth "Freakin" Rollins` |
| Big Show's 2012 reign as three reigns | One. Split on the word "The" |
| The Dudleys losing and regaining the tag titles, 2001-02-25 | No title change. Respelled Buh Buh Ray to Bubba Ray |
| La Resistance doing the same, 2004-09-12 | No title change. Rob to Robert Conway |

### Guard 3: a revived belt is a new lineage

A belt unseen past the existing 550-day threshold ends its lineage, **unless the
same champion walks in on the far side.** That veto matters: the corpus carries
almost no NXT UK, and without it Pete Dunne's real 685-day reign was cut in half
by the hole in the middle of it.

| Was showing | Truth |
|---|---|
| Hart Dynasty, World Tag Team, 5,110 days | Belt retired Aug 2010, name revived 2024 |
| Randy Orton, Big Gold, 3,459 days | Unified away at TLC 2013, name revived 2023 |
| Hornswoggle, Cruiserweight, 3,353 days | Retired 2007, revived by the 2016 Cruiserweight Classic |
| Charlotte, WWE Women's, 2,504 days | Renamed 2016 |
| Big E and Kofi, WWE Tag, 2,175 days | Brand split renamed the belts |
| Michelle McCool, Women's, 2,082 days | Unified into the Divas Championship, Sept 2010 |
| Trish Stratus, World Women's, 1,562 days | Trish retired in 2006 |

Longest reigns now top out at Roman Reigns 1,316 days, Pete Dunne 685 and
Gunther 666, all matching the published records.

### Corrected inaugural champions

Five of the nine additions are belts whose first champion the board had wrong:
Eddie Guerrero (US, Vengeance 2003), Benoit and Angle (WWE Tag, No Mercy 2002),
Slater and Rhyno (SmackDown Tag, Backlash 2016), Banks and Bayley (Women's Tag,
Elimination Chamber 2019), Charlotte (Women's, WrestleMania 32).

### Known limits of the fix

Both are under-claims rather than inventions. Wrong dates beat wrong champions.

- Triple H now reads Sep 2004 to Apr 2005 continuously, because the corpus does
  not carry Randy Orton's 2004-12-06 win.
- Adam Cole's NXT reign (743 days, real is 449) and Carlito and Primo's tag
  reign (723 days) stay long. Both are corpus coverage holes: weekly NXT is not
  ingested, so the title changes are invisible. Not fixable in the reign walk.

---

## Open findings

Ranked by what a knowledgeable viewer notices first.

### 1. 435 matches silently drop a wrestler

The parser reads `Name & The Group ( A & B )` and keeps only the parenthesised
pair. The person named before the group is discarded. Distribution: 48 in 2001,
41 in 2013, 53 in 2015, 435 total across 2001 to 2019.

This hits the landing show (2001-01-01 Raw) twice:

- M02 renders 3-on-2. The label says "AS BILLY GUNN & THE APA" but only Bradshaw
  and Faarooq are listed.
- M04 says "AS CHRIS JERICHO & THE DUDLEY BOYZ" with only the two Dudleys.

Worst case found: 2001-01-18 SmackDown, where the parser made **Triple H (the
special guest referee)** the entire opposing team and dropped Kurt Angle,
Rikishi and Kane.

This is the highest-value remaining fix. It is a parser change in one place,
the same shape as the guards above.

### 2. Unrendered source markup reaches the UI

- **752 matches render raw MediaWiki link syntax.** With spoilers on, Worlds
  Collide 2020 shows `[[Kay Lee Ray]] defeated [[Mia Yim]] by [[pinfall]]` and
  `[[DIY (professional wrestling)|DIY]]`. All from the Wikipedia lane, 2020
  onward.
- **27 matches list placeholders as opponents:** "Erick Rowan def. a jobber",
  "Shayna Baszler def. 3 jobbers", plus `countout`, `double countout`,
  `no contest` and `2 local competitors` parsed as people.
- **`and` appears as a wrestler four times**, from pipe links like
  `[[Fraxiom|and]]`.
- **One participant is named `Jeff Hardy by TKO`.**

### 3. Era-wrong branding

- **The landing show is branded wrong.** It reads `WWF RAW #397` while every
  other 2001 episode reads `WWF RAW is WAR`. The Up Next list directly below it
  shows `RAW is WAR #398`. Two names for the same show in one viewport.
- **All 149 SmackDown episodes from 2001 to 2003 are labelled "Thursday Night
  SmackDown".** That branding is from the 2014 to 2016 Syfy era. In 2001 to 2003
  it was `WWF SmackDown!` then `WWE SmackDown!`. It also drops the promotion
  prefix, so 2002 and 2003 carry two naming conventions in parallel
  ("Thursday Night SmackDown" and "WWE SmackDown").
- **Attitude and Ruthless Aggression matches get a bare "Match" label** while
  modern shows get "Singles match" and "Eight-man tag team match".
- **2001 title matches miss the belt chip** that modern shows get, because
  `title_at_stake` sometimes has "Match" glued onto it.

### 4. Era-wrong identity and photos

Merging is right for tracking a person, but the card shows the *latest*
gimmick's profile and photo. On a 2001 card, "Bradshaw" renders the Wall Street
JBL suit-and-tie headshot.

| Card says (era) | Opens profile and photo of |
|---|---|
| Bradshaw (2001 to 2007, 103 matches) | John Bradshaw Layfield |
| Albert (2001), A-Train (2002 to 2004) | Tensai, a 2012 gimmick |
| Jamal (2002, 3-Minute Warning) | Umaga |
| Nicky (Spirit Squad, 2006) | Dolph Ziggler |
| Festus (2007 to 2008) | Luke Gallows |
| Akio (2003 to 2005) | Jimmy Wang Yang |
| Johnny Nitro (2004 to 2007) | John Morrison |

For a spoiler-safe chronological app this is not only an era error, it is a
spoiler: it shows a gimmick years before the viewer reaches it.

### 5. Era-wrong names

- **Buh Buh Ray Dudley.** WWF billed him Bubba Ray from 1999. Both spellings
  appear in January 2001, a week apart.
- **The Good Father.** It is Goodfather, one word. On the landing show.
- **Kai En Tai.** It is Kaientai. Searching the correct spelling returns zero
  results.
- **Gregory Helms in 2001.** He was Shane Helms, then The Hurricane. Gregory
  Helms is a 2006 name.
- **Walter** title-cased. It was stylised WALTER.
- **Steve Austin** rather than "Stone Cold" Steve Austin, which appears exactly
  once in the whole corpus (2001-09-20).

118 pairs of same-person, two-spellings-in-one-month remain.

### 6. Championship naming is unnormalised

**276 distinct title strings for roughly 40 belts.** Includes
`World Heavyweight    Title` (four spaces), `WWE Women's Tag Tean Championship`,
smart-quote and straight-quote duplicates of the same belt, a `Title` versus
`Championship` vocabulary split at the 2020 source seam, and dozens of full
stipulation sentences such as
`"If Bryan wins he gets a WWE Universal Championship match af Fastlane"`.

The reign guards work around this; they do not fix it.

### 7. The Titles page structure

- **The WWE Championship and the World Heavyweight Championship are merged into
  one belt page.** Those were two separate world titles on two separate brands
  for the entire 2002 to 2013 brand-split era, which is the whole point of a
  Ruthless Aggression rewatch. The reign data underneath is correct now; the
  grouping above it is not.
- **Section headers repeat out of order** with contradictory year ranges:
  "WWE CHAMPIONSHIP 2001-2001", "BIG GOLD 2001-2001", "WWE CHAMPIONSHIP
  2001-2002", "BIG GOLD 2002-2013", "WWE CHAMPIONSHIP 2013-2016".
- **The WCW World Heavyweight Championship has no page at all**, despite 18
  matches in the corpus and being the belt the entire 2001 Invasion was built
  around. Booker T's and Kurt Angle's reigns are absent. WCW US and WCW Tag both
  get their own pages, so the omission reads as arbitrary.
- **The belt page defaults to "As of your date"**, which shows zero reigns under
  a headline claiming 94, with the self-contradicting line "Not yet established
  as of 1 Jan 2001. The corpus's first reign here begins Jan 2001."

### 8. Missing episodes

Twenty-three weeks absent.

- **Raw:** 2008-02-11, 2009-07-06, 2010-08-02, 2010-08-23, 2010-09-27,
  2011-07-04, plus four Christmas weeks (2018-12-24, 2019-12-23, 2022-12-26,
  2023-12-25).
- **SmackDown:** six alternating weeks in early 2009 (01-09, 01-23, 02-06,
  02-27, 03-13, 03-27), plus 2006-12-29, 2008-11-21, 2008-12-05, 2013-10-04 and
  three Christmas weeks (2018-12-25, 2021-12-31, 2023-12-29).

### 9. Missing artwork

**716 of the 1,155 wrestlers who appear in a match have no headshot**, which is
5.9% of all match slots. On the landing show `roster-img/the-goodfather.webp`
404s and leaves a blank hole rather than falling back to the silhouette,
breaking the column alignment. Also missing: Jerry Lawler, Vince McMahon,
Jacqueline, D-Lo Brown, Crash Holly, Taka Michinoku.

### 10. Smaller items

- **Footer credits "Cagematch + Fandom".** The README says Cagematch, The
  SmackDown Hotel and Wikipedia. The wrestler profile page correctly credits The
  SmackDown Hotel, contradicting the footer above it.
- **Footer counts (3,053 / 19,563) do not match the README (3,046 / 19,521).**
- **Tape date renders as raw ISO,** `Taped 2000-12-29`, next to properly
  formatted dates like "Jan 1, 2001".
- **The wrestler profile is mostly empty state.** Steve Austin's page is seven
  stacked one-line placeholders, roughly 60% dead page on first visit.
- **Fonts load from fontshare and Google Fonts,** and the service worker only
  handles same-origin, so "works fully offline" is not quite true for
  typography.
- **The "Champ" badge renders after the last name in a team,** so in the
  Undisputed Era eight-man it reads as though Roderick Strong is champion when
  it is Adam Cole.

---

## Verified correct

Recorded so nobody "fixes" these by mistake. All were checked and are right.

- **The PPV slate 2001 to 2008 is exact.** Every event, date and venue checked,
  including New Year's Revolution 2005 in Puerto Rico and ECW December to
  Dismember in Augusta.
- **Raw is War branding correctly ends 2001-09-10.** WWF dropped "Is War" after
  September 11.
- **The WWF to WWE rename lands exactly on 2002-05-06.**
- **Every SmackDown broadcast-night change is right:** Fridays 2005-09-09,
  Thursdays 2015-01-15, Tuesdays as SmackDown Live 2016-07-19, Fox Fridays
  2019-10-04. The Jan 2015 date in `src/smackdown_schedule.py` is correct and
  was double-checked against the source.
- **The alias map is sound.** WALTER and Gunther, Mankind and Cactus Jack and
  Mick Foley, Stardust and Cody, Santina and Santino all merge correctly.
- **Austin's 2001 title lineage is exact,** including the one-night Chris
  Jericho WWF Championship reign at Vengeance.
- **The winner notation is clear.** "DEF ->" reads ambiguous as plain text, but
  the rendered card puts the winner in red bold on a highlighted row and greys
  the loser, so it cannot be misread.
- **Search works well,** including stipulations and venues.
- **Zero console errors** across the whole session.
