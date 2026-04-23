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
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "wrestling.db"
TEMPLATE = ROOT / "frontend" / "index.html"
OUT = ROOT / "dist" / "wrestling-dashboard.html"


def _to_bool(v):
    return None if v is None else bool(v)


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

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
            "match_count": len(matches_rows),
            "year_range": year_range,
        },
        "events_by_date": events_by_date,
        "events": events,
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
    print(f"  events={meta['event_count']}  matches={meta['match_count']}  generated_at={meta['generated_at']}")


if __name__ == "__main__":
    main()
