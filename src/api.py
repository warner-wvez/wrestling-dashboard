"""
Read-only FastAPI over the local SQLite store.

Run:
    .venv/bin/python -m uvicorn src.api:app --reload --host 127.0.0.1 --port 8000

Endpoints:
    GET /api/health
    GET /api/events?year=<int>&month=<int>
    GET /api/events/{event_id}
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "wrestling.db"

app = FastAPI(title="Wrestling Dashboard API", version="1.0.0")

# Permissive CORS for local dev: the frontend is file:// (origin "null") when
# opened directly, or http://localhost:<port> via any static server.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_conn() -> sqlite3.Connection:
    # Open read-only so a curious API call can't corrupt the DB.
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _to_bool(v):
    if v is None:
        return None
    return bool(v)


# --- response models ---------------------------------------------------------

class EventSummary(BaseModel):
    id: int
    air_date: str
    show_type: str
    title: Optional[str] = None
    venue: Optional[str] = None
    city: Optional[str] = None
    episode_number: Optional[int] = None
    ppv_name: Optional[str] = None
    match_count: int


class MatchTeam(BaseModel):
    team_number: int
    team_name: Optional[str] = None
    accompaniment: Optional[str] = None
    was_champion_entering: bool
    was_winner: Optional[bool] = None
    match_outcome: Optional[str] = None
    participants: list[str]


class Match(BaseModel):
    id: int
    match_order: int
    match_type: Optional[str] = None
    stipulation: Optional[str] = None
    title_at_stake: Optional[str] = None
    duration_seconds: Optional[int] = None
    result_method: Optional[str] = None
    match_guide_rating: Optional[float] = None
    raw_description: Optional[str] = None
    teams: list[MatchTeam]


class EventDetail(EventSummary):
    tape_date: Optional[str] = None
    date_derivation: Optional[str] = None
    primary_source: str
    promotion: Optional[str] = None
    promotion_raw: Optional[str] = None
    attendance: Optional[int] = None
    tv_network: Optional[str] = None
    tv_rating: Optional[float] = None
    commentary: Optional[str] = None
    verification_status: str
    matches: list[Match]


# --- endpoints --------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    conn = get_conn()
    try:
        ec = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        mc = conn.execute("SELECT COUNT(*) AS n FROM matches").fetchone()["n"]
        return {"status": "ok", "events": ec, "matches": mc}
    finally:
        conn.close()


@app.get("/api/events", response_model=list[EventSummary])
def list_events(
    year: int = Query(..., ge=2001, le=2004),
    month: int = Query(..., ge=1, le=12),
) -> list[EventSummary]:
    start = date(year, month, 1).isoformat()
    end = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)).isoformat()

    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT e.id, e.air_date, e.show_type, e.title, e.venue, e.city,
                   e.episode_number, e.ppv_name,
                   (SELECT COUNT(*) FROM matches m WHERE m.event_id = e.id) AS match_count
            FROM events e
            WHERE e.air_date >= ? AND e.air_date < ?
            ORDER BY e.air_date ASC, e.show_type ASC
            """,
            (start, end),
        ).fetchall()
        return [EventSummary(**dict(r)) for r in rows]
    finally:
        conn.close()


@app.get("/api/events/{event_id}", response_model=EventDetail)
def get_event(event_id: int) -> EventDetail:
    conn = get_conn()
    try:
        e = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if e is None:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        # Single JOIN over matches x teams x participants. Order the result so
        # we can fold it into nested dicts in one linear pass.
        join_rows = conn.execute(
            """
            SELECT
                m.id                       AS match_id,
                m.match_order              AS match_order,
                m.match_type               AS match_type,
                m.stipulation              AS stipulation,
                m.title_at_stake           AS title_at_stake,
                m.duration_seconds         AS duration_seconds,
                m.result_method            AS result_method,
                m.match_guide_rating       AS match_guide_rating,
                m.raw_description          AS raw_description,
                mt.id                      AS team_id,
                mt.team_number             AS team_number,
                mt.team_name               AS team_name,
                mt.accompaniment           AS accompaniment,
                mt.was_winner              AS was_winner,
                mt.match_outcome           AS match_outcome,
                mt.was_champion_entering   AS was_champion_entering,
                mp.wrestler_name_used      AS wrestler_name_used
            FROM matches m
            LEFT JOIN match_teams mt          ON mt.match_id = m.id
            LEFT JOIN match_participants mp   ON mp.team_id  = mt.id
            WHERE m.event_id = ?
            ORDER BY m.match_order ASC, mt.team_number ASC, mp.id ASC
            """,
            (event_id,),
        ).fetchall()

        matches: list[dict] = []
        match_by_id: dict[int, dict] = {}
        team_by_id: dict[int, dict] = {}

        for r in join_rows:
            mid = r["match_id"]
            if mid not in match_by_id:
                md = {
                    "id": mid,
                    "match_order": r["match_order"],
                    "match_type": r["match_type"],
                    "stipulation": r["stipulation"],
                    "title_at_stake": r["title_at_stake"],
                    "duration_seconds": r["duration_seconds"],
                    "result_method": r["result_method"],
                    "match_guide_rating": r["match_guide_rating"],
                    "raw_description": r["raw_description"],
                    "teams": [],
                }
                match_by_id[mid] = md
                matches.append(md)

            tid = r["team_id"]
            if tid is None:
                continue
            if tid not in team_by_id:
                td = {
                    "team_number": r["team_number"],
                    "team_name": r["team_name"],
                    "accompaniment": r["accompaniment"],
                    "was_champion_entering": _to_bool(r["was_champion_entering"]) or False,
                    "was_winner": _to_bool(r["was_winner"]),
                    "match_outcome": r["match_outcome"],
                    "participants": [],
                }
                team_by_id[tid] = td
                match_by_id[mid]["teams"].append(td)

            if r["wrestler_name_used"]:
                team_by_id[tid]["participants"].append(r["wrestler_name_used"])

        payload = dict(e)
        payload["match_count"] = len(matches)
        payload["matches"] = matches
        return EventDetail(**payload)
    finally:
        conn.close()
