"""
Fandom scraper for prowrestling.fandom.com SmackDown pages.

Two-layer scrape:
  1. List pages (already cached in data/fandom/smackdown_{year}.html).
     Gives 52 episode entries per year with air_date, city, venue, per-episode href.
  2. Per-episode pages (cached under data/fandom/episodes/<slug>.html on first fetch).
     Gives episode number, tape date, promotion, match list with winners and durations.

Run:
  .venv/bin/python src/fandom_scraper.py           # smoke test: parse all 3 list pages and enrich ONE sample episode
  .venv/bin/python src/fandom_scraper.py --full    # full enrichment, 156 fetches at 2s delay

Writes:
  data/fandom_events.json   156 list-level events, with matches populated on whichever episodes were enriched
"""

import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FANDOM_DIR = DATA_DIR / "fandom"
EPISODES_DIR = FANDOM_DIR / "episodes"

FANDOM_BASE = "https://prowrestling.fandom.com/wiki/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_DELAY_SEC = 2.0
RETRY_BACKOFFS_SEC = [1, 2, 4]

YEARS = ("2001", "2002", "2003")
SMOKE_TEST_SLUG = "March_29,_2001_Smackdown_results"

MONTH_MAP = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], 1)}


def parse_long_date(s):
    """Parse 'January 3, 2002' style dates. Returns date or None."""
    if not s:
        return None
    s = s.replace(" ", " ").strip()
    m = re.match(r"([A-Za-z]+)\s+(\d+)\s*,\s*(\d{4})", s)
    if not m:
        return None
    mon = MONTH_MAP.get(m.group(1))
    if not mon:
        return None
    try:
        return date(int(m.group(3)), mon, int(m.group(2)))
    except ValueError:
        return None


def parse_list_page(year):
    """Parse cached data/fandom/smackdown_{year}.html, return list of episode dicts."""
    html_path = FANDOM_DIR / f"smackdown_{year}.html"
    soup = BeautifulSoup(html_path.read_text(), "html.parser")
    main = soup.find("div", class_="mw-parser-output")
    if main is None:
        raise RuntimeError(f"no mw-parser-output in {html_path}")

    data_table = next((t for t in main.find_all("table") if not t.get("class")), None)
    if data_table is None:
        raise RuntimeError(f"no unclassed data table in {html_path}")

    rows = data_table.find_all("tr")
    episodes = []
    for tr in rows[1:]:  # skip header
        cells = tr.find_all(["td", "th"])
        if len(cells) < 4:
            continue
        ep_link = cells[0].find("a", href=True)
        if not ep_link:
            continue
        date_text = cells[1].get_text(" ", strip=True)
        air_date = parse_long_date(date_text)
        if air_date is None:
            continue
        href = ep_link["href"]
        slug = href[len("/wiki/"):] if href.startswith("/wiki/") else href
        episodes.append({
            "event_label": cells[0].get_text(" ", strip=True),
            "href": href,
            "slug": slug,
            "url": FANDOM_BASE + slug,
            "air_date_raw": date_text,
            "air_date": air_date.isoformat(),
            "city": cells[2].get_text(" ", strip=True),
            "venue": cells[3].get_text(" ", strip=True),
        })
    return episodes


def parse_all_list_pages():
    """Parse all three cached list pages. Returns 156 episode dicts sorted by air_date."""
    episodes = []
    for y in YEARS:
        episodes.extend(parse_list_page(y))
    episodes.sort(key=lambda e: e["air_date"])
    return episodes


def fetch_episode_html(slug, delay=REQUEST_DELAY_SEC):
    """Fetch (or load from cache) a per-episode page HTML."""
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    path = EPISODES_DIR / f"{slug}.html"
    if path.exists():
        return path.read_text(encoding="utf-8"), True  # cached

    url = FANDOM_BASE + slug
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            path.write_text(resp.text, encoding="utf-8")
            time.sleep(delay)
            return resp.text, False  # freshly fetched
        except requests.RequestException as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(RETRY_BACKOFFS_SEC[attempt])
    raise RuntimeError(f"fetch failed for {slug}: {last_err}")


def _extract_infobox(main):
    """Return flat dict from <aside class="portable-infobox"> data-source items."""
    aside = main.find("aside", class_="portable-infobox")
    if aside is None:
        return {}, None
    box = {}
    for item in aside.find_all(attrs={"data-source": True}):
        key = item.get("data-source")
        val_el = item.find("div", class_="pi-data-value") or item
        box[key] = val_el.get_text(" ", strip=True)
    # The infobox h2 with data-source="name" carries the show title.
    name_h2 = aside.find("h2", attrs={"data-source": "name"})
    name = name_h2.get_text(strip=True) if name_h2 else None
    return box, name


_TAPE_DATE_RE = re.compile(r"took place on\s+([A-Z][a-z]+\s+\d+\s*,\s*\d{4})")
_EPISODE_NUM_RE = re.compile(r"(?:Smackdown|SmackDown)\s*#\s*(\d+)", re.IGNORECASE)
# Duration is (M:SS) or (H:MM:SS) found anywhere in the body. We extract it,
# then strip it AND any trailing prose (context notes that follow it). The
# optional third group catches hour-long bouts (Iron Man / 60-min Broadways);
# without it a "(1:05:23)" matched nothing and the duration was lost.
_DURATION_RE = re.compile(r"\((\d+):(\d+)(?::(\d+))?\)")
_ACCOMP_RE = re.compile(r"\(w\s*/\s*([^)]+)\)")
_STABLE_RE = re.compile(r"^(.+?)\s*\(\s*(.+?)\s*\)\s*$")
_CHAMPION_RE = re.compile(r"\s*\(\s*c\s*\)\s*", re.IGNORECASE)
_WIN_VERB_RE = re.compile(r"\s+(?P<verb>defeated|beat|def\.?)\s+", re.IGNORECASE)
_VS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
_SEGMENT_TYPES = {"segment", "promo", "angle", "interview"}


# Strip from " in a/an " to end of string. Aggressive on purpose: it catches
# "Steve Austin in a Two On One Handicap Match", "Lita in a Three Way Match to
# retain the WWF Women's Championship", "Chris Benoit in a Best 2 out of 3
# falls match ... [2:1]", and similar narrative tails that leaked into the
# last participant on unusually-formatted Fandom pages. Risk of overreach is
# low; wrestler names essentially never contain the phrase " in a/an ".
_TRAILING_MATCH_NARRATIVE_RE = re.compile(
    r"\s+in\s+an?\s+.+$", re.IGNORECASE | re.DOTALL
)
# Cagematch outcome modifiers, case-insensitive, allowing spaces in "Count Out".
# The previous strip in cagematch_scraper.py only matched lowercase patterns
# without spaces and missed "by Count Out", "by referee's decision", etc.
_TRAILING_OUTCOME_MOD_RE = re.compile(
    r"\s+by\s+("
    r"disqualification|dq|count[\s-]?out|"
    r"referee'?s?\s+decision|submission|matchabbruch|knockout|ko"
    r")\b.*$",
    re.IGNORECASE,
)
# Cagematch outcome-prose tails like "X to retain the WWE Title" or
# "X to win the WWF European Championship". Captures the entire suffix.
_TRAILING_RETAIN_WIN_RE = re.compile(
    r"\s+to\s+(retain|win|capture|regain)\s+(?:the\s+)?.*$",
    re.IGNORECASE,
)
# Title-holder PREFIX pulled into the wrestler name, e.g.
# "WWE IC Champion Chris Benoit", "WCW World Champion The Rock".
_LEADING_TITLE_PREFIX_RE = re.compile(
    r"^\s*(WWE|WWF|WCW|ECW|TNA)\s+("
    r"Cruiserweight|IC|Intercontinental|US|United\s+States|Hardcore|"
    r"European|Tag\s+Team|World|Heavyweight|Light\s+Heavyweight|Women'?s"
    r")?\s*Champion\s+",
    re.IGNORECASE,
)
# Pre-name match-context like "(Special Referee: Jacqueline ): Chris Jericho"
# or "Steel Cage Match (Special Referee: Kurt Angle ): Brock Lesnar".
_LEADING_PAREN_CONTEXT_RE = re.compile(
    r"^[^:]*\([^)]*\)[^:]*:\s*",
)
# Leading role-prefix WITHOUT parens: "Special Guest Referee: Triple H",
# "Guest Referee: X", "Special Enforcer: Y", "Commentator: Joe Smith", etc.
_LEADING_ROLE_PREFIX_RE = re.compile(
    r"^\s*(special\s+)?(guest\s+)?(referee|enforcer|host|commentator):\s*",
    re.IGNORECASE,
)
# Match-description sentinel. Any name containing literal " vs. " is a match
# narrative that swallowed multiple wrestlers, e.g. "The Undertaker vs. Triple
# H vs. Vladimir Kozlov". Drop the entire entry — not a strip, a filter.
_MATCH_DESCRIPTION_VS_RE = re.compile(r"\svs\.\s")
# Trailing Cagematch annotations.
_TRAILING_TITLE_CHANGE_RE = re.compile(
    r"\s*-\s*title\s+change\s*!*\s*$", re.IGNORECASE
)
_TRAILING_ENDED_RE = re.compile(
    r"\s+ended(\s+.*)?$", re.IGNORECASE
)
_TRAILING_DRAFT_RE = re.compile(
    r"\s*[-(]\s*draft(ed[^)]*)?\)?\s*$", re.IGNORECASE
)
# Narrative result-prose tails. Cagematch occasionally inlines "X via Y",
# "X when Y did Z", "X defeated Y", etc. into the participant name when the
# match-result HTML has unusual structure. These strip everything from the
# trigger onward.
_TRAILING_VIA_RE = re.compile(r"\s+via\s+.*$", re.IGNORECASE | re.DOTALL)
_TRAILING_NARRATIVE_VERBS_RE = re.compile(
    r"\s+(defeated|applied|hit|pinned|submitted|eliminated|disqualified|counted\s+out)\s+.*$",
    re.IGNORECASE | re.DOTALL,
)
# Trailing " when " is applied LAST (after other strips), and the strip is
# rejected if the surviving prefix is shorter than 2 chars (defensive — the
# remaining length filter would also catch it, but the rejection lets a real
# 2-char name like "AJ when ..." survive intact for manual review).
_TRAILING_WHEN_RE = re.compile(r"\s+when\s+.*$", re.IGNORECASE | re.DOTALL)
# Leading narrative verb: the parser lost the wrestler's name entirely and
# kept only the verb-prefixed prose. Drop the row.
_LEADING_NARRATIVE_VERB_RE = re.compile(
    r"^(applied|defeated|pinned|submitted|hit|eliminated)\s+",
    re.IGNORECASE,
)
# Leading lowercase English pronoun: pure narrative orphan with no recoverable
# wrestler name (e.g., "she would have flashed the crowd"). Drop the row.
_LEADING_PRONOUN_RE = re.compile(
    r"^(she|he|they|it|we|you)\s+",
)
# Round D narrative-tail strips. " with the " is unconditional (real ring
# names don't contain that phrase). " with a " and " after " are conditional
# on a >=3-char surviving prefix to preserve the rare edge case of a 2-char
# real name with appended narrative.
_TRAILING_WITH_THE_RE = re.compile(r"\s+with\s+the\s+.*$", re.IGNORECASE | re.DOTALL)
_TRAILING_WITH_A_RE = re.compile(r"\s+with\s+a\s+.*$", re.IGNORECASE | re.DOTALL)
_TRAILING_AFTER_RE = re.compile(r"\s+after\s+.*$", re.IGNORECASE | re.DOTALL)
# Trailing numeric/version brackets like "[5]", "[2:1]".
_TRAILING_BRACKET_NUM_RE = re.compile(r"\s*\[\d[^\]]*\]\s*$")
# Trailing accompaniment "(w/ X)" with or without closing paren.
# The cagematch _ACCOMP_RE only handles the closed form. This catches the
# split-leak case where a participant ends "Triple H (w/ Stephanie McMahon"
# (no close).
_TRAILING_ACCOMP_RE = re.compile(r"\s*\(\s*w/[^)]*\)?\s*$", re.IGNORECASE)
# Trailing close paren with no open paren ahead: drop the paren and any
# trailing junk. Catches "D-Von Dudley )", "Curtis Axel )", "The Good Father )".
_TRAILING_CLOSE_PAREN_RE = re.compile(r"\s*\).*$")
# Leading "stable_name ( " artifact when split swallowed the open paren of an
# outer stable wrap. Catches "The Dudley Boyz ( Bubba Ray Dudley" → keep the
# wrestler after the paren. Requires an ALPHA character after the paren so we
# don't misread a digit-leak case like "Charlotte Flair (10:324" (handled by
# _TRAILING_PAREN_DIGIT_RE below).
_LEADING_STABLE_PAREN_RE = re.compile(r"^.+?\s*\(\s*(?=[A-Za-z])")
# Trailing "( <digit>..." with no closing paren. Cagematch sometimes leaks
# annotation/duration brackets like "Charlotte Flair (10:324" or
# "Brock Lesnar (5:30)". Strip from the open paren to end of string.
_TRAILING_PAREN_DIGIT_RE = re.compile(r"\s*\(\s*\d.*$")
# Last-ditch: replace any stray paren left after directional strips with a
# space (not empty), so "Foo(Bar" becomes "Foo Bar" and the next whitespace
# pass collapses it cleanly.
_STRAY_PAREN_RE = re.compile(r"\s*[()]\s*")

# One combined separator for participants. Matches &, comma, or ' and ' in a
# single pass so mixed-separator lists like
#   "Bubba Ray Dudley , D-Von Dudley & Spike Dudley"
# split cleanly into three names instead of falling through the first-match
# fallback (which would stop at '&' and leave the comma chunk whole).
_PARTICIPANT_SPLIT_RE = re.compile(r"\s*(?:&|,|\s+and\s+)\s*", re.IGNORECASE)


def _canonicalize_name(name):
    """Normalize a single wrestler name.

    Strips, in order:
      1. Pre-name match-context that contains parens, e.g.
         "(Special Referee: Jacqueline ): Chris Jericho" -> "Chris Jericho".
      2. Title-holder prefix ("WWE IC Champion Chris Benoit" -> "Chris Benoit").
      3. Trailing Cagematch outcome modifiers ("X by Count Out" -> "X").
      4. Trailing outcome-prose tails ("X to retain the WWE Title" -> "X").
      5. Trailing numeric brackets ("Brock Lesnar [5]" -> "Brock Lesnar").
      6. Trailing 'in a <X> Match' narrative leaks (Fandom).
      7. Surrounding double quotes on nicknames ('"Stone Cold" Steve Austin'
         -> 'Stone Cold Steve Austin').
      8. Stray opening/closing parens left over from _STABLE_RE failures
         ("The Usos ( Jey Uso" -> "The Usos Jey Uso", further cleaned below).
      9. Whitespace collapse and end-punctuation trim.

    Returns "" for inputs that collapse to <= 1 char (Type 3 junk filter).
    Real 2-char ring names like "AJ" (AJ Lee) and "B²" (B-2) are preserved.
    """
    if not name:
        return ""
    n = name.strip()
    # Fast-path: any " vs. " survivor is a match-description swallow → drop.
    if _MATCH_DESCRIPTION_VS_RE.search(n):
        return ""
    # Pre-name strips (parens-context first because it can expose a role-prefix).
    n = _LEADING_PAREN_CONTEXT_RE.sub("", n)
    n = _LEADING_ROLE_PREFIX_RE.sub("", n)
    n = _LEADING_TITLE_PREFIX_RE.sub("", n)
    # Drop entirely if the line starts with a narrative verb (Cagematch lost
    # the wrestler name and kept only the action prose).
    if _LEADING_NARRATIVE_VERB_RE.match(n):
        return ""
    # Drop entirely if the line starts with a lowercase English pronoun
    # (pure narrative orphan, no recoverable wrestler name).
    if _LEADING_PRONOUN_RE.match(n):
        return ""
    # Trailing strips. Order: explicit accompaniment / outcome prose / brackets
    # before directional paren strips so "Triple H (w/ Stephanie McMahon" loses
    # its accompaniment cleanly and isn't misread as a leading-stable-paren.
    n = _TRAILING_ACCOMP_RE.sub("", n)
    n = _TRAILING_OUTCOME_MOD_RE.sub("", n)
    n = _TRAILING_RETAIN_WIN_RE.sub("", n)
    n = _TRAILING_BRACKET_NUM_RE.sub("", n)
    n = _TRAILING_TITLE_CHANGE_RE.sub("", n)
    n = _TRAILING_ENDED_RE.sub("", n)
    n = _TRAILING_DRAFT_RE.sub("", n)
    n = _TRAILING_MATCH_NARRATIVE_RE.sub("", n)
    n = _TRAILING_PAREN_DIGIT_RE.sub("", n)
    # Round C: narrative result-prose strips.
    n = _TRAILING_VIA_RE.sub("", n)
    n = _TRAILING_NARRATIVE_VERBS_RE.sub("", n)
    # Round D: finishing-move + connector strips. " with the " unconditional;
    # " with a " and " after " require a >=3-char surviving prefix.
    n = _TRAILING_WITH_THE_RE.sub("", n)
    for trailing_re, min_len in (
        (_TRAILING_WITH_A_RE, 3),
        (_TRAILING_AFTER_RE, 3),
        (_TRAILING_WHEN_RE, 2),
    ):
        match = trailing_re.search(n)
        if match:
            candidate = n[: match.start()].rstrip()
            if len(candidate) >= min_len:
                n = candidate
    n = re.sub(r'"([^"]+)"', r"\1", n)
    n = re.sub(r"\s+", " ", n).strip()
    n = n.strip(" ,.:;")
    # Directional paren strips for split-leak cases.
    n = _TRAILING_CLOSE_PAREN_RE.sub("", n)
    n = _LEADING_STABLE_PAREN_RE.sub("", n)
    # Final safety: any remaining strays become a space (preserves word boundary).
    n = _STRAY_PAREN_RE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    n = n.strip(" ,.:;")
    # Re-check the match-description filter in case a strip exposed " vs. ".
    if _MATCH_DESCRIPTION_VS_RE.search(n):
        return ""
    # Type-3 junk: drop names with no alpha characters (pure digits, pure
    # punctuation, "10:324", "2:1", "5/", etc.) and 1-char names. Preserves
    # real ring names like "AJ", "B²", and "2 Cold Scorpio".
    if not any(c.isalpha() for c in n):
        return ""
    if len(n) <= 1:
        return ""
    return n


def _split_participants(team_text):
    """Return a list of individual wrestler names.

    Splits on any mixture of '&', ',', or ' and ' in one pass. One-element
    list for a single wrestler.
    """
    text = team_text.strip()
    if not text:
        return []
    parts = _PARTICIPANT_SPLIT_RE.split(text)
    names = [_canonicalize_name(p) for p in parts]
    return [n for n in names if n]


def _split_team(team_text):
    """Return (team_name, participants). Unpacks stables written as 'Name (A & B)'.

    team_name is the composite label (stable name, or the full 'A & B' string
    for no-parens tag teams). participants is always a list of individual
    wrestler names.
    """
    team_text = team_text.strip()
    m = _STABLE_RE.match(team_text)
    if m:
        team_name = _canonicalize_name(m.group(1))
        participants = _split_participants(m.group(2).strip())
        return team_name, participants
    cleaned = re.sub(r"\s+", " ", team_text).strip()
    cleaned = _TRAILING_MATCH_NARRATIVE_RE.sub("", cleaned).strip()
    participants = _split_participants(cleaned)
    if len(participants) > 1:
        return _canonicalize_name(cleaned), participants
    solo = _canonicalize_name(cleaned)
    return solo, ([solo] if solo else [])


def _classify_outcome(winner_idx, team_index, result_flavor):
    """Map (winner slot, this team's slot, flavor) to (was_winner, match_outcome)."""
    if result_flavor in ("no-contest", "draw"):
        return None, result_flavor
    if winner_idx is None:
        return None, None
    won = (team_index == winner_idx)
    if result_flavor == "dq":
        return won, "dq-win" if won else "dq-loss"
    if result_flavor == "countout":
        return won, "countout-win" if won else "countout-loss"
    return won, "win" if won else "loss"


def _is_match_li(li):
    """Skip context-note <li> elements that aren't real matches. A <li> counts
    as a match if it has a bold <b> match-type prefix OR contains a winner
    verb (defeated/beat/def/def.) OR a 'vs' separator."""
    if li.find("b") is not None:
        return True
    text = li.get_text(" ", strip=True)
    if _WIN_VERB_RE.search(text):
        return True
    if _VS_RE.search(text):
        return True
    return False


def _parse_match_li(li, order):
    """Heuristic extract of one match <li>. Always preserves raw_description."""
    raw = li.get_text(" ", strip=True)

    bold = li.find("b")
    match_type = bold.get_text(strip=True).rstrip(":").strip() if bold else None

    body = raw
    if match_type and body.lower().startswith(match_type.lower()):
        body = body[len(match_type):].lstrip(":").strip()

    # Duration may appear anywhere. Extract the first (M:SS), then drop it and
    # any trailing context prose after it. Anything ahead of the duration is
    # the match description we'll parse.
    duration_seconds = None
    m = _DURATION_RE.search(body)
    if m:
        g1, g2, g3 = m.group(1), m.group(2), m.group(3)
        if g3 is not None:                       # H:MM:SS
            duration_seconds = int(g1) * 3600 + int(g2) * 60 + int(g3)
        else:                                    # M:SS
            duration_seconds = int(g1) * 60 + int(g2)
        body = body[:m.start()].strip()
    body = body.rstrip("-").strip()
    body_lower = body.lower()

    # Result flavor tells us which outcome enum variants to use, independent of
    # who won. It's set during split, then consumed when we classify each team.
    result_flavor = "win"
    winner_idx = None
    result_method = None
    teams_text = []

    win_match = _WIN_VERB_RE.search(body)
    if win_match:
        result_method = "defeated"  # canonical label regardless of actual verb
        teams_text = [body[:win_match.start()].strip(), body[win_match.end():].strip()]
        winner_idx = 0
        if "by disqualification" in body_lower or re.search(r"\bby dq\b", body_lower):
            result_flavor = "dq"
        elif ("by countout" in body_lower or "by count-out" in body_lower
              or "by count out" in body_lower):
            result_flavor = "countout"
    elif _VS_RE.search(body):
        split_parts = _VS_RE.split(body, maxsplit=1)
        teams_text = [re.sub(r"\s*-\s*.*$", "", p).strip() for p in split_parts]
        if "no contest" in body_lower:
            result_method = "no contest"
            result_flavor = "no-contest"
        elif "draw" in body_lower:
            result_method = "draw"
            result_flavor = "draw"
        elif "double countout" in body_lower:
            result_method = "double countout"
            result_flavor = "no-contest"
        elif "double dq" in body_lower or "double disqualification" in body_lower:
            result_method = "double dq"
            result_flavor = "no-contest"
        else:
            result_method = "vs"
    else:
        result_method = "unparsed"

    teams = []
    for i, team_text in enumerate(teams_text):
        # Accomp: "(w / X & Y)"
        accomp = None
        m = _ACCOMP_RE.search(team_text)
        if m:
            accomp = re.sub(r"\s+", " ", m.group(1).strip())
            team_text = _ACCOMP_RE.sub(" ", team_text).strip()
        # Champion tag: "(c)" anywhere in the team_text. Tag team champions may
        # have two (c) markers; re.sub strips all occurrences in one pass.
        was_champion_entering = False
        if _CHAMPION_RE.search(team_text):
            was_champion_entering = True
            team_text = _CHAMPION_RE.sub(" ", team_text).strip()
        # Trim trailing "by X" modifier clauses that attach to either side.
        team_text = re.sub(r"\s+by\s+(disqualification|dq|countout|count-?out).*$", "",
                           team_text, flags=re.I).strip()
        team_name, participants = _split_team(team_text)
        was_winner, match_outcome = _classify_outcome(winner_idx, i, result_flavor)
        teams.append({
            "team_number": i + 1,
            "team_name": team_name,
            "participants": participants,
            "accompaniment": accomp,
            "was_champion_entering": was_champion_entering,
            "was_winner": was_winner,
            "match_outcome": match_outcome,
        })

    stipulation = None
    title_at_stake = None
    if match_type:
        mt_low = match_type.lower()
        if "non title" not in mt_low and "non-title" not in mt_low:
            if "championship" in mt_low or "title" in mt_low:
                title_at_stake = match_type
        for key in ("no dq", "no disqualification", "cage", "ladder", "tables",
                    "hardcore", "street fight", "bra and panties", "hell in a cell",
                    "royal rumble", "battle royal", "handicap", "first blood"):
            if key in mt_low:
                stipulation = key
                break

    # Parse confidence.
    is_segment = bool(match_type and match_type.lower() in _SEGMENT_TYPES)
    parse_confidence = "high"
    if not teams:
        parse_confidence = "low"
    elif duration_seconds is None and not is_segment:
        parse_confidence = "low"
    elif any(t["match_outcome"] is None for t in teams):
        parse_confidence = "low"

    return {
        "match_order": order,
        "match_type": match_type,
        "stipulation": stipulation,
        "title_at_stake": title_at_stake,
        "duration_seconds": duration_seconds,
        "result_method": result_method,
        "parse_confidence": parse_confidence,
        "raw_description": raw,
        "teams": teams,
    }


def parse_episode_page(html, list_entry=None):
    """Parse a Fandom per-episode page. Returns an event dict in the shape described in the spec."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("div", class_="mw-parser-output")
    if main is None:
        raise RuntimeError("no mw-parser-output")

    infobox, infobox_name = _extract_infobox(main)

    # Tape date lives in the intro prose ("took place on ...").
    tape_date = None
    intro_prose = None
    for p in main.find_all("p", recursive=False):
        text = p.get_text(" ", strip=True)
        if "took place on" in text:
            intro_prose = text
            m = _TAPE_DATE_RE.search(text)
            if m:
                tape_date = parse_long_date(m.group(1))
            break

    # Walk top-level tags for Results section and External links.
    tops = [k for k in main.children if isinstance(k, Tag)]

    matches = []
    in_results = False
    order = 0
    for el in tops:
        if el.name == "h2":
            text = el.get_text(" ", strip=True).lower()
            if "results" in text and not in_results:
                in_results = True
                continue
            elif in_results:
                break
        if in_results and el.name == "ul":
            for li in el.find_all("li"):
                if not _is_match_li(li):
                    continue
                order += 1
                matches.append(_parse_match_li(li, order))

    episode_number = None
    for i, el in enumerate(tops):
        if el.name == "h2" and "external links" in el.get_text(" ", strip=True).lower():
            if i + 1 < len(tops) and tops[i + 1].name == "ul":
                for li in tops[i + 1].find_all("li"):
                    m = _EPISODE_NUM_RE.search(li.get_text(" ", strip=True))
                    if m:
                        episode_number = int(m.group(1))
                        break
            break

    promotion_raw = infobox.get("promotion")
    # `promotion` stays null in the scraper output. Normalization (WWF vs WWE
    # by era, or matching Cagematch's long-form) happens at merge time where
    # Cagematch's value is available for cross-reference.
    promotion = None
    air_date_raw = infobox.get("date")
    air_date = parse_long_date(air_date_raw) if air_date_raw else None
    venue = infobox.get("venue")
    city = infobox.get("city")

    # Prefer list entry values where the infobox is silent.
    if list_entry is not None:
        air_date = air_date or parse_long_date(list_entry.get("air_date_raw"))
        venue = venue or list_entry.get("venue")
        city = city or list_entry.get("city")

    air_iso = air_date.isoformat() if air_date else (list_entry.get("air_date") if list_entry else None)
    tape_iso = tape_date.isoformat() if tape_date else None

    if air_iso and tape_iso:
        date_derivation = "fandom-provided"
    elif air_iso:
        date_derivation = "fandom-provided"
    elif tape_iso:
        # Derive the air date from SmackDown's era-aware broadcast schedule
        # rather than a flat tape + 2 (only correct in the Thursday eras).
        from src.smackdown_schedule import smackdown_air_date
        air_d, date_derivation = smackdown_air_date(date.fromisoformat(tape_iso))
        air_iso = air_d.isoformat()
    else:
        date_derivation = "unknown"

    return {
        "source": "fandom",
        "slug": list_entry["slug"] if list_entry else None,
        "url": list_entry["url"] if list_entry else None,
        "title": infobox_name or (list_entry["event_label"] if list_entry else None),
        "episode_number": episode_number,
        "show_type": "SmackDown",
        "promotion": promotion,
        "promotion_raw": promotion_raw,
        "air_date": air_iso,
        "tape_date": tape_iso,
        "date_derivation": date_derivation,
        "venue": venue,
        "city": city,
        "infobox_raw": infobox,
        "intro_prose": intro_prose,
        "matches": matches,
    }


def enrich(list_entry):
    """Fetch (or load cached) detail page and parse it, merged with list entry metadata."""
    html, cached = fetch_episode_html(list_entry["slug"])
    parsed = parse_episode_page(html, list_entry=list_entry)
    parsed["_cached"] = cached
    return parsed


def skeleton_from_list(entry):
    """Turn a list-page entry into a minimal event dict, no match data yet."""
    return {
        "source": "fandom",
        "slug": entry["slug"],
        "url": entry["url"],
        "title": entry["event_label"],
        "episode_number": None,
        "show_type": "SmackDown",
        "promotion": None,
        "promotion_raw": None,
        "air_date": entry["air_date"],
        "tape_date": None,
        "date_derivation": None,
        "venue": entry["venue"],
        "city": entry["city"],
        "matches": None,
    }


def main():
    parser = argparse.ArgumentParser(description="Parse Fandom SmackDown list and per-episode pages.")
    parser.add_argument("--full", action="store_true",
                        help="Enrich all 156 episodes with per-episode fetches (polite 2s delay).")
    parser.add_argument("--smoke-slug", default=SMOKE_TEST_SLUG,
                        help="Slug to enrich when --full is not passed.")
    args = parser.parse_args()

    list_entries = parse_all_list_pages()
    print(f"Parsed {len(list_entries)} list-page entries across {YEARS}.", flush=True)

    events = [skeleton_from_list(e) for e in list_entries]

    if args.full:
        print(f"Enriching all {len(list_entries)} episodes (network, ~{len(list_entries) * REQUEST_DELAY_SEC / 60:.1f} min)", flush=True)
        fresh_fetches = 0
        errors = []
        for i, entry in enumerate(list_entries, 1):
            try:
                parsed = enrich(entry)
                if not parsed.pop("_cached", True):
                    fresh_fetches += 1
                events[i - 1] = parsed
            except Exception as exc:
                errors.append({"slug": entry["slug"], "error": repr(exc)})
                events[i - 1]["enrich_error"] = repr(exc)
            if i % 10 == 0:
                print(f"  enriched {i}/{len(list_entries)}  fresh_fetches={fresh_fetches}  errors={len(errors)}", flush=True)
        print(f"Done. Fresh fetches this run: {fresh_fetches}. Errors: {len(errors)}", flush=True)
        if errors:
            (DATA_DIR / "fandom_errors.json").write_text(json.dumps(errors, indent=2))
            print(f"Wrote data/fandom_errors.json ({len(errors)} errored episodes)", flush=True)
    else:
        # Smoke: enrich only the requested slug.
        match = next((e for e in list_entries if e["slug"] == args.smoke_slug), None)
        if match is None:
            print(f"No list entry matches slug {args.smoke_slug!r}", file=sys.stderr)
            sys.exit(1)
        print(f"Smoke: enriching {args.smoke_slug}", flush=True)
        parsed = enrich(match)
        parsed.pop("_cached", None)
        idx = list_entries.index(match)
        events[idx] = parsed

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "fandom_events.json"
    out_path.write_text(json.dumps(events, indent=2, ensure_ascii=False))
    print(f"Wrote {out_path} ({len(events)} events, "
          f"{sum(1 for e in events if e.get('matches'))} enriched)", flush=True)


if __name__ == "__main__":
    main()
