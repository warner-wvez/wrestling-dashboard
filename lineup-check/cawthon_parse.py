"""Parse Graham Cawthon's results pages (thehistoryofwwe.com) into lineups.

Pure functions over page HTML, no network. Two page kinds:

  show year page   /wwf-raw-2001/, /wwe-smackdown-2013/: every episode starts
                   "1/8/01; San Jose, CA; HP Pavilion<br /><i>1/8/01</i>:" (or
                   "Taped 12/29/00; ..." when the air date differs), then one
                   match per <br />-separated line. In later years the next
                   header can run straight on from the last match line, so
                   episodes are found by that header pattern, not by lines.
  results year page /wwf-results-2001/: every event of the year, house shows
                   included. A PPV is a "<b>... January 21, 2001 ...</b>" entry
                   with an "<i>Pay-per-view bouts ...</i>:" section, usually
                   after an "<i>Sunday Night Heat ...</i>:" pre-show section.

A match line is prose: "The Acolytes (w/ Jackie) & Billy Gunn defeated the
Goodfather, Val Venis, & Bull Buchanon (w/ Steven Richards) when Gunn pinned
Venis ...". parse_match_line keeps the two sides, drops escorts, champion
titles and the finish clause, and saves "(sub. for X)" notes.
"""
import html as htmllib
import re
from datetime import date

# The air-date line is "<i>1/8/01</i>:", optionally titled ("<i>Smackdown!
# Xtreme - 2/1/01 - ...</i>:"). The colon is optional because the page
# sometimes drops it and runs the first match on (Raw 11/2/09).
_EPISODE_RE = re.compile(
    r"((Taped\s+)?(\d{1,2})/(\d{1,2})/(\d{2});\s*([^;<]+?)(?:;\s*([^<]*?))?)\s*<br\s*/?>\s*"
    r"<i>\s*(?:[^<\d]{0,60}?(?:&#8211;|\u2013|-)\s*)?(\d{1,2})/(\d{1,2})/(\d{2})"
    r"([^<]*(?:<(?!/i>)[^<]*)*)</i>\s*:?", re.I)
_AIRDATE_RE = re.compile(
    r"<i>\s*(?:[^<\d]{0,60}?(?:&#8211;|\u2013|-)\s*)?(\d{1,2})/(\d{1,2})/(\d{2})(?:(?!<br).)*?</i>\s*:",
    re.I | re.S)
_PRODUCT_REF_RE = re.compile(r"\(\s*<i>.*?</i>\s*\)", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_PPV_HEAD_RE = re.compile(
    r"<b>((?:(?!</b>).)*?([A-Z][a-z]+ \d{1,2}, \d{4})(?:(?!</b>).)*)</b>", re.S)
_SECTION_RE = re.compile(r"<i>\s*([A-Z][^<:]*?)(?:\s*&#8211;|\s*–|</i>)", re.S)

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def _year(yy):
    return 2000 + int(yy) if int(yy) < 70 else 1900 + int(yy)


def _iso(m, d, yy):
    return date(_year(yy), int(m), int(d)).isoformat()


def _text(fragment):
    fragment = _PRODUCT_REF_RE.sub(" ", fragment)
    t = htmllib.unescape(_TAG_RE.sub(" ", fragment)).replace("’", "'")
    return re.sub(r"\s+", " ", t).strip()


def _lines(fragment):
    parts = re.split(r"<br\s*/?>|</p>|<p>", fragment, flags=re.I)
    return [t for t in (_text(p) for p in parts) if t]


_LOOSE_HEAD_RE = re.compile(
    r"<p>\s*((Taped\s+)?(\d{1,2})/(\d{1,2})/(\d{2});\s*([^;<]+?)(?:;\s*([^<]*?))?)\s*<br\s*/?>",
    re.I)
_HEAD_NOTE_RE = re.compile(r"\s*<i>((?:[^<]|<(?!/i>))*)</i>\s*:?", re.I)


def _until_next_event(body):
    """Cut a body at the next bold dated header ("WWF @ Ft. Worth, TX -
    April 2, 2001", the next night's TV or a house show). Without the cut,
    WrestleMania X-Seven took on the next night's Raw cage match and
    SmackDown 1/9/03 a Trenton house show's second DeMott vs Moore."""
    nxt = next((b for b in _PPV_HEAD_RE.finditer(body) if b.group(2).split()[0] in MONTHS), None)
    return body[:nxt.start()] if nxt else body


def _loose_heads(page_html, strict):
    """Episode headers the strict pattern misses because the italic line
    under them has no plain air date: no italic line at all (Raw 8/30/04), a
    note with no date (Raw 11/3/08), text before the date with no dash ("Raw
    SuperShow 9/5/11") or an entity before it ("&#8220;Holiday with the
    Troops&#8221; &#8211; 12/19/05"). Each is a paragraph that opens with the
    header. Missed, a header's matches ran on into the week before.

    Yields (start, end, groups) shaped like an _EPISODE_RE match: groups 3-5
    the header date, 8-10 the air date (None when it cannot be known)."""
    taken = {h.start() for h in strict}
    for m in _LOOSE_HEAD_RE.finditer(page_html):
        if m.start(1) in taken:
            continue
        end = m.end()
        note = _HEAD_NOTE_RE.match(page_html, end)
        air = None
        if note:
            end = note.end()
            found = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2})\b", _text(note.group(1))[:80])
            air = found.groups() if found else None
        if air is None and not m.group(2):
            air = m.group(3, 4, 5)      # a live show airs on its header date
        g = m.groups()
        yield m.start(1), end, g[:7] + (air or (None, None, None))


def parse_show_page(page_html):
    """Episodes on a Raw or SmackDown year page: [{air_date, tape_date,
    header_date, date_conflict, city, venue, lines}] in page order."""
    strict = list(_EPISODE_RE.finditer(page_html))
    heads = sorted([(h.start(), h.end(), (None, None) + h.groups()[1:]) for h in strict] +
                   [(s, e, (None,) + g) for s, e, g in _loose_heads(page_html, strict)])
    out = []
    for n, (_, h_end, g) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(page_html)
        body = _until_next_event(page_html[h_end:end])
        if g[8] is None:
            continue        # a taped header whose air date the page never gives
        tape = _iso(g[3], g[4], g[5])
        taped = bool(g[2])
        city, venue = _text(g[6]), _text(g[7] or "")
        # One taping can carry a second episode: another "<i>date</i>:" inside.
        cuts = [(g[8], g[9], g[10], 0)]
        cuts += [(m.group(1), m.group(2), m.group(3), m.end()) for m in _AIRDATE_RE.finditer(body)]
        for k, (mo, dd, yy, start) in enumerate(cuts):
            stop = cuts[k + 1][3] if k + 1 < len(cuts) else len(body)
            chunk = body[start:stop]
            if k + 1 < len(cuts):
                chunk = chunk[: chunk.rfind("<i>")] if "<i>" in chunk else chunk
            air = _iso(mo, dd, yy)
            # A live show's header date is its air date. When they differ on
            # an untaped header, the page contradicts itself (Raw 2009 labels
            # its 6/29/09 San Jose show 7/6/09), so say so instead of guessing.
            conflict = (not taped and k == 0 and air != tape)
            out.append({"air_date": air, "tape_date": tape, "header_date": tape,
                        "date_conflict": conflict, "city": city, "venue": venue,
                        "lines": _lines(chunk)})
    return out


_EVENT_HEAD_RE = re.compile(
    r"([^<>]{2,120}?)\s*(?:&#8211;|\u2013)[^<>]{0,160}?(?:&#8211;|\u2013)\s*"
    r"([A-Z][a-z]+ \d{1,2}, \d{4})")


def parse_ppv_page(page_html):
    """PPVs on a results year page: {air_date: {title, heat, ppv}} where heat
    and ppv are match lines from those sections. Every event starts with a
    "Name - City - Venue - Month D, YYYY" line; only events with a
    pay-per-view section are kept (house shows and TV are skipped)."""
    heads = [h for h in _EVENT_HEAD_RE.finditer(page_html) if h.group(2).split()[0] in MONTHS]
    out = {}
    for n, h in enumerate(heads):
        end = heads[n + 1].start() if n + 1 < len(heads) else len(page_html)
        body = _until_next_event(page_html[h.end():end])
        if "pay-per-view bouts" not in body.lower():
            continue
        month, rest = h.group(2).split(" ", 1)
        dd, yyyy = rest.replace(",", "").split()
        when = date(int(yyyy), MONTHS[month], int(dd)).isoformat()
        sections = {"heat": [], "ppv": []}
        current = None
        for piece in re.split(r"(<i>(?:[^<]|<(?!/i>))*</i>\s*:)", body):
            head = re.match(r"<i>\s*([^<]*)", piece or "")
            if head and piece.rstrip().endswith(":"):
                label = head.group(1).lower()
                # Only a section label switches sections; any other italic
                # note mid-show ("featured a video package ...") does not end
                # the pay-per-view list (No Mercy 02 lost 3 of 8 matches).
                if label.startswith("pay-per-view"):
                    current = "ppv"
                elif label.startswith(("sunday night heat", "heat")):
                    current = "heat"
                continue
            if current:
                sections[current] += _lines(piece)
        title = _text(h.group(1)).strip(" >")
        out.setdefault(when, {"title": title, **sections})
    return out


# ---------- match lines ----------

_MATCH_LIKE_RE = re.compile(r"\b(?:defeated|pinned|fought|won)\b", re.I)


def looks_like_match(line):
    """A line that reads like a result, whether or not it parsed. A show with
    one of these unparsed must never have its leftovers called unaired."""
    return bool(_MATCH_LIKE_RE.search(line or ""))

_FOUGHT_RE = re.compile(
    r"^(?P<a>.+?)\s+fought\s+(?P<b>.+?)\s+to\s+an?\s+(?P<how>no contest|draw|time[- ]limit draw|"
    r"double (?:count[- ]?out|disqualification|dq))\b", re.I)
_WIN_RE = re.compile(r"^(?P<a>.+?)\s+(?P<verb>defeated|pinned|beat)\s+(?P<b>.+)$", re.I)
_FOUGHT_ALL_RE = re.compile(
    r"^(?P<a>.+?)\s+fought\s+to\s+an?\s+(?P<how>no contest|draw|double (?:count[- ]?out|disqualification|dq))\b",
    re.I)
_MULTI_RE = re.compile(r"\bwon\s+(?:the\s+|an?\s+)?.*?\b(?:royal rumble|battle royal|gauntlet|"
                       r"elimination chamber|tournament)\b", re.I)
# Where the loser side ends and the finish narrative begins.
_FINISH_RE = re.compile(
    r"\s+(?:when|after|following|with|at|via|by|to win|to retain|to become|to earn|"
    r"due to|as|before|during|backstage|outside|for|in (?:a|an|the|his|her|what|TLC)\b|"
    r"in\s+(?:[\w-]+\s+){0,4}match)\b|;|\s+\(", re.I)
_ESCORT_RE = re.compile(r"\(\s*w\s*/\s*[^()]*\)", re.I)
_SUB_RE = re.compile(r"\(\s*sub\.?\s+for\s+([^()]*)\)", re.I)
# A champion's billing before the name: "WWF IC & Tag Team Champion Triple H",
# "WWF Tag Team Champions - the Dudley Boyz". It must start on a promotion or a
# title word, so a partner named before it ("Steve Austin & WWF World Champion
# the Rock") is never eaten.
_TITLE_PREFIX_RE = re.compile(
    r"\b(?:former\s+)?(?:WWF|WWE|WCW|ECW|World|Unified|Undisputed|Intercontinental|"
    r"United|US|IC|Women's|Divas|Hardcore|European|Cruiserweight|Light|Tag|Raw|SmackDown)\b"
    r"(?:(?:\s+|\s*[/&]\s*)(?:[A-Z][\w'.-]*|IC|US))*?\s+Champions?\b\s*(?:[-\u2013]\s*)?")
_NOTE_RE = re.compile(r"\(([^()]*)\)")
_PREFIX_RE = re.compile(r"^[^:]{2,90}?\s:\s+|^[^:]{2,90}?:\s+(?=[A-Z])")
_SPLIT_RE = re.compile(r"\s*,\s*&\s*|\s*,\s*and\s+|\s*,\s*|\s+&\s+|\s+and\s+")


def split_side(side):
    """'Matt & Jeff Hardy (w/ Lita)' -> ['Matt', 'Jeff Hardy']. Escorts, sub
    notes, other parenthetical notes and champion titles are removed; names
    keep Cawthon's spelling."""
    side = _ESCORT_RE.sub(" ", side)
    side = _SUB_RE.sub(" ", side)
    side = _NOTE_RE.sub(" ", side)
    prev = None
    while prev != side:
        prev, side = side, _TITLE_PREFIX_RE.sub("", side)
    side = re.sub(r"\s+", " ", side).strip(" ,.")
    out = []
    for p in (p.strip(" ,.") for p in _SPLIT_RE.split(side)):
        if not p:
            continue
        if out and re.fullmatch(r"(?:Sr|Jr|II|III)", p):
            out[-1] = f"{out[-1]} {p}."    # "Chavo Guerrero, Sr." is one man
        else:
            out.append(p)
    return out


def parse_match_line(line):
    """{kind, winners, losers, result, sub_for, notes, line} or None for a
    non-match line. result is 'win' or 'no contest'/'draw'/...; for a no-winner
    result the two sides land in winners/losers in page order. kind 'multi'
    marks battle royals, Rumbles, gauntlets and tournaments, whose entrants are
    not listed as sides. sub_for and notes ("mystery partner") are kept for the
    spoiler-safe lineup feature."""
    subs = [s.strip() for s in _SUB_RE.findall(line)]
    notes = [n.strip() for n in _NOTE_RE.findall(line)
             if re.search(r"mystery|surprise|debut|return", n, re.I)]
    if _MULTI_RE.search(line) and " defeated " not in line and " pinned " not in line:
        winner = _PREFIX_RE.sub("", line[: _MULTI_RE.search(line).start()].strip())
        return {"kind": "multi", "winners": split_side(winner), "losers": [],
                "result": "win", "sub_for": subs, "notes": notes, "line": line}
    m = _FOUGHT_ALL_RE.match(_PREFIX_RE.sub("", line))
    if m:
        # "Naomi, Brie Bella, and Natalya fought to a no contest": one list,
        # every name its own side, nobody won.
        return {"kind": "match", "winners": split_side(m.group("a")), "losers": [],
                "result": m.group("how").lower(), "sub_for": subs, "notes": notes,
                "all_sides": True, "line": line}
    m = _FOUGHT_RE.match(_PREFIX_RE.sub("", line))
    if m:
        b = _FINISH_RE.split(m.group("b"), maxsplit=1)[0]
        return {"kind": "match", "winners": split_side(m.group("a")), "losers": split_side(b),
                "result": m.group("how").lower(), "sub_for": subs, "notes": notes, "line": line}
    m = _WIN_RE.match(line)
    if not m:
        return None
    a = _PREFIX_RE.sub("", m.group("a"))
    if re.search(r"\b(?:included|featured|hosted|aired|fought|when|after|during)\b|;", a, re.I):
        return None
    rest = _ESCORT_RE.sub(" ", m.group("b"))
    rest = _SUB_RE.sub(" ", rest)
    b = _FINISH_RE.split(rest, maxsplit=1)[0]
    return {"kind": "match", "winners": split_side(a), "losers": split_side(b),
            "result": "win", "sub_for": subs, "notes": notes, "line": line}
