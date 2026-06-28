#!/usr/bin/env python3
"""
Wikipedia PPV/PLE results lane for the wrestling dashboard.

Pulls WWE pay-per-view / Premium Live Event results from Wikipedia via the
sanctioned MediaWiki API (no scraping, no WAF, CC BY-SA, zero firecrawl credits)
and parses the standardized {{Pro wrestling results table}} template into the
project's event/match schema shape.

Weekly TV (Raw/SmackDown) is a separate lane (Wikipedia has no episode articles).

Usage:
    uv run wikipedia_ppv.py "WrestleMania 41"        # live fetch + summary
    uv run wikipedia_ppv.py --file wm41.wikitext     # parse a local dump
    uv run wikipedia_ppv.py "WrestleMania 41" --json # emit JSON
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://en.wikipedia.org/w/api.php"
# MediaWiki etiquette: descriptive UA with contact, serial requests, honor 429.
UA = ("WrestlingDashboard/1.0 "
      "(https://github.com/warner-wvez/wrestling-dashboard; wvarnadoluc@gmail.com)")

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
REF_RE = re.compile(r"<ref[^>]*?/>|<ref[^>]*?>.*?</ref>", re.DOTALL | re.IGNORECASE)
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
MONTH_RE = ("(january|february|march|april|may|june|july|august|september|"
            "october|november|december)")

MULTIWAY_RE = re.compile(
    r"triple threat|fatal|four[- ]way|three[- ]way|gauntlet|battle royal|"
    r"royal rumble|elimination chamber|money in the bank|war ?games", re.I)
STIP_KEYS = ("hell in a cell", "tlc", "tables, ladders", "ladder", "tables", "steel cage",
             "cage", "last man standing", "no disqualification", "no dq", "street fight",
             "submission match", "iron man", "i quit", "first blood", "casket",
             "buried alive", "hardcore", "battle royal", "royal rumble",
             "elimination chamber", "money in the bank", "war games", "gauntlet")


def fetch_wikitext(page):
    params = {"action": "parse", "page": page, "prop": "wikitext",
              "format": "json", "formatversion": "2", "redirects": "1"}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            if "error" in data:
                raise RuntimeError(data["error"].get("info", "API error"))
            return data["parse"]["wikitext"]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def strip_refs(s):
    return REF_RE.sub("", s or "").strip()


def strip_templates(s):
    """Drop embedded templates ({{efn}} footnotes, {{cite}}, {{'}}, ...) but
    first expand {{sortname|First|Last}} to the plain name. Footnotes commonly
    hide non-participant wikilinks that would otherwise pollute the match."""
    s = s or ""
    s = re.sub(r"\{\{sortname\|([^{}]*)\}\}",
               lambda m: " ".join(p for p in m.group(1).split("|")[1:3] if "=" not in p),
               s, flags=re.I)
    while True:                       # remove balanced {{...}} innermost-out
        new = re.sub(r"\{\{[^{}]*\}\}", "", s)
        if new == s:
            return new.strip()
        s = new


def link_display(target, disp):
    if disp:
        return disp.strip()
    return re.sub(r"\s*\([^)]*\)\s*$", "", target).strip()


def links_in(s):
    return [link_display(m.group(1), m.group(2)) for m in WIKILINK_RE.finditer(s or "")]


def split_top(s, seps):
    """Split s on any literal in seps, but only at [[]]/{{}}/() depth 0."""
    out, cur, i, db, dl, dp = [], [], 0, 0, 0, 0
    while i < len(s):
        two = s[i:i + 2]
        if two == "{{":
            db += 1; cur.append(two); i += 2; continue
        if two == "}}":
            db -= 1; cur.append(two); i += 2; continue
        if two == "[[":
            dl += 1; cur.append(two); i += 2; continue
        if two == "]]":
            dl -= 1; cur.append(two); i += 2; continue
        ch = s[i]
        if ch == "(":
            dp += 1
        elif ch == ")":
            dp -= 1
        if db == 0 and dl == 0 and dp == 0:
            hit = next((sep for sep in seps if s[i:i + len(sep)] == sep), None)
            if hit:
                out.append("".join(cur)); cur = []; i += len(hit); continue
        cur.append(ch); i += 1
    out.append("".join(cur))
    return [p.strip() for p in out if p.strip()]


def find_blocks(text, prefix):
    """Return raw text of each balanced {{prefix...}} template block.

    Case-insensitive on the prefix: WWE event articles are inconsistent about
    template-name casing. Royal Rumble pages use "{{Pro Wrestling results table}}"
    (capital W) while most others use a lowercase w, so match either or the whole
    undercard is silently dropped and the page parses to zero matches."""
    blocks, start, needle = [], 0, ("{{" + prefix).lower()
    low = text.lower()
    while True:
        idx = low.find(needle, start)
        if idx < 0:
            break
        depth, i = 0, idx
        while i < len(text):
            if text[i:i + 2] == "{{":
                depth += 1; i += 2; continue
            if text[i:i + 2] == "}}":
                depth -= 1; i += 2
                if depth == 0:
                    break
                continue
            i += 1
        blocks.append(text[idx:i]); start = i
    return blocks


def template_params(block):
    parts = split_top(block[2:-2], ["|"])  # strip {{ }}, split on top-level |
    params = {}
    for p in parts[1:]:                     # parts[0] is the template name
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip()] = v.strip()
    return params


def parse_time(t):
    if not t:
        return None
    m = TIME_RE.search(strip_refs(t))
    if not m:
        return None
    a, b, c = m.group(1), m.group(2), m.group(3)
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def _iso(y, mo, d):
    return "%04d-%02d-%02d" % (y, mo, d)


def parse_dates(text):
    """Plain-text infobox date field -> list of ISO dates. Handles single dates
    and multi-night ranges ('April 19-20, 2025', 'April 30 - May 1, 2025')."""
    s = strip_templates(strip_refs(text or "")).replace("–", "-").replace("—", "-").lower()
    ym = re.search(r"(\d{4})", s)
    if not ym:
        return []
    y = int(ym.group(1))
    m = re.search(MONTH_RE + r"\s+(\d{1,2})\s*-\s*" + MONTH_RE + r"\s+(\d{1,2})", s)
    if m:
        return [_iso(y, MONTHS[m.group(1)], int(m.group(2))),
                _iso(y, MONTHS[m.group(3)], int(m.group(4)))]
    m = re.search(MONTH_RE + r"\s+(\d{1,2})\s*(?:-|and)\s*(\d{1,2})", s)
    if m:
        mo, d1, d2 = MONTHS[m.group(1)], int(m.group(2)), int(m.group(3))
        return [_iso(y, mo, d) for d in range(d1, d2 + 1)] if d1 <= d2 else [_iso(y, mo, d1)]
    m = re.search(MONTH_RE + r"\s+(\d{1,2})", s)
    if m:
        return [_iso(y, MONTHS[m.group(1)], int(m.group(2)))]
    return []


def parse_caption_date(caption, year):
    if not caption or not year:
        return None
    m = re.search(MONTH_RE + r"\s+(\d{1,2})", caption.lower())
    return _iso(year, MONTHS[m.group(1)], int(m.group(2))) if m else None


def parse_stip(stip):
    stip = strip_templates(strip_refs(stip or ""))
    title, head = None, stip
    m = re.search(r"\bfor the\s+(.+)$", stip, re.I)
    if m:
        head = stip[:m.start()].strip()
        title = " / ".join(links_in(m.group(1))) or None
    names = links_in(head)
    mtype = names[0] if names else (re.sub(r"\s+", " ", head).strip() or None)
    low = stip.lower()
    special = next((k for k in STIP_KEYS if k in low), None)
    return mtype, title, special


def parse_side(side):
    side = strip_refs(side).strip()
    champ = bool(re.search(r"\(c\)", side))
    side = re.sub(r"\(c\)", "", side)
    accompaniment = None
    m = re.search(r"\(with (.+?)\)", side, re.I)
    if m:
        accompaniment = ", ".join(links_in(m.group(1))) or m.group(1).strip()
        side = side[:m.start()] + side[m.end():]
    team_name, participants = None, []
    # Team pattern: a leading wikilink immediately followed by a parenthetical
    # listing members, e.g. "[[The New Day|...]] ([[Kofi]] and [[Xavier]])".
    # Balanced-paren scan so disambiguators like "[[Erik (wrestler)|Erik]]" inside
    # the member list don't trip it up.
    tm = re.match(r"\s*(\[\[[^\]]+\]\])\s*\(", side)
    if tm:
        depth, j = 0, tm.end() - 1
        while j < len(side):
            if side[j] == "(":
                depth += 1
            elif side[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner_links = links_in(side[tm.end():j])
        if inner_links:
            team_name = links_in(tm.group(1))[0]
            participants = inner_links
    if not participants:
        participants = links_in(side)
    if not participants:  # names not wikilinked: split plain text on "and"/comma
        txt = re.sub(r"\s+", " ", side).strip(" ,")
        participants = [p.strip() for p in re.split(r"\s+and\s+|,\s*", txt) if p.strip()]
    # Split combined-team links like "[[Liv Morgan and Raquel Rodriguez]]".
    participants = [n.strip() for p in participants
                    for n in re.split(r"\s+and\s+", p) if n.strip()]
    return {"team_name": team_name, "participants": participants,
            "accompaniment": accompaniment, "was_champion_entering": champ}


def parse_match(order, match_str, stip_str, time_str):
    raw = strip_templates(strip_refs(match_str))
    mtype, title, stip = parse_stip(stip_str)
    multiway = bool(MULTIWAY_RE.search((stip_str or "") + " " + (mtype or "")))

    finish, body = None, raw
    fm = re.search(r"\bby\s+(\[\[[^\]]+\]\]|[A-Za-z][\w' \-]*?)\s*$", body)
    if fm:
        g = fm.group(1)
        finish = links_in(g)[0] if "[[" in g else g.strip()
        body = body[:fm.start()].strip()

    teams = []
    halves = re.split(r"\s+defeated\s+", body, maxsplit=1, flags=re.I)
    # Royal Rumble / battle royal rows have no "defeated": they read
    # "Winner won by last eliminating Loser". Match on raw (pre finish-strip) so
    # the eliminated entrant is not mistaken for a finish and lost.
    winm = re.match(r"(?P<win>.+?)\s+won\b(?P<rest>.*)$", raw, re.I | re.S)
    if len(halves) == 2:
        win_str, lose_str = halves
        sides = [(win_str, True, "win")]
        losers = split_top(lose_str, [" and ", ", "]) if multiway else [lose_str]
        sides += [(ls, False, "loss") for ls in losers]
        result_method = "defeated"
    elif winm:
        sides = [(winm.group("win"), True, "win")]
        lm = re.search(r"\blast eliminat(?:ed|ing)\s+(.+?)\s*$",
                       winm.group("rest"), re.I | re.S)
        if lm:
            sides.append((lm.group(1), False, "loss"))
            finish = "last elimination"
        result_method = "defeated"
    else:
        sides = [(s, None, None) for s in split_top(body, [" vs. ", " vs "])]
        result_method = "no-decision"

    for side, won, outcome in sides:
        t = parse_side(side)
        t.update(team_number=len(teams) + 1, was_winner=won, match_outcome=outcome)
        teams.append(t)

    return {"match_order": order, "match_type": mtype, "stipulation": stip,
            "title_at_stake": title, "duration_seconds": parse_time(time_str),
            "result_method": result_method, "finish": finish,
            "raw_description": raw, "teams": teams}


def parse_table(block):
    p = template_params(block)
    matches, n = [], 1
    while f"match{n}" in p:
        matches.append(parse_match(n, p.get(f"match{n}", ""),
                                   p.get(f"stip{n}", ""), p.get(f"time{n}", "")))
        n += 1
    return {"caption": strip_refs(p.get("caption", "")) or None, "matches": matches}


def _clean(v):
    v = strip_refs(v or "")
    v = re.sub(r"<!--.*?-->", "", v, flags=re.S)
    v = strip_templates(v)
    v = WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), v)
    v = re.sub(r"\[\[|\]\]|'''|''", "", v)
    v = re.sub(r"<[^>]+>", " ", v)   # strip stray HTML (e.g. <br> in infobox names)
    return re.sub(r"\s+", " ", v).strip() or None


def parse_infobox(wikitext):
    blocks = find_blocks(wikitext, "Infobox")
    if not blocks:
        return {}
    p = template_params(blocks[0])
    out = {k: _clean(p.get(k)) for k in ("name", "promotion", "venue", "city", "attendance")}
    date_field = p.get("date", "") or ""
    out["dates"] = parse_dates(date_field)
    ym = re.search(r"(\d{4})", date_field)
    out["year"] = int(ym.group(1)) if ym else None
    return out


def parse_event(wikitext):
    info = parse_infobox(wikitext)
    tables = [parse_table(b) for b in find_blocks(wikitext, "Pro wrestling results table")]
    dates = info.get("dates") or []
    year = info.get("year")
    for i, tbl in enumerate(tables):
        cap = parse_caption_date(tbl["caption"], year)
        tbl["date"] = cap or (dates[i] if i < len(dates) else (dates[0] if dates else None))
    return {"info": info, "tables": tables}


def render(event):
    info = event["info"]
    head = info.get("name") or "(unknown event)"
    meta = " | ".join(x for x in [
        ", ".join(info.get("dates") or []) or None,
        info.get("venue"), info.get("city"),
        ("att " + info["attendance"]) if info.get("attendance") else None] if x)
    print(f"EVENT: {head}")
    if meta:
        print(f"       {meta}")
    for tbl in event["tables"]:
        cap = tbl["caption"] or "Card"
        print(f"\n  [{cap}]  ({tbl['date'] or '?'})  {len(tbl['matches'])} matches")
        for m in tbl["matches"]:
            def team(t):
                names = "/".join(t["participants"]) or "?"
                if t["was_champion_entering"]:
                    names += "(c)"
                return names
            win = " & ".join(team(t) for t in m["teams"] if t["was_winner"])
            los = " & ".join(team(t) for t in m["teams"] if t["was_winner"] is False)
            line = f"{win} def. {los}" if win else " vs ".join(team(t) for t in m["teams"])
            bits = [f"#{m['match_order']}", line]
            if m["title_at_stake"]:
                bits.append(f"[{m['title_at_stake']}]")
            elif m["match_type"]:
                bits.append(m["match_type"])
            if m["duration_seconds"] is not None:
                bits.append(f"{m['duration_seconds'] // 60}:{m['duration_seconds'] % 60:02d}")
            if m["finish"]:
                bits.append(f"({m['finish']})")
            print("    " + "  ".join(bits))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", help="Wikipedia article title")
    ap.add_argument("--file", help="parse a local wikitext dump instead of fetching")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    a = ap.parse_args()

    if a.file:
        wikitext = open(a.file, encoding="utf-8").read()
    elif a.page:
        wikitext = fetch_wikitext(a.page)
    else:
        ap.error("give a page title or --file")

    event = parse_event(wikitext)
    if a.json:
        print(json.dumps(event, ensure_ascii=False, indent=2))
    else:
        render(event)


if __name__ == "__main__":
    main()
