"""Pair our cards with Cawthon's, show by show, and sort every difference.

Shows join on air date + show type. Inside a show, matches pair by how many
people they share, after Cawthon's spellings are resolved to ours. Each
difference lands in one class:

  auto, applied by migration 0004:
    not_aired     our source labels it a dark match and his televised list
                  does not have it (both agree it never aired)
    aired_heat    our PPV match pairs with his Sunday Night Heat pre-show
    add_wrestler  he names a wrestler our paired side lacks, and our own match
                  text names him too (our parse lost him)

  review, for Warner to rule:
    extra_name     a name on our side that his fully resolved side lacks
    result         winner or finish differs
    missing_match  a televised match of his with no partner on our card
    unpaired       our match is not on his televised list, but our source
                   does not call it a dark match
    dark_but_televised  our source says dark, his televised list has it
    missing_show   an episode one source has and the other does not
    date_conflict  his page contradicts itself about the date
"""
import re
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher

# Cawthon spellings that fuzzy matching cannot reach, as name keys.
NAME_ALIASES = {
    "farooq": "faarooq",
    "jackie": "jacqueline",
    "mikemizanin": "miz",
    "evenbourne": "evanbourne",
    "acolytes": "apa",
    "bullbuchanon": "bullbuchanan",
}
# One wrestler under two ring names the alias map does not know: Bull Buchanan
# wrestled as B-2 (B\u00b2) in 2002-03.
ERA_NAMES = {"B\u00b2": "Bull Buchanan", "B-2": "Bull Buchanan"}
# The dashboard's own alias map (ring-name changes, respellings), set by the
# caller from src.roster_aliases: name -> canonical name.
CANON = {}
MULTI_TYPES = re.compile(r"rumble|battle royal|gauntlet|elimination chamber|royal", re.I)


def nkey(name):
    n = re.sub(r"^the\s+", "", (name or "").strip().lower())
    n = re.sub(r"[^a-z0-9]", "", n)
    return NAME_ALIASES.get(n, n)


def _tokens(name):
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split() if t != "the"]


def match_strength(a, b):
    """How sure two spellings are one person: 3 equal keys, 2 one name's
    words inside the other's ('Funaki' / 'Sho Funaki', 'Stephanie McMahon' /
    'Stephanie McMahon-Helmsley'), 1 a near spelling ('K-Kwick' / 'K-Kwik'),
    0 different people."""
    ka, kb = nkey(a), nkey(b)
    if not ka or not kb:
        return 0
    if ka == kb or (CANON.get(a, a) == CANON.get(b, b)) or \
            nkey(ERA_NAMES.get(a, a)) == nkey(ERA_NAMES.get(b, b)):
        return 3
    # Initials: "MVP" is Montel Vontavious Porter.
    for short, long_ in ((a, b), (b, a)):
        words = _tokens(long_)
        if short.isupper() and len(short) >= 2 and len(words) == len(short) and \
                "".join(w[0] for w in words) == short.lower():
            return 3
    ta, tb = set(_tokens(a)), set(_tokens(b))
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if small and small <= big and max(len(t) for t in small) >= 4:
        return 2
    if len(ka) >= 5 and SequenceMatcher(None, ka, kb).ratio() >= 0.88:
        return 1
    return 0


def best_match(name, candidates):
    """Our spelling for one of his names, or None. The strongest candidate
    wins, so 'Stephanie McMahon' never lands on 'Shane McMahon' when
    'Stephanie McMahon-Helmsley' is on the card; a tie between two different
    people is no answer at all."""
    scored = sorted(((match_strength(name, c), c) for c in candidates), reverse=True)
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0] and scored[1][1] != scored[0][1]:
        return None
    return scored[0][1]


def group_members(events, stable_re, split_depth0):
    """{label key: [(air_date, [members])]} from every 'Label ( A & B )' in our
    stored match text, so a group Cawthon names without members ('the
    Acolytes') can be expanded the way our source wrote it that year."""
    out = defaultdict(list)
    for ev in events.values():
        for m in ev.get("matches") or []:
            raw = re.sub(r"\(\s*w\s*/[^()]*\)", " ", m.get("raw_description") or "")
            for side in re.split(r"\s+(?:defeat(?:s|ed)?|vs\.?)\s+", raw):
                for tok in split_depth0(side):
                    g = stable_re.match(tok)
                    if g:
                        members = split_depth0(g.group(2))
                        if len(members) >= 2:
                            out[nkey(g.group(1))].append((ev["air_date"], members))
    return out


def _nearest(entries, day):
    return min(entries, key=lambda e: abs((date.fromisoformat(e[0]) - date.fromisoformat(day)).days))[1]


def resolve_side(names, show_names, groups, day):
    """Cawthon's names for one side -> (explicit, expanded, unresolved).
    explicit: our spelling of a name he wrote out; expanded: members of a
    group he named; unresolved: names we cannot place on our card. A bare
    first name borrows the side's shared surname ('Bubba Ray, D-Von, & Spike
    Dudley')."""
    explicit, expanded, unresolved = [], [], []
    surname = names[-1].split()[-1] if names and len(names[-1].split()) >= 2 else None
    for n in names:
        tries = [n] + ([f"{n} {surname}"] if surname and not n.endswith(surname) else [])
        hit = next((h for h in (best_match(t, show_names) for t in tries) if h), None)
        if hit:
            explicit.append(hit)
            continue
        key = nkey(n)
        if key in groups:
            for mem in _nearest(groups[key], day):
                expanded.append(best_match(mem, show_names) or mem)
            continue
        unresolved.append(n)
    return explicit, expanded, unresolved


def _people(match):
    return [p for t in match.get("teams") or [] for p in t.get("participants") or [] if p]


def _score(c_names, o_names):
    common = len(set(c_names) & set(o_names))
    if not common:
        return 0.0
    return common / min(len(set(c_names)), len(set(o_names)))


def compare_show(ev, cawthon_lines, groups, heat_lines=(), unreadable=0, sdh_matches=None):
    """Rows for one show. ev is our event (with matches); cawthon_lines are
    parsed match dicts from his televised list; heat_lines from his PPV
    pre-show section; unreadable counts his lines that read like a result
    but did not parse, which blocks any not_aired call on this show."""
    ours = [m for m in ev.get("matches") or [] if m.get("teams")]
    show_names = sorted({p for m in ours for p in _people(m)})
    day = ev["air_date"]

    def prep(lines):
        out = []
        for c in lines:
            if c.get("all_sides"):
                # Everyone on one list with no winner: compare people only.
                w = resolve_side(c["winners"], show_names, groups, day)
                out.append({"c": c, "w": w, "l": ([], [], []), "names": w[0] + w[1]})
                continue
            w = resolve_side(c["winners"], show_names, groups, day)
            l = resolve_side(c["losers"], show_names, groups, day)
            out.append({"c": c, "w": w, "l": l,
                        "names": w[0] + w[1] + l[0] + l[1]})
        return out

    # His own "Dark match after the taping" lines are not televised.
    dark = prep([c for c in cawthon_lines if c["line"].lower().startswith("dark match")])
    tv = prep([c for c in cawthon_lines if not c["line"].lower().startswith("dark match")])
    heat = prep(heat_lines)

    def both_ways(names, o, floor_min=0.5, floor_max=0.34):
        """Shares enough people both ways round: a 4-way is never "the same
        match" as a singles bout that happens to share one wrestler."""
        a, b = set(names), set(_people(o))
        common = len(a & b)
        if not common:
            return 0.0
        s_min, s_max = common / min(len(a), len(b)), common / max(len(a), len(b))
        return s_min if s_min >= floor_min and s_max >= floor_max else 0.0

    pairs = []
    for i, o in enumerate(ours):
        for j, c in enumerate(tv):
            if c["c"]["kind"] == "multi":
                s = 1.0 if (MULTI_TYPES.search(o.get("match_type") or "") and
                            set(c["names"]) & set(_people(o))) else 0.0
            else:
                s = both_ways(c["names"], o)
            if s:
                pairs.append((s, i, j))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    o_of, c_of = {}, {}
    for s, i, j in pairs:
        if i not in o_of and j not in c_of:
            o_of[i], c_of[j] = j, i
    # Second pass for leftovers, still both ways round but looser, so a match
    # with one unplaceable name is compared rather than reported twice.
    rest = sorted(((both_ways(tv[j]["names"], ours[i], 0.0, 0.34), i, j)
                   for i in range(len(ours)) if i not in o_of
                   for j in range(len(tv)) if j not in c_of and tv[j]["c"]["kind"] != "multi"),
                  key=lambda p: (-p[0], p[1], p[2]))
    for s, i, j in rest:
        if s > 0 and i not in o_of and j not in c_of:
            o_of[i], c_of[j] = j, i

    rows = []
    from lineup_vote import vote as _vote

    def row(cls, o=None, c=None, **kw):
        his = (c or {}).get("names") or []
        his_w = (c["w"][0] + c["w"][1]) if c and c["c"].get("result") == "win" else []
        complete = not (c and (c["w"][2] or c["l"][2]))
        verdict, sdh_line, sdh_match = _vote({"class": cls}, o, his, his_w, sdh_matches,
                                             show_names, complete)
        if verdict in ("fix_result_same_people", "add_match_same_people"):
            kw = {**kw, "his_winners": his_w, "outcome": outcome_kind(c["c"]["line"]),
                  "duration_seconds": duration_of(c["c"]["line"]),
                  "sdh_match": {"match_type": sdh_match.get("match_type"),
                                "title_at_stake": sdh_match.get("title_at_stake"),
                                "teams": [{"participants": [best_match(p, show_names) or p
                                                            for p in t.get("participants") or []],
                                           "was_winner": t.get("was_winner")}
                                          for t in sdh_match.get("teams") or []]}}
        rows.append({"class": cls, "vote": verdict, "sdh": sdh_line,
                     "event_id": ev["id"], "air_date": day,
                     "show_type": ev.get("show_type"), "title": ev.get("title"),
                     "match_id": (o or {}).get("id"), "match_order": (o or {}).get("match_order"),
                     "ours": (o or {}).get("raw_description", ""),
                     "cawthon": (c or {}).get("c", {}).get("line", ""), **kw})

    for i, o in enumerate(ours):
        if i in o_of:
            continue
        hj = next((j for j, h in enumerate(heat) if both_ways(h["names"], o, 0.5, 0.5)), None)
        dj = next((j for j, d in enumerate(dark) if both_ways(d["names"], o)), None)
        labelled_dark = "dark" in (o.get("match_type") or "").lower()
        if hj is not None:
            row("aired_heat", o, heat[hj])
        elif labelled_dark and not unreadable:
            # Our own source labels it a dark match and his televised list
            # does not have it: both say it never aired.
            row("not_aired", o)
        elif dj is not None:
            # He writes it out as a dark match; our source does not say so.
            row("cawthon_says_dark", o, dark[dj])
        else:
            # His list lacks it but our source does not call it dark (or his
            # page had an unreadable line): a person decides.
            row("unpaired", o)
    multi_people = [set(_people(o)) for o in ours if is_multi(o)]
    for j in range(len(tv)):
        if j in c_of:
            continue
        names = set(tv[j]["names"])
        if names and any(names <= mp for mp in multi_people):
            continue      # one segment of a gauntlet or elimination match we hold whole
        if names and any(names == set(_people(o)) for o in ours):
            # The same people already meet on our card: his second line is a
            # rematch or restart that night (Michaels vs Goldberg twice on Raw
            # 2003-10-20, the 24/7 title swaps). A person decides.
            row("possible_second_bout", c=tv[j])
            continue
        # Where it sits on the card: right after our match that pairs with
        # the nearest earlier line of his.
        before = [c_of[k] for k in range(j) if k in c_of]
        row("missing_match", c=tv[j], after_match_id=ours[max(before)]["id"] if before else None)

    for i, j in o_of.items():
        o, c = ours[i], tv[j]
        if "dark" in (o.get("match_type") or "").lower():
            row("dark_but_televised", o, c)
        teams = [t for t in o["teams"] if t.get("participants")]
        if c["c"].get("all_sides"):
            continue
        if c["c"]["kind"] != "multi" and not is_multi(o) and len(teams) == 2:
            _lineup_rows(o, c, teams, row)
        _result_rows(o, c, teams, row)
    return rows


def outcome_kind(line):
    """How his line says the match ended: 'no-contest', 'draw', 'dq',
    'countout' or 'win'."""
    low = (line or "").lower()
    if re.search(r"fought .* to an? (?:no contest|double (?:count[- ]?out|disqualification|dq))", low):
        return "no-contest"
    if re.search(r"fought .* to an? (?:time[- ]limit )?draw", low):
        return "draw"
    if "disqualification" in low or "reverse decision" in low:
        return "dq"
    if re.search(r"count[- ]?out", low):
        return "countout"
    return "win"


def duration_of(line):
    """Seconds from his "at 12:05", or None."""
    m = re.search(r"\bat (?:around )?(\d{1,2}):(\d{2})\b", line or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


MULTI_MATCH = re.compile(r"rumble|battle royal|gauntlet|elimination|chamber|turmoil|"
                         r"tournament|scramble|beat the clock", re.I)


def is_multi(o):
    """Battle royals, gauntlets, elimination tags and anything with more than
    two sides or eight people: only who won is compared, never the lineup."""
    teams = [t for t in o.get("teams") or [] if t.get("participants")]
    return bool(MULTI_MATCH.search(o.get("match_type") or "")) or len(teams) > 2 or \
        len(_people(o)) >= 8


_PARTICLES = {"de", "del", "la", "le", "van", "von", "da", "the", "of", "and", "el", "y"}


def looks_like_prose(name):
    """A participant that is really a sentence ("Molly knocked Noble into Nidia")."""
    words = name.split()
    return len(words) >= 3 and any(w.islower() and w not in _PARTICLES for w in words)


def loosely_same(a, b):
    """Two spellings of one wrestler in the same slot of the same match:
    Ezikial/Ezekiel Jackson, Conquistadors #45/Conquistador Uno, Shawn/Sean
    O'Haire. Only used when exactly these two names are the difference."""
    if match_strength(a, b):
        return True
    # A one-word billing of a full name: "Eve" is Eve Torres, "Christian" on
    # one side is Christian Cage on the other.
    ta, tb = _tokens(a), _tokens(b)
    if (len(ta) == 1 and ta[0] in (tb[:1] + tb[-1:])) or (len(tb) == 1 and tb[0] in (ta[:1] + ta[-1:])):
        return True
    ka, kb = nkey(a), nkey(b)
    if ka and kb and SequenceMatcher(None, ka, kb).ratio() >= 0.7:
        return True
    stems = lambda n: {t[:6] for t in _tokens(re.sub(r"[#\d]+", " ", n)) if len(t) >= 4}
    return bool(stems(a) & stems(b))


def _lineup_rows(o, c, teams, row):
    sides = [c["w"], c["l"]]
    ov = lambda side, t: len(set(side[0] + side[1]) & set(t.get("participants") or []))
    straight = ov(sides[0], teams[0]) + ov(sides[1], teams[1])
    crossed = ov(sides[0], teams[1]) + ov(sides[1], teams[0])
    assign = [(sides[0], teams[0]), (sides[1], teams[1])] if straight >= crossed else \
             [(sides[0], teams[1]), (sides[1], teams[0])]
    from src.export_to_html import clean_participant
    # Junk on our side ("The X" cut from "The X-Factor") is not a person, so it
    # neither blocks an addition nor counts as someone already in the match.
    real = lambda names: {p for p in names if clean_participant(p)}
    in_match = real(_people(o))
    # Escort credits "(w/ X)" do not name X as a wrestler.
    raw = re.sub(r"\(\s*w\s*/[^()]*\)", " ", (o.get("raw_description") or "")).lower()
    # Several teams fused into one side ("A & B and C & D"): which team a name
    # belongs to is not knowable, so nothing is added automatically.
    multi_team = re.search(r"\s+and\s+", re.sub(r"\([^()]*\)", " ", raw))
    for side, team in assign:
        have = real(team.get("participants") or [])
        his = set(side[0] + side[1])
        ours_only = sorted(have - his)
        his_only = [n for n in side[0] if n not in have] + list(side[2])
        # A one-for-one swap that is just a spelling is not a difference.
        for a in list(ours_only):
            b = next((x for x in his_only if loosely_same(a, x)), None)
            if b is not None:
                ours_only.remove(a)
                his_only.remove(b)
        for name in his_only:
            if name in in_match or any(loosely_same(name, p) for p in in_match):
                continue          # already in this match, under this or another spelling
            # Our text must name him as a wrestler: not as an escort, and not
            # as a gimmick label "Calgary Kid ( The Miz )" whose person is in
            # the brackets and already on the card.
            label_use = re.search(re.escape(re.sub(r"^the\s+", "", name.lower())) + r"\s*\(", raw)
            ours_says = all(t in raw for t in _tokens(name)) and not label_use
            if ours_says and not multi_team:
                row("add_wrestler", o, c, team_number=team.get("team_number"), name=name)
            elif have & his:
                row("cawthon_only_name", o, c, team_number=team.get("team_number"), name=name)
        if not (have & his) and ours_only and his_only:
            row("different_opponent", o, c, team_number=team.get("team_number"),
                name=", ".join(his_only), detail="ours: " + ", ".join(ours_only))
            continue
        if not side[2]:
            for p in ours_only:
                row("junk_on_our_card" if looks_like_prose(p) else "extra_name",
                    o, c, team_number=team.get("team_number"), name=p)


def _result_rows(o, c, teams, row):
    """Who won is the one thing wording cannot change: a different winner, or
    a win on one side against no winner on the other."""
    win_team = next((t for t in teams if t.get("was_winner")), None)
    his_w = set(c["w"][0] + c["w"][1])
    if c["c"]["result"] != "win":
        if win_team is not None:
            row("result", o, c, detail=f"he has {c['c']['result']}, we have a winner")
        return
    if not his_w:
        return                    # his winner did not resolve: nothing to compare
    if win_team is None:
        row("result", o, c, detail="he has a winner, we have none")
        return
    if his_w & set(win_team["participants"]):
        return
    if any(his_w & set(t["participants"]) for t in teams if t is not win_team):
        row("result", o, c, detail="different winner")
