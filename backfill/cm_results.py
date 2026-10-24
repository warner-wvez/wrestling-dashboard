#!/usr/bin/env python3
"""Parse the cached Cagematch results rows for 1985 to 2000 into events and matches.

Input:  .firecrawl/cagematch-raw/results-*.md (the July scrape, one event per
        table cell: logo, "(DD.MM.YYYY) [Title](?id=1&nr=N) \\- Type @ Venue in
        City, State, Country", then "<br>- " separated match lines)
Output: backfill/out/cm_cards.json  events in bundle shape plus "workers"
        backfill/out/cm_unparsed.tsv lines that did not parse (nr, line)

Cagematch dates the TAPING night. Every TV family keeps that date here with
date_derivation "cagematch-taping"; join.py swaps in Cawthon's air date.
SmackDown alone gets the era rule now (Thursday air night in 1999 to 2000).

Classification is logo first, title stem second, type last, and an unknown
row halts the run (classify-or-halt), so a new show family can never be filed
under a wrong one silently.

Match-line grammar seen in the 47,897 lines of 1985 to 2000 (scan of
2026-10-23): an optional title link "[WWF X Title](?id=5&nr=N):", an optional
type prefix before a colon ("Tag Team", "Dark", "Dark Six Man Tag Team",
"Steel Cage", "Tournament First Round"), sides joined by " defeats " /
" defeat " (losers of a multi-way joined by " and ") or " vs. " for a
no-decision tail ("\\- Time Limit Draw", "Double Count Out", "Double DQ",
"No Contest", "Draw", "Double Pinfall"), a "by DQ" / "by Count Out" / "by KO"
finish, a trailing "(M:SS)", and " - TITLE CHANGE !!!" after the time.
Battle royals may read "Winner: [X]" with no losers listed.

    uv run --with requests --with beautifulsoup4 python backfill/cm_results.py
"""
from __future__ import annotations

import re
import sys
import urllib.parse
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "cagematch-pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

from parse_raw import _EVENT_RE, _LOGO_RE, _WORKER_RE, _EPISODE_RE, parse_location  # noqa: E402
from src.smackdown_schedule import smackdown_air_date  # noqa: E402
from backfill.common import OUT, YEARS, fresh_event, fresh_match, record_status, write_json  # noqa: E402

RAW_DIR = ROOT / ".firecrawl" / "cagematch-raw"

# Logo file stem (date range stripped) -> (show_type, family).
LOGO_FAMILIES = {
    "1_WWF Monday Night RAW": ("Raw", "main"),
    "1_WWF RAW is WAR": ("Raw", "main"),
    "1_WWF SmackDown": ("SmackDown", "main"),
    "1_WWF Saturday Night's Main Event": ("SNME", "main"),
    "1_WWF The Main Event": ("SNME", "main"),
    "1_WWF Friday Night's Main Event": ("SNME", "main"),
    "1_WWF In Your House": ("PPV", "main"),
    "1_WWF Superstars": ("Superstars", "syndicated"),
    "1_WWF Wrestling Challenge": ("Challenge", "syndicated"),
    "1_WWF Prime Time Wrestling": ("PrimeTime", "syndicated"),
    "1_WWF All American Wrestling": ("AllAmerican", "syndicated"),
    "1_WWF Sunday Night Heat": ("Heat", "syndicated"),
    "1_WWF Shotgun Saturday Night": ("Shotgun", "syndicated"),
    "1_WWF Mania~": ("Mania", "syndicated"),
    "1_WWF Sunday Night Slam": ("SundaySlam", "syndicated"),
    "1_WWF Jakked": ("Jakked", "syndicated"),
    "1_WWF Action Zone": ("ActionZone", "syndicated"),
}
# Title stems for rows that wear the promotion logo instead of a show logo.
TITLE_STEMS = [
    ("WWF Monday Night RAW", ("Raw", "main")), ("WWF RAW", ("Raw", "main")),
    ("WWF SmackDown", ("SmackDown", "main")),
    ("WWF Saturday Night's Main Event", ("SNME", "main")), ("WWF The Main Event", ("SNME", "main")),
    ("WWF Friday Night's Main Event", ("SNME", "main")),
    ("WWF Superstars", ("Superstars", "syndicated")), ("WWF Wrestling Challenge", ("Challenge", "syndicated")),
    ("WWF Prime Time Wrestling", ("PrimeTime", "syndicated")),
    ("WWF All American Wrestling", ("AllAmerican", "syndicated")),
    ("WWF Sunday Night Heat", ("Heat", "syndicated")), ("WWF Shotgun", ("Shotgun", "syndicated")),
    ("WWF Mania", ("Mania", "syndicated")), ("WWF Sunday Night Slam", ("SundaySlam", "syndicated")),
    ("WWF Jakked", ("Jakked", "syndicated")), ("WWF Action Zone", ("ActionZone", "syndicated")),
    # The 1988 Royal Rumble aired as a USA Network special; Wikipedia files it
    # with the pay-per-views, and that is the lane that carries it here.
    ("WWF Royal Rumble", ("PPV", "main")),
]
# TV-Show rows outside the fourteen families (spec, Scope): televised house
# shows on regional networks, the 1985 to 1986 syndicated shows the spec
# leaves out, tour broadcasts, one-off specials. Counted into
# backfill/out/cm_skipped.tsv so nothing is dropped silently.
SKIP_STEMS = (
    "WWF on ", "WWF On ", "WWF @ ", "WWF/", "SWS ", "WWF TV", "WWF House Show", "WWF All-Star Wrestling",
    "WWF Championship Wrestling", "WWF Georgia Championship Wrestling", "WWF Maple Leaf Wrestling",
    "WWF Super Astros", "WWF European ", "WWF UK Rampage", "WWF Wrestling Spotlight",
    "WWF SummerSlam Spectacular", "WWF March To WrestleMania", "WWF Survivor Series Showdown",
    "WWF Battle Royal At The Albert Hall", "WWF Paul Boesch Retirement Show", "WWF Houston Summit",
    "WWF Halftime Heat", "WWF Sun City SuperBowl", "WWF The War To Settle The Score",
)


def logo_stem(logo: str | None) -> str | None:
    if not logo:
        return None
    stem = urllib.parse.unquote(logo)
    stem = stem[:-4] if stem.lower().endswith(".gif") else stem
    return re.sub(r"_\d{4,8}-\d{0,8}$", "", stem)


def classify(logo: str | None, title: str, ctype: str):
    if ctype in ("House Show", "Event"):
        return ("SKIP", None)
    fam = LOGO_FAMILIES.get(logo_stem(logo) or "")
    if fam:
        return fam
    for stem, fam in TITLE_STEMS:
        if title.startswith(stem):
            return fam
    if ctype == "Pay Per View":
        return ("PPV", "main")
    if title.strip() == "WWF" or title.startswith(SKIP_STEMS):
        return ("SKIP", None)
    raise ValueError(f"unclassified row: logo={logo!r} title={title!r} type={ctype!r}")


# ---- match lines -----------------------------------------------------------

_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)]*)\)")
_DUR_RE = re.compile(r"\((\d{1,2}):(\d{1,2})(?::(\d{2}))?\)\s*$")
_NO_DECISION_RE = re.compile(
    r"\s*\\?-\s*(Time Limit Draw|Double DQ|Double Count Out|Double Countout|Double Count|"
    r"Double Pinfall|Double Pin|No Contest|No Result|Draw)\s*$", re.I)
# "by DQ", "by Count Out", and Cagematch's lower-case "by referee's decision"
# and "by forfeit", which otherwise stay glued to the loser's name.
_BY_RE = re.compile(r"\s+by\s+((?:[A-Z]|referee|forfeit)[A-Za-z' ]*?)\s*$")
_CHAMP_RE = re.compile(r"\s*\(c\)")
_TITLE_CHANGE_RE = re.compile(r"\s*\\?-\s*TITLE CHANGE\s*!*\s*$", re.I)
_WINNER_ONLY_RE = re.compile(r"^Winner:\s*(.+)$", re.I)


def _plain(md: str) -> str:
    return re.sub(r"\s+", " ", _LINK_RE.sub(r"\1", md)).strip()


def _split_top(text: str, sep: str) -> list[str]:
    """Split on sep outside parentheses and outside markdown link text."""
    out, depth, buf, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if depth == 0 and text.startswith(sep, i):
            out.append(buf)
            buf, i = "", i + len(sep)
            continue
        buf += ch
        i += 1
    out.append(buf)
    return [s.strip() for s in out if s.strip()]


def _cut_escort(md: str):
    """Remove "(w/ ...)" with its parens matched, so a manager's link URL
    (which holds its own parens) stays inside the escort. Returns (rest, escort)."""
    start = md.find("(w/")
    if start < 0:
        return md, None
    depth, i = 0, start
    while i < len(md):
        if md[i] == "(":
            depth += 1
        elif md[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    inner = md[start + 3:i].strip()
    return (md[:start] + " " + md[i + 1:]).strip(), inner


# A named side with its members in parens: "[Demolition](?id=28...) ( [Ax] & [Smash] )",
# or unlinked "The Dream Team ( [A], [B], [C] & [D] )" for teams without a
# Cagematch page. Two or more members inside; a single name in parens is an
# alias ("Hulk Machine ( Hulk Hogan )") and stays with the outer name.
_INNER = r"(?:[^()]|\((?:[^()]|\([^()]*\))*\))"       # text with parens nested two deep (a link inside an alias)
_GROUP_ANY_RE = re.compile(
    r"(\[[^\]]+\]\(https://www\.cagematch\.net/\?id=2[89]&nr=\d+[^)]*\)|[^()\[\]&,]+?)"
    r"\s*\(\s*(" + _INNER + r"*?(?: & |, )" + _INNER + r"*?)\s*\)")
_ALIAS_RE = re.compile(r"\s*\(" + _INNER + r"*\)")
_NOTE_RE = re.compile(r"\\\[[^\]]*\\\]")          # markdown-escaped "\[Runde 3\]" notes
_TITLE_ANY_RE = re.compile(r"\[([^\]]+)\]\(https://www\.cagematch\.net/\?id=5&nr=\d+\)")


def _split_head(md: str):
    """(head, rest) at the first colon outside parentheses, brackets and link
    URLs ("https:" sits inside the link's parens). (None, md) without one."""
    depth = 0
    for i, ch in enumerate(md):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == ":" and depth == 0:
            head = md[:i]
            if head.strip().lower() == "winner":
                return None, md
            return head, md[i + 1:]
    return None, md


def _members(md: str, workers: dict) -> list[str]:
    for name, nr in _WORKER_RE.findall(md):
        workers.setdefault(name.strip(), int(nr))
    out = []
    for part in _split_top(md, " & "):
        for p in _split_top(part, ", "):
            p, _ = _cut_escort(p)
            name = _plain(_ALIAS_RE.sub("", _LINK_RE.sub(r"\1", p)))   # links to text first, then aliases
            if name and name != "???":
                out.append(name)
    return out


def _side(md: str, workers: dict) -> dict:
    champ = bool(_CHAMP_RE.search(md))
    md = _CHAMP_RE.sub("", md)
    for name, nr in _WORKER_RE.findall(md):        # managers included: they are people too
        workers.setdefault(name.strip(), int(nr))
    md, esc = _cut_escort(md)
    accompaniment = _plain(esc) if esc else None
    md = md.strip()
    team_name = None
    g = _GROUP_ANY_RE.fullmatch(md)
    if g:                                           # the side IS one named group
        team_name = _plain(g.group(1))
        md = g.group(2)
    else:                                           # groups inside a bigger side
        md = _GROUP_ANY_RE.sub(lambda m: m.group(2), md)
    members = _members(md, workers)
    return {"team_name": team_name, "participants": members,
            "accompaniment": accompaniment, "was_champion_entering": champ}


def parse_line(text: str, order: int) -> dict | None:
    """One "- " match line of a results cell -> bundle match + workers + aired."""
    original = text.strip().lstrip("-").strip()
    md = _NOTE_RE.sub("", _TITLE_CHANGE_RE.sub("", original)).strip()
    workers: dict[str, int] = {}
    title, mtype, aired = None, None, True
    head, rest = _split_head(md)
    if head is not None:
        titles = _TITLE_ANY_RE.findall(head)
        if titles:
            title = " & ".join(t.strip() for t in titles)
        head_text = _plain(re.sub(r"\([^()]*\)", " ", _TITLE_ANY_RE.sub(" ", head)))
        if head_text.lower().startswith("dark"):
            aired, head_text = False, head_text[4:].strip()
        mtype = head_text or None
        md = rest.strip()
    duration, method, decided = None, "defeated", True
    for _ in range(2):                              # "(11:37) - Double DQ" and "- Double DQ (11:37)"
        nd = _NO_DECISION_RE.search(md)
        if nd:
            method, decided, md = nd.group(1), False, md[:nd.start()].rstrip()
        d = _DUR_RE.search(md)
        if d:
            parts = [int(x) for x in d.groups() if x is not None]
            duration = parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]
            md = md[:d.start()].rstrip()
        md = _TITLE_CHANGE_RE.sub("", md).strip()
    if decided:
        by = _BY_RE.search(md)
        if by:
            method, md = "by " + by.group(1).strip(), md[:by.start()].rstrip()
    wo = _WINNER_ONLY_RE.match(md)
    has_defeat = bool(re.search(r"\s+defeats?\s+", md))
    if not wo and decided and not has_defeat and " vs. " in md:
        method, decided = "No Result", False          # a listed bout with no result given
    if wo:
        sides, winners = [wo.group(1).strip()], {0}
    elif decided:
        halves = re.split(r"\s+defeats?\s+", md, maxsplit=1)
        if len(halves) != 2:
            return None
        sides = [halves[0]] + _split_top(halves[1], " and ")
        winners = {0}
    else:
        sides = _split_top(md, " vs. ")
        if len(sides) < 2 and has_defeat:
            halves = re.split(r"\s+defeats?\s+", md, maxsplit=1)
            sides = [halves[0]] + _split_top(halves[1], " and ")
        if len(sides) < 2:
            sides = _split_top(md, " and ")
        winners = set()
    if not sides or (len(sides) < 2 and not wo):
        return None
    teams = []
    for i, s in enumerate(sides):
        side = _side(s, workers)
        if not side["participants"]:
            if _plain(s).replace("???", "").strip(" &,"):
                return None                     # a real name we could not read
            side["team_name"] = "Unknown"       # Cagematch's "???": an unnamed opponent
        side["was_winner"] = (i in winners) if decided else None
        teams.append(side)
    if not any(t["participants"] for t in teams):
        return None
    # The corpus keeps Cagematch's "- TITLE CHANGE !!!" marker in the text: the
    # reign walk reads it to crown a new champion and to fill a vacant belt.
    m = fresh_match(order, teams, match_type=mtype, title_at_stake=title,
                    duration_seconds=duration, result_method=method,
                    raw_description=_plain(_NOTE_RE.sub("", original)))
    m["workers"] = workers
    m["aired"] = aired
    return m


def rule_unmarked_wins(matches: list[dict], url: str) -> int:
    """Cagematch writes "TITLE CHANGE !!!" on every change it records, so a
    challenger's clean win over the "(c)" side without it is a belt that
    stayed put: a reversed decision, a non-title finish Cagematch left out, or
    a dark match listed with no finish ("Mr. Perfect defeats Shawn Michaels
    (c) (6:05)", Superstars taping 1993-04-06). The reign walk crowns any clean
    win over the champion, so each such match gets a ruling naming the
    champion. A match with two belts on the line is left to the walk. Returns
    how many were ruled."""
    ruled = 0
    for m in matches:
        title = m.get("title_at_stake") or ""
        if not title or " & " in title or "TITLE CHANGE" in (m.get("raw_description") or "").upper():
            continue
        champ = [t for t in m["teams"] if t["was_champion_entering"]]
        winner = [t for t in m["teams"] if t["was_winner"]]
        if len(champ) != 1 or len(winner) != 1 or winner[0] is champ[0] \
                or winner[0]["match_outcome"] != "win" or not champ[0]["participants"]:
            continue
        m["title_result"] = {"title": title, "champions": list(champ[0]["participants"]),
                             "why": "Cagematch marks every title change it records and marks none on this match",
                             "source": url}
        ruled += 1
    return ruled


def _change_key(text: str) -> str:
    return re.sub(r"\W+", " ", _plain(text)).strip().lower()


def mark_replays(events: list[dict], seen: dict) -> int:
    """A TV show that aired a clip of a title change somewhere else carries the
    same Cagematch line as the night it happened: Action Zone #6, dated
    1994-11-09, lists Diesel's eight-second win over Bob Backlund from Madison
    Square Garden on 1994-11-26. The walk would crown Diesel at the clip. A
    TITLE CHANGE line on one of our TV shows is a replay when Cagematch also
    lists it on another night: at a house show or pay-per-view within 60
    days, or on an earlier TV show of ours within 120. The match gets
    `replay_of`, which the walk skips (the card still shows it). Returns how
    many were marked."""
    marked = 0
    for ev in events:
        if ev["show_type"] in ("PPV", "SNME"):
            continue
        day = date.fromisoformat(ev["tape_date"] or ev["air_date"])
        for m in ev["matches"]:
            if "TITLE CHANGE" not in (m.get("raw_description") or "").upper():
                continue
            orig = None
            for when, nr, kind in seen.get(_change_key(m["raw_description"]), []):
                if nr == ev["cagematch_nr"]:
                    continue
                gap = (when - day).days
                live = kind in (None, "SKIP", "PPV", "SNME")
                # A night apart or less is one taping listed twice (Halftime
                # Heat, 1999-01-26), not a clip of it; on two of our TV shows
                # the later listing is the copy (Money Inc.'s win of 1992 on
                # Superstars taped 10-12 and Wrestling Challenge taped 10-13).
                if abs(gap) < 2 and not (gap == -1 and not live):
                    continue
                if (live and abs(gap) <= 60) or (not live and -120 <= gap < 0):
                    orig = (when, nr)
                    break
            if orig:
                m["replay_of"] = f"https://www.cagematch.net/?id=1&nr={orig[1]}"
                marked += 1
    return marked


# ---- rows ------------------------------------------------------------------

def _cells(line: str):
    """(hit, cell text) per event on the line. The cell starts right after
    the location so the "<br>- " ahead of the first match is kept: the row
    regex swallows that <br>, and reading from h.end() lost every event's
    first match."""
    hits = list(_EVENT_RE.finditer(line))
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(line)
        yield h, line[h.end("loc"):end]


def parse_rows(lines, years=YEARS, skipped=None):
    """-> (events, unparsed). `skipped`, when given, is a Counter that
    receives (title stem, type) for every in-range row left out."""
    events, unparsed, halts = [], [], []
    seen = {}       # a TITLE CHANGE line -> [(date, nr, show type or None)], every row on file
    for line in lines:
        if "?id=1&nr=" not in line:
            continue
        for h, cell in _cells(line):
            y = int(h.group("y"))
            kind = None
            if y in years:
                logo_m = None
                for cand in _LOGO_RE.finditer(line, 0, h.start()):
                    logo_m = cand
                try:
                    kind = classify(urllib.parse.unquote(logo_m.group(1)) if logo_m else None,
                                    h.group("title").strip(), h.group("ctype").strip())[0]
                except ValueError:
                    kind = "SKIP"
            for piece in cell.split("<br>- ")[1:]:
                piece = piece.split("<br>")[0]
                if "TITLE CHANGE" in piece.upper():
                    seen.setdefault(_change_key(piece.split("<br>")[0].rstrip(" |").strip().lstrip("-").strip()), []).append(
                        (date(y, int(h.group("m")), int(h.group("d"))), int(h.group("nr")), kind))
            if y not in years:
                continue
            # The logo sits just ahead of this cell's date; a line can hold
            # several cells, so read the logo nearest before the hit.
            logo_m = None
            for cand in _LOGO_RE.finditer(line, 0, h.start()):
                logo_m = cand
            logo = urllib.parse.unquote(logo_m.group(1)) if logo_m else None
            title, ctype, nr = h.group("title").strip(), h.group("ctype").strip(), int(h.group("nr"))
            try:
                show_type, family = classify(logo, title, ctype)
            except ValueError as ex:
                halts.append(str(ex))
                continue
            if show_type == "SKIP":
                if skipped is not None:
                    skipped[(re.sub(r"\s*(#\d+|\d{4}|- Tag \d+.*|\(.*\))\s*$", "", title), ctype)] += 1
                continue
            tape = date(y, int(h.group("m")), int(h.group("d")))
            if show_type == "SmackDown":
                air, derivation = smackdown_air_date(tape)
            elif show_type in ("PPV", "SNME"):
                air, derivation = tape, "live-broadcast"
            else:
                air, derivation = tape, "cagematch-taping"
            venue, city, state, country = parse_location(h.group("loc"))
            matches, workers = [], {}
            for k, piece in enumerate(cell.split("<br>- ")[1:], 1):
                piece = piece.split("<br>")[0].rstrip(" |").strip()
                if not piece:
                    continue
                m = parse_line(piece, k)
                if m is None:
                    unparsed.append((nr, _plain(piece)))
                    continue
                workers.update(m.pop("workers"))
                matches.append(m)
            rule_unmarked_wins(matches, f"https://www.cagematch.net/?id=1&nr={nr}")
            ep = _EPISODE_RE.search(title)
            keep_tape = (air != tape) or derivation == "cagematch-taping"
            ev = fresh_event(air_date=air.isoformat(), tape_date=tape.isoformat() if keep_tape else None,
                             date_derivation=derivation, show_type=show_type, family=family,
                             episode_number=int(ep.group(1)) if ep else None, title=title,
                             ppv_name=title if show_type == "PPV" else None,
                             venue=venue, city=city, state_province=state, country=country,
                             cagematch_nr=nr, cagematch_url=f"https://www.cagematch.net/?id=1&nr={nr}",
                             primary_source="cagematch", logo=logo, matches=matches)
            ev["workers"] = workers
            ev["cm_type"] = ctype
            events.append(ev)
    if halts:
        raise SystemExit("classify-or-halt: " + "; ".join(sorted(set(halts))[:20]))
    mark_replays(events, seen)
    return events, unparsed


def main():
    files = sorted(RAW_DIR.glob("results-*.md"))
    if not files:
        sys.exit(f"no results-*.md under {RAW_DIR}")
    lines = (ln for f in files for ln in f.read_text(encoding="utf-8").splitlines())
    skipped = Counter()
    events, unparsed = parse_rows(lines, skipped=skipped)
    events.sort(key=lambda e: (e["air_date"], e["show_type"], e["cagematch_nr"]))
    write_json(OUT / "cm_cards.json", events)
    (OUT / "cm_unparsed.tsv").write_text(
        "".join(f"{nr}\t{ln}\n" for nr, ln in unparsed), encoding="utf-8")
    (OUT / "cm_skipped.tsv").write_text(
        "".join(f"{n}\t{ctype}\t{stem}\n" for (stem, ctype), n in sorted(skipped.items(), key=lambda kv: -kv[1])),
        encoding="utf-8")
    print(f"skipped {sum(skipped.values())} in-range rows outside the fourteen families "
          f"({len(skipped)} kinds) -> {OUT / 'cm_skipped.tsv'}")
    by = {}
    for e in events:
        key = (e["air_date"][:4], e["show_type"])
        by[key] = by.get(key, 0) + 1
    for k in sorted(by):
        print(f"  {k[0]} {k[1]:12s} {by[k]}")
    total_lines = sum(len(e["matches"]) for e in events) + len(unparsed)
    print(f"{len(events)} events, {sum(len(e['matches']) for e in events)} matches, "
          f"{len(unparsed)} unparsed lines of {total_lines} -> {OUT / 'cm_unparsed.tsv'}")
    print(f"{sum(1 for e in events for m in e['matches'] if m.get('title_result'))} unmarked wins over a "
          f"champion ruled as retained")
    for e in events:
        for m in e["matches"]:
            if m.get("replay_of"):
                print(f"  replay: {e['show_type']} {e['air_date']} #{m['match_order']} {m['raw_description'][:90]} "
                      f"(original {m['replay_of']})")
    record_status("cm_results", True, f"{len(events)} events, {len(unparsed)} unparsed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
