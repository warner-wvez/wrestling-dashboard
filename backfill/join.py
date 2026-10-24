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
import itertools
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
from backfill.title_rulings import apply_title_rulings  # noqa: E402

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


def _assign(evs, cands, show_type, tape):
    """Pair one taping's Cagematch shows with Cawthon's episodes: the
    assignment sharing the most people in all, then the one that keeps
    Cagematch's episode numbers in air order. Taken one show at a time, Raw
    #96 (the live 1995-01-23 show, mostly dark matches on Cagematch) took the
    02-06 episode on four shared names and pushed #98 onto 01-23.
    Yields (event, (key, episode or None), shared, candidates, by_order):
    by_order marks a show that shares no one with its episode but is the one
    left when every other show of the taping paired on names and the episode
    numbers stay in air order (Raw #34, the second of three taped 1993-09-27,
    whose 10-04 episode Cawthon describes in a line or two)."""
    if not cands:
        for ev in evs:
            yield ev, (None, None), 0, 0, False
        return
    if show_type in COMPILATION or len(evs) * len(cands) > 36:
        left = list(cands)
        for ev in evs:
            mine = _people(ev)

            def score(item):
                i, e = item
                exact = 1 if (show_type in COMPILATION and e["air_date"] == tape) else 0
                return (len(mine & _ep_people(e)), exact)
            if not left:
                yield ev, (None, None), 0, 0, False
                continue
            best = max(left, key=score)
            n, sc = len(left), score(best)[0]
            if not ((n > 1 and sc == 0) or (show_type in COMPILATION and sc < 2)):
                left.remove(best)           # taken; a rejected episode stays for the next show
            yield ev, best, sc, n, False
        return
    order = sorted(range(len(evs)), key=lambda k: (evs[k].get("episode_number") is None, evs[k].get("episode_number") or 0))
    shared = [[len(_people(evs[k]) & _ep_people(e)) for _, e in cands] for k in range(len(evs))]
    slots = list(range(len(cands))) + [None] * max(0, len(evs) - len(cands))
    best = None
    for perm in itertools.permutations(slots, len(evs)):
        total = sum(shared[k][c] for k, c in zip(range(len(evs)), perm) if c is not None)
        airs = [cands[perm[k]][1]["air_date"] for k in order if perm[k] is not None]
        in_order = sum(1 for a, b in zip(airs, airs[1:]) if a <= b)
        key = (total, in_order)
        if best is None or key > best[0]:
            best = (key, perm)
    perm = best[1]
    placed = [k for k in range(len(evs)) if perm[k] is not None]
    in_order = best[0][1] == len(placed) - 1
    named = [k for k in placed if shared[k][perm[k]] > 0]
    for k, c in enumerate(perm):
        sc = shared[k][c] if c is not None else 0
        by_order = c is not None and sc == 0 and in_order and len(named) == len(placed) - 1 and len(placed) > 1
        yield evs[k], (cands[c] if c is not None else (None, None)), sc, len(cands), by_order


def pair_dates(cm_events, cawthon):
    """Give every TV show Cawthon's air date, pairing tapings by shared people."""
    used, paired, unpaired = set(), [], []
    by_key = defaultdict(list)
    for ev in cm_events:
        by_key[(ev["show_type"], ev["tape_date"] or ev["air_date"])].append(ev)
    for (show_type, tape), evs in by_key.items():
        # A December taping airs into January, on the next year's page.
        slugs = [s for s in (_cawthon_slug(show_type, int(tape[:4]) + k) for k in (0, 1)) if s]
        eps_all = [((s, i), e) for s in slugs for i, e in enumerate(cawthon.get(s, []))]
        if show_type in COMPILATION:
            cands = [(i, e) for i, e in eps_all
                     if i not in used and e.get("air_date") and _days(e["air_date"], tape) <= 10]
        else:
            cands = [(i, e) for i, e in eps_all if e.get("tape_date") == tape and i not in used]
        for ev, (i, ep), shared, n_cands, by_order in _assign(evs, cands, show_type, tape):
            if ep is None or (n_cands > 1 and shared == 0 and not by_order) \
                    or (show_type in COMPILATION and shared < 2):
                unpaired.append(ev)
                continue
            used.add(i)
            ev = dict(ev, air_date=ep["air_date"], tape_date=tape,
                      date_derivation="cawthon-air-date-by-order" if by_order else "cawthon-air-date", cawthon=ep)
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
            # Wikipedia writes "The British Bulldogs (Davey Boy Smith and Dynamite
            # Kid)" and the parser keeps the label beside the members; a label
            # is never a wrestler, so it goes once the members are there.
            label = t.get("team_name")
            parts = [p for p in parts if not (len(parts) >= 3 and (nkey(p) in groups or p == label)
                                              and any(q != p for q in parts))]
            seen, out = set(), []
            for p in parts:
                if p not in seen:
                    seen.add(p); out.append(p)
            t["participants"] = out
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


def _surnames(m):
    return {re.sub(r"^the ", "", p.lower()).split()[-1] for t in m["teams"] for p in t["participants"] if p.strip()}


def take_cagematch_marks(ev, cmev):
    """Wikipedia's results tables write no TITLE CHANGE marker; Cagematch's
    row for the same night writes one on every change. Each single-belt title
    match on a Wikipedia card takes Cagematch's word from the one title line
    that shares the most people with it (a tie decides nothing):
    - marked there: the belt changed hands (`title_change_source`). Not when
      a team wins a singles belt: the mark cannot say which of them took it
      (King of the Ring 2000, The Rock pinned Vince McMahon in a six-man), so
      that takes a ruling in TITLE_RULINGS.
    - not marked, though our line has the champion losing cleanly: a ruling
      that the champion kept it (The Main Event IV 1990, the Rockers' win
      over the Hart Foundation that WWF never recognized)."""
    titled = [c for c in cmev["matches"] if c.get("title_at_stake")]
    for m in ev["matches"]:
        stake = m.get("title_at_stake") or ""
        if not stake or " / " in stake:
            continue
        mine = _surnames(m)
        scored = sorted(((len(mine & _surnames(c)), i) for i, c in enumerate(titled)), reverse=True)
        if not scored or scored[0][0] < min(2, len(mine)) or (len(scored) > 1 and scored[1][0] == scored[0][0]):
            continue
        cm = titled[scored[0][1]]
        champ = [t for t in m["teams"] if t.get("was_champion_entering")]
        won = [t for t in m["teams"] if t.get("was_winner")]
        if "TITLE CHANGE" in (cm.get("raw_description") or "").upper():
            if "tag" in stake.lower() or (len(won) == 1 and len(won[0]["participants"]) == 1):
                m["title_change_source"] = cmev["cagematch_url"]
            continue
        if len(champ) == 1 and len(won) == 1 and won[0] is not champ[0] and won[0].get("match_outcome") == "win":
            m["title_result"] = {"title": stake, "champions": list(champ[0]["participants"]),
                                 "why": "Cagematch marks every title change it records and marks none on this match",
                                 "source": cmev["cagematch_url"]}
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


APPLIED_VOTES = {"fix_result", "fix_result_same_people", "add_match", "add_match_same_people", "fix_lineup"}


def apply_votes(ev, rows, applied, event_key=""):
    """Two sources against the spine: the comparer's vote says the third
    source agrees with the other record, so the card takes that reading
    (the spec's two-sources-agree rule). A winner is swapped, a missing match
    appended, an extra name dropped. Every change lands in `applied` so the
    run report lists it, and the row leaves the sheet."""
    kept = []
    by_order = {m["match_order"]: m for m in ev["matches"]}
    for r in rows:
        vote, cls = r.get("vote"), r.get("class")
        done = False
        if vote in ("fix_result", "fix_result_same_people") and cls == "result" and r.get("match_order") in by_order:
            m = by_order[r["match_order"]]
            his = set(r.get("his_winners") or [])
            if not his:
                c = cawthon_lines([r.get("cawthon") or ""])
                his = set(c[0]["winners"]) if c and c[0].get("result") == "win" else set()
            his = {RING_NAMES.get(n, [n])[0] if n not in _people(ev) and any(x in _people(ev) for x in RING_NAMES.get(n, [])) else n for n in his}
            winner = [t for t in m["teams"] if set(t["participants"]) & his]
            if len(winner) == 1:
                # The finish comes with the winner: Marc Mero beat HHH by
                # count-out on Raw (1996-12-23), and a swap that left the
                # spine's clean "defeats" crowned him Intercontinental champion.
                how = finish_of(r.get("cawthon") or "")["method"]
                kind = {"dq": "dq-", "countout": "countout-"}.get(how, "")
                for t in m["teams"]:
                    t["was_winner"] = t is winner[0]
                    t["match_outcome"] = kind + ("win" if t is winner[0] else "loss")
                if kind:
                    m["result_method"] = {"dq": "by DQ", "countout": "by Count Out"}[how]
                else:
                    m["result_method"] = "defeated" if m.get("result_method") in (None, "No Contest", "Draw", "No Result", "by DQ", "by Count Out") else m["result_method"]
                done = True
        elif vote in ("add_match", "add_match_same_people") and cls == "missing_match":
            sm = r.get("sdh_match")
            if sm and sm.get("teams"):
                new = fresh_match(len(ev["matches"]) + 1, [{"participants": t["participants"], "was_winner": t.get("was_winner")} for t in sm["teams"]],
                                  match_type=sm.get("match_type"), title_at_stake=sm.get("title_at_stake"),
                                  raw_description=r.get("cawthon") or "")
            else:
                c = cawthon_lines([r.get("cawthon") or ""])
                new = cawthon_match(c[0], len(ev["matches"]) + 1) if c else None
            if new and any(t["participants"] for t in new["teams"]):
                ev["matches"].append(new)
                by_order[new["match_order"]] = new
                done = True
        elif vote == "fix_lineup" and cls == "extra_name" and r.get("name") and r.get("match_order") in by_order:
            m = by_order[r["match_order"]]
            for t in m["teams"]:
                if t.get("team_number") == r.get("team_number") and r["name"] in t["participants"] and len(t["participants"]) > 1:
                    t["participants"] = [x for x in t["participants"] if x != r["name"]]
                    t["team_name"] = " & ".join(t["participants"])
                    done = True
        if done:
            applied.append({"event_key": r.get("event_key") or event_key, "match_order": r.get("match_order", ""), "class": cls,
                            "vote": vote, "ours": r.get("ours", ""), "other": r.get("cawthon", ""), "third": r.get("sdh", "")})
        else:
            kept.append(r)
    ev["match_count"] = len(ev["matches"])
    return kept


def _reclass_results(rows, ev):
    """A result row only means "same match, different winner" when the other
    source's line names everyone on our match; otherwise the pairing crossed
    two matches that share a person, and that is a lineup difference."""
    people = {m["match_order"]: {p.lower() for t in m["teams"] for p in t["participants"]} for m in ev["matches"]}
    for r in rows:
        if r.get("class") == "result" and r.get("match_order") in people:
            his = (r.get("cawthon") or "").lower()
            if not all(n in his for n in people[r["match_order"]]):
                r["class"] = "different_opponent"
    return rows


def _review_rows(rows, event_key):
    out = []
    for r in rows:
        r["event_key"] = event_key
        if r.get("class") in REVIEW_CLASSES | {"date_unconfirmed", "date_split"} and r.get("vote") not in AUTO_VOTES:
            out.append(r)
    return out


def join_all(cm, cawthon, wiki, sdh, fandom, rulings=frozenset()):
    cards, review, applied = [], [], []
    report = {"by_status": Counter(), "by_family": Counter(), "unpaired_dates": 0,
              "out_of_range": 0, "no_match": 0, "ruled": 0, "same_night_arenas": 0}
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
            # that differs on the very same people is a disagreement here.
            ours = [{p for t in m["teams"] for p in t["participants"]} for m in ev["matches"]]
            same = [ln for ln in as_lines(vote["matches"]) if set(ln["winners"] + ln["losers"]) in ours]
            rows = [r for r in compare_show(ev, same, groups) if r.get("class") == "result"]
            ev["verification_status"] = bucket(rows)
            ev["cagematch_nr"], ev["cagematch_url"], ev["logo"] = vote["cagematch_nr"], vote["cagematch_url"], vote["logo"]
            # A recap show airs matches from many tapings, so it has no one
            # taping night (the vote's own night can fall after the broadcast).
            ev["tape_date"] = None
            ev["venue"], ev["city"] = vote.get("venue"), vote.get("city")
            ev["state_province"], ev["country"] = vote.get("state_province"), vote.get("country")
        else:
            rows = []
            ev["verification_status"] = "single-source"
        review += _review_rows(_reclass_results(rows, ev), key)
        cards.append(_strip(ev))
    for ev in paired + unpaired:
        ev = dict(ev)
        ep = ev.get("cawthon")
        key = f"{ev['show_type']}|{ev['air_date']}|{ev.get('cagematch_nr')}"
        year = ev["air_date"][:4]
        # A late-December taping airs on next year's page.
        sdh_eps = [e for y in (int(year), int(year) + 1)
                   for e in sdh.get(SDH_SLUG[ev["show_type"]].format(y=y), [])] if ev["show_type"] in SDH_SLUG else []
        sdh_match = next((e for e in sdh_eps if e["date"] == ev["air_date"]), None)
        if ep is None and sdh_match is None and sdh_eps:
            # No Cawthon episode: SmackDown Hotel's episode within a week that
            # shares two people dates the show (Heat 2000 tapes days ahead).
            mine = _people(ev)
            # A show airs on or after its taping, never before it.
            near = [(len(mine & {p for m in e["matches"] for t in m["teams"] for p in t.get("participants") or []}), e)
                    for e in sdh_eps
                    if 0 <= (date.fromisoformat(e["date"]) - date.fromisoformat(ev["air_date"])).days <= 7]
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
            rows = apply_votes(ev, _reclass_results(rows, ev), applied, key)
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
        review += _review_rows(_reclass_results(rows, ev), key)
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
            take_cagematch_marks(ev, cmev)
            caw_lines = with_ring_names(caw_lines, _people(ev))
            rows = compare_show(ev, as_lines(cmev["matches"]), groups, sdh_matches=as_matches(caw_lines) or None)
            rows = apply_votes(ev, _reclass_results(rows, ev), applied,
                               f"{art['show_type']}|{ev['air_date']}|{cmev['cagematch_nr']}")
            ev["verification_status"] = bucket(rows)
            if caw_lines:
                _fill_from_cawthon(ev, caw_lines)
            review += _review_rows(_reclass_results(rows, ev), f"{art['show_type']}|{ev['air_date']}|{cmev['cagematch_nr']}")
            cards.append(_strip(ev))
    # PPV and SNME rows Wikipedia has no card for (Friday Night's Main Event
    # 1997, a special the list skips) stand on Cagematch alone, never dropped.
    # A row on the same night as a claimed Wikipedia card of the same kind is
    # that card's other arena (Cagematch files WrestleMania 2 as three shows),
    # not a second show: counted, not shipped.
    wiki_nights = {(c["show_type"], c["air_date"]) for c in cards if c["primary_source"] == "wikipedia"}
    for e in in_range:
        if e["show_type"] in ("PPV", "SNME") and e["cagematch_nr"] not in taken and e["cagematch_nr"] not in held:
            if (e["show_type"], e["air_date"]) in wiki_nights or (e["show_type"], e.get("tape_date")) in wiki_nights:
                report["same_night_arenas"] += 1
                continue
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
    report["applied_votes"] = len(applied)
    report["_applied"] = applied
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
    report["title_rulings"] = apply_title_rulings(cards)
    cards.sort(key=lambda c: (c["air_date"], c["show_type"], c.get("cagematch_nr") or 0))
    write_json(OUT / "cards.json", cards)
    cols = ["event_key", "air_date", "show_type", "title", "class", "vote", "match_order", "ours", "cawthon", "sdh"]
    with (OUT / "review.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(review, key=lambda r: (r.get("class", ""), r.get("air_date", ""))):
            w.writerow({k: r.get(k, "") for k in cols})
    applied = report.pop("_applied", [])
    with (OUT / "applied_votes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["event_key", "match_order", "class", "vote", "ours", "other", "third"])
        w.writeheader()
        w.writerows(applied)
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
