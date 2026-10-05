#!/usr/bin/env python3
"""The 24/7 title's changes outside a match.

The 24/7 title (2019 to 2022) changed hands wherever a referee was near:
backstage on Raw, at house shows, on a golf course, at a wedding. Our cards
carry the changes that were taped as matches, about a third of the title's
reigns; the rest happened in segments, at live events or on no show at all, so
the title history ran one reign straight across a week of swaps. This builds
data/247-title-changes.json, which the reign walk merges in.

A change goes in when two of three title histories list it, in the same place
in that night's run of changes:
  Wikipedia      List of WWE 24/7 Champions (wiki-cache/)
  Duncan & Will  wrestling-titles.com, wwe/wwe-247.html (wiki-cache/)
  WWE.com        the official title history (wwe-cache/)
Where Wikipedia tells a night in another order and the other two agree with
each other, theirs is used (Hershey, 2019-12-29). Anything only one history
lists is printed, not applied.

Dates follow the cards. A change on a taped show takes the day it aired (the
day WWE recognizes, or WWE.com's date), and a change on a show we carry names
that show and sits between its matches in the order the histories give, so a
segment after Saxton's win and before Reggie's lands there. The rest keep
their own date and sort ahead of any card that day.

    uv run --with requests --with beautifulsoup4 lineup-check/title_247.py
"""
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from wiki_titles import fetch, reigns  # noqa: E402

TITLE = "WWE 24/7 Title"
OUT = ROOT / "data" / "247-title-changes.json"
WIKI_PAGE = "List of WWE 24/7 Champions"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_WWE_24/7_Champions"
DW_URL = "https://www.wrestling-titles.com/wwe/wwe-247.html"
DW_FILE = HERE / "wiki-cache" / "wt_wwe-247.html"
WWE_URL = "https://www.wwe.com/classics/titlehistory/24-7-championship"
WWE_FILE = HERE / "wwe-cache" / "titlehistory_24-7-championship.html"

# One person under two names across the three histories. WWE.com uses today's
# ring name (SCRYPTS was Reggie, Madcap Moss was Riddick Moss).
ALIASES = {"scrypts": "reggie", "reginald": "reggie", "teddibiase": "milliondollarman",
           "glenjacobs": "glennjacobs", "madcapmoss": "riddickmoss", "pipernniven": "doudrop",
           "pipernivenx": "doudrop"}
# A history's event for a show we carry, by the card's show type.
NOT_CARRIED = re.compile(r"^(?:N/A|WWE Live|Main Event)?$|New Year|Founders|Flag Football|Michael Kay", re.I)
# A taped change's air date, as the list's notes give it.
AIRED = re.compile(r"(?:WWE recognizes this reign as beginning on|Aired on tape delay on) ([A-Z][a-z]+ \d{1,2})")


def _get(url, f):
    if not f.exists():
        import requests
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        r.raise_for_status()
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(r.content)
    return f.read_bytes().decode("utf-8", "replace")


def plain(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"<[^>]+>|\(.*?\)|\[.*?\]", "", s)       # "<br>", "(Michael Hutter)", "[2]"
    s = s.split("/")[0].split(":")[0]                    # "Reginald/Reggie", "Revival: Dash Wilder & ..."
    s = re.sub(r"^\s*(?:the|mayor)\s+", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def key(name):
    """For matching one history's name to another's. Never for finding a
    profile: "The Million Dollar Man" must not land on Ted DiBiase Jr."""
    s = plain(name)
    return ALIASES.get(s, s)


def same(a, b):
    x, y = key(a), key(b)
    return x == y or (min(len(x), len(y)) >= 5 and x[:5] == y[:5])


def wikipedia():
    rows = [r for r in reigns(fetch(WIKI_PAGE)["text"]) if r["champion"]]
    for i, r in enumerate(rows):
        r["n"] = i + 1
        for f in ("champion", "event", "notes"):
            r[f] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r[f])).strip()
    return rows


def duncan_will():
    from bs4 import BeautifulSoup
    out = []
    for tr in BeautifulSoup(_get(DW_URL, DW_FILE), "html.parser").find_all("tr"):
        w, d = tr.find("td", class_="wrestlers"), tr.find("td", class_="date")
        m = d and re.match(r"(\d{4}-\d\d-\d\d)", d.get_text(strip=True))
        if w and m:
            out.append({"date": m.group(1), "champion": re.sub(r"\s*\[\d+\]", "", w.get_text(" ", strip=True))})
    return out


def wwe_com():
    """WWE.com lists newest first, each reign as a name line then its dates."""
    from bs4 import BeautifulSoup
    lines = [ln.strip() for ln in BeautifulSoup(_get(WWE_URL, WWE_FILE), "html.parser").get_text("\n").split("\n")
             if ln.strip()]
    day = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})(?: - .*)?$")
    out = []
    for i in range(lines.index("Champion"), len(lines) - 1):
        m = day.match(lines[i + 1])
        if m and not day.match(lines[i]) and lines[i] not in ("day", "days") and not re.match(r"^[<\d]", lines[i]):
            out.append({"date": datetime.strptime(" ".join(m.groups()), "%b %d %Y").date().isoformat(),
                        "champion": lines[i]})
    return out[::-1]


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def align(a, b, ok):
    """Index pairs of the longest common subsequence of a and b under ok."""
    n, m = len(a), len(b)
    L = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            L[i][j] = L[i + 1][j + 1] + 1 if ok(a[i], b[j]) else max(L[i + 1][j], L[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if ok(a[i], b[j]) and L[i][j] == L[i + 1][j + 1] + 1:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif L[i + 1][j] >= L[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def confirm(wiki, dw, wwe):
    """Mark each Wikipedia row with the histories that list it, and take the
    other two's order for a night Wikipedia tells differently."""
    for r in wiki:
        r["sources"] = {"Wikipedia": f"{WIKI_URL} #{r['n']}"}
    # Duncan and Will date a change the way Wikipedia does, give or take a day
    # ("2020-03-26" for Gronkowski's WrestleMania win); WWE.com dates a taped
    # one by its air date, up to two weeks later. A shifted date counts only
    # when Wikipedia has no night of its own that day, or a change could pair
    # with the same wrestler's win the night before (Samir Singh won on both
    # 2019-12-28 and 2019-12-29).
    nights = {}
    for r in wiki:
        nights.setdefault(r["date"], []).append(r)

    def near(w, other, lo, hi):
        return other["date"] == w["date"] or (
            lo <= _days(w["date"], other["date"]) <= hi and other["date"] not in nights)

    for i, j in align(wiki, dw, lambda w, d: same(w["champion"], d["champion"]) and near(w, d, -1, 1)):
        wiki[i]["sources"]["Duncan & Will"] = DW_URL
    for i, j in align(wiki, wwe, lambda w, e: same(w["champion"], e["champion"]) and near(w, e, -1, 14)):
        wiki[i]["sources"]["WWE.com"] = WWE_URL
        wiki[i]["wwe_date"] = wwe[j]["date"]
    for day, rows in nights.items():
        if all(len(r["sources"]) >= 2 for r in rows):
            continue
        d = [x["champion"] for x in dw if x["date"] == day]
        e = [x["champion"] for x in wwe if x["date"] == day]
        w = [r["champion"] for r in rows]
        if len(d) == len(e) == len(w) and all(same(x, y) for x, y in zip(d, e)) \
                and sorted(map(key, d)) == sorted(map(key, w)):
            print(f"{day}: Wikipedia's order {w} differs from Duncan & Will and WWE.com {d}; using theirs")
            pool = list(rows)
            for k, name in enumerate(d):
                r = next(x for x in pool if same(x["champion"], name))
                pool.remove(r)
                r["order_in_night"] = k
                r["sources"] = {"Duncan & Will": DW_URL, "WWE.com": WWE_URL,
                                "Wikipedia": f"{WIKI_URL} #{r['n']} (lists this night in another order)"}
            rows.sort(key=lambda x: x["order_in_night"])
    return [r for rows in nights.values() for r in rows]


def air_date(events_by_date, r):
    """The day a viewer saw the change: the air date the notes give for a
    taped change; else the day of our card for that show, on the day it
    happened or, taped, on WWE.com's later day; else the day it happened."""
    m = AIRED.search(r["notes"])
    if m:
        d = datetime.strptime(f"{m.group(1)} {r['date'][:4]}", "%B %d %Y").date().isoformat()
        return d if d >= r["date"] else d.replace(d[:4], str(int(d[:4]) + 1), 1)
    if card_event(events_by_date, r, r["date"]):
        return r["date"]
    if r.get("wwe_date") and card_event(events_by_date, r, r["wwe_date"]):
        return r["wwe_date"]
    return r["date"]


def card_event(events_by_date, r, day):
    """Our Raw, SmackDown or pay-per-view that aired the change, if we carry it."""
    if NOT_CARRIED.search(r["event"]):
        return None
    want = "Raw" if re.search(r"\bRaw\b", r["event"]) else "SmackDown" if "SmackDown" in r["event"] else "PPV"
    return next((e for e in events_by_date.get(day, []) if e["show_type"] == want), None)


def card_changes(events):
    """The 24/7 changes our cards already carry, as (date, event id, match
    order, champion), from the reign walk without this file."""
    from src.export_to_html import build_title_reigns, load_offcard_changes
    others = load_offcard_changes(t247=Path("/nonexistent"))
    chain = build_title_reigns(events, offcard=others)[TITLE]
    used, out = set(), []
    for rg in chain:
        if rg["pre_corpus"] or not rg["start_event_id"]:
            continue
        ev = events[str(rg["start_event_id"])]
        m = next(m for m in sorted(ev["matches"], key=lambda m: m["match_order"])
                 if (m["id"] not in used and "24/7" in (m.get("title_at_stake") or "")
                     and any(same(p, rg["champion_names"][0])
                             for t in m["teams"] if t.get("was_winner") for p in t["participants"])))
        used.add(m["id"])
        out.append({"date": rg["start"], "event_id": ev["id"], "order": m["match_order"],
                    "champion": rg["champion_names"][0]})
    return out


def champ_markers(ev):
    return [p for m in ev["matches"] if "24/7" in (m.get("title_at_stake") or "")
            for t in m["teams"] if t.get("was_champion_entering") for p in t["participants"]]


def main():
    from src.build_update import load_existing
    data = load_existing()
    events = data["events"]
    by_plain = {}
    for n in data["wrestlers_by_name"]:
        by_plain.setdefault(plain(n), n)
    events_by_date = {}
    for e in events.values():
        events_by_date.setdefault(e["air_date"], []).append(e)

    wiki = confirm(wikipedia(), duncan_will(), wwe_com())
    keep = [r for r in wiki if len(r["sources"]) >= 2]
    for r in wiki:
        if len(r["sources"]) < 2:
            print(f"only Wikipedia lists it, not applied: {r['date']} {r['champion']} ({r['event']})")
    for r in keep:
        r["air"] = air_date(events_by_date, r)
        r["card"] = card_event(events_by_date, r, r["air"])

    # The changes a card already carries, matched on the day the card aired it.
    carried = card_changes(events)
    for i, j in align(keep, carried, lambda r, c: same(r["champion"], c["champion"]) and r["air"] == c["date"]):
        keep[i]["carried"] = carried[j]
    missing = [c for c in carried if not any(r.get("carried") is c for r in keep)]
    for c in missing:
        print(f"on our card but in no history: {c['date']} {c['champion']} (event {c['event_id']})")

    changes = []
    for idx, r in enumerate(keep):
        if r.get("carried"):
            continue
        champs = r["members"] if len(r["members"]) > 1 and "/" not in r["champion"] else [r["champion"]]
        champs = [by_plain.get(plain(n), re.sub(r"/.*$", "", n).strip()) for n in champs]
        entry = {"title": TITLE, "date": r["air"], "champions": champs, "event": r["event"],
                 "place": r["location"], "why": r["notes"][:300], "sources": r["sources"]}
        if r["air"] != r["date"]:
            entry["happened"] = r["date"]
        ev = r["card"]
        if ev:
            # Between this show's matches, by the histories' order of the night.
            night = [x for x in keep if x["air"] == r["air"] and x["card"] is ev]
            k = night.index(r)
            before = [x for x in night[:k] if x.get("carried")]
            after = [x for x in night[k + 1:] if x.get("carried")]
            if before:
                entry["order"] = before[-1]["carried"]["order"] + 0.1 * (k - night.index(before[-1]))
            elif after:
                entry["order"] = after[0]["carried"]["order"] - 0.1 * (night.index(after[0]) - k)
            else:
                # No change of the night is on the card. A defense on it says
                # where it sits: its (c) side holds the belt either going in
                # (the changes came after it) or coming out (before it).
                entering = keep[keep.index(night[0]) - 1]["champion"]
                marks = champ_markers(ev)
                after_card = not marks or any(same(p, entering) for p in marks)
                if not after_card and not any(same(p, night[-1]["champion"]) for p in marks) and k == 0:
                    print(f"  {r['air']}: card defense {marks} fits neither side of {[x['champion'] for x in night]}")
                entry["order"] = (100 if after_card else -10) + 0.1 * k
            entry["event_id"] = ev["id"]
            entry["order"] = round(entry["order"], 2)
        else:
            entry["order"] = sum(1 for c in changes if c["date"] == r["air"] and "event_id" not in c)
        changes.append(entry)

    changes.sort(key=lambda c: (c["date"], c.get("event_id") or 0, c["order"]))
    OUT.write_text(json.dumps({
        "about": "The 24/7 title's changes outside a match: backstage, at ringside, at house shows and away from "
                 "any show. Each is listed by at least two of Wikipedia's List of WWE 24/7 Champions, Duncan and "
                 "Will's title history and WWE.com's. A change on a show we carry names its event and an order "
                 "between that show's matches. Built by lineup-check/title_247.py.",
        "changes": changes}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(keep)} changes two histories agree on, {sum(1 for r in keep if r.get('carried'))} already on our "
          f"cards, {len(changes)} written to {OUT.relative_to(ROOT)}")
    for c in changes:
        if c["date"] != c.get("happened", c["date"]) or c.get("event_id"):
            print(f"  {c['date']} {' & '.join(c['champions'])}: event {c.get('event_id')} order {c['order']}"
                  + (f", happened {c['happened']}" if "happened" in c else ""))


if __name__ == "__main__":
    main()
