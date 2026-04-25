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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


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


def build_wrestlers_index(events: dict) -> tuple[dict, dict]:
    """Pre-compute wrestler profiles from the assembled events dict.

    Returns (wrestlers, wrestlers_by_name) where wrestlers is keyed by slug
    and wrestlers_by_name maps canonical display name -> slug.

    Invariant enforced by assertion:
        total_matches == wins + losses + draws + no_contests
    Ambiguous outcomes (was_winner=None, not a draw or no-contest) are
    counted as no_contests so the invariant holds exactly.
    """
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
        show_type = ev.get("show_type", "")
        is_ppv = show_type == "PPV"
        event_name = ev.get("ppv_name") or ev.get("title") or ""

        matches = ev.get("matches", [])
        orders = [m["match_order"] for m in matches if m.get("match_order") is not None]
        max_order = max(orders) if orders else None

        for match in matches:
            teams = match.get("teams", [])
            duration = match.get("duration_seconds")
            title_at_stake = match.get("title_at_stake")
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
                parts = [p for p in team.get("participants", []) if p]
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

                    if title_at_stake and was_winner is True and not was_champ:
                        w_title_wins[name][title_at_stake] += 1

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
                a_parts = [p for p in teams[0].get("participants", []) if p]
                b_parts = [p for p in teams[1].get("participants", []) if p]
                for a in a_parts:
                    for b in b_parts:
                        w_rivals[a][b] += 1
                        w_rivals[b][a] += 1

            # Tag partners: pairs within any team that has 2+ participants
            for team in teams:
                team_parts = [p for p in team.get("participants", []) if p]
                if len(team_parts) < 2:
                    continue
                for i, p1 in enumerate(team_parts):
                    for p2 in team_parts[i + 1:]:
                        w_partners[p1][p2] += 1
                        w_partners[p2][p1] += 1

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

    return wrestlers, wrestlers_by_name


# ============================================================================
# Title reign tracking (Phase 1b)
# ============================================================================

_TITLE_FILTER_PATTERNS = (
    re.compile(r'Contendership', re.I),
    re.compile(r'Tournament', re.I),
    re.compile(r'Battle Royal', re.I),
)

_TITLE_SUFFIXES_TO_STRIP = (
    'Tables, Ladders and Chairs match',
    'No Disqualification Match',
    'No DQ Match',
    'Elimination Match',
    'Matches',
    'Match',
)

TITLE_ALIASES = {
    "WWF Championship Title": "WWF World Heavyweight Title",
    "ECW Heavyweight Title":  "ECW World Heavyweight Title",
}


def _normalize_title_part(part: str) -> str | None:
    s = re.sub(r'\s+', ' ', part).strip()
    for suf in _TITLE_SUFFIXES_TO_STRIP:
        if s.endswith(' ' + suf):
            s = s[: -(len(suf) + 1)].rstrip()
            break
    s = re.sub(r'\bChampionship$', 'Title', s).strip()
    s = TITLE_ALIASES.get(s, s)
    return s or None


def _get_component_titles(raw: str | None) -> list[str]:
    if not raw:
        return []
    for p in _TITLE_FILTER_PATTERNS:
        if p.search(raw):
            return []
    out: list[str] = []
    for part in raw.split(' / '):
        s = _normalize_title_part(part)
        if s:
            out.append(s)
    return out


def _same_champions(a: list[str], b: list[str]) -> bool:
    return set(a) == set(b)


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
    for eid_str, ev in events.items():
        air_date = ev.get('air_date')
        if not air_date:
            continue
        eid = int(eid_str)
        for match in ev.get('matches', []):
            for title in _get_component_titles(match.get('title_at_stake')):
                timelines[title].append({
                    'air_date': air_date,
                    'event_id': eid,
                    'match_order': match.get('match_order') or 0,
                    'teams': match.get('teams', []),
                })

    for title in timelines:
        timelines[title].sort(key=lambda m: (m['air_date'], m['event_id'], m['match_order']))

    reigns_by_title: dict[str, list[dict]] = {}
    for title, matches in timelines.items():
        reigns: list[dict] = []
        current: dict | None = None
        first = True
        for m in matches:
            teams = m['teams']
            champ_team = next((t for t in teams if t.get('was_champion_entering')), None)
            winner = next((t for t in teams if t.get('was_winner')), None)

            if first:
                if champ_team and champ_team.get('participants'):
                    current = {
                        'champion_names': list(champ_team['participants']),
                        'start': m['air_date'],
                        'end': None,
                        'start_event_id': m['event_id'],
                        'end_event_id': None,
                        'pre_corpus': True,
                    }
                first = False

            if winner is None or not winner.get('participants'):
                continue

            new_champs = list(winner['participants'])
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
        reigns_by_title[title] = reigns

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
            "SELECT team_id, wrestler_name_used FROM match_participants ORDER BY team_id ASC, id ASC"
        ).fetchall()
    finally:
        conn.close()

    parts_by_team: dict[int, list[str]] = {}
    for r in parts_rows:
        parts_by_team.setdefault(r["team_id"], []).append(r["wrestler_name_used"])

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

    wrestlers, wrestlers_by_name = build_wrestlers_index(events)

    title_reigns = build_title_reigns(events)
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


def main() -> None:
    bundle = build_bundle()
    template_html = TEMPLATE.read_text(encoding="utf-8")
    out_html = inject(bundle, template_html)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out_html, encoding="utf-8")
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
