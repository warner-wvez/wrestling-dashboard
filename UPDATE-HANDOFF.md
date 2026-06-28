# WWE Dashboard: Fill to Present Day (Handoff)

## YOUR ONE MOVE

Open a terminal, start Claude in this repo, and paste the kickoff prompt. Claude does the rest.

```
cd ~/wrestling-dashboard && claude
```

Then paste this:

> Read UPDATE-HANDOFF.md in the repo root and the memory file project_wrestling_sourcing_upgrade.md, then execute the handoff end to end: apply the 2 fixes, generalize src/build_update.py to fill 2020 through present using the SmackDown Hotel (weekly) plus Wikipedia (PPVs, auto-discovered), rebuild index.html and dist/wrestling-dashboard.html, verify the new shows show up and the counts look sane, show me a before/after summary, then commit and push the full update to present day.

That is the whole job for you. Everything below is the map Claude follows. You do not need to read it.

---

## Where we are (about 90% done)

- [x] Weekly results parser, curated + clean dates, no fantasy junk: `src/smackdownhotel.py`
- [x] PPV results parser, free Wikipedia API, exact durations + correct dates: `src/wikipedia_ppv.py`
- [x] Merge + rebuild engine: `src/build_update.py` (PROVEN: added all of 2020 onto the live corpus, recomputed wrestler stats + title reigns with zero errors)
- [ ] 2 small fixes
- [ ] Full run: 2020 to present, all weekly shows + every PPV
- [ ] Rebuild the real bundle, commit, push live

The data plan is locked: **weekly shows from the SmackDown Hotel, PPVs from Wikipedia.** No durations or ratings on brand-new weeklies, and that is fine and approved. Full source reasoning lives in memory: `project_wrestling_sourcing_upgrade.md`.

---

## The plan (Claude: do these in order)

### 1. Two fixes

**Fix A (cosmetic): singles get no team_name.** In `src/build_update.py`, `map_match()`, the team dict sets `"team_name": t.get("team_name")`, which is `None` for singles. Default it so the UI never shows a blank: `t.get("team_name") or " & ".join(t.get("participants", [])) or None`. (Existing corpus sets a team_name even for singles, e.g. "Chris Jericho".)

**Fix B (real): Royal Rumble pages return 0 matches.** `uv run src/wikipedia_ppv.py "Royal Rumble (2020)"` yields nothing. Investigate the wikitext (`action=parse&prop=wikitext`): the Rumble match likely uses "won by" / last-eliminated phrasing instead of "defeated", and the undercard may sit in a separate table the parser misses. Make the undercard parse, and capture the Rumble match as one row (winner = the Rumble winner) or flag it low-confidence, just never return 0. Affects ~6 Rumbles (2020-2026). Money in the Bank and Elimination Chamber already parse fine (tested), so this is Rumble-specific.

### 2. Generalize `src/build_update.py` from proof mode to the full run

It currently hardcodes 2020 + 3 PPVs and writes a PROOF file. Change it to:
- **Weekly:** loop `show in ("raw","smackdown")`, `year in range(2020, 2027)`, `fetch_year(show, year)` then `parse_year_html` then `map_sdh`. (URL pattern `<show>-<year>` works for 2020-2026; 2026 is partial/current, that is expected.)
- **PPV discovery:** parse Wikipedia's "List of WWE pay-per-view and livestreaming supercards" to get every PPV article title for 2020-2026, then `parse_event(fetch_wikitext(title))` then `map_wikipedia` for each. If that list page is messy to parse, fall back to the known per-year PPV titles (Royal Rumble, Elimination Chamber, WrestleMania, Backlash, Money in the Bank, SummerSlam, Survivor Series, Crown Jewel, etc.).
- **De-dupe** by `(air_date, show_type)` so nothing doubles up (the existing corpus ends 2019-12-30, so overlap should be zero, but guard anyway).
- **Write the real bundle to BOTH** `index.html` and `dist/wrestling-dashboard.html` (not the PROOF path). Use the existing `inject(bundle, template)` with `frontend/index.html` as the template.

### 3. Run + sanity check

```
cd ~/wrestling-dashboard && uv run --with requests --with beautifulsoup4 src/build_update.py
```
Expect: events ~2,266 to ~3,000+, `year_range` [2001, 2026], no exceptions (the `build_*` assertions passing IS the integrity check). Then open `index.html` in a browser (or use `/run`): confirm 2020-2026 appear in the year selector, spot-check a recent Raw and a 2025/2026 PPV, confirm the spoiler toggle and My List still work. Bundle will be ~18-20 MB, expected.

### 4. Ship it

```
rm -f dist/wrestling-dashboard-PROOF.html
git checkout -b feat/fill-to-present-2026
git add src/wikipedia_ppv.py src/smackdownhotel.py src/build_update.py UPDATE-HANDOFF.md index.html dist/wrestling-dashboard.html
git commit  # message below
git push -u origin feat/fill-to-present-2026
```
Commit message (NO em dashes, NO emojis, brand rule):
```
feat: extend corpus to present day (2020-2026)

Adds a SmackDown Hotel weekly lane (curated Raw/SmackDown) and a
Wikipedia PPV lane (MediaWiki API), merged into the bundle with
wrestler stats and title reigns recomputed.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```
Then **show the user the before/after summary and the browser check, and on their go, take it live** (main is the GitHub Pages source):
```
git checkout main && git merge feat/fill-to-present-2026 && git push origin main
```

---

## Don't-rabbit-hole notes

- **The UI probably needs zero changes.** The frontend builds its year selector from `year_range` at load time and already handles matches with no rating (only ~21% of the old corpus had them). So the new shows should just appear once the bundle rebuilds. Verify in the browser; do not redesign anything.
- **Bundle size (~18-20 MB) is fine on desktop.** It brushes the iOS-Safari memory ceiling, so era-sharding is a real follow-up, but it is a LATER task, not part of this update. Do not start it now.
- **profightdb durations = optional later enrichment.** Skip for this update; weeklies ship without durations and that is approved.
- **Environment:** system Python is broken, always use `uv run`. The parsers are stdlib-only (`uv run src/...`); `build_update.py` needs `--with requests --with beautifulsoup4` because it imports `export_to_html`.
- **Sources serve to normal requests** (SmackDown Hotel sits behind Cloudflare but answers a browser User-Agent; Wikipedia is the sanctioned API). No bouncer-bypassing anywhere, by design.
