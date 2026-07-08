#!/usr/bin/env python3
"""
SmackDown Hotel weekly lane for the wrestling dashboard.

The curated weekly spine (Raw/SmackDown). One page per show-year
(e.g. /events-results/wwe/raw-2026) holds every episode as an <h3> header
(number + date) followed by a <ul> of <li> match results. Editor-curated, so
no fantasy junk; carries clean per-episode dates + accurate cards, but NO match
durations (those get enriched from profightdb later) and NO ratings.

Usage:
    uv run smackdownhotel.py raw 2026          # live fetch a show-year
    uv run smackdownhotel.py --file tsh_year.html
    uv run smackdownhotel.py raw 2026 --json
"""
import argparse
import json
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
BASE = "https://www.thesmackdownhotel.com/events-results/wwe/{show}-{year}"

# Real WWE family/sibling tag teams whose side text writes the shared surname
# once ('Jimmy & Jey Uso', 'Nikki & Brie Bella'). Only these surnames may be
# lent back to a preceding mononym partner (see split_members); everything else
# is left as-is so a mononym like 'Kane' or 'Edge' is never fused into a fake
# name. Verified against the 2001-2026 corpus; add a surname here only after
# confirming both partners appear under it as a genuine family team.
# Sibling teams whose members are genuinely written first-name-first with the
# surname stated once ('Jimmy & Jey Uso', 'Nikki & Brie Bella'). Deliberately
# NARROW: wrestlers known by a full ring name (Rey Mysterio, Cody Rhodes, Eddie
# Guerrero) are written in full, so putting those surnames here would fabricate
# names when they tag with an outsider mononym ('Edge & Rey Mysterio' ->
# 'Edge Mysterio'). Single-token surnames only (the lend takes the partner's
# last word). Add a surname only after confirming BOTH members appear as bare
# first names in the corpus.
SHARED_SURNAME = frozenset({
    "Uso", "Hardy", "Steiner", "Dudley", "Bella", "Singh",
})

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
DATE_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
    re.I)
MULTIWAY_RE = re.compile(
    r"triple threat|fatal|four[- ]way|three[- ]way|gauntlet|battle royal|"
    r"royal rumble|elimination chamber|money in the bank|war ?games|gambit", re.I)
STIP_KEYS = ("hell in a cell", "tlc", "tables, ladders", "ladder", "tables", "steel cage",
             "cage", "last man standing", "no disqualification", "no dq", "street fight",
             "submission", "iron man", "i quit", "first blood", "casket", "hardcore",
             "battle royal", "royal rumble", "elimination chamber", "money in the bank",
             "war games", "gauntlet", "triple threat", "fatal")


def fetch_year(show, year):
    url = BASE.format(show=show, year=year)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = (s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'")
         .replace("&quot;", '"').replace("&rsquo;", "'").replace("&ndash;", "-"))
    s = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s)   # zero-width chars break tail strips
    return re.sub(r"\s+", " ", s).strip()


def parse_date(text):
    m = DATE_RE.search(text or "")
    if not m:
        return None
    return "%04d-%02d-%02d" % (int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))


def _split_depth0(s, seps):
    """Split s on any literal in seps, but only at paren depth 0."""
    out, cur, depth, i = [], [], 0, 0
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0:
            hit = next((sep for sep in seps if s[i:i + len(sep)] == sep), None)
            if hit:
                out.append("".join(cur)); cur = []; i += len(hit); continue
        cur.append(c); i += 1
    out.append("".join(cur))
    return [p.strip() for p in out if p.strip()]


def split_members(s):
    """Recursively flatten a side into individual wrestler names, descending into
    nested stables: 'The Bloodline (Roman Reigns & The Usos (Jimmy & Jey Uso))'
    -> [Roman Reigns, Jimmy Uso, Jey Uso]. A 'Label (members)' token contributes
    only its members (the stable name is dropped); a bare token is a wrestler.
    Greedy paren match spans nesting where the old [^()]* failed and leaked the
    whole stable string as one fake 'wrestler'."""
    members = []
    for tok in _split_depth0(s, [" & ", " and ", ", "]):
        m = re.match(r"^(.+?)\s*\((.*)\)\s*$", tok)
        if m and re.search(r"&|\band\b|,", m.group(2)):
            members.extend(split_members(m.group(2)))
        else:
            members.append(tok)
    # Partners often share a surname written once ('Jimmy & Jey Uso' arrives as
    # ['Jimmy', 'Jey Uso']): lend the trailing two-word name's surname back to a
    # preceding bare first-name partner so they don't fragment. Guard to two-person
    # sides only, AND only lend a surname that is a known shared-surname family
    # (SHARED_SURNAME): a bare mononym is usually a COMPLETE name, not a first name
    # missing its surname, so lending unconditionally invents wrestlers -- 'Kane &
    # Daniel Bryan' would become 'Kane Bryan', 'Edge & Rey Mysterio' -> 'Edge
    # Mysterio'. Fragmentation ('Jimmy' + 'Jey Uso' left unmerged) is recoverable
    # downstream by alias resolution; a fabricated participant is corruption that
    # is not. When in doubt, do not lend.
    if len(members) == 2:
        for i in range(len(members) - 1):
            if (members[i] and " " not in members[i]
                    and members[i + 1].count(" ") == 1
                    and members[i + 1].split()[-1] in SHARED_SURNAME):
                members[i] = members[i] + " " + members[i + 1].split()[-1]
    return members


def strip_result_tail(s):
    """Drop trailing result prose the source appends to the last name in a side:
    '... ends in a No Contest', '; X retains the title', 'via Count-out', 'to win
    the title', 'after interference', and battle-royal elimination narrative
    ('<entrants>. X eliminates Y'). Keeps the wrestler/team, drops the narrative
    so it never becomes part of a participant name. The elimination cut is
    period-anchored and lookahead-guarded so initials like 'C.M. Punk' survive."""
    s = re.split(r"\.\s+[^.]*\beliminat", s, maxsplit=1, flags=re.I)[0]
    return re.split(
        r"\s+ends in\b|;\s|\s+via\s+|\s+to\s+(?:win|retain|capture|become|advance|earn)\b|\s+after\s+",
        s, maxsplit=1, flags=re.I)[0].strip()


def split_teams_top(s):
    """Split a multi-team side on ', ' / ' and ' at paren depth 0 (keeps '&'
    partners together). Best-effort for multi-way matches."""
    out, cur, depth, i = [], [], 0, 0
    seps = [", ", " and "]
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0:
            hit = next((sep for sep in seps if s[i:i + len(sep)] == sep), None)
            if hit:
                out.append("".join(cur)); cur = []; i += len(hit); continue
        cur.append(c); i += 1
    out.append("".join(cur))
    return [p.strip() for p in out if p.strip()]


def parse_side(s):
    s = s.strip()
    s = re.sub(r"\[[^\]]*\]", " ", s)          # drop score annotations like [2-1]
    champ = "(c)" in s
    s = s.replace("(c)", "").strip()
    accompaniment = None
    m = re.search(r"\((?:w/|with)\s+(.+?)\)", s, re.I)
    if m:
        accompaniment = m.group(1).strip()
        s = (s[:m.start()] + s[m.end():]).strip()
    # A leftover trailing "(Name)" with no team separators is a manager / real-
    # name note, not a tag partner: peel it off so it doesn't fuse into the name.
    note = re.match(r"^(.+?)\s*\(\s*([^()&,]+?)\s*\)\s*$", s)
    if note and not re.search(r"\band\b", note.group(2)):
        accompaniment = accompaniment or note.group(2).strip()
        s = note.group(1).strip()
    team_name, participants = None, []
    tm = re.match(r"^(.+?)\s*\((.*)\)\s*$", s)            # "Team (a & b)", nesting ok
    if tm and re.search(r"&|\band\b|,", tm.group(2)):
        team_name = tm.group(1).strip()
        participants = split_members(tm.group(2))
    else:
        participants = split_members(s)
    return {"team_name": team_name, "participants": participants,
            "accompaniment": accompaniment, "was_champion_entering": champ}


def parse_descriptor(desc):
    if not desc:
        return None, None, None
    title = desc if re.search(r"championship|title", desc, re.I) and "contender" not in desc.lower() else None
    low = desc.lower()
    stip = next((k for k in STIP_KEYS if k in low), None)
    mtype = desc if not title else None
    return title, mtype, stip


def parse_match(li_html, order):
    sm = re.search(r"<strong>(.*?)</strong>", li_html, re.S)
    desc = strip_tags(sm.group(1)).rstrip(":").strip() if sm else None
    text = strip_tags(re.sub(r"<strong>.*?</strong>", "", li_html, flags=re.S))
    if not text:
        return None
    # Skip scraped page comments that leak in as <li> items ("... &middot; 3
    # months ago", "pending moderation").
    if re.search(r"&middot;|\b\d+\s+(?:month|year|week|day)s?\s+ago\b|pending moderation",
                 text, re.I):
        return None
    title, mtype, stip = parse_descriptor(desc)
    multiway = bool(MULTIWAY_RE.search((desc or "") + " " + text))

    # Match "defeats"/"defeat", the typo "defeatz", and the abbreviation "def.";
    # any unsplit result otherwise fuses both teams into one fake participant.
    halves = re.split(r"\s+(?:defeat[sz]?|def\.)\s+", text, maxsplit=1, flags=re.I)
    teams, result_method, finish, conf = [], None, None, "high"
    if len(halves) == 2:
        win, lose = halves
        fm = re.search(r"\s+(?:via|by)\s+(.+)$", lose, re.I)
        if fm:
            finish = fm.group(1).strip(); lose = lose[:fm.start()].strip()
        om = re.search(r"\s+to\s+(?:win|retain|capture|become).*$", lose, re.I)
        if om:
            lose = lose[:om.start()].strip()
        result_method = "defeated"
        sides = [(win, True, "win")]
        losers = split_teams_top(lose) if multiway else [lose]
        sides += [(l, False, "loss") for l in losers]
    else:
        sides = [(s, None, None) for s in re.split(r"\s+vs\.?\s+", text, flags=re.I)]
        result_method = "no-decision"; conf = "low"

    for side, won, outcome in sides:
        t = parse_side(strip_result_tail(side))
        if not t["participants"]:
            conf = "low"
        t.update(team_number=len(teams) + 1, was_winner=won, match_outcome=outcome)
        teams.append(t)
    if multiway and any(len(t["participants"]) > 2 for t in teams if not t["was_winner"]):
        conf = "low"   # possible team-grouping ambiguity in a multi-way

    return {"match_order": order, "match_type": mtype, "stipulation": stip,
            "title_at_stake": title, "duration_seconds": None,
            "result_method": result_method, "finish": finish,
            "parse_confidence": conf, "raw_description": text, "teams": teams}


def parse_year_html(html):
    episodes = []
    parts = re.split(r"(<h3[^>]*>.*?</h3>)", html, flags=re.S)
    for i in range(1, len(parts), 2):
        header = strip_tags(parts[i])
        date = parse_date(header)
        if not date:
            continue
        body = parts[i + 1] if i + 1 < len(parts) else ""
        epnum = None
        em = re.search(r"#\s*(\d+)", header)
        if em:
            epnum = int(em.group(1))
        matches, order = [], 1
        for li in re.findall(r"<li[^>]*>(.*?)</li>", body, flags=re.S):
            m = parse_match(li, order)
            if m and m["teams"]:
                matches.append(m); order += 1
        if matches:
            episodes.append({"date": date, "episode_number": epnum,
                             "header": header, "matches": matches})
    return episodes


def render(episodes):
    print(f"{len(episodes)} episodes parsed")
    for ep in episodes:
        n = f"#{ep['episode_number']}" if ep['episode_number'] else ""
        print(f"\n== {ep['date']} {n} ({len(ep['matches'])} matches) ==")
        for m in ep["matches"]:
            win = " & ".join("/".join(t["participants"]) + ("(c)" if t["was_champion_entering"] else "")
                             for t in m["teams"] if t["was_winner"])
            los = " & ".join("/".join(t["participants"]) + ("(c)" if t["was_champion_entering"] else "")
                             for t in m["teams"] if t["was_winner"] is False)
            line = f"{win} def. {los}" if win else m["raw_description"]
            extra = []
            if m["title_at_stake"]:
                extra.append(f"[{m['title_at_stake']}]")
            elif m["match_type"]:
                extra.append(m["match_type"])
            if m["finish"]:
                extra.append(f"({m['finish']})")
            if m["parse_confidence"] == "low":
                extra.append("<?>")
            print(f"  {m['match_order']}. {line}  " + "  ".join(extra))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("show", nargs="?", help="raw | smackdown")
    ap.add_argument("year", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.file:
        html = open(a.file, encoding="utf-8").read()
    elif a.show and a.year:
        html = fetch_year(a.show, a.year)
    else:
        ap.error("give: <show> <year>  or  --file")
    episodes = parse_year_html(html)
    if a.json:
        print(json.dumps(episodes, ensure_ascii=False, indent=2))
    else:
        render(episodes)


if __name__ == "__main__":
    main()
