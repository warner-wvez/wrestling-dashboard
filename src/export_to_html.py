"""
Bundle the full local wrestling.db into a single standalone HTML file.

Reads data/wrestling.db, walks events + matches + teams + participants into a
nested JSON object, and injects that JSON as an inline <script
id="wrestling-data" type="application/json"> tag inside frontend/index.html.
The output at dist/wrestling-dashboard.html needs no network connection and no
backend: open it and the calendar works.

Run:
    .venv/bin/python src/export_to_html.py
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Allow direct-script execution (`python src/export_to_html.py`) to resolve
# the sibling fandom_scraper module under the `src` package.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.fandom_scraper import _canonicalize_name  # noqa: E402
from src.ship_guard import atomic_write_text       # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "wrestling.db"
TEMPLATE = ROOT / "frontend" / "index.html"
OUT = ROOT / "dist" / "wrestling-dashboard.html"


def _to_bool(v):
    return None if v is None else bool(v)


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    return s or "unknown"


# Non-person participants that must never become wrestlers in the index (they
# would otherwise pollute the roster, rivalries, and tag partners). Two kinds:
#   - "???"         : Cagematch's unidentified-wrestler marker.
#   - generic crowd : counts of enhancement talent a result names in place of a
#                     real opponent, e.g. "a jobber", "3 local competitors",
#                     "The Masked Ninja", and the numbered "El Local #1" variants
#                     (but NOT the real recurring "El Local" gimmick).
# Match cards still show the text: the frontend renders any name absent from the
# wrestler index as plain text (see renderTeam/renderTeamBlock in
# frontend/index.html), so these never become broken links either.
PLACEHOLDER_NAMES: frozenset[str] = frozenset({"???"})

_PLACEHOLDER_RE = re.compile(
    r"^(?:"
    r"(?:a|an|\d+)\s+jobbers?"                      # a jobber, 2 jobbers
    r"|\d+\s+local\s+(?:competitors?|athletes?)"    # 3 local competitors / athletes
    r"|\d+\s+ninjas?|the\s+masked\s+ninja"          # 3 ninjas, The Masked Ninja
    r"|el\s+local\s+#?\d+"                          # El Local #1 (not bare "El Local")
    # comment-section UI a scraper can swallow as a participant:
    r"|facebook|google|twitter|disqus|login\s+this\s+site|newest(?:\s+best)?|oldest|popular"
    r"|\d+\s+up\s+\d+\s+down|\d+\s+comments?"
    # result-method words and title descriptors leaked in place of a name:
    r"|and|countout|double\s+countout|no\s+contest|no\s+decision"
    r"|.*\bchampion"
    r")$", re.I)


def is_placeholder_name(name: str) -> bool:
    """True for non-person participants to keep out of the wrestlers index."""
    n = (name or "").strip()
    return n in PLACEHOLDER_NAMES or bool(_PLACEHOLDER_RE.match(n))


def build_wrestlers_index(events: dict, canon=None, title_reigns=None) -> tuple[dict, dict]:
    """Pre-compute wrestler profiles from the assembled events dict.

    Returns (wrestlers, wrestlers_by_name) where wrestlers is keyed by slug
    and wrestlers_by_name maps display name -> slug.

    `title_reigns` (the output of build_title_reigns) is the preferred source
    for per-wrestler title wins: each non-pre-corpus reign start counts one win
    per champion, so a profile's title count can never disagree with the title
    history page. Without it, wins fall back to per-match counting, which
    cannot see mislabeled contender matches.

    `canon` optionally maps a raw participant name to a canonical wrestler name,
    merging ring-name changes and spelling variants (WALTER + Gunther -> one
    "Gunther" entry). Matches keep their era-accurate names; only the roster
    aggregates under the canonical name, and wrestlers_by_name additionally maps
    every alias -> the canonical slug so the frontend can still link an old name
    in a match card to the merged profile.

    Invariant enforced by assertion:
        total_matches == wins + losses + draws + no_contests
    Ambiguous outcomes (was_winner=None, not a draw or no-contest) are
    counted as no_contests so the invariant holds exactly.
    """
    canon = canon or (lambda n: n)

    # A group label that leaked into the participant list ("The Usos" beside Jey
    # and Jimmy) must not become a wrestler. Derived from the corpus, so every
    # caller of build_wrestlers_index gets the exclusion without threading it
    # through; the frontend already renders a non-indexed name as plain text, so
    # a bare group label still shows on the card, just without a fake profile.
    group_labels = collect_group_labels(events)

    def parts_of(team):
        return [canon(p) for p in team.get("participants", [])
                if p and not is_placeholder_name(p) and _label_key(p) not in group_labels]

    w_appearances: dict[str, list[tuple[str, int]]] = defaultdict(list)
    w_wins: Counter = Counter()
    w_losses: Counter = Counter()
    w_draws: Counter = Counter()
    w_ncs: Counter = Counter()
    w_ppv_events: dict[str, set] = defaultdict(set)
    w_main_events: Counter = Counter()
    w_title_wins: dict[str, Counter] = defaultdict(Counter)
    w_longest: dict[str, dict] = {}
    w_rivals: dict[str, Counter] = defaultdict(Counter)
    w_partners: dict[str, Counter] = defaultdict(Counter)

    for eid_str, ev in events.items():
        eid = int(eid_str)
        air_date = ev.get("air_date", "")
        # A dateless event can't be placed on the roster timeline, and a null
        # air_date would blow up the first_date min()/int(date[:4]) below. Skip
        # the whole event so appearances and outcomes stay in lockstep (the
        # W+L+D+NC == appearances invariant asserted later depends on it).
        if not air_date:
            continue
        show_type = ev.get("show_type", "")
        is_ppv = show_type == "PPV"
        event_name = ev.get("ppv_name") or ev.get("title") or ""

        matches = ev.get("matches", [])
        orders = [m["match_order"] for m in matches if m.get("match_order") is not None]
        max_order = max(orders) if orders else None

        for match in matches:
            teams = match.get("teams", [])
            duration = match.get("duration_seconds")
            # Same normalization as the reigns page: real belts only (no
            # stipulation blurbs, contendership matches, or match-type
            # decoration), Championship/Title spellings unified.
            belts_at_stake = _get_component_titles(match.get("title_at_stake"), match)
            match_order = match.get("match_order")
            is_main = max_order is not None and match_order == max_order
            raw_desc = match.get("raw_description") or ""

            any_nc = any(t.get("match_outcome") == "no-contest" for t in teams)
            any_draw = any(t.get("match_outcome") == "draw" for t in teams)

            is_singles = (
                len(teams) == 2
                and all(len(t.get("participants", [])) == 1 for t in teams)
            )

            # Per-wrestler stats
            for team in teams:
                parts = parts_of(team)
                was_winner = team.get("was_winner")
                was_champ = bool(team.get("was_champion_entering"))

                for name in parts:
                    w_appearances[name].append((air_date, eid))

                    # Outcome must be exactly one of W/L/D/NC to satisfy invariant.
                    # was_winner=None with no draw/nc is treated as NC.
                    if any_nc:
                        w_ncs[name] += 1
                    elif any_draw:
                        w_draws[name] += 1
                    elif was_winner is True:
                        w_wins[name] += 1
                    elif was_winner is False:
                        w_losses[name] += 1
                    else:
                        w_ncs[name] += 1

                    if is_ppv:
                        w_ppv_events[name].add(eid)

                    if is_main:
                        w_main_events[name] += 1

                    # Per-match fallback only (see title_reigns below). A
                    # DQ/countout win never moves a belt: the champion
                    # retains, so the challenger "winning" is not a title win.
                    if (title_reigns is None
                            and was_winner is True and not was_champ
                            and team.get("match_outcome") not in ("dq-win", "countout-win")):
                        for belt in belts_at_stake:      # one win per component belt
                            w_title_wins[name][belt] += 1

                    if duration is not None:
                        existing = w_longest.get(name)
                        if existing is None or duration > existing["duration_seconds"]:
                            w_longest[name] = {
                                "duration_seconds": duration,
                                "event_id": eid,
                                "event_date": air_date,
                                "event_name": event_name,
                                "description": raw_desc,
                            }

            # Rivalries: two-team singles only
            if is_singles:
                a_parts = parts_of(teams[0])
                b_parts = parts_of(teams[1])
                for a in a_parts:
                    for b in b_parts:
                        w_rivals[a][b] += 1
                        w_rivals[b][a] += 1

            # Tag partners: pairs within any team that has 2+ participants
            for team in teams:
                team_parts = parts_of(team)
                if len(team_parts) < 2:
                    continue
                for i, p1 in enumerate(team_parts):
                    for p2 in team_parts[i + 1:]:
                        w_partners[p1][p2] += 1
                        w_partners[p2][p1] += 1

    # Preferred source for title wins: the reign chains. One win per champion
    # per reign start observed in the corpus (pre-corpus reigns were won
    # before our data begins, so there is no win to count).
    if title_reigns is not None:
        for title, reigns in title_reigns.items():
            for reign in reigns:
                if reign.get("pre_corpus"):
                    continue
                for champ in reign["champion_names"]:
                    if not is_placeholder_name(champ):
                        w_title_wins[canon(champ)][title] += 1

    # Assign slugs with composite sort for determinism.
    # Primary: name (alphabetical). Tiebreak: earliest (air_date, event_id).
    # This ensures two wrestlers sharing a display name consistently get the
    # same slug assigned to the same person across rebuilds.
    def _first_appearance(name: str) -> tuple[str, int]:
        return min(w_appearances[name], key=lambda x: (x[0], x[1]))

    all_names = sorted(w_appearances.keys(), key=lambda n: (n, _first_appearance(n)))

    slug_counter: Counter = Counter()
    name_to_slug: dict[str, str] = {}
    for name in all_names:
        base = slugify(name)
        slug_counter[base] += 1
        name_to_slug[name] = base if slug_counter[base] == 1 else f"{base}-{slug_counter[base]}"

    wrestlers: dict[str, dict] = {}
    wrestlers_by_name: dict[str, str] = {}

    for name in all_names:
        slug = name_to_slug[name]
        appearances = w_appearances[name]

        wins = w_wins[name]
        losses = w_losses[name]
        draws = w_draws[name]
        ncs = w_ncs[name]
        total_matches = wins + losses + draws + ncs

        assert total_matches == len(appearances), (
            f"outcome sum mismatch for {name!r}: "
            f"W{wins}+L{losses}+D{draws}+NC{ncs}={total_matches} "
            f"!= appearances {len(appearances)}"
        )

        dates = [a[0] for a in appearances]
        first_date = min(dates)
        last_date = max(dates)
        first_year = int(first_date[:4])
        last_year = int(last_date[:4])

        unique_eids: set[int] = {a[1] for a in appearances}

        win_pct = round(wins / total_matches * 100, 1) if total_matches >= 10 else None

        title_wins_sorted = sorted(w_title_wins[name].items(), key=lambda x: -x[1])
        signature_title = title_wins_sorted[0][0] if title_wins_sorted else None

        top_rivalries = [
            [name_to_slug.get(opp, slugify(opp)), opp, cnt]
            for opp, cnt in w_rivals[name].most_common(10)
        ]
        top_tag_partners = [
            [name_to_slug.get(partner, slugify(partner)), partner, cnt]
            for partner, cnt in w_partners[name].most_common(5)
        ]

        # Latest air_date per event_id for sorting recent events
        eid_to_date: dict[int, str] = {}
        for air_date, eid in appearances:
            if eid not in eid_to_date or air_date > eid_to_date[eid]:
                eid_to_date[eid] = air_date
        recent_event_ids = sorted(unique_eids, key=lambda e: eid_to_date[e], reverse=True)[:10]

        wrestlers[slug] = {
            "slug": slug,
            "name": name,
            "first_match_date": first_date,
            "last_match_date": last_date,
            "active_years": [first_year, last_year],
            "total_matches": total_matches,
            "unique_event_count": len(unique_eids),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "no_contests": ncs,
            "ppv_appearances": len(w_ppv_events[name]),
            "main_events": w_main_events[name],
            "win_pct": win_pct,
            "signature_title": signature_title,
            "title_wins": title_wins_sorted,
            "top_rivalries": top_rivalries,
            "top_tag_partners": top_tag_partners,
            "longest_match": w_longest.get(name),
            "recent_event_ids": recent_event_ids,
        }
        wrestlers_by_name[name] = slug

    # Map every era-accurate alias (the name as it appears in a match card) to
    # the canonical wrestler's slug, so clicking "WALTER" in a 2019 card opens
    # the merged "Gunther" profile. Canonical names already mapped above win.
    for ev in events.values():
        for m in ev.get("matches", []):
            for t in m.get("teams", []):
                for p in t.get("participants", []):
                    if p and not is_placeholder_name(p) and p not in wrestlers_by_name:
                        s = name_to_slug.get(canon(p))
                        if s:
                            wrestlers_by_name[p] = s

    return wrestlers, wrestlers_by_name


# ============================================================================
# Title reign tracking (Phase 1b)
# ============================================================================

_TITLE_FILTER_PATTERNS = (
    re.compile(r'Contendership', re.I),
    re.compile(r'Contender', re.I),
    re.compile(r'Tournament', re.I),
    re.compile(r'Battle Royal', re.I),
    re.compile(r'Qualif', re.I),
)

# Contendership detection against the MATCH TYPE (see _drop_contendership_parts).
# Deliberately much narrower than _TITLE_FILTER_PATTERNS above, which is safe
# only against a belt string: run that set over a match type and 'Qualif' matches
# "No Disqualification", while 'Battle Royal' and 'Tournament' throw away real
# title wins (a vacant belt is legitimately decided by both).
_CONTENDERSHIP_RE = re.compile(r'\bcontender(?:ship|s)?\b', re.I)
# The marker as it trails the belt it points at: "<belt> #1 Contendership Match",
# "<belt> # 1 Contender ...", "<belt> Number One Contenders ...".
_TRAILING_CONTENDER_RE = re.compile(
    r'^\s*(?:#\s*\d+\s*|no\.?\s*\d+\s*|number\s+one\s+)?contender(?:ship|s)?\b', re.I)

# Scrapers store the belt name plus whatever decorated the line: a quoted
# stipulation blurb, the match type ("... Championship Steel Cage Match"), or
# both. Everything from a quote pair is stipulation, never belt.
_QUOTED_STIP_RE = re.compile(r'"[^"]*"')
# A belt is the shortest leading phrase that ends in Championship(s)/Title(s);
# whatever follows ("Triple Threat Match", "Lumberjack Match", "Street Fight")
# is match-type decoration. Parts with no such phrase ("vacant", "Steel Cage",
# "New Year's Evil") are not belts at all.
_BELT_RE = re.compile(r'^(.*?\b(?:Championships?|Titles?))(?=\s|$)', re.I)

TITLE_ALIASES = {
    "WWF Championship Title": "WWF World Heavyweight Title",
    "ECW Heavyweight Title":  "ECW World Heavyweight Title",
    # A source typo, one letter, that forked a live belt into a second lineage
    # with one champion who then never lost it. Not fixable by rule.
    "WWE Women's Tag Tean Title": "WWE Women's Tag Team Title",
}


def _normalize_title_part(part: str) -> str | None:
    s = re.sub(r'\s+', ' ', part).strip()
    m = _BELT_RE.match(s)
    if not m:
        return None
    s = m.group(1)
    s = re.sub(r'\bRAW\b', 'Raw', s)                       # WWE RAW / WWE Raw: same belt
    s = re.sub(r'\bChampionships$', 'Titles', s)
    s = re.sub(r'\bChampionship$', 'Title', s).strip()
    # The sources are inconsistent about the apostrophe and WWE never is, so
    # "WWE Womens Tag Team Title" is not a second belt. Left alone, one dropped
    # apostrophe forks a lineage: the fork inherits a single champion, and with
    # no later change to end the reign that champion holds it forever.
    s = re.sub(r"\bWomens\b", "Women's", s)
    s = TITLE_ALIASES.get(s, s)
    return s or None


# Shows whose card is a highlight reel, not a night of wrestling. Cagematch
# lists the clips a retrospective aired as that show's matches, complete with
# their original "TITLE CHANGE !!!" markers, so the reign walk re-crowns the
# winner years later: the Year In Review Special replayed WrestleMania X-Seven
# on 2001-12-31 and left Steve Austin holding the WWF Title for the next 25
# years, and the Benoit tribute replayed his career (the 2004 Royal Rumble, a
# 90s WCW match, a 1990 New Japan title change) onto one Raw in 2007.
#
# Curated by id rather than detected, because neither signal is safe alone.
# Title patterns catch real shows: WrestleMania 25 is subtitled "The 25th
# Anniversary Of WrestleMania" and Raw #759 is a 15th Anniversary show, and both
# are real cards with real title changes. Replay detection misses clips whose
# original predates the corpus or carries no duration to match on. Each id below
# was confirmed by reading its card.
#
# Only the reign walk skips these. The clips still show on the event page: they
# did air that night, and dropping them would empty the card.
CLIP_SHOWS = {
    221: "WWF RAW #449 - Year In Review Special (2001-12-31), 10/10 replays",
    471: "WWE RAW #604 - Year In Review Special (2004-12-20), 6/6 replays",
    770: "WWE Monday Night RAW #735 - Chris Benoit Tribute (2007-06-25)",
    831: "WWE SmackDown #436 - The Greatest Matches Of 2007 (2007-12-28)",
}


# A match type that declares how many SIDES it has. Cagematch writes a triple
# threat as "A defeats B and C", the parser splits on the verb, and everything
# right of it lands in one team, so three individuals become one man against two.
# The landing page's first main event has read "Steve Austin vs Kane & The
# Undertaker" ever since: a handicap match that never happened.
_MATCH_SIDES = (
    (re.compile(r'\btriple threat\b', re.I), 3),
    (re.compile(r'\bfatal (?:four|4)[- ]way\b', re.I), 4),
    (re.compile(r'\bfatal (?:five|5)[- ]way\b', re.I), 5),
    (re.compile(r'\bfour[- ]way\b', re.I), 4),
    (re.compile(r'\bthree[- ]way\b', re.I), 3),
    (re.compile(r'\bsix[- ]pack challenge\b', re.I), 6),
)


def _declared_sides(match_type: str | None) -> int | None:
    for pattern, n in _MATCH_SIDES:
        if pattern.search(match_type or ''):
            return n
    return None


def _is_fused_side(team: dict) -> bool:
    """True when a team's name is just its members listed, which is what the
    parser produces when it fuses two sides ("Kane & The Undertaker").

    A real team is named, not listed: "The Dudley Boyz" whose members are Bubba
    Ray and D-Von is a tag team and must never be cut into singles, even when it
    turns up in a match the side arithmetic says is one-per-side."""
    names = [p for p in (team.get('participants') or []) if p]
    if len(names) < 2:
        return False
    label = re.sub(r'\s+', ' ', (team.get('team_name') or '')).strip().lower()
    return label in {' & '.join(names).lower(), ' and '.join(names).lower()}


def _champion_among(names: list[str], raw: str) -> str | None:
    """Which of these people does the result text mark with (c)? Cagematch puts
    it straight after the champion ("Kane defeats Raven (c) and The Big Show"),
    so a fused side can be un-fused without inventing a second champion. None
    when it is not attributable, which includes the (c) sitting on a team name
    rather than a person."""
    hits = [n for n in names if re.search(re.escape(n) + r'\s*\(c\)', raw or '')]
    return hits[0] if len(hits) == 1 else None


# A stable/tag-team name that the modern (SmackDown Hotel) source writes as
# "[[The Usos]] ([[Jey Uso]] and [[Jimmy Uso]])" and the parser flattened into
# the participant list AS WELL AS its members, so the group label became a
# roster entry with its own win/loss record: The Usos, #DIY, Imperium, and
# ~17 others show up in the roster as if they were people.
_GROUP_LABEL_KEY = re.compile(r'[^a-z0-9]')


def _label_key(name: str) -> str:
    """Identity key for a group label: lowercase, drop a leading 'the', keep
    only a-z0-9, so 'The New Day' and 'New Day' are one label."""
    s = re.sub(r'^the\s+', '', (name or '').strip().lower())
    return _GROUP_LABEL_KEY.sub('', s)


# [[Otis (wrestler)|Otis]] -> [[Otis]]: normalize each wikilink to its display
# form so the ) inside a disambiguation does not break the member capture.
_WIKILINK_NORM = re.compile(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]')
_LABEL_PAREN = re.compile(r'\[\[([^\]]*)\]\]\s*\(([^)]*)\)')
_WIKILINK_INNER = re.compile(r'\[\[([^\]]*)\]\]')


def _expanded_members(raw: str):
    """Yield (label, [members]) for every '[[Label]] (m1 and m2 ...)' in the raw,
    with wikilinks normalized so a disambiguation paren does not truncate it.
    Skips accompaniment '(w/ ...)'."""
    norm = _WIKILINK_NORM.sub(lambda m: '[[' + m.group(1) + ']]', raw or '')
    for m in _LABEL_PAREN.finditer(norm):
        inside = m.group(2)
        if re.match(r'^\s*w\s*/|^\s*with\b', inside, re.I):
            continue
        members = [x.strip() for x in _WIKILINK_INNER.findall(inside)]
        if len(members) >= 2:
            yield m.group(1).strip(), members


def collect_group_labels(events: dict) -> set[str]:
    """The identity keys of every stable/tag-team name the corpus expands into
    real wrestlers.

    A name qualifies only when it is written '[[L]] (M1 and M2 ...)' AND every
    Mi is itself a competitor (a name that wrestles somewhere). That competitor
    test is what rejects the brand/title descriptor the same markup produces,
    "[[Cody Rhodes]] ([[SmackDown]]'s [[Undisputed WWE Champion]])", where the
    parenthetical is a brand and a belt, not members. Verified against the
    corpus: every name this returns is a group, no individual with a real match
    count is caught."""
    competitors = set()
    for ev in events.values():
        for match in ev.get('matches') or []:
            for t in match.get('teams') or []:
                for p in t.get('participants') or []:
                    if p:
                        competitors.add(p)
    labels: set[str] = set()
    for ev in events.values():
        for match in ev.get('matches') or []:
            for label, members in _expanded_members(match.get('raw_description') or ''):
                if all(mem in competitors for mem in members):
                    labels.add(_label_key(label))
    return labels


def strip_phantom_group_labels(events: dict, labels: set[str] | None = None) -> int:
    """Drop a group label from a team when its members are standing right beside
    it, in place. "[Roman Reigns, The Usos, Jey Uso, Jimmy Uso]" -> drop The Usos.

    Only removes the label when >=2 of its expanded members are co-participants,
    so a team represented ONLY by its group name (a gauntlet entry the source
    never expanded) keeps it; that bare label is instead kept out of the roster
    by build_wrestlers_index. Returns how many teams were trimmed."""
    if labels is None:
        labels = collect_group_labels(events)
    trimmed = 0
    for ev in events.values():
        for match in ev.get('matches') or []:
            expansions = {label: members
                          for label, members in _expanded_members(match.get('raw_description') or '')}
            if not expansions:
                continue
            for t in match.get('teams') or []:
                parts = [p for p in (t.get('participants') or []) if p]
                pset = set(parts)
                drop = set()
                for p in parts:
                    if _label_key(p) not in labels:
                        continue
                    members = expansions.get(p) or []
                    if sum(1 for mem in members if mem in pset and mem != p) >= 2:
                        drop.add(p)
                if drop:
                    t['participants'] = [p for p in parts if p not in drop]
                    trimmed += 1
    return trimmed


def split_fused_multiman_sides(events: dict) -> int:
    """Un-fuse the sides of a multi-man match, in place. Returns how many.

    Only the unambiguous shape is touched: the type declares N sides, the match
    has fewer, the people divide evenly into one-per-side, and every oversized
    team is a fused side rather than a named team. Anything else is left alone,
    because the alternative is cutting up a real tag team or manufacturing a
    second champion.
    """
    fixed = 0
    for ev in events.values():
        for match in ev.get('matches') or []:
            want = _declared_sides(match.get('match_type'))
            teams = match.get('teams') or []
            if not want or len(teams) >= want:
                continue
            people = [p for t in teams for p in (t.get('participants') or []) if p]
            if len(people) != want:            # one per side only; tag sides are
                continue                       # ambiguous about who pairs with whom
            oversized = [t for t in teams if len([p for p in (t.get('participants') or []) if p]) > 1]
            if not all(_is_fused_side(t) for t in oversized):
                continue
            # Only one side can win a three-way, so a fused WINNER is not a fused
            # side at all: the type is mislabelled, or the result is. Splitting
            # would hand the match two winners.
            if any(t.get('was_winner') for t in oversized):
                continue
            raw = match.get('raw_description') or ''
            champ_of = {}
            ok = True
            for t in oversized:
                if not t.get('was_champion_entering'):
                    continue
                names = [p for p in (t.get('participants') or []) if p]
                who = _champion_among(names, raw)
                if who is None:                # cannot say which one holds it
                    ok = False
                    break
                champ_of[id(t)] = who
            if not ok:
                continue

            out: list[dict] = []
            for t in teams:
                names = [p for p in (t.get('participants') or []) if p]
                if len(names) < 2:
                    out.append(t)
                    continue
                champ = champ_of.get(id(t))
                for n in names:
                    side = dict(t)
                    side['team_name'] = n
                    side['participants'] = [n]
                    # The belt belongs to one of them, not to both halves of a
                    # side the parser invented.
                    side['was_champion_entering'] = (n == champ) if t.get('was_champion_entering') else False
                    out.append(side)
            for i, t in enumerate(out, 1):
                t['team_number'] = i
            match['teams'] = out
            fixed += 1
    return fixed


# How long a belt may go unseen before the corpus stops claiming someone holds
# it. A reign ends when the next title change happens, so the LAST reign of a
# belt has nothing to end it and runs forever: left alone the corpus insists Rob
# Van Dam has held the Hardcore Title for 24 years, The Rock still has the WCW
# World Heavyweight Title, and ECW still crowns a champion. Those reigns then
# badge their holder as champion on every card for the rest of time.
#
# Retirement is not recorded anywhere, so the belt's own last title match stands
# in for it: we simply stop claiming a belt exists once the corpus stops showing
# it being defended. The gap is where the data separates itself. Ordering every
# open lineage by how long since its last title match leaves a clean break: the
# quietest live belt is 398 days (TNA World, a crossover defended rarely) and
# the noisiest dead one is 602 (Crown Jewel, annual and last seen 2024). 550
# sits in that gap and leaves room for a belt defended once a year plus the few
# weeks the corpus habitually lags reality.
#
# Deliberately NOT cagematch's INACTIVE flag, though cm_titles.json carries one.
# It keys by title name, and WWE reuses names: the World Heavyweight and World
# Tag Team titles were both revived years after the originals retired, so the
# derived lineage holds the old belt and its modern namesake together and the
# flag would end Roman Reigns' current reign. Last-seen gets those right for
# free, because the revival's matches keep the lineage live.
_TITLE_UNSEEN_GRACE_DAYS = 550


def _close_reign_at_retirement(reigns: list[dict], matches: list[dict],
                               corpus_end: str) -> None:
    """End a still-open final reign at the belt's last title match, when the
    corpus has not seen the belt in a long time. Mutates `reigns` in place."""
    final = reigns[-1]
    if final.get('end') is not None:
        return
    last_seen = matches[-1]                      # matches are sorted by air_date
    gap = (datetime.fromisoformat(corpus_end) - datetime.fromisoformat(last_seen['air_date'])).days
    if gap <= _TITLE_UNSEEN_GRACE_DAYS:
        return                                   # still being defended: genuinely current
    final['end'] = last_seen['air_date']
    final['end_event_id'] = last_seen['event_id']


def _looks_like_a_title_match(match: dict) -> bool:
    """Did a belt actually ride on this match? True when the source marked a
    champion entering, or says a belt changed hands."""
    if 'TITLE CHANGE' in (match.get('raw_description') or '').upper():
        return True
    return any(t.get('was_champion_entering') for t in match.get('teams') or [])


def _drop_contendership_parts(parts: list[str], match: dict) -> list[str]:
    """Drop the belts a contendership match only *points at*.

    Cagematch renders "WWF World Tag Team Title #1 Contendership Match" and links
    the belt's title page from that line, so _extract_titles_at_stake records the
    belt as at stake. It is not: a contendership match awards a title SHOT, and
    the belt never moves. Left alone, build_title_reigns crowns the winner, which
    invents reigns, truncates the real champion's, and (because a reign starts the
    night it is won) badges the winner of a match nobody has watched yet.

    _TITLE_FILTER_PATTERNS already means to catch this, but it only ever sees
    title_at_stake ("WWF World Tag Team Title"), which does not carry the marker.
    The marker lives in the match type, so the decision has to be made here.

    Per component, because the two can be mixed: "WWE Intercontinental Title /
    World Heavyweight Title #1 Contendership Match" really did put the IC belt on
    the line while awarding a World title shot. A component survives only when the
    marker does not trail it AND the match behaves like a title match, so a
    contendership battle royal naming two belts keeps neither.
    """
    match_type = match.get('match_type') or ''
    if not _CONTENDERSHIP_RE.search(match_type):
        return parts                  # ordinary title match: leave it alone
    hay = match_type.lower()
    kept: list[str] = []
    for part in parts:
        probe = re.sub(r'\s+', ' ', part).strip()
        if _CONTENDERSHIP_RE.search(probe):
            continue                  # the belt string itself carries the marker
        i = hay.find(probe.lower())
        if i < 0:
            continue                  # marker-first phrasing ("#1 Contender (WWE
            #                           Championship)"): belt not locatable, so it
            #                           can only be the thing being contended for
        if _TRAILING_CONTENDER_RE.match(match_type[i + len(probe):]):
            continue                  # "<belt> #1 Contendership ...": the prize
        kept.append(part)
    # A survivor is only credible if a belt truly rode on the match. Without that
    # corroboration the leading belt of a multi-belt contendership match would be
    # crowned off a battle royal nobody defended anything in.
    if kept and not _looks_like_a_title_match(match):
        return []
    return kept


def _get_component_titles(raw: str | None, match: dict | None = None) -> list[str]:
    if not raw:
        return []
    rem = re.sub(r'\s+', ' ', _QUOTED_STIP_RE.sub(' ', raw)).strip()
    if not rem:                       # pure stipulation ("If X wins ..."): no belt at stake
        return []
    for p in _TITLE_FILTER_PATTERNS:
        if p.search(rem):
            return []
    # Split first, decide contendership on the raw spellings (they are what appear
    # verbatim in the match type), and only then normalize the survivors.
    parts: list[str] = []
    for chunk in rem.split(' / '):
        # Unification matches join two belts with "vs.": both are at stake.
        parts.extend(re.split(r'\s+vs\.?\s+', chunk))
    if match is not None:
        parts = _drop_contendership_parts(parts, match)
    out: list[str] = []
    for part in parts:
        s = _normalize_title_part(part)
        if s:
            out.append(s)
    return out


# The World / Heavyweight singles family and the main WWE/F Championship under
# its bare renames. These are NOT prefix-collapsed (see _title_lineage_key): the
# big-gold World Heavyweight (2002-2013), the white strap revived in 2023 and the
# main title's many names sit in DISJOINT eras, so dropping the promotion prefix
# would fuse them into one chain spanning the gaps between them.
_WORLD_SINGLES_EXACT = {'wwe', 'wwf', 'undisputed wwe', 'wwe world', 'wwf world'}


def _is_world_singles(n: str) -> bool:
    """True for a normalized title in the world/heavyweight singles swamp."""
    if 'tag' in n or 'women' in n or 'divas' in n:
        return False
    if 'light heavyweight' in n or 'junior' in n or 'cruiserweight' in n:
        return False
    if ('world' in n and 'heavyweight' in n) or ('heavyweight' in n and ('wwe' in n or 'wwf' in n)):
        return True
    return n in _WORLD_SINGLES_EXACT


def _title_lineage_key(title: str) -> str:
    """Collapse the promotion-prefix spellings of one belt to a single lineage.

    The corpus tags a belt WWF, WWE and bare across its life ("WWF
    Intercontinental Title", "WWE Intercontinental Title", "Intercontinental
    Title"). build_title_reigns groups by this key so all three walk as ONE reign
    chain instead of three overlapping ones, each dangling its own open reign.
    Same idea as lineage_key in cagematch-pipeline/fill_titles.py.

    The world/heavyweight singles family is deliberately left as identity (see
    _is_world_singles): untangling WWE's own renames there is a separate problem,
    and a naive prefix strip would fabricate reigns across the eras' gaps.
    """
    n = re.sub(r'[^a-z0-9 ]', ' ', title.lower())
    n = re.sub(r'\b(championship|title|the|of)\b', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    if _is_world_singles(n):
        return 'world::' + n
    return 'belt::' + re.sub(r'\s+', ' ',
                             re.sub(r'\b(wwf|wwe|undisputed)\b', ' ', n)).strip()


def _same_champions(a: list[str], b: list[str]) -> bool:
    return set(a) == set(b)


def _pick_singles_champion(participants: list, appearances: Counter, incumbents) -> list:
    """Collapse a singles belt's winning team to its one real champion.

    A singles title is held by exactly one wrestler, but a title match's winning
    team is sometimes recorded with several participants: a valet or stablemates
    folded in (Gunther with Imperium), a handicap match (Sami Zayn with the Artist
    Collective), or a multi-belt match where each winner takes a DIFFERENT belt
    (Beth Phoenix + Santino Marella winning the Women's and IC titles in one
    intergender tag). The champion is the participant who actually wrestles for
    THIS belt, i.e. the one with the most appearances in the lineage's title
    matches; a valet or the other belt's winner has almost none. Ties prefer the
    incumbent (so a defense is not misread as a new champion), then break by name
    for determinism.
    """
    parts = [p for p in participants if p]
    if len(parts) <= 1:
        return list(parts)
    inc = incumbents or ()
    return [min(parts, key=lambda p: (-appearances.get(p, 0), 0 if p in inc else 1, p))]


def build_title_reigns(events: dict) -> dict[str, list[dict]]:
    """Walk all title matches in chronological order and build per-title reign timelines.

    Reign shape:
        champion_names: list[str] (singles = 1 entry, tag = 2+)
        start: ISO date. For pre_corpus=True reigns this is the first observed
               event date (a practical floor, not a true start; the actual reign
               began before our corpus and we don't know when).
        end: ISO date or None (None = current as of corpus end).
        start_event_id: int
        end_event_id: int | None
        pre_corpus: bool

    Limitations:
      * No vacancy detection: belts are assumed continuously held until the next
        title change. Real-world vacancies (forfeits, retirements, suspensions)
        are not modeled.
      * Same-day title changes resolve to end-of-day state in champions_by_date.
      * Champion-vs-champion unification: when a composite match has both teams
        marked was_champion_entering=True, attribution falls out of "winner takes
        all listed belts" via per-component reign-chain comparison.
    """
    timelines: dict[str, list[dict]] = defaultdict(list)
    # Per lineage, tally each raw spelling (count, latest air_date) so the merged
    # chain can be named after its most current spelling: WWF/WWE/bare
    # Intercontinental collapse to one chain displayed as "WWE Intercontinental
    # Title", the name still in use.
    spelling_stats: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0, '']))
    # Per lineage, how often each wrestler appears in its title matches. A singles
    # belt has one holder, so when a title match's winning team lists several
    # people this disambiguates the real champion (the one who wrestles for the
    # belt) from a valet, handicap partner, or the winner of the OTHER belt in a
    # multi-belt match. See _pick_singles_champion.
    lineage_appearances: dict[str, Counter] = defaultdict(Counter)
    for eid_str, ev in events.items():
        air_date = ev.get('air_date')
        if not air_date:
            continue
        eid = int(eid_str)
        if eid in CLIP_SHOWS:      # a replayed title change is not a title change
            continue
        for match in ev.get('matches', []):
            for title in _get_component_titles(match.get('title_at_stake'), match):
                lk = _title_lineage_key(title)
                timelines[lk].append({
                    'air_date': air_date,
                    'event_id': eid,
                    'match_order': match.get('match_order') or 0,
                    'teams': match.get('teams', []),
                    # carried for the stand-in check when reconciling (c) markers
                    'raw_description': match.get('raw_description') or '',
                })
                st = spelling_stats[lk][title]
                st[0] += 1
                if air_date > st[1]:
                    st[1] = air_date
                for t in match.get('teams', []):
                    for p in t.get('participants', []):
                        if p:
                            lineage_appearances[lk][p] += 1

    # Canonical display name per lineage: the spelling that carries the most
    # matches, tie-broken by most recent match then name. The dominant name is
    # stable and unsurprising (an active belt still reads under its modern name,
    # since that spelling owns the most matches) and avoids latching onto a
    # short-lived late rename the way "most recent spelling" would.
    canon_name: dict[str, str] = {
        lk: max(spellings.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0]))[0]
        for lk, spellings in spelling_stats.items()
    }

    for lk in timelines:
        timelines[lk].sort(key=lambda m: (m['air_date'], m['event_id'], m['match_order']))

    # How far the corpus reaches, to judge which belts have gone quiet against.
    # Taken from the events rather than today's clock so a rebuild is
    # reproducible and an older corpus stays self-consistent.
    corpus_end = max((ev.get('air_date') or '' for ev in events.values()), default='')

    reigns_by_title: dict[str, list[dict]] = {}
    for lk, matches in timelines.items():
        reigns: list[dict] = []
        current: dict | None = None
        first = True
        # A tag title legitimately has 2+ holders; a singles title has exactly
        # one, so a multi-person winning team there needs disambiguating.
        is_singles = 'Tag' not in canon_name[lk]
        appearances = lineage_appearances[lk]
        for m in matches:
            teams = m['teams']
            champ_team = next((t for t in teams if t.get('was_champion_entering')), None)
            winner = next((t for t in teams if t.get('was_winner')), None)

            if first:
                if champ_team and champ_team.get('participants'):
                    seed = list(champ_team['participants'])
                    if is_singles:
                        seed = _pick_singles_champion(seed, appearances, None)
                    current = {
                        'champion_names': seed,
                        'start': m['air_date'],
                        'end': None,
                        'start_event_id': m['event_id'],
                        'end_event_id': None,
                        'pre_corpus': True,
                    }
                first = False

            # The (c) marker is the source stating who walked in holding the
            # belt. When it names someone other than the reign we are tracking,
            # a title change happened that the corpus never recorded, and the
            # walk has to take the source's word for it: it cannot see a card it
            # does not have.
            #
            # Without this the belt appears never to have left, and the two
            # halves of the incumbent's reign fuse across the gap. The Miz beat
            # Wade Barrett for the Intercontinental Title at WrestleMania 29 and
            # lost it back the next night, but only the second match is in the
            # corpus, so the walk read "Barrett defeats The Miz (c)" as Barrett
            # retaining and gave him one unbroken reign from December to June,
            # swallowing Miz's reign whole. Same shape wherever a belt changed
            # hands on a card we do not carry, or was vacated and awarded off
            # television (Naomi's SmackDown Women's Title, Kevin Owens' United
            # States Title).
            #
            # The inserted reign is pre_corpus: its end is observed here, but its
            # start is not knowable, so `start` is a floor and not a real date.
            # A multi-man title match is stored as two teams, so the (c) side can
            # carry the champion AND a challenger: Payback 2013's triple threat
            # reads "Curtis Axel defeats The Miz and Wade Barrett (c)", with Miz
            # and Barrett sharing a team. The marker is therefore only evidence
            # of a change we missed when it names NOBODY we think holds the belt.
            # Asking _pick_singles_champion to choose here instead would let it
            # pick Miz off appearance counts and invent a reign for him.
            # Two more ways the marker lies, both rare and both detectable:
            #
            #   champion vs champion. No Mercy 2002 reads "Triple H (c)
            #   [Heavyweight] defeats Kane (c) [Intercontinental]": both sides
            #   are (c), for different belts, and champ_team just takes the first
            #   it finds, so on the Intercontinental chain it hands back the
            #   HEAVYWEIGHT champion. 22 matches in the corpus. Ambiguous, so
            #   the marker is no evidence here at all.
            #
            #   a champion who sent a stand-in. "The Undertaker defeats Orlando
            #   Jordan [Replacement for John Bradshaw Layfield] (w/ JBL) (c)":
            #   the belt is JBL's and the (c) landed on the replacement. 4
            #   matches.
            multi_champ = sum(1 for t in teams if t.get('was_champion_entering')) > 1
            stand_in = '[replacement for' in (m.get('raw_description') or '').lower()
            if current is not None and champ_team is not None and not multi_champ and not stand_in:
                entering = [p for p in (champ_team.get('participants') or []) if p]
                if entering and not (set(current['champion_names']) & set(entering)):
                    named = _pick_singles_champion(entering, appearances, None) \
                        if is_singles else entering
                    current['end'] = m['air_date']
                    current['end_event_id'] = m['event_id']
                    reigns.append(current)
                    current = {
                        'champion_names': named,
                        'start': m['air_date'],
                        'end': None,
                        'start_event_id': m['event_id'],
                        'end_event_id': None,
                        'pre_corpus': True,
                    }

            if winner is None or not winner.get('participants'):
                continue
            # Champion retains on a challenger's DQ/countout win: no reign change.
            if (winner.get('match_outcome') in ('dq-win', 'countout-win')
                    and not winner.get('was_champion_entering')):
                continue
            # Mid-chain match with no champion in it: a mislabeled contender
            # match (scrapers sometimes store the belt a match is qualifying
            # FOR as title_at_stake). The belt cannot change hands in a match
            # its holder is not part of. current is None still passes so the
            # first observed winner of a never-seen belt starts its chain.
            if current is not None and champ_team is None:
                continue

            new_champs = list(winner['participants'])
            if is_singles:
                new_champs = _pick_singles_champion(
                    new_champs, appearances,
                    current['champion_names'] if current else None)
            if current is None or not _same_champions(current['champion_names'], new_champs):
                if current is not None:
                    current['end'] = m['air_date']
                    current['end_event_id'] = m['event_id']
                    reigns.append(current)
                current = {
                    'champion_names': new_champs,
                    'start': m['air_date'],
                    'end': None,
                    'start_event_id': m['event_id'],
                    'end_event_id': None,
                    'pre_corpus': False,
                }

        if current is not None:
            reigns.append(current)
        if reigns:
            _close_reign_at_retirement(reigns, matches, corpus_end)
        reigns_by_title[canon_name[lk]] = reigns

    for title, reigns in reigns_by_title.items():
        for i in range(len(reigns) - 1):
            r, n = reigns[i], reigns[i + 1]
            if r['end'] is None:
                raise AssertionError(
                    f"title_reigns: non-final reign has end=None for {title!r} at index {i}: {r}"
                )
            if r['start'] > n['start']:
                raise AssertionError(
                    f"title_reigns: reigns out of order for {title!r} at indices {i},{i+1}: {r} then {n}"
                )
            if r['end'] != n['start']:
                raise AssertionError(
                    f"title_reigns: reign chain broken for {title!r} at indices {i},{i+1}: "
                    f"end={r['end']} != next.start={n['start']}"
                )

    return reigns_by_title


def build_wrestler_reigns_by_date(title_reigns: dict) -> dict[str, list[dict]]:
    """Per-wrestler interval list of title reigns.

    Shape: { name: [{title, start, end, pre_corpus}, ...] } sorted by start asc.
    end is ISO date or None (None = current as of corpus end). Frontend uses a
    small helper to filter intervals by date.

    Asserts that no wrestler has two overlapping intervals on the SAME title.
    Different titles may overlap (a wrestler can hold a singles + tag belt
    concurrently); the same title cannot be held twice at once.
    """
    out: dict[str, list[dict]] = {}
    for title, reigns in title_reigns.items():
        for r in reigns:
            entry = {
                'title': title,
                'start': r['start'],
                'end': r['end'],
                'pre_corpus': r['pre_corpus'],
            }
            for name in r['champion_names']:
                out.setdefault(name, []).append(entry)

    for name in out:
        out[name].sort(key=lambda iv: (iv['start'], iv['title']))

    for name, intervals in out.items():
        by_title: dict[str, list[dict]] = defaultdict(list)
        for iv in intervals:
            by_title[iv['title']].append(iv)
        for title, ivs in by_title.items():
            for i in range(len(ivs) - 1):
                a, b = ivs[i], ivs[i + 1]
                if a['end'] is None:
                    raise AssertionError(
                        f"wrestler_reigns_by_date: open-ended reign for {name!r} on "
                        f"{title!r} precedes another: {a} then {b}"
                    )
                if a['end'] > b['start']:
                    raise AssertionError(
                        f"wrestler_reigns_by_date: overlapping reigns for {name!r} on "
                        f"{title!r}: {a} and {b}"
                    )

    return out


def build_bundle(db_path: Path = DB_PATH) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        events_rows = conn.execute(
            "SELECT id, air_date, tape_date, date_derivation, show_type, "
            "episode_number, title, ppv_name, venue, city, state_province, "
            "country, attendance, tv_network, tv_rating, broadcast_type, "
            "commentary, promotion, promotion_raw, cagematch_nr, cagematch_url, "
            "fandom_slug, fandom_url, primary_source, verification_status "
            "FROM events ORDER BY air_date ASC, show_type ASC"
        ).fetchall()
        matches_rows = conn.execute(
            "SELECT id, event_id, match_order, match_type, stipulation, "
            "title_at_stake, duration_seconds, result_method, "
            "match_guide_rating, raw_description "
            "FROM matches ORDER BY event_id ASC, match_order ASC"
        ).fetchall()
        teams_rows = conn.execute(
            "SELECT id, match_id, team_number, team_name, accompaniment, "
            "was_winner, match_outcome, was_champion_entering "
            "FROM match_teams ORDER BY match_id ASC, team_number ASC"
        ).fetchall()
        parts_rows = conn.execute(
            "SELECT mp.team_id, mp.wrestler_id, mp.wrestler_name_used, "
            "w.canonical_name "
            "FROM match_participants mp "
            "LEFT JOIN wrestlers w ON mp.wrestler_id = w.id "
            "ORDER BY mp.team_id ASC, mp.id ASC"
        ).fetchall()
    finally:
        conn.close()

    # Hybrid Option B: prefer the migrated canonical_name from wrestlers when
    # joinable; fall back to canonicalizing the raw wrestler_name_used at
    # export time when wrestler_id is NULL (Type-3 dropped or future garbage
    # the migration didn't catch). Names that collapse to empty are skipped.
    parts_by_team: dict[int, list[str]] = {}
    for r in parts_rows:
        if r["wrestler_id"] is not None and r["canonical_name"]:
            name = r["canonical_name"]
        else:
            name = _canonicalize_name(r["wrestler_name_used"])
        if not name:
            continue
        parts_by_team.setdefault(r["team_id"], []).append(name)

    teams_by_match: dict[int, list[dict]] = {}
    for r in teams_rows:
        teams_by_match.setdefault(r["match_id"], []).append({
            "team_number": r["team_number"],
            "team_name": r["team_name"],
            "accompaniment": r["accompaniment"],
            "was_winner": _to_bool(r["was_winner"]),
            "match_outcome": r["match_outcome"],
            "was_champion_entering": bool(r["was_champion_entering"]),
            "participants": parts_by_team.get(r["id"], []),
        })

    matches_by_event: dict[int, list[dict]] = {}
    for r in matches_rows:
        matches_by_event.setdefault(r["event_id"], []).append({
            "id": r["id"],
            "match_order": r["match_order"],
            "match_type": r["match_type"],
            "stipulation": r["stipulation"],
            "title_at_stake": r["title_at_stake"],
            "duration_seconds": r["duration_seconds"],
            "result_method": r["result_method"],
            "match_guide_rating": r["match_guide_rating"],
            "raw_description": r["raw_description"],
            "teams": teams_by_match.get(r["id"], []),
        })

    events: dict[str, dict] = {}
    events_by_date: dict[str, list[int]] = {}
    for r in events_rows:
        e = dict(r)
        eid = e["id"]
        ms = matches_by_event.get(eid, [])
        e["match_count"] = len(ms)
        e["matches"] = ms
        events[str(eid)] = e
        events_by_date.setdefault(e["air_date"], []).append(eid)

    years = sorted({e["air_date"][:4] for e in events.values()})
    year_range = [int(years[0]), int(years[-1])] if years else [0, 0]

    # Same alias handling as build_update: without it this path ships an
    # un-merged roster that disagrees with the live one.
    from src.roster_aliases import build_canon_map, load_roster_snapshot
    name_counts = Counter(
        p for e in events.values() for m in e["matches"]
        for t in m["teams"] for p in t.get("participants", []) if p)
    canon = build_canon_map(name_counts, roster_pairs=load_roster_snapshot() or [])

    title_reigns = build_title_reigns(events)
    wrestlers, wrestlers_by_name = build_wrestlers_index(
        events, canon=lambda n: canon.get(n, n), title_reigns=title_reigns)
    wrestler_reigns_by_date = build_wrestler_reigns_by_date(title_reigns)

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
            "match_count": len(matches_rows),
            "year_range": year_range,
        },
        "events_by_date": events_by_date,
        "events": events,
        "wrestlers": wrestlers,
        "wrestlers_by_name": wrestlers_by_name,
        "title_reigns": title_reigns,
        "wrestler_reigns_by_date": wrestler_reigns_by_date,
    }


def inject(bundle: dict, template_html: str) -> str:
    # Escape </script> inside any string so the JSON payload can't end the tag.
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    tag = f'<script id="wrestling-data" type="application/json">{payload}</script>\n'
    idx = template_html.find("<script>")
    if idx < 0:
        raise RuntimeError("no <script> tag found in frontend/index.html")
    return template_html[:idx] + tag + template_html[idx:]


# --------------------------------------------------------------------------
# Sharded build: the heavy 87% of the bundle is the per-match teams/participants
# detail. We split that out of the inline core into 3-year era files fetched on
# demand, so the page loads a ~6MB core (event metadata + indexes + a compact
# search index) instead of ~16MB, and never instantiates all match objects at
# once. The single-file dist build keeps everything inline and is unaffected.
SHARD_DIR = "shards"
ERA_SPAN = 3


def era_start(year) -> int:
    """Start year of the 3-year era bucket holding `year`, aligned to multiples
    of ERA_SPAN (2024 -> 2022, 2026 -> 2025). Stable for any year incl. the
    pre-2001 backfill, and the frontend computes the identical bucket."""
    return (int(year) // ERA_SPAN) * ERA_SPAN


def build_search_index(events: dict) -> list:
    """Compact per-match search records so global match search works in sharded
    mode without the era files loaded: [event_id, match_id, matchup, sub].
    The frontend joins date/show/show-name from the (always-present) compact
    event and rebuilds the lowercase haystack client-side."""
    out = []
    for ev in events.values():
        for m in ev.get("matches", []):
            names = []
            for t in m.get("teams", []):
                ps = t.get("participants") or ([t["team_name"]] if t.get("team_name") else [])
                if ps:
                    names.append(" & ".join(ps))
            matchup = " vs ".join(names)
            sub = " · ".join(x for x in (m.get("match_type"), m.get("stipulation"),
                                              m.get("title_at_stake")) if x)
            out.append([ev["id"], m["id"], matchup, sub])
    return out


def split_core_and_shards(bundle: dict):
    """Return (core, shards_by_era). core is the bundle with each event's heavy
    `matches` array removed, plus a compact `search_matches` index and a
    `meta.shards` manifest. shards_by_era maps an era-start year to
    {event_id(str): [matches]} for every dated event in that era."""
    events = bundle["events"]
    shards = defaultdict(dict)
    compact = {}
    for eid, ev in events.items():
        compact[eid] = {k: v for k, v in ev.items() if k != "matches"}
        year = (ev.get("air_date") or "")[:4]
        bucket = era_start(year) if year.isdigit() else 0
        shards[bucket][str(ev["id"])] = ev.get("matches", [])
    core = dict(bundle)
    core["events"] = compact
    core["search_matches"] = build_search_index(events)
    core["meta"] = dict(bundle["meta"], shards=sorted(shards))
    return core, shards


def write_sharded(bundle: dict, root: Path, template_html: str):
    """Write the sharded GitHub Pages build: index.html with the inline core and
    shards/matches-<era>.json files. Returns (core, shards) for reporting."""
    core, shards = split_core_and_shards(bundle)
    sdir = root / SHARD_DIR
    sdir.mkdir(parents=True, exist_ok=True)
    # Write the new artifacts first (atomically), then clear stale eras, so a
    # crash at any point leaves either the old set or the new set servable,
    # never an empty shards/ directory or a truncated index.html.
    fresh = {f"matches-{era}.json" for era in shards}
    for era, matches_map in shards.items():
        atomic_write_text(
            sdir / f"matches-{era}.json",
            json.dumps(matches_map, ensure_ascii=False, separators=(",", ":")))
    atomic_write_text(root / "index.html", inject(core, template_html))
    for stale in sdir.glob("matches-*.json"):   # clear old eras so none linger
        if stale.name not in fresh:
            stale.unlink()
    return core, shards


def main() -> None:
    bundle = build_bundle()
    template_html = TEMPLATE.read_text(encoding="utf-8")
    out_html = inject(bundle, template_html)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUT, out_html)
    size = OUT.stat().st_size
    meta = bundle["meta"]
    print(f"Wrote {OUT} ({size:,} bytes, {size/1024/1024:.2f} MB)")
    print(
        f"  events={meta['event_count']}  matches={meta['match_count']}"
        f"  wrestlers={len(bundle['wrestlers'])}"
        f"  titles={len(bundle['title_reigns'])}"
        f"  generated_at={meta['generated_at']}"
    )


if __name__ == "__main__":
    main()
