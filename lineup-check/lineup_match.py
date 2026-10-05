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
}
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
    if ka == kb or (CANON.get(a, a) == CANON.get(b, b)):
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

    tv, heat = prep(cawthon_lines), prep(heat_lines)
    pairs = []
    for i, o in enumerate(ours):
        for j, c in enumerate(tv):
            if c["c"]["kind"] == "multi":
                s = 1.0 if (MULTI_TYPES.search(o.get("match_type") or "") and
                            set(c["names"]) & set(_people(o))) else 0.0
            else:
                s = _score(c["names"], _people(o))
            if s >= 0.5:
                pairs.append((s, i, j))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    o_of, c_of = {}, {}
    for s, i, j in pairs:
        if i not in o_of and j not in c_of:
            o_of[i], c_of[j] = j, i
    # Second pass: whatever is left on both sides pairs on any shared person,
    # so a match with one unplaceable name is compared rather than reported
    # twice (once as ours unpaired, once as his missing).
    rest = sorted(((_score(tv[j]["names"], _people(ours[i])), i, j)
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
        rows.append({"class": cls, "vote": _vote({"class": cls}, o, his, his_w, sdh_matches, show_names),
                     "event_id": ev["id"], "air_date": day,
                     "show_type": ev.get("show_type"), "title": ev.get("title"),
                     "match_id": (o or {}).get("id"), "match_order": (o or {}).get("match_order"),
                     "ours": (o or {}).get("raw_description", ""),
                     "cawthon": (c or {}).get("c", {}).get("line", ""), **kw})

    leftovers = [j for j in range(len(tv)) if j not in c_of]
    for i, o in enumerate(ours):
        if i in o_of:
            continue
        # Both ways round: a 20-man battle royal is not "the same match" as a
        # singles bout that happens to share one of its entrants.
        hj = next((j for j, h in enumerate(heat)
                   if _score(h["names"], _people(o)) >= 0.5
                   and len(set(h["names"]) & set(_people(o))) / max(len(set(h["names"])), len(set(_people(o))), 1) >= 0.5),
                  None)
        if hj is not None:
            row("aired_heat", o, heat[hj])
        elif "dark" in (o.get("match_type") or "").lower() and not unreadable:
            # Our own source labels it a dark match and his televised list
            # does not have it: both say it never aired.
            row("not_aired", o)
        else:
            # His list lacks it but our source does not call it dark (or his
            # page had an unreadable line): a person decides.
            row("unpaired", o)
    for j in leftovers:
        row("missing_match", c=tv[j])

    for i, j in o_of.items():
        o, c = ours[i], tv[j]
        if "dark" in (o.get("match_type") or "").lower():
            row("dark_but_televised", o, c)
        if c["c"]["kind"] == "multi" or c["c"].get("all_sides"):
            continue
        teams = [t for t in o["teams"] if t.get("participants")]
        sides = [c["w"], c["l"]]
        # Map his two sides onto our teams by overlap; only a clean two-team
        # match can take an automatic addition.
        if len(teams) == 2:
            ov = lambda side, t: len(set(side[0] + side[1]) & set(t.get("participants") or []))
            straight = ov(sides[0], teams[0]) + ov(sides[1], teams[1])
            crossed = ov(sides[0], teams[1]) + ov(sides[1], teams[0])
            assign = [(sides[0], teams[0]), (sides[1], teams[1])] if straight >= crossed else \
                     [(sides[0], teams[1]), (sides[1], teams[0])]
            for side, team in assign:
                have = set(team.get("participants") or [])
                his = set(side[0] + side[1])
                if have and not (have & his) and (side[0] or side[2]):
                    # Nobody in common on this side: a different opponent
                    # (a substitution), never an addition.
                    row("different_opponent", o, c, team_number=team.get("team_number"),
                        name=", ".join(side[0] + side[2]))
                    continue
                if have <= his:
                    # Our side is a strict subset of his. Add a name only when
                    # our own source text names him too, so both sources agree
                    # he was there and only our parse lost him; otherwise he is
                    # Cawthon's word alone and goes to review.
                    # Escort credits "(w/ X)" do not name X as a wrestler.
                    raw = re.sub(r"\(\s*w\s*/[^()]*\)", " ", (o.get("raw_description") or "")).lower()
                    in_match = set(_people(o))
                    # Several teams fused into one side ("A & B and C & D and E &
                    # F", the source's multi-team form): which team a name
                    # belongs to is not knowable, so a person decides.
                    multi_team = re.search(r"\s+and\s+", re.sub(r"\([^()]*\)", " ", raw))
                    for name in side[0] + side[2]:
                        if name in have:
                            continue
                        if name in in_match:
                            # Already wrestling on another side of this match:
                            # the two sources describe different matches.
                            row("different_opponent", o, c, team_number=team.get("team_number"), name=name)
                            continue
                        ours_says = all(t in raw for t in _tokens(name))
                        row("add_wrestler" if ours_says and not multi_team else "cawthon_only_name",
                            o, c, team_number=team.get("team_number"), name=name)
                elif not side[2]:   # fully resolved side: our extras are suspect
                    for p in have - his:
                        row("extra_name", o, c, team_number=team.get("team_number"), name=p)
                if not have <= his:
                    for u in side[2]:
                        row("unresolved_name", o, c, team_number=team.get("team_number"), name=u)
        # Result: his winners against our winning team.
        win_team = next((t for t in teams if t.get("was_winner")), None)
        if c["c"]["result"] != "win":
            if win_team is not None:
                row("result", o, c, detail=f"he has {c['c']['result']}, we have a winner")
        elif win_team is None:
            row("result", o, c, detail="he has a winner, we have none")
        else:
            w = set(c["w"][0] + c["w"][1])
            lose = [t for t in teams if t is not win_team]
            if lose and len(w & set(win_team["participants"])) < max(
                    len(w & set(t["participants"])) for t in lose):
                row("result", o, c, detail="different winner")
    return rows
