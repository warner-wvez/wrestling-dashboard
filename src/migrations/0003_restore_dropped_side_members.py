"""
Restore the wrestlers the historical parser dropped from 2001-2019 cards.

src/fandom_scraper._split_team read "Billy Gunn & The APA ( Bradshaw & Faarooq )"
as one stable whose members are the parenthesised pair, so anyone named before
the group vanished from the card: the landing show, Raw 2001-01-01, rendered a
six-man tag as three-on-two. The same regex read "(Special Guest Referee:
Triple H )" as a member list and made the referee the whole team. The parser is
fixed; this re-derives the affected teams from each match's stored
raw_description, patches the shipped bundle, and rebuilds every index the same
way src/rebuild_indexes.py does.

Operates on the live artifacts (index.html core + shards), the source of truth
on machines without data/wrestling.db.

Safety gates, in order:
  1. Fidelity. A team is touched only when its stored participants are exactly
     what the OLD parser produces from the same raw_description, with the same
     number of teams. Anything a later pass already edited is left alone.
  2. No silent removals. A patched team may only lose a name the raw names as
     an official (referee, enforcer, timekeeper). Anything else aborts the run.
  3. Group names are not people. When a name the fix would add is a stable or
     tag-team name elsewhere in the corpus ("Los Matadores", whose member list
     the source misplaced after Santino Marella), the team is skipped and listed
     for review instead.
  4. Count. Aborts unless the patched-team count sits in the window measured
     when this was written (400 to 460, measured 2026-10-04 at 442).

Idempotent: once applied, the patched teams match the NEW parser's output, so
gate 1 skips them and the run reports "already applied".

Run from project root:
    uv run --with requests --with beautifulsoup4 src/migrations/0003_restore_dropped_side_members.py [--dry-run]
"""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bs4 import BeautifulSoup  # noqa: E402

import src.cagematch_scraper as cagematch  # noqa: E402
import src.fandom_scraper as fandom  # noqa: E402
from src.build_update import load_existing  # noqa: E402

CUTOFF = "2020-01-01"          # 2020 on comes from the SmackDown Hotel / Wikipedia lanes
EXPECTED = range(400, 461)
_OFFICIAL_NAME_RE = re.compile(
    r"\(\s*[^()]*\b(?:referee|enforcer|timekeeper)\b\s*:\s*([^()]*?)\s*\)", re.IGNORECASE)


def old_split_team(team_text):
    """_split_team as it was before the fix, frozen here so gate 1 can tell
    which stored teams came straight from it."""
    team_text = team_text.strip()
    m = fandom._STABLE_RE.match(team_text)
    if m:
        return (fandom._canonicalize_name(m.group(1)),
                fandom._split_participants(m.group(2).strip()))
    cleaned = re.sub(r"\s+", " ", team_text).strip()
    cleaned = fandom._TRAILING_MATCH_NARRATIVE_RE.sub("", cleaned).strip()
    participants = fandom._split_participants(cleaned)
    if len(participants) > 1:
        return fandom._canonicalize_name(cleaned), participants
    solo = fandom._canonicalize_name(cleaned)
    return solo, ([solo] if solo else [])


@contextmanager
def _splitter(fn):
    saved = cagematch._split_team
    cagematch._split_team = fn
    try:
        yield
    finally:
        cagematch._split_team = saved


def parse_teams(raw, split):
    """Teams for a stored raw_description, run through the real match parser
    with the given side splitter."""
    div = BeautifulSoup(f'<div><div class="MatchResults">{raw}</div></div>',
                        "html.parser").div
    with _splitter(split):
        return cagematch.parse_match_block(div, 1)["teams"]


def group_labels(events):
    """Label keys of every 'Label ( A & B )' group in the historical raws."""
    keys = set()
    for ev in events.values():
        if ev["air_date"] >= CUTOFF:
            continue
        for m in ev.get("matches") or []:
            for side in re.split(r"\s+(?:defeat(?:s|ed)?|vs\.?)\s+", m.get("raw_description") or ""):
                # escorts "(w/ A & B )", officials and "(c)" are not member lists
                for strip in (fandom._ACCOMP_RE, fandom._OFFICIAL_PAREN_RE, fandom._CHAMPION_RE):
                    side = strip.sub(" ", side)
                for tok in fandom._split_depth0(side):
                    g = fandom._STABLE_RE.match(tok)
                    if g and len(fandom._split_depth0(g.group(2))) >= 2:
                        keys.add(_key(g.group(1)))
    return keys


def _key(name):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^the\s+", "", (name or "").strip().lower()))


def plan(events):
    """(patches, skipped, already) where patches are
    (event, match, team_index, old_participants, new_participants)."""
    labels = group_labels(events)
    patches, skipped, already = [], [], 0
    for ev in events.values():
        if ev["air_date"] >= CUTOFF:
            continue
        for m in ev.get("matches") or []:
            raw = m.get("raw_description") or ""
            stored = m.get("teams") or []
            if not raw or not stored:
                continue
            old = parse_teams(raw, old_split_team)
            new = parse_teams(raw, fandom._split_team)
            if len(old) != len(stored) or len(new) != len(stored):
                continue
            for i, team in enumerate(stored):
                have, was, now = team.get("participants") or [], old[i]["participants"], new[i]["participants"]
                if was == now:
                    continue
                if have == now:
                    already += 1
                    continue
                if have != was:                                   # gate 1
                    continue
                removed = [n for n in have if n not in now]
                officials = {fandom._canonicalize_name(x) for x in _OFFICIAL_NAME_RE.findall(raw)}
                if any(n not in officials for n in removed):      # gate 2
                    raise SystemExit(f"ABORT gate 2: {ev['air_date']} would drop {removed}: {raw}")
                added = [n for n in now if n not in have]
                if any(_key(n) in labels for n in added):         # gate 3
                    skipped.append((ev, m, have, now))
                    continue
                patches.append((ev, m, i, have, now))
    return patches, skipped, already


def main():
    dry = "--dry-run" in sys.argv
    data = load_existing()
    events = data["events"]
    patches, skipped, already = plan(events)

    if not patches and already in EXPECTED:
        print(f"already applied ({already} teams carry the fixed sides)")
        return
    if len(patches) not in EXPECTED:                              # gate 4
        raise SystemExit(f"ABORT gate 4: {len(patches)} teams to patch, expected "
                         f"{EXPECTED.start} to {EXPECTED.stop - 1}")

    print(f"patching {len(patches)} teams in {len({id(p[1]) for p in patches})} matches "
          f"on {len({p[0]['id'] for p in patches})} shows")
    for ev, m, have, now in skipped:
        print(f"  SKIPPED for review (group name would become a person): "
              f"{ev['air_date']} {have} -> {now} | {m['raw_description'][:120]}")
    for ev, m, i, have, now in patches[:5]:
        print(f"  e.g. {ev['air_date']} {ev['title']}: {have} -> {now}")
    if dry:
        print("dry run: nothing written")
        return

    for ev, m, i, have, now in patches:
        m["teams"][i]["participants"] = now
    from src.rebuild_indexes import rebuild
    rebuild(data)


if __name__ == "__main__":
    main()
