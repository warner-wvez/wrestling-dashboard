"""
SQLite schema and helpers for the wrestling dashboard.

Schema lineage:
  * Base: the spec's CLAUDE.md tables (events, matches, wrestlers,
    match_participants, segments, sources, verification_flags, video_sources).
  * Evolutions applied this session:
      - air_date / tape_date / date_derivation on events (replaces event_date).
      - primary_source enum cagematch|fandom.
      - verification_status default 'unverified', enum verified|flagged|unverified.
      - UNIQUE (air_date, show_type) as the cross-source dedup key.
      - UNIQUE fandom_slug and UNIQUE cagematch_nr for source-import detection.
      - intro_prose + infobox_raw on events (kept for the LLM verification pass).
      - promotion_raw alongside promotion (Fandom says 'WWE' regardless of era).
      - matches.parse_confidence.
      - match_teams split out of match_participants (team-level facts live
        there; match_participants is now one row per wrestler).
      - match_teams.was_winner is nullable INTEGER (0/1/NULL). draw and
        no-contest leave both teams NULL.
      - match_teams.match_outcome enum
        (win|loss|draw|no-contest|dq-win|dq-loss|countout-win|countout-loss).
      - was_champion_entering / was_champion_leaving as INTEGER 0/1 (SQLite has
        no native bool).

Usage:
    from src.db import get_connection, init_schema, upsert_event, insert_match
    init_schema("data/wrestling.db")
    with get_connection("data/wrestling.db") as conn:
        event_id = upsert_event(conn, event_dict)
        for m in event_dict.get("matches") or []:
            insert_match(conn, event_id, m)
        conn.commit()
"""

import json
import sqlite3
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  air_date           TEXT    NOT NULL,
  tape_date          TEXT,
  date_derivation    TEXT CHECK (date_derivation IN (
                       'live-broadcast', 'fandom-provided', 'tape-plus-2-estimate',
                       'air-night-estimate')),
  show_type          TEXT    NOT NULL CHECK (show_type IN ('Raw', 'SmackDown', 'PPV')),
  episode_number     INTEGER,
  title              TEXT,
  ppv_name           TEXT,
  venue              TEXT,
  city               TEXT,
  state_province     TEXT,
  country            TEXT,
  attendance         INTEGER,
  tv_network         TEXT,
  tv_rating          REAL,
  broadcast_type     TEXT,
  commentary         TEXT,
  promotion          TEXT,
  promotion_raw      TEXT,
  cagematch_nr       INTEGER UNIQUE,
  cagematch_url      TEXT,
  fandom_slug        TEXT    UNIQUE,
  fandom_url         TEXT,
  primary_source     TEXT    NOT NULL CHECK (primary_source IN ('cagematch', 'fandom')),
  intro_prose        TEXT,
  infobox_raw        TEXT,
  verification_status TEXT   NOT NULL DEFAULT 'unverified'
                       CHECK (verification_status IN ('verified', 'flagged', 'unverified')),
  created_at         TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (air_date, show_type)
);

CREATE INDEX IF NOT EXISTS idx_events_air_date         ON events(air_date);
CREATE INDEX IF NOT EXISTS idx_events_show_type        ON events(show_type);
CREATE INDEX IF NOT EXISTS idx_events_primary_source   ON events(primary_source);
CREATE INDEX IF NOT EXISTS idx_events_verification     ON events(verification_status);

CREATE TABLE IF NOT EXISTS matches (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id           INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  match_order        INTEGER NOT NULL,
  match_type         TEXT,
  stipulation        TEXT,
  title_at_stake     TEXT,
  duration_seconds   INTEGER,
  match_guide_rating REAL,
  result_method      TEXT,
  parse_confidence   TEXT CHECK (parse_confidence IN ('high', 'low')),
  raw_description    TEXT,
  created_at         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (event_id, match_order)
);

CREATE INDEX IF NOT EXISTS idx_matches_event           ON matches(event_id);
CREATE INDEX IF NOT EXISTS idx_matches_parse_conf      ON matches(parse_confidence);

CREATE TABLE IF NOT EXISTS match_teams (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id               INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  team_number            INTEGER NOT NULL,
  team_name              TEXT,
  accompaniment          TEXT,
  was_winner             INTEGER,   -- 0 / 1 / NULL (null = draw or no-contest)
  match_outcome          TEXT CHECK (match_outcome IN (
                           'win', 'loss', 'draw', 'no-contest',
                           'dq-win', 'dq-loss',
                           'countout-win', 'countout-loss')),
  was_champion_entering  INTEGER NOT NULL DEFAULT 0 CHECK (was_champion_entering IN (0, 1)),
  was_champion_leaving   INTEGER NOT NULL DEFAULT 0 CHECK (was_champion_leaving  IN (0, 1)),
  UNIQUE (match_id, team_number)
);

CREATE INDEX IF NOT EXISTS idx_teams_match             ON match_teams(match_id);

CREATE TABLE IF NOT EXISTS wrestlers (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name TEXT    NOT NULL UNIQUE,
  ring_names     TEXT    DEFAULT '[]',   -- JSON array
  cagematch_id   INTEGER UNIQUE
);

CREATE TABLE IF NOT EXISTS match_participants (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id           INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  team_id            INTEGER REFERENCES match_teams(id) ON DELETE CASCADE,
  wrestler_id        INTEGER REFERENCES wrestlers(id),
  wrestler_name_used TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_participants_match      ON match_participants(match_id);
CREATE INDEX IF NOT EXISTS idx_participants_team       ON match_participants(team_id);
CREATE INDEX IF NOT EXISTS idx_participants_wrestler   ON match_participants(wrestler_id);

CREATE TABLE IF NOT EXISTS segments (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id       INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  segment_order  INTEGER,
  segment_type   TEXT,
  description    TEXT,
  participants   TEXT DEFAULT '[]'       -- JSON array
);

CREATE TABLE IF NOT EXISTS sources (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id      INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  source_name   TEXT    NOT NULL,
  source_url    TEXT    NOT NULL,
  verified_date TEXT,
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS verification_flags (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id          INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  field_name        TEXT    NOT NULL,
  cagematch_value   TEXT,
  wikipedia_value   TEXT,   -- renamed at your discretion, kept to match spec wording
  resolved          INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
  resolution_notes  TEXT,
  created_at        TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS video_sources (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id        INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  source_platform TEXT,
  video_url       TEXT,
  quality         TEXT,
  is_full_card    INTEGER CHECK (is_full_card IN (0, 1)),
  uploader        TEXT,
  notes           TEXT
);
"""


EVENT_COLUMNS = (
    "air_date", "tape_date", "date_derivation", "show_type", "episode_number",
    "title", "ppv_name", "venue", "city", "state_province", "country",
    "attendance", "tv_network", "tv_rating", "broadcast_type", "commentary",
    "promotion", "promotion_raw", "cagematch_nr", "cagematch_url",
    "fandom_slug", "fandom_url", "primary_source", "intro_prose",
    "infobox_raw", "verification_status",
)

MATCH_COLUMNS = (
    "match_order", "match_type", "stipulation", "title_at_stake",
    "duration_seconds", "match_guide_rating", "result_method",
    "parse_confidence", "raw_description",
)

TEAM_COLUMNS = (
    "team_number", "team_name", "accompaniment", "was_winner", "match_outcome",
    "was_champion_entering", "was_champion_leaving",
)


def get_connection(db_path):
    """Open a SQLite connection with foreign keys enforced and row-dict access."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(db_path):
    """Create all tables and indexes. Idempotent via IF NOT EXISTS."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _coerce_int_bool(value):
    """Return 0/1/None from a bool/int/None input."""
    if value is None:
        return None
    return 1 if value else 0


def _prepare_event_row(event):
    """Build a dict keyed by EVENT_COLUMNS from whatever shape the caller passed."""
    infobox_raw = event.get("infobox_raw")
    if isinstance(infobox_raw, (dict, list)):
        infobox_raw = json.dumps(infobox_raw, ensure_ascii=False)

    row = {
        "air_date": event.get("air_date"),
        "tape_date": event.get("tape_date"),
        "date_derivation": event.get("date_derivation"),
        "show_type": event.get("show_type"),
        "episode_number": event.get("episode_number"),
        "title": event.get("title"),
        "ppv_name": event.get("ppv_name"),
        "venue": event.get("venue"),
        "city": event.get("city"),
        "state_province": event.get("state_province"),
        "country": event.get("country"),
        "attendance": event.get("attendance"),
        "tv_network": event.get("tv_network"),
        "tv_rating": event.get("tv_rating"),
        "broadcast_type": event.get("broadcast_type"),
        "commentary": event.get("commentary"),
        "promotion": event.get("promotion"),
        "promotion_raw": event.get("promotion_raw"),
        "cagematch_nr": event.get("cagematch_nr") or (
            event.get("nr") if event.get("source") == "cagematch" else None),
        "cagematch_url": event.get("cagematch_url") or (
            event.get("url") if event.get("source") == "cagematch" else None),
        "fandom_slug": event.get("fandom_slug") or (
            event.get("slug") if event.get("source") == "fandom" else None),
        "fandom_url": event.get("fandom_url") or (
            event.get("url") if event.get("source") == "fandom" else None),
        "primary_source": event.get("primary_source") or event.get("source"),
        "intro_prose": event.get("intro_prose"),
        "infobox_raw": infobox_raw,
        "verification_status": event.get("verification_status", "unverified"),
    }
    return row


def insert_event(conn, event):
    """Insert a single event row. Returns the new event id."""
    row = _prepare_event_row(event)
    cols = ", ".join(EVENT_COLUMNS)
    placeholders = ", ".join("?" for _ in EVENT_COLUMNS)
    values = [row[c] for c in EVENT_COLUMNS]
    cur = conn.execute(f"INSERT INTO events ({cols}) VALUES ({placeholders})", values)
    return cur.lastrowid


def upsert_event(conn, event):
    """INSERT OR merge on (air_date, show_type).

    If a row already exists for this (air_date, show_type), update only the
    columns that are currently NULL in the existing row, using non-None values
    from the new event dict. Never overwrite an existing non-NULL value.
    Returns the event id either way.
    """
    row = _prepare_event_row(event)
    cur = conn.execute(
        "SELECT * FROM events WHERE air_date = ? AND show_type = ?",
        (row["air_date"], row["show_type"]),
    )
    existing = cur.fetchone()
    if existing is None:
        return insert_event(conn, event)

    event_id = existing["id"]
    updates = {}
    for col in EVENT_COLUMNS:
        new_val = row.get(col)
        if new_val is None:
            continue
        if existing[col] is None:
            updates[col] = new_val
    if updates:
        set_clause = ", ".join(f"{c} = ?" for c in updates)
        conn.execute(
            f"UPDATE events SET {set_clause} WHERE id = ?",
            list(updates.values()) + [event_id],
        )
    return event_id


def get_or_create_wrestler(conn, name):
    """Return id of a wrestler with this canonical_name, creating if absent."""
    name = (name or "").strip()
    if not name:
        return None
    cur = conn.execute("SELECT id FROM wrestlers WHERE canonical_name = ?", (name,))
    row = cur.fetchone()
    if row is not None:
        return row["id"]
    cur = conn.execute("INSERT INTO wrestlers (canonical_name) VALUES (?)", (name,))
    return cur.lastrowid


def _insert_match_team(conn, match_id, team):
    row = (
        match_id,
        team.get("team_number"),
        team.get("team_name"),
        team.get("accompaniment"),
        _coerce_int_bool(team.get("was_winner")),
        team.get("match_outcome"),
        _coerce_int_bool(team.get("was_champion_entering")) or 0,
        _coerce_int_bool(team.get("was_champion_leaving")) or 0,
    )
    cur = conn.execute(
        "INSERT INTO match_teams "
        "(match_id, team_number, team_name, accompaniment, was_winner, "
        " match_outcome, was_champion_entering, was_champion_leaving) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    return cur.lastrowid


def insert_match(conn, event_id, match):
    """Insert a match with its teams and participants. Returns match id."""
    row = (
        event_id,
        match.get("match_order"),
        match.get("match_type"),
        match.get("stipulation"),
        match.get("title_at_stake"),
        match.get("duration_seconds"),
        match.get("match_guide_rating"),
        match.get("result_method"),
        match.get("parse_confidence"),
        match.get("raw_description"),
    )
    cur = conn.execute(
        "INSERT INTO matches "
        "(event_id, match_order, match_type, stipulation, title_at_stake, "
        " duration_seconds, match_guide_rating, result_method, "
        " parse_confidence, raw_description) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    match_id = cur.lastrowid

    for team in match.get("teams") or []:
        team_id = _insert_match_team(conn, match_id, team)
        for name in team.get("participants") or []:
            wrestler_id = get_or_create_wrestler(conn, name)
            conn.execute(
                "INSERT INTO match_participants "
                "(match_id, team_id, wrestler_id, wrestler_name_used) "
                "VALUES (?, ?, ?, ?)",
                (match_id, team_id, wrestler_id, name),
            )
    return match_id


FANDOM_KEEPS = frozenset({
    "air_date", "intro_prose", "infobox_raw", "fandom_slug", "fandom_url",
    "venue", "city",
})
CAGEMATCH_OVERWRITES = frozenset({
    "tape_date", "cagematch_nr", "cagematch_url", "primary_source",
})


def merge_cagematch_event(conn, event):
    """Merge a Cagematch event. Returns (event_id, was_merge: bool).

    Behavior:
      - If no existing row at (air_date, show_type): straight INSERT with
        primary_source='cagematch'. was_merge=False.
      - If an existing row is found (typically a Fandom-sourced SmackDown):
          * Cagematch overwrites: tape_date, cagematch_nr, cagematch_url,
            primary_source.
          * Fandom keeps: air_date, intro_prose, infobox_raw, fandom_slug,
            fandom_url, venue, city (never overwritten).
          * All other columns: COALESCE(existing, new) -- fill NULLs only.
          * DELETE existing matches (and their teams/participants, cascaded).
            The caller then calls insert_match() for the fresh Cagematch ones.
        was_merge=True.
    """
    event = {**event, "primary_source": "cagematch"}
    row = _prepare_event_row(event)

    cur = conn.execute(
        "SELECT * FROM events WHERE air_date = ? AND show_type = ?",
        (row["air_date"], row["show_type"]),
    )
    existing = cur.fetchone()

    if existing is None:
        return insert_event(conn, event), False

    event_id = existing["id"]
    updates = {}
    for col in EVENT_COLUMNS:
        new_val = row.get(col)
        if col in FANDOM_KEEPS:
            continue
        if col in CAGEMATCH_OVERWRITES:
            if new_val is not None:
                updates[col] = new_val
            continue
        if new_val is not None and existing[col] is None:
            updates[col] = new_val

    if updates:
        set_clause = ", ".join(f"{c} = ?" for c in updates)
        conn.execute(
            f"UPDATE events SET {set_clause} WHERE id = ?",
            list(updates.values()) + [event_id],
        )

    # Drop existing matches so the caller can insert a fresh Cagematch set.
    # ON DELETE CASCADE drops match_teams and match_participants too.
    conn.execute("DELETE FROM matches WHERE event_id = ?", (event_id,))
    return event_id, True


def ensure_source(conn, event_id, source_name, source_url, notes=None):
    """Record a source URL against an event. Safe to call multiple times."""
    cur = conn.execute(
        "SELECT id FROM sources WHERE event_id = ? AND source_name = ? AND source_url = ?",
        (event_id, source_name, source_url),
    )
    if cur.fetchone() is not None:
        return
    conn.execute(
        "INSERT INTO sources (event_id, source_name, source_url, notes) VALUES (?, ?, ?, ?)",
        (event_id, source_name, source_url, notes),
    )
