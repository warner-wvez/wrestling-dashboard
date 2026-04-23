"""
Cagematch per-event scraper. Parses the 273 events in data/events_to_scrape.json,
extracts match-level data, and writes into SQLite via db.merge_cagematch_event
(which handles the Cagematch-after-Fandom merge path for SmackDown events).

Date handling:
  Raw  / PPV     : air_date = tape_date = Cagematch 'Date' field; derivation='live-broadcast'
  SmackDown      : tape_date = Cagematch 'Date' field; air_date = tape_date + 2 days
                   derivation='tape-plus-2-estimate' when no Fandom row exists.
                   When a Fandom row already lives at this air_date, the merge
                   preserves Fandom's derivation='fandom-provided' (COALESCE
                   never overwrites non-NULL values).

Run:
  .venv/bin/python src/cagematch_scraper.py               # default: run both smoke tests
  .venv/bin/python src/cagematch_scraper.py --smoke-raw
  .venv/bin/python src/cagematch_scraper.py --smoke-smackdown
  .venv/bin/python src/cagematch_scraper.py --full        # all 273 events

Caches Cagematch HTML at data/cagematch/events/<nr>.html.
"""

import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Ensure the project root is importable when invoked as `python src/cagematch_scraper.py`.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests
from bs4 import BeautifulSoup

from src.db import (
    get_connection, init_schema, merge_cagematch_event, insert_match,
    ensure_source,
)
from src.fandom_scraper import _split_team, _classify_outcome


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EVENTS_DIR = DATA_DIR / "cagematch" / "events"
DB_PATH = DATA_DIR / "wrestling.db"

BASE_URL = "https://www.cagematch.net/?id=1&nr={}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}

REQUEST_DELAY_SEC = 2.0
RETRY_BACKOFFS_SEC = [1, 2, 4]

SMOKE_RAW_NR = 2300          # WWE RAW #470, 2002-05-27
SMOKE_SMACKDOWN_NR = 2269    # WWF SmackDown #131, taped 2002-02-12, air 2002-02-14


# --- Regexes ------------------------------------------------------------------

# Duration: (M:SS) or (H:MM:SS). Require at least one colon to avoid matching
# stray parenthesized numbers.
_DURATION_RE = re.compile(r"\((\d+):(\d+)(?::(\d+))?\)")
# Cagematch uses present tense: "defeat" / "defeats" (also handle "defeated").
_WIN_VERB_RE = re.compile(r"\s+(defeat(?:s|ed)?|beat(?:s|en)?)\s+", re.IGNORECASE)
_VS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
_ACCOMP_RE = re.compile(r"\(w\s*/\s*([^)]+)\)")
# Champion tag: "(c)" with optional "[Title]" bracket suffix that names which
# title the wrestler holds (common in mixed-title matches).
_CHAMPION_RE = re.compile(r"\s*\(\s*c\s*\)\s*(?:\[[^\]]*\])?\s*", re.IGNORECASE)
_TITLE_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_RATING_RE = re.compile(r"Matchguide\s*Rating\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)

# Cagematch date strings are DD.MM.YYYY.
_CM_DATE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")

STIPULATION_KEYS = (
    "no dq", "no disqualification", "cage", "ladder", "tables", "hardcore",
    "street fight", "bra and panties", "hell in a cell", "royal rumble",
    "battle royal", "handicap", "first blood", "iron man", "submission match",
    "last man standing", "tlc", "three stages of hell", "inferno", "i quit",
)


# --- Fetch --------------------------------------------------------------------

def fetch_event_html(nr, delay=REQUEST_DELAY_SEC):
    """Load from cache or fetch. Returns (html, was_cached)."""
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = EVENTS_DIR / f"{nr}.html"
    if path.exists():
        return path.read_text(encoding="utf-8"), True
    url = BASE_URL.format(nr)
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            resp.encoding = "iso-8859-15"
            path.write_text(resp.text, encoding="utf-8")
            time.sleep(delay)
            return resp.text, False
        except requests.RequestException as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(RETRY_BACKOFFS_SEC[attempt])
    raise RuntimeError(f"fetch failed nr={nr}: {last_err}")


# --- Metadata -----------------------------------------------------------------

def _parse_cagematch_date(raw):
    """DD.MM.YYYY -> date or None."""
    if not raw:
        return None
    m = _CM_DATE_RE.match(raw)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _parse_attendance(raw):
    """'ca. 9.500' / '9500' / '15,000' -> int or None. Strips non-digits."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def _parse_location(raw):
    """'Edmonton, Alberta, Canada' -> (city, state_province, country)."""
    if not raw:
        return None, None, None
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    return parts[0], None, None


def parse_informationbox(soup):
    """Return a label->value dict from the InformationBoxTable."""
    info_box = soup.find("div", class_="InformationBoxTable")
    if info_box is None:
        return {}
    meta = {}
    for row in info_box.find_all("div", class_="InformationBoxRow"):
        label = row.find("div", class_="InformationBoxTitle")
        value = row.find("div", class_="InformationBoxContents")
        if label and value:
            key = label.get_text(strip=True).rstrip(":")
            meta[key] = value.get_text(" ", strip=True)
    return meta


class SkipEvent(Exception):
    """Raised when an event is intentionally out of corpus (House Show, PPV Pre-Show)."""


def classify_show_type(title, cm_type):
    """Map Cagematch (title, type) -> schema show_type, or SKIP for out-of-corpus kinds."""
    if cm_type == "House Show":
        return "SKIP"
    if cm_type == "Online Stream" and "Pre-Show" in (title or ""):
        return "SKIP"
    if cm_type == "Event" and "Axxess" in (title or ""):
        return "SKIP"
    if cm_type == "Pay Per View":
        return "PPV"
    t = (title or "").upper()
    if "SMACKDOWN" in t:
        return "SmackDown"
    if "RAW" in t:
        return "Raw"
    return None


# --- Match parsing ------------------------------------------------------------

def _parse_duration(text):
    """Return the first (M:SS) / (H:MM:SS) as seconds, and its match object."""
    m = _DURATION_RE.search(text)
    if not m:
        return None, None
    parts = [int(p) for p in m.group(0).strip("()").split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2], m
    return parts[0] * 60 + parts[1], m


def _extract_titles_at_stake(type_div):
    """Cagematch title pages live at id=5. Pull anchor texts for those links."""
    if type_div is None:
        return None
    titles = []
    for a in type_div.find_all("a", href=True):
        if "id=5" in a["href"]:
            titles.append(a.get_text(" ", strip=True))
    return " / ".join(titles) if titles else None


def _detect_stipulation(match_type):
    if not match_type:
        return None
    mt_low = match_type.lower()
    for key in STIPULATION_KEYS:
        if key in mt_low:
            return key
    return None


def parse_match_block(match_div, order):
    """Return a match dict shaped for db.insert_match."""
    type_div = match_div.find("div", class_="MatchType")
    results_div = match_div.find("div", class_="MatchResults")
    rec_div = match_div.find("div", class_="MatchRecommendedLine")

    match_type = type_div.get_text(" ", strip=True) if type_div else None
    title_at_stake = _extract_titles_at_stake(type_div)
    stipulation = _detect_stipulation(match_type)

    match_guide_rating = None
    if rec_div:
        rm = _RATING_RE.search(rec_div.get_text(" ", strip=True))
        if rm:
            try:
                match_guide_rating = float(rm.group(1))
            except ValueError:
                pass

    if results_div is None:
        return {
            "match_order": order,
            "match_type": match_type,
            "stipulation": stipulation,
            "title_at_stake": title_at_stake,
            "duration_seconds": None,
            "match_guide_rating": match_guide_rating,
            "result_method": "unparsed",
            "parse_confidence": "low",
            "raw_description": "",
            "teams": [],
        }

    raw = results_div.get_text(" ", strip=True)

    duration_seconds, dur_match = _parse_duration(raw)
    body = raw if dur_match is None else raw[:dur_match.start()].strip()
    body = body.rstrip("-").strip()
    body_lower = body.lower()

    result_flavor = "win"
    winner_idx = None
    result_method = None
    teams_text = []

    win_match = _WIN_VERB_RE.search(body)
    if win_match:
        result_method = "defeated"
        teams_text = [body[:win_match.start()].strip(), body[win_match.end():].strip()]
        winner_idx = 0
        if " by dq" in body_lower or " by disqualification" in body_lower:
            result_flavor = "dq"
        elif " by countout" in body_lower or " by count-out" in body_lower or " by count out" in body_lower:
            result_flavor = "countout"
    elif _VS_RE.search(body):
        parts = _VS_RE.split(body, maxsplit=1)
        teams_text = [re.sub(r"\s*-\s*.*$", "", p).strip() for p in parts]
        if "no contest" in body_lower:
            result_method = "no contest"
            result_flavor = "no-contest"
        elif "draw" in body_lower:
            result_method = "draw"
            result_flavor = "draw"
        elif "double dq" in body_lower or "double disqualification" in body_lower:
            result_method = "double dq"
            result_flavor = "no-contest"
        elif "double countout" in body_lower:
            result_method = "double countout"
            result_flavor = "no-contest"
        else:
            result_method = "vs"
    elif "went to a draw" in body_lower or "fought to a draw" in body_lower:
        result_method = "draw"
        result_flavor = "draw"
    else:
        result_method = "unparsed"

    teams = []
    for i, team_text in enumerate(teams_text):
        accomp = None
        am = _ACCOMP_RE.search(team_text)
        if am:
            accomp = re.sub(r"\s+", " ", am.group(1).strip())
            team_text = _ACCOMP_RE.sub(" ", team_text).strip()

        was_champion_entering = bool(_CHAMPION_RE.search(team_text))
        if was_champion_entering:
            team_text = _CHAMPION_RE.sub(" ", team_text).strip()
        # Drop any stray title brackets left over (defensive).
        team_text = _TITLE_BRACKET_RE.sub(" ", team_text).strip()
        # Trim trailing "by X" modifiers.
        team_text = re.sub(
            r"\s+by\s+(disqualification|dq|countout|count-?out).*$", "",
            team_text, flags=re.I).strip()

        team_name, participants = _split_team(team_text)
        was_winner, match_outcome = _classify_outcome(winner_idx, i, result_flavor)

        teams.append({
            "team_number": i + 1,
            "team_name": team_name,
            "participants": participants,
            "accompaniment": accomp,
            "was_winner": was_winner,
            "match_outcome": match_outcome,
            "was_champion_entering": was_champion_entering,
        })

    parse_confidence = "high"
    if not teams:
        parse_confidence = "low"
    elif duration_seconds is None:
        parse_confidence = "low"
    elif any(t["match_outcome"] is None for t in teams):
        parse_confidence = "low"

    return {
        "match_order": order,
        "match_type": match_type,
        "stipulation": stipulation,
        "title_at_stake": title_at_stake,
        "duration_seconds": duration_seconds,
        "match_guide_rating": match_guide_rating,
        "result_method": result_method,
        "parse_confidence": parse_confidence,
        "raw_description": raw,
        "teams": teams,
    }


# --- Event builder ------------------------------------------------------------

def build_event_from_html(nr, html, cagematch_url):
    """Return (event_dict_for_merge, matches_list)."""
    soup = BeautifulSoup(html, "html.parser")
    meta = parse_informationbox(soup)
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else meta.get("Name of the event")

    cm_type = meta.get("Type")
    show_type = classify_show_type(title, cm_type)
    if show_type == "SKIP":
        raise SkipEvent(f"nr={nr}: skipped kind, title={title!r}, type={cm_type!r}")
    if show_type is None:
        raise ValueError(f"nr={nr}: could not classify show_type from title={title!r}, type={cm_type!r}")

    tape_date = _parse_cagematch_date(meta.get("Date"))
    if tape_date is None:
        raise ValueError(f"nr={nr}: could not parse Date={meta.get('Date')!r}")

    if show_type == "SmackDown":
        air_date = tape_date + timedelta(days=2)
        date_derivation = "tape-plus-2-estimate"
    else:
        air_date = tape_date
        date_derivation = "live-broadcast"

    city, state_province, country = _parse_location(meta.get("Location"))
    episode_number = None
    em = re.search(r"#\s*(\d+)", title or "")
    if em:
        episode_number = int(em.group(1))

    ppv_name = title if show_type == "PPV" else None

    event = {
        "air_date": air_date.isoformat(),
        "tape_date": tape_date.isoformat(),
        "date_derivation": date_derivation,
        "show_type": show_type,
        "episode_number": episode_number,
        "title": title,
        "ppv_name": ppv_name,
        "venue": meta.get("Arena"),
        "city": city,
        "state_province": state_province,
        "country": country,
        "attendance": _parse_attendance(meta.get("Attendance")),
        "tv_network": meta.get("TV station/network"),
        "tv_rating": float(meta["TV rating"]) if meta.get("TV rating") and re.match(r"^\d+(?:\.\d+)?$", meta["TV rating"]) else None,
        "broadcast_type": meta.get("Broadcast type"),
        "commentary": meta.get("Commentary by"),
        "promotion": meta.get("Promotion"),
        "promotion_raw": meta.get("Promotion"),
        "source": "cagematch",
        "nr": nr,
        "cagematch_nr": nr,
        "url": cagematch_url,
        "cagematch_url": cagematch_url,
    }

    match_blocks = soup.find_all("div", class_="Match")
    matches = [parse_match_block(b, i + 1) for i, b in enumerate(match_blocks)]

    return event, matches


def scrape_one(nr, conn, delay=REQUEST_DELAY_SEC):
    """Fetch (or cache), parse, merge, insert matches. Returns (event_id, merged, event_dict, matches)."""
    html, cached = fetch_event_html(nr, delay=delay)
    url = BASE_URL.format(nr)
    event, matches = build_event_from_html(nr, html, url)
    event_id, merged = merge_cagematch_event(conn, event)
    ensure_source(conn, event_id, "cagematch", url)
    for m in matches:
        insert_match(conn, event_id, m)
    return event_id, merged, event, matches, cached


# --- CLI ----------------------------------------------------------------------

def _show_event_and_sample_match(tag, event_id, merged, event, matches, conn):
    print(f"[{tag}] event_id={event_id}  merged={merged}")
    print(f"       show_type={event['show_type']!r}  air_date={event['air_date']}  tape_date={event['tape_date']}")
    print(f"       derivation={event['date_derivation']!r}  episode_number={event['episode_number']}")
    print(f"       title={event['title']!r}")
    print(f"       venue={event['venue']!r}  city={event['city']!r}  state={event['state_province']!r}  country={event['country']!r}")
    print(f"       attendance={event['attendance']}  tv_network={event['tv_network']!r}  tv_rating={event['tv_rating']}")
    print(f"       commentary={event['commentary']!r}")
    print(f"       promotion={event['promotion']!r}")
    print(f"       cagematch_nr={event['cagematch_nr']}  cagematch_url={event['cagematch_url']}")
    print(f"       match_count={len(matches)}")
    if matches:
        mi = min(len(matches) - 1, 2)
        sample = matches[mi]
        print(f"       --- sample match #{mi + 1} ---")
        print(json.dumps(sample, indent=2, ensure_ascii=False))

    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    print(f"       --- DB row after merge ---")
    for k in ("id", "air_date", "tape_date", "date_derivation", "show_type",
             "title", "venue", "city", "fandom_slug", "cagematch_nr",
             "primary_source", "promotion", "promotion_raw", "intro_prose",
             "verification_status"):
        v = row[k]
        if k == "intro_prose" and v:
            v = v[:80] + "..."
        print(f"         {k}: {v!r}")
    mct = conn.execute("SELECT COUNT(*) AS n FROM matches WHERE event_id = ?", (event_id,)).fetchone()["n"]
    print(f"         matches in DB: {mct}")


def smoke(conn):
    print("=" * 72)
    print(f"Smoke 1: Raw straight-insert (nr={SMOKE_RAW_NR})")
    print("=" * 72)
    r = scrape_one(SMOKE_RAW_NR, conn)
    _show_event_and_sample_match("RAW", *r[:-1], conn)
    print()
    print("=" * 72)
    print(f"Smoke 2: SmackDown merge into Fandom row (nr={SMOKE_SMACKDOWN_NR})")
    print("=" * 72)
    r = scrape_one(SMOKE_SMACKDOWN_NR, conn)
    _show_event_and_sample_match("SD", *r[:-1], conn)
    conn.commit()


def full(conn):
    events_to_scrape = json.load(open(DATA_DIR / "events_to_scrape.json"))
    n = len(events_to_scrape)
    print(f"Full run: {n} events", flush=True)
    stats = {"inserted": 0, "merged": 0, "errors": 0, "skipped": 0, "cached": 0, "fresh": 0,
             "zero_match_events": 0}
    errors = []
    skipped = []
    for i, e in enumerate(events_to_scrape, 1):
        nr = e["nr"]
        try:
            html, cached = fetch_event_html(nr)
            stats["cached" if cached else "fresh"] += 1
            event, matches = build_event_from_html(nr, html, BASE_URL.format(nr))
            event_id, merged = merge_cagematch_event(conn, event)
            ensure_source(conn, event_id, "cagematch", BASE_URL.format(nr))
            for m in matches:
                insert_match(conn, event_id, m)
            stats["merged" if merged else "inserted"] += 1
            if not matches:
                stats["zero_match_events"] += 1
            low = sum(1 for m in matches if m.get("parse_confidence") == "low")
            low_ratio = (low / len(matches)) if matches else 0.0
            tag = "MERGE" if merged else "INSERT"
            print(
                f"  [{i:3d}/{n}] nr={nr:<4} {tag:<6} air={event['air_date']} "
                f"{event['show_type']:<9} matches={len(matches):2d} "
                f"low={low}/{len(matches) or 0} ({low_ratio:.0%})",
                flush=True,
            )
        except SkipEvent as exc:
            stats["skipped"] += 1
            skipped.append({"nr": nr, "reason": str(exc)})
            print(f"  [{i:3d}/{n}] nr={nr:<4} SKIP  {exc}", flush=True)
        except Exception as exc:
            stats["errors"] += 1
            errors.append({"nr": nr, "error": repr(exc)})
            print(f"  [{i:3d}/{n}] nr={nr:<4} ERROR {exc!r}", flush=True)
        if i % 20 == 0:
            conn.commit()
            print(
                f"  -- tally @{i}/{n}  inserted={stats['inserted']}  merged={stats['merged']}  "
                f"errors={stats['errors']}  skipped={stats['skipped']}  cached={stats['cached']}  "
                f"fresh={stats['fresh']}  zero_match={stats['zero_match_events']}",
                flush=True,
            )
    conn.commit()
    print(f"Done: {stats}", flush=True)
    if errors:
        (DATA_DIR / "cagematch_errors.json").write_text(json.dumps(errors, indent=2))
        print(f"Wrote data/cagematch_errors.json ({len(errors)} errors)", flush=True)
    if skipped:
        skipped_path = DATA_DIR / "cagematch_skipped.json"
        existing = []
        if skipped_path.exists():
            try:
                existing = json.loads(skipped_path.read_text())
                if not isinstance(existing, list):
                    existing = []
            except json.JSONDecodeError:
                existing = []
        merged = {s["nr"]: s for s in existing if "nr" in s}
        for s in skipped:
            merged[s["nr"]] = s
        skipped_path.write_text(json.dumps(list(merged.values()), indent=2))
        print(f"Wrote data/cagematch_skipped.json ({len(merged)} total skips)", flush=True)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--smoke-raw", action="store_true")
    group.add_argument("--smoke-smackdown", action="store_true")
    group.add_argument("--full", action="store_true")
    args = parser.parse_args()

    init_schema(DB_PATH)
    conn = get_connection(DB_PATH)

    try:
        if args.full:
            full(conn)
        elif args.smoke_raw:
            r = scrape_one(SMOKE_RAW_NR, conn)
            _show_event_and_sample_match("RAW", *r[:-1], conn)
            conn.commit()
        elif args.smoke_smackdown:
            r = scrape_one(SMOKE_SMACKDOWN_NR, conn)
            _show_event_and_sample_match("SD", *r[:-1], conn)
            conn.commit()
        else:
            smoke(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
