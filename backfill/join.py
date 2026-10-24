#!/usr/bin/env python3
"""Pair every spine show with its votes and bucket it.

Spines: the Cagematch cards for every TV family (backfill/out/cm_cards.json),
Wikipedia for PPV and SNME (wiki_cards.json). Votes: Cawthon (cawthon_cards.json,
also the air-date authority for TV), SmackDown Hotel (sdh_cards.json, Raw 1993
on, SmackDown, Heat), Fandom (fandom_cards.json, Raw and SmackDown), and for
PPV and SNME the Cagematch card itself plus Cawthon's pay-per-view section.

Dates. Cagematch dates the taping night. A TV show pairs with the Cawthon
episode of the same family whose taped (header) date equals the Cagematch
date; when one taping carries several episodes (Superstars taped three at a
time), each pairs with the episode sharing the most people. The studio shows
(Prime Time, All-American, Mania) have no taping in Cawthon, so they pair on
the air date, or on shared people within ten days. The paired show takes
Cawthon's air date. A PPV or SNME ships only when Wikipedia's night equals a
Cagematch row's date (SNME rows carry the taping, so either night counts).

Matches. lineup_match.compare_show pairs matches by shared people and
classes every difference; the SmackDown Hotel or Fandom card is passed as
its third vote. A show is "verified" when no row needs a person, "flagged"
when one does (the spine's card ships, the rows go to review.csv), and
"single-source" when no vote exists at all. Rows a person has already ruled
on (out/rulings.csv: event_key, ruling, source_url) are left off the sheet.

Outputs: cards.json (bundle-shaped events), review.csv, join_report.json.

    uv run --with requests --with beautifulsoup4 python backfill/join.py
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "lineup-check")):
    if p not in sys.path:
        sys.path.insert(0, p)
from lineup_match import MULTI_MATCH, compare_show, group_members  # noqa: E402
import src.fandom_scraper as fs  # noqa: E402
from cawthon_parse import finish_of, parse_match_line  # noqa: E402
from backfill.common import OUT, YEARS, fresh_event, fresh_match, read_json, record_status, write_json  # noqa: E402

SLUG_OF = {"Raw": "wwf-raw-{y}", "SmackDown": "wwf-smackdown-{y}", "Superstars": "wwf-superstars-{y}",
           "Challenge": "wwf-wrestling-challenge-{y}", "PrimeTime": "wwf-prime-time-wrestling-{y}",
           "AllAmerican": "wwf-all-american-wrestling-{y}", "Heat": "wwf-sunday-night-heat-{y}",
           "Shotgun": "wwf-shotgun-{y}", "Mania": "wwf-mania", "SundaySlam": "wwf-sunday-night-slam"}
# The studio shows: Cawthon lists what each broadcast aired (matches taped
# at several arenas), Cagematch lists the taping's own exclusives, so the two
# are different records. Cawthon is the spine here and a Cagematch row that
# pairs is the vote.
COMPILATION = {"PrimeTime", "AllAmerican", "Mania"}
COMPILATION_TITLE = {"PrimeTime": "WWF Prime Time Wrestling", "AllAmerican": "WWF All American Wrestling",
                     "Mania": "WWF Mania"}
# Cawthon names the man where Cagematch bills the gimmick of the week. A
# Cawthon name is swapped for the ring name only when the card has the ring
# name and lacks the man's name, so the swap can never fuse two people.
RING_NAMES = {"Davey Boy Smith": ["The British Bulldog"], "Billy Gunn": ["Mr. Ass", "Rockabilly"],
              "Kerry Von Erich": ["The Texas Tornado"], "Ricky Steamboat": ["The Dragon"],
              "Tito Santana": ["El Matador"], "Chris Candido": ["Skip"], "Bob Holly": ["Sparky Plugg"],
              "Sparky Plugg": ["Bob Holly"], "Terry Funk": ["Chainsaw Charlie"], "Mick Foley": ["Mankind", "Cactus Jack", "Dude Love"],
              "Glenn Jacobs": ["Isaac Yankem", "Kane"], "Steve Austin": ["The Ringmaster"]}
METHOD_OF = {"pin": "defeated", "submission": "by Submission", "dq": "by DQ", "countout": "by Count Out",
             "ko": "by KO", "win": "defeated", "no-contest": "No Contest", "draw": "Draw"}
SDH_SLUG = {"Raw": "raw-{y}", "SmackDown": "smackdown-{y}", "Heat": "heat-{y}"}
REVIEW_CLASSES = {"result", "missing_match", "unpaired", "extra_name", "different_opponent",
                  "cawthon_only_name", "possible_second_bout", "dark_but_televised", "cawthon_says_dark"}
AUTO_VOTES = {"keep", "aired", "not_aired", "add_wrestler"}
NO_DECISION = {"time limit draw": "draw", "draw": "draw", "double dq": "no contest",
               "double count out": "no contest", "double countout": "no contest", "double count": "no contest",
               "double pinfall": "no contest", "double pin": "no contest", "no contest": "no contest",
               "no result": "no contest"}


def _people(ev):
    return {p for m in ev["matches"] for t in m["teams"] for p in t["participants"]}


def _cawthon_slug(show_type, year):
    tmpl = SLUG_OF.get(show_type)
    if not tmpl:
        return None
    if show_type == "Raw" and year == 1994:
        return "wwf-raw-1994-results"
    return tmpl.format(y=year)


def _ep_people(ep):
    return {n for m in ep["matches"] for n in m["winners"] + m["losers"]}


def _days(a, b):
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def pair_dates(cm_events, cawthon):
    """Give every TV show Cawthon's air date, pairing tapings by shared people."""
    used, paired, unpaired = set(), [], []
    by_key = defaultdict(list)
    for ev in cm_events:
        by_key[(ev["show_type"], ev["tape_date"] or ev["air_date"])].append(ev)
    for (show_type, tape), evs in by_key.items():
        slug = _cawthon_slug(show_type, int(tape[:4]))
        eps_all = cawthon.get(slug, []) if slug else []
        if show_type in COMPILATION:
            cands = [(i, e) for i, e in enumerate(eps_all)
                     if (slug, i) not in used and e.get("air_date") and _days(e["air_date"], tape) <= 10]
        else:
            cands = [(i, e) for i, e in enumerate(eps_all) if e.get("tape_date") == tape and (slug, i) not in used]
        for ev in evs:
            if not cands:
                unpaired.append(ev)
                continue
            mine = _people(ev)

            def score(item):
                i, e = item
                shared = len(mine & _ep_people(e))
                exact = 1 if (show_type in COMPILATION and e["air_date"] == tape) else 0
                return (shared, exact)
            i, ep = max(cands, key=score)
            shared, exact = score((i, ep))
            if (len(cands) > 1 and shared == 0) or (show_type in COMPILATION and shared < 2):
                unpaired.append(ev)
                continue
            cands.remove((i, ep))
            used.add((slug, i))
            ev = dict(ev, air_date=ep["air_date"], tape_date=tape,
                      date_derivation="cawthon-air-date", cawthon=ep)
            if not ev.get("city") and ep.get("city"):
                ev["city"] = ep["city"].split(",")[0].strip()
            paired.append(ev)
    return paired, unpaired


def cawthon_match(c, order):
    """One of Cawthon's parsed lines -> a bundle match (the spine for studio shows)."""
    decided = c.get("result") == "win"
    teams = [{"participants": c["winners"], "was_winner": True if decided else None}]
    if c.get("losers"):
        teams.append({"participants": c["losers"], "was_winner": False if decided else None})
    method = METHOD_OF.get(c.get("method", "win"), "defeated") if decided else METHOD_OF.get(c.get("result"), "No Contest")
    return fresh_match(order, teams, duration_seconds=c.get("duration_seconds"), result_method=method,
                       raw_description=c.get("line", ""))


def compilation_spine(cawthon):
    """Studio-show episodes as events, from Cawthon: {(show_type, air_date): event}."""
    out = {}
    for show_type in COMPILATION:
        slugs = [k for k in cawthon if k.startswith(SLUG_OF[show_type].split("{")[0])]
        for slug in slugs:
            for ep in cawthon[slug]:
                if not ep.get("matches") or int(ep["air_date"][:4]) not in YEARS:
                    continue
                matches = [cawthon_match(c, k) for k, c in enumerate(ep["matches"], 1)]
                out[(show_type, ep["air_date"])] = fresh_event(
                    air_date=ep["air_date"], date_derivation="cawthon-air-date", show_type=show_type,
                    title=COMPILATION_TITLE[show_type], primary_source="cawthon", matches=matches)
    return out


def label_multi(ev):
    """Wikipedia writes a battle royal as "X won by last eliminating Y" with a
    type the comparer does not read as multi-man; name it so only the winner
    is compared, never the lineup."""
    for m in ev["matches"]:
        stip = (m.get("stipulation") or "") + " " + (m.get("raw_description") or "")
        if not MULTI_MATCH.search(m.get("match_type") or "") and re.search(r"battle royal|last eliminating|rumble", stip, re.I):
            m["match_type"] = ((m.get("match_type") or "") + " Battle Royal").strip()
    return ev


def as_lines(matches):
    """Bundle matches -> the dicts compare_show expects as cawthon_lines. Dark
    matches stay out: a vote never lists what did not air."""
    out = []
    for m in matches:
        if m.get("aired") is False:
            continue
        teams = m["teams"]
        win = [p for t in teams if t.get("was_winner") for p in t["participants"]]
        lose = [p for t in teams if not t.get("was_winner") for p in t["participants"]]
        method = (m.get("result_method") or "").lower()
        result = "win" if win else NO_DECISION.get(method, "no contest")
        out.append({"kind": "match", "winners": win or lose, "losers": lose if win else [],
                    "result": result, "sub_for": [], "notes": [],
                    "all_sides": not win, "line": m.get("raw_description") or ""})
    return out


def cawthon_lines(items):
    """Cawthon's PPV sections arrive as raw prose lines; his TV episodes as
    parsed dicts. Either way, parsed dicts with finish_of's two keys come out."""
    out = []
    for c in items:
        if isinstance(c, dict):
            out.append(c)
            continue
        m = parse_match_line(c)
        if m:
            m.update(finish_of(c))
            out.append(m)
    return out


def with_ring_names(lines, card_people):
    """Cawthon's lines with each man's name swapped for the ring name the card uses."""
    out = []
    for c in lines:
        c = dict(c)
        for side in ("winners", "losers"):
            names = []
            for n in c.get(side, []):
                ring = next((r for r in RING_NAMES.get(n, []) if r in card_people), None)
                names.append(ring if ring and n not in card_people else n)
            c[side] = names
        out.append(c)
    return out


def expand_groups(ev, groups):
    """A participant that is only a team label ("The British Bulldogs") becomes
    the members our Cagematch rows list for that label nearest that night."""
    from lineup_match import _nearest, nkey
    for m in ev["matches"]:
        for t in m["teams"]:
            parts = []
            for p in t["participants"]:
                key = nkey(p)
                if key in groups and p not in parts:
                    parts.extend(_nearest(groups[key], ev["air_date"]))
                else:
                    parts.append(p)
            t["participants"] = parts
    return ev


_TITLE_WORD = re.compile(r"\b(?:Championship|Title)s?\b", re.I)


def clean_stakes(ev):
    """Wikipedia's stipulation column leaves referees and notes on the title
    string ("WWF Championship / Mr. Perfect / special guest referee", "vacant /
    WWF Championship"). Keep the belt parts only; a bare belt name gets its word
    back ("WWF Intercontinental / WWF European")."""
    for m in ev["matches"]:
        t = m.get("title_at_stake")
        if not t or " / " not in t:
            continue
        keep = []
        for part in [x.strip() for x in t.split(" / ")]:
            if _TITLE_WORD.search(part):
                keep.append(part)
            elif part.startswith(("WWF ", "WWE ")) and len(part.split()) >= 2 and not re.search(r"special|referee|enforcer|vacant", part, re.I):
                keep.append(part + " Championship")
        m["title_at_stake"] = " / ".join(keep) or None
    return ev


def as_matches(lines):
    """Cawthon line dicts -> the bundle-like matches compare_show takes as a third vote."""
    out = []
    for c in lines:
        if c.get("result") == "win":
            teams = [{"participants": c["winners"], "was_winner": True},
                     {"participants": c["losers"], "was_winner": False}]
        else:
            teams = [{"participants": c["winners"], "was_winner": None},
                     {"participants": c["losers"], "was_winner": None}]
        out.append({"match_type": None, "title_at_stake": None, "teams": [t for t in teams if t["participants"]]})
    return out


def bucket(rows):
    for r in rows:
        if r.get("class") in REVIEW_CLASSES and r.get("vote") not in AUTO_VOTES:
            return "flagged"
    return "verified"


def _fill_from_cawthon(ev, lines):
    """Durations from Cawthon's lines where Cagematch had none."""
    for m in ev["matches"]:
        if m.get("duration_seconds"):
            continue
        mine = {p for t in m["teams"] for p in t["participants"]}
        best = max(lines, key=lambda c: len(mine & set(c["winners"] + c["losers"])), default=None)
        if best and len(mine & set(best["winners"] + best["losers"])) >= 1 and best.get("duration_seconds"):
            m["duration_seconds"] = best["duration_seconds"]


def _strip(ev):
    ev = dict(ev)
    for k in ("workers", "cm_type", "cawthon"):
        ev.pop(k, None)
    for m in ev["matches"]:
        m.pop("workers", None)
        if m.get("aired", True):
            m.pop("aired", None)            # the corpus marks only the dark ones
    ev["match_count"] = len(ev["matches"])
    return ev


def _review_rows(rows, event_key):
    out = []
    for r in rows:
        r["event_key"] = event_key
        if r.get("class") in REVIEW_CLASSES | {"date_unconfirmed", "date_split"} and r.get("vote") not in AUTO_VOTES:
            out.append(r)
    return out


def join_all(cm, cawthon, wiki, sdh, fandom, rulings=frozenset()):
    cards, review = [], []
    report = {"by_status": Counter(), "by_family": Counter(), "unpaired_dates": 0,
              "out_of_range": 0, "no_match": 0, "ruled": 0}
    in_range = []
    for e in cm:
        if int(e["air_date"][:4]) not in YEARS:
            report["out_of_range"] += 1
        elif not e["matches"]:
            report["no_match"] += 1
        else:
            in_range.append(e)
    groups = group_members({str(i): e for i, e in enumerate(in_range)}, fs._STABLE_RE, fs._split_depth0)
    tv = [e for e in in_range if e["show_type"] not in ("PPV", "SNME") and e["show_type"] not in COMPILATION]
    paired, unpaired = pair_dates(tv, cawthon)
    report["unpaired_dates"] = len(unpaired)
    # Studio shows: Cawthon's broadcast is the spine; a Cagematch taping row that
    # pairs (same air date, or shared people within ten days) is its vote.
    studio = compilation_spine(cawthon)
    cm_studio = [e for e in in_range if e["show_type"] in COMPILATION]
    studio_paired, studio_unpaired = pair_dates(cm_studio, cawthon)
    report["studio_tapings_unpaired"] = len(studio_unpaired)
    studio_votes = {(e["show_type"], e["air_date"]): e for e in studio_paired}
    for (show_type, day), ev in sorted(studio.items()):
        key = f"{show_type}|{day}|cawthon"
        ev["id"] = 0
        vote = studio_votes.get((show_type, day))
        if vote:
            # The taping lists other matches than the broadcast; only a result
            # that differs on the same people is a disagreement here.
            rows = [r for r in compare_show(ev, as_lines(vote["matches"]), groups) if r.get("class") == "result"]
            ev["verification_status"] = bucket(rows)
            ev["cagematch_nr"], ev["cagematch_url"], ev["logo"] = vote["cagematch_nr"], vote["cagematch_url"], vote["logo"]
            ev["tape_date"] = vote["tape_date"] if vote["tape_date"] != day else None
            ev["venue"], ev["city"] = vote.get("venue"), vote.get("city")
            ev["state_province"], ev["country"] = vote.get("state_province"), vote.get("country")
        else:
            rows = []
            ev["verification_status"] = "single-source"
        review += _review_rows(rows, key)
        cards.append(_strip(ev))
    for ev in paired + unpaired:
        ev = dict(ev)
        ep = ev.get("cawthon")
        key = f"{ev['show_type']}|{ev['air_date']}|{ev.get('cagematch_nr')}"
        year = ev["air_date"][:4]
        sdh_eps = sdh.get(SDH_SLUG.get(ev["show_type"], "").format(y=year), []) if ev["show_type"] in SDH_SLUG else []
        sdh_match = next((e for e in sdh_eps if e["date"] == ev["air_date"]), None)
        if ep is None and sdh_match is None and sdh_eps:
            # No Cawthon episode: SmackDown Hotel's episode within a week that
            # shares two people dates the show (Heat 2000 tapes days ahead).
            mine = _people(ev)
            near = [(len(mine & {p for m in e["matches"] for t in m["teams"] for p in t.get("participants") or []}), e)
                    for e in sdh_eps if _days(e["date"], ev["air_date"]) <= 7]
            best = max(near, key=lambda x: x[0], default=(0, None))
            if best[0] >= 2:
                sdh_match = best[1]
                ev["tape_date"], ev["air_date"], ev["date_derivation"] = ev["air_date"], sdh_match["date"], "sdh-air-date"
                key = f"{ev['show_type']}|{ev['air_date']}|{ev.get('cagematch_nr')}"
        fan = fandom.get(f"{ev['show_type']}|{ev['air_date']}")
        third = (sdh_match or {}).get("matches") or (fan or {}).get("matches")
        ev["id"] = ev.get("id") or 0
        if ep:
            rows = compare_show(ev, with_ring_names(ep["matches"], _people(ev)), groups, sdh_matches=third)
            ev["verification_status"] = bucket(rows)
            _fill_from_cawthon(ev, ep["matches"])
        elif third:
            rows = compare_show(ev, as_lines(third), groups)
            ev["verification_status"] = bucket(rows)
        else:
            rows = []
            ev["verification_status"] = "single-source"
        if not ep and ev["date_derivation"] != "sdh-air-date":
            rows.append({"class": "date_unconfirmed", "vote": "split", "air_date": ev["air_date"],
                         "show_type": ev["show_type"], "title": ev["title"], "ours": "", "cawthon": ""})
        review += _review_rows(rows, key)
        cards.append(_strip(ev))
    cm_main = defaultdict(list)
    for e in in_range:
        if e["show_type"] in ("PPV", "SNME"):
            for d in {e["air_date"], e.get("tape_date")}:
                if d:
                    cm_main[(e["show_type"], d)].append(e)
    taken, held = set(), set()
    for art in wiki:
        for ev in art["events"]:
            cands = [c for d in {ev["air_date"], ev.get("tape_date")} if d
                     for c in cm_main.get((art["show_type"], d), []) if c["cagematch_nr"] not in taken]
            if not cands:
                near = [c for c in in_range if c["show_type"] == art["show_type"]
                        and _days(c["air_date"], ev["air_date"]) <= 3]
                held.update(c["cagematch_nr"] for c in near)      # a date split holds both sides
                review.append({"class": "date_split", "vote": "split", "event_key": f"{art['show_type']}|{ev['air_date']}|wiki",
                               "air_date": ev["air_date"], "show_type": art["show_type"], "title": ev["title"],
                               "ours": art["title"], "cawthon": ", ".join(f"{c['title']} {c['air_date']}" for c in near)})
                continue
            cmev = max(cands, key=lambda c: len(_people(c) & _people(ev)))
            taken.add(cmev["cagematch_nr"])
            ev = dict(ev, cagematch_nr=cmev["cagematch_nr"], cagematch_url=cmev["cagematch_url"],
                      logo=cmev["logo"], venue=ev.get("venue") or cmev.get("venue"),
                      city=ev.get("city") or cmev.get("city"),
                      state_province=ev.get("state_province") or cmev.get("state_province"),
                      country=ev.get("country") or cmev.get("country"),
                      episode_number=cmev.get("episode_number"), family="main",
                      primary_source="wikipedia", id=0)
            caw = cawthon.get(f"wwf-results-{ev['air_date'][:4]}", {}).get(ev["air_date"]) if art["show_type"] == "PPV" else None
            caw_lines = cawthon_lines(caw["ppv"]) if caw and caw.get("ppv") else []
            label_multi(expand_groups(clean_stakes(ev), groups))
            caw_lines = with_ring_names(caw_lines, _people(ev))
            rows = compare_show(ev, as_lines(cmev["matches"]), groups, sdh_matches=as_matches(caw_lines) or None)
            ev["verification_status"] = bucket(rows)
            if caw_lines:
                _fill_from_cawthon(ev, caw_lines)
            review += _review_rows(rows, f"{art['show_type']}|{ev['air_date']}|{cmev['cagematch_nr']}")
            cards.append(_strip(ev))
    # PPV and SNME rows Wikipedia has no card for (Friday Night's Main Event
    # 1997, a special the list skips) stand on Cagematch alone, never dropped.
    for e in in_range:
        if e["show_type"] in ("PPV", "SNME") and e["cagematch_nr"] not in taken and e["cagematch_nr"] not in held:
            ev = dict(e, id=0, verification_status="single-source")
            cards.append(_strip(ev))
    if rulings:
        before = len(review)
        review = [r for r in review if r["event_key"] not in rulings
                  and f"{r['event_key']}|{r.get('match_order')}" not in rulings]
        report["ruled"] = before - len(review)
    for c in cards:
        report["by_status"][c["verification_status"]] += 1
        report["by_family"][c["show_type"]] += 1
    return cards, review, report


def _load(name, default):
    p = OUT / name
    return read_json(p) if p.exists() else default


def main():
    cm = read_json(OUT / "cm_cards.json")
    cawthon, wiki, sdh, fandom = _load("cawthon_cards.json", {}), _load("wiki_cards.json", []), \
        _load("sdh_cards.json", {}), _load("fandom_cards.json", {})
    rulings = set()
    if (OUT / "rulings.csv").exists():
        with (OUT / "rulings.csv").open(encoding="utf-8") as f:
            rulings = {r["event_key"] for r in csv.DictReader(f)}
    cards, review, report = join_all(cm, cawthon, wiki, sdh, fandom, rulings)
    cards.sort(key=lambda c: (c["air_date"], c["show_type"], c.get("cagematch_nr") or 0))
    write_json(OUT / "cards.json", cards)
    cols = ["event_key", "air_date", "show_type", "title", "class", "vote", "match_order", "ours", "cawthon", "sdh"]
    with (OUT / "review.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(review, key=lambda r: (r.get("class", ""), r.get("air_date", ""))):
            w.writerow({k: r.get(k, "") for k in cols})
    report["by_status"] = dict(report["by_status"])
    report["by_family"] = dict(report["by_family"])
    report["review_rows"] = len(review)
    report["review_by_class"] = dict(Counter(r.get("class") for r in review))
    write_json(OUT / "join_report.json", report)
    for k, v in report.items():
        print(f"  {k}: {v}")
    print(f"{len(cards)} cards, {len(review)} review rows -> {OUT / 'review.csv'}")
    record_status("join", True, f"{len(cards)} cards, {len(review)} review rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
