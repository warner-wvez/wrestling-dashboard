#!/usr/bin/env python3
"""Build the media map: classify every cached channel video and join it to events/matches.

Signals, in order: title grammar, duration veto, description rescue (cache/desc/).
Outputs: reports/coverage.md, reports/ambiguous.tsv, reports/unmatched.tsv, media_map.json
"""
import json, os, re, sys
from datetime import date, timedelta
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

ALIASES = {
    "stone cold": "steve austin", "stone cold steve austin": "steve austin",
    "hhh": "triple h", "y2j": "chris jericho", "hbk": "shawn michaels",
    "taker": "the undertaker", "undertaker": "the undertaker",
    "rvd": "rob van dam", "mr. mcmahon": "vince mcmahon", "mr mcmahon": "vince mcmahon",
    "buh buh ray dudley": "bubba ray dudley", "rock": "the rock",
}

def month_num(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if w[:3] in MONTHS:
        return MONTHS[w[:3]]
    for pref, n in MONTHS.items():  # typo tolerance: FEBURARAY etc.
        if w.startswith(pref[:2]) and pref[2] in w:
            return n
    return None

def norm_show(s):
    s = s.lower()
    if "raw" in s:
        return "Raw"
    if "mack" in s or s.startswith("sma") or s.startswith("sam"):
        return "SmackDown"
    return None

def norm_name(n):
    n = n.replace("“", "").replace("”", "").replace("’", "'")
    n = re.sub(r"[^\w\s]", "", n.lower()).strip()
    n = re.sub(r"\s+", " ", n)
    return ALIASES.get(n, n)

def split_sides(txt):
    """'A & B vs. C & D' -> [[a,b],[c,d]] (normalized)."""
    sides = re.split(r"\s+vs\.?\s+", txt, flags=re.I)
    if len(sides) < 2:
        return None
    out = []
    for s in sides:
        # drop trailing locator/stipulation: colon on, em dash, spaced hyphen, pipe, paren
        s = re.sub(r":.*$", "", s)
        s = re.sub(r"\s+[—|]\s*.*$|\s+-\s+.*$|\(.*$", "", s).strip()
        names = re.split(r"\s*[&,]\s*|\s+and\s+", s)
        out.append([norm_name(x) for x in names if x.strip()])
    return out

# ---------- load corpus ----------

def load_corpus():
    h = open(os.path.join(REPO, "index.html"), encoding="utf-8").read()
    m = re.search(r'<script[^>]*id="wrestling-data"[^>]*>(.*?)</script>', h, re.S)
    data = json.loads(m.group(1))
    events = {int(k): v for k, v in data["events"].items()}
    matches = {}
    for f in os.listdir(os.path.join(REPO, "shards")):
        if f.startswith("matches-"):
            s = json.load(open(os.path.join(REPO, "shards", f)))
            for eid, ms in s.items():
                matches[int(eid)] = ms
    return events, matches

def build_indexes(events, matches):
    by_show_date = {}           # (show, iso_date) -> eid
    ppv_by_year = defaultdict(list)   # year -> [(norm ppv tokens, eid)]
    for eid, e in events.items():
        d = e["air_date"]
        st = e["show_type"]
        if st in ("Raw", "SmackDown"):
            by_show_date[(st, d)] = eid
        else:
            name = (e.get("ppv_name") or e.get("title") or "")
            toks = set(re.sub(r"[^\w\s]", "", name.lower()).split()) - {"wwf", "wwe", "nxt", "the", str(int(d[:4]))}
            ppv_by_year[int(d[:4])].append((toks, eid))
    # participant index per event match
    ev_match_parts = {}         # eid -> [(match_id, match_order, set(norm participants))]
    year_show_matches = defaultdict(list)  # (show, year) -> [(eid, match_id, order, parts)]
    for eid, ms in matches.items():
        e = events.get(eid)
        if not e:
            continue
        rows = []
        for m in ms:
            parts = set()
            for t in m.get("teams", []):
                for p in t.get("participants", []):
                    parts.add(norm_name(p))
                if t.get("team_name"):
                    parts.add(norm_name(t["team_name"]))
            rows.append((m["id"], m.get("match_order"), parts))
            if e["show_type"] in ("Raw", "SmackDown"):
                year_show_matches[(e["show_type"], int(e["air_date"][:4]))].append(
                    (eid, m["id"], m.get("match_order"), parts))
        ev_match_parts[eid] = rows
    return by_show_date, ppv_by_year, ev_match_parts, year_show_matches

def find_event(by_show_date, show, iso):
    eid = by_show_date.get((show, iso))
    if eid:
        return eid, "exact"
    if show == "SmackDown":  # pre-2016 tape+2 estimates: search +-3 days
        d0 = date.fromisoformat(iso)
        for off in (1, -1, 2, -2, 3, -3):
            eid = by_show_date.get((show, (d0 + timedelta(days=off)).isoformat()))
            if eid:
                return eid, f"window{off:+d}"
    return None, None

def find_ppv(ppv_by_year, name, year):
    """Returns (eid, n_candidates). n>1 means ambiguous (e.g. two-night events)."""
    toks = set(re.sub(r"[^\w\s]", "", name.lower()).split()) - {"wwf", "wwe", "the", str(year)}
    hits = []
    for cand_toks, eid in ppv_by_year.get(year, []):
        if toks and (toks <= cand_toks or cand_toks <= toks or len(toks & cand_toks) >= max(1, len(toks) - 1)):
            if eid not in hits:
                hits.append(eid)
    return (hits[0] if len(hits) == 1 else None), len(hits)

def find_match_row(rows, sides):
    """Score match rows by how many title names appear in participants."""
    names = [n for side in sides for n in side]
    scored = []
    for mid, order, parts in rows:
        blob = " ".join(parts)
        hits = sum(1 for n in names if n and (n in parts or (len(n) > 3 and n in blob)))
        if hits:
            scored.append((hits, mid, order))
    if not scored:
        return None, "no-hit"
    scored.sort(reverse=True)
    need = min(len(names), 2)
    top = [s for s in scored if s[0] == scored[0][0]]
    if scored[0][0] < need:
        return None, "weak"
    if len(top) > 1:
        return None, "tie"
    return (top[0][1], top[0][2]), "ok"

# ---------- per-source title grammars ----------

DATE_RX = re.compile(
    r"(Jan\w*\.?|Feb\w*\.?|Mar\w*\.?|Apr\w*\.?|May\.?|Jun\w*\.?|Jul\w*\.?|Aug\w*\.?|Sept?\w*\.?|Oct\w*\.?|Nov\w*\.?|Dec\w*\.?)\s+(\d{1,2}),?\s+(\d{4})", re.I)
DMY_RX = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})")
SHOW_RX = re.compile(r"\b(Raw(?:\s+is\s+War)?|Monday\s+Night\s+Raw|Smack\s?Down!?|Samckdown|Smackdow)\b", re.I)

def parse_mdY(m):
    mo = month_num(m.group(1))
    return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}" if mo else None

def parse_vault(v):
    t = v["title"]
    kind = None
    m = re.match(r"FULL (MATCH|EPISODE|SEGMENT|TOURNAMENT|SHOW)", t, re.I)
    if m:
        kind = {"MATCH": "match", "EPISODE": "show", "SEGMENT": "moment",
                "TOURNAMENT": "other", "SHOW": "show"}[m.group(1).upper()]
    else:
        return {"kind": "other"}
    body = t.split(":", 1)[1] if ":" in t else t
    dm, sm = DATE_RX.search(t), SHOW_RX.search(t)
    out = {"kind": kind, "sides": split_sides(body)}
    if dm and sm:
        out.update(show=norm_show(sm.group(1)), date=parse_mdY(dm))
    elif dm:
        out["date"] = parse_mdY(dm)
    else:
        pm = re.search(r"[:|]\s*([^:|]+?)\s+(\d{4})\s*$", t)
        if pm:
            out.update(ppv=pm.group(1), year=int(pm.group(2)))
    return out

def parse_momo(v):
    t = re.sub(r"\s+HD\s*(\(.*\))?$", "", v["title"])
    dm, sm = DATE_RX.search(t), SHOW_RX.search(t)
    sides = split_sides(t.split(":")[0])
    kind = "match" if sides else "moment"
    if re.match(r"(Best of|Story of|Every)", t, re.I):
        kind = "other"
    out = {"kind": kind, "sides": sides}
    if dm and sm:
        out.update(show=norm_show(sm.group(1)), date=parse_mdY(dm))
    elif dm:
        out["date"] = parse_mdY(dm)
    else:
        pm = re.search(r"\b(WWF|WWE)\s+([A-Z][\w\s]+?)\s+(\d{4})\b", t)
        if pm:
            out.update(ppv=pm.group(2), year=int(pm.group(3)))
    return out

def parse_yearonly(v, desc=None):
    t = v["title"]
    part = None
    pm = re.search(r"\s(\d)\s*$", t)
    if pm:
        part = int(pm.group(1))
        t = t[:pm.start()]
    ym = re.search(r"\|\s*(WWF|WWE)\s+(RAW|SMACKDOWN!?|SmackDown!?|Raw)\s*\((\d{4})\)", t, re.I)
    sides = split_sides(t.split("|")[0])
    kind = "match" if sides else "moment"
    out = {"kind": kind, "sides": sides, "part": part}
    if ym:
        out.update(show=norm_show(ym.group(2)), year=int(ym.group(3)))
    # description rescue: exact date
    if desc:
        dm = DATE_RX.search(desc) or DMY_RX.search(desc)
        if dm:
            if dm.re is DMY_RX:
                mo = month_num(dm.group(2))
                if mo:
                    out["date"] = f"{int(dm.group(3)):04d}-{mo:02d}-{int(dm.group(1)):02d}"
            else:
                out["date"] = parse_mdY(dm)
    return out

def parse_dmfull(v):
    t = v["title"].upper()
    part = None
    pm = re.search(r"PART\s*(\d)", t)
    if pm:
        part = int(pm.group(1))
    dm = re.search(r"(\d{1,2})\s+([A-Z]{3,})\s+(\d{4})", t)
    sm = SHOW_RX.search(t)
    out = {"kind": "show", "part": part}
    if dm and sm:
        mo = month_num(dm.group(2))
        if mo:
            out.update(show=norm_show(sm.group(1)),
                       date=f"{int(dm.group(3)):04d}-{mo:02d}-{int(dm.group(1)):02d}")
    elif not sm:
        pm2 = re.search(r"WWE\s+([A-Z][A-Z\s]+?)\s+(\d{4})\s+FULL SHOW", t)
        if pm2:
            out.update(ppv=pm2.group(1).title(), year=int(pm2.group(2)))
    # description rescue for date-less shows
    if "date" not in out and "ppv" not in out and v.get("description"):
        dm2 = DATE_RX.search(v["description"]) or DMY_RX.search(v["description"])
        if dm2 and sm:
            if dm2.re is DMY_RX:
                mo = month_num(dm2.group(2))
                if mo:
                    out.update(show=norm_show(sm.group(1)),
                               date=f"{int(dm2.group(3)):04d}-{mo:02d}-{int(dm2.group(1)):02d}")
            else:
                out.update(show=norm_show(sm.group(1)), date=parse_mdY(dm2))
    return out

GRAMMARS = {"vault": parse_vault, "momo": parse_momo, "yearonly": parse_yearonly, "dmfull": parse_dmfull}

def clean_label(title):
    """Short human label for the UI: drop FULL MATCH prefixes, locators, HD tails."""
    t = re.sub(r"^FULL (MATCH|EPISODE|SEGMENT|TOURNAMENT|SHOW|HOME VIDEO):\s*", "", title, flags=re.I)
    t = re.sub(r"\s+HD\s*(\(.*\))?\s*$", "", t)
    parts = t.split(":")
    if len(parts) > 1 and re.search(r"\d{4}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec", parts[-1]):
        t = ":".join(parts[:-1])
    t = re.sub(r"\|\s*(WWF|WWE)\s+(RAW|SMACKDOWN!?)\s*\(\d{4}\)\s*\d?\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+\d\s*$", "", t)
    return t.strip(" -—|—").strip()

# ---------- duration veto ----------

def veto(kind, dur, part):
    if dur is None:
        return kind
    mins = dur / 60
    if kind == "show" and mins < 45 and not part:
        return "flag:short-show"
    if kind == "match" and mins > 60:
        return "flag:long-match"
    if kind in ("match", "moment") and mins < 1:
        return "flag:tiny"
    return kind

# ---------- main ----------

def main():
    events, matches = load_corpus()
    by_show_date, ppv_by_year, ev_match_parts, ysm = build_indexes(events, matches)
    sources = json.load(open(os.path.join(HERE, "sources.json")))["sources"]

    media = defaultdict(lambda: {"show": [], "matches": defaultdict(list), "moments": []})
    ambiguous, unmatched = [], []
    stats = defaultdict(lambda: defaultdict(int))
    desc_dir = os.path.join(HERE, "cache", "desc")

    for src in sources:
        if not src.get("enabled"):
            continue
        sid, gram, tier = src["id"], GRAMMARS[src["grammar"]], src["tier"]
        if src["platform"] == "youtube":
            vids = json.load(open(os.path.join(HERE, f"cache/yt_{src['handle']}.json")))
        else:
            vids = json.load(open(os.path.join(HERE, f"cache/dm_{src['handle']}.json")))
            for v in vids:
                v["url"] = v.get("url") or f"https://www.dailymotion.com/video/{v['id']}"

        # group multi-part uploads by base title
        for v in vids:
            desc = v.get("description")
            if src["platform"] == "youtube":
                p = os.path.join(desc_dir, f"{v['id']}.json")
                if os.path.exists(p):
                    dd = json.load(open(p))
                    desc = dd.get("description") or desc
            info = gram(v, desc) if src["grammar"] == "yearonly" else gram(v)
            kind = veto(info.get("kind"), v.get("duration"), info.get("part"))
            stats[sid][f"kind:{info.get('kind')}"] += 1
            row = {"url": v["url"], "src": sid, "tier": tier, "title": v["title"],
                   "label": clean_label(v["title"]),
                   "platform": "YouTube" if src["platform"] == "youtube" else "Dailymotion",
                   "min": round((v.get("duration") or 0) / 60)}
            if info.get("part"):
                row["part"] = info["part"]
            if kind.startswith("flag:"):
                unmatched.append((sid, kind, v["title"]))
                stats[sid]["flagged"] += 1
                continue
            if kind == "other":
                stats[sid]["skipped-other"] += 1
                continue

            eid = how = None
            if info.get("date") and info.get("show"):
                eid, how = find_event(by_show_date, info["show"], info["date"])
            elif info.get("ppv") and info.get("year"):
                eid, n_cand = find_ppv(ppv_by_year, info["ppv"], info["year"])
                how = "ppv" if eid else None
                if not eid and n_cand > 1:
                    ambiguous.append((sid, f"{n_cand} ppv candidates", v["title"]))
                    stats[sid]["ambiguous"] += 1
                    continue
            elif info.get("date") and not info.get("show") and kind in ("match", "moment"):
                for st in ("Raw", "SmackDown"):
                    eid, how = find_event(by_show_date, st, info["date"])
                    if eid:
                        break

            if eid:
                if kind == "show":
                    media[eid]["show"].append(row)
                    stats[sid]["joined-show"] += 1
                elif kind == "match" and info.get("sides"):
                    hit, why = find_match_row(ev_match_parts.get(eid, []), info["sides"])
                    if hit:
                        media[eid]["matches"][str(hit[1] or hit[0])].append(row)
                        stats[sid]["joined-match"] += 1
                    else:
                        media[eid]["moments"].append(row)  # right show, row unclear
                        stats[sid][f"match-fallback-moment({why})"] += 1
                else:
                    media[eid]["moments"].append(row)
                    stats[sid]["joined-moment"] += 1
                stats[sid][f"join:{how}"] += 1
                yr = events[eid]["air_date"][:4]
                stats[sid][f"year:{yr}"] += 1
                continue

            # year-only unique join
            if kind == "match" and info.get("sides") and info.get("show") and info.get("year"):
                cands = []
                names = [n for side in info["sides"] for n in side]
                for ceid, mid, order, parts in ysm.get((info["show"], info["year"]), []):
                    blob = " ".join(parts)
                    hits = sum(1 for n in names if n and (n in parts or (len(n) > 3 and n in blob)))
                    if hits >= min(len(names), 2):
                        cands.append((ceid, mid, order, hits))
                best = max((c[3] for c in cands), default=0)
                tops = [c for c in cands if c[3] == best]
                if len(tops) == 1:
                    ceid, mid, order, _ = tops[0]
                    media[ceid]["matches"][str(order or mid)].append(row)
                    stats[sid]["joined-match-yearonly"] += 1
                    stats[sid][f"year:{events[ceid]['air_date'][:4]}"] += 1
                    continue
                elif len(tops) > 1:
                    ambiguous.append((sid, f"{len(tops)} candidates", v["title"]))
                    stats[sid]["ambiguous"] += 1
                    continue
            unmatched.append((sid, "no-join", v["title"]))
            stats[sid]["unmatched"] += 1

    # ---- outputs ----
    out_map = {}
    for eid, buckets in media.items():
        out_map[str(eid)] = {
            "show": buckets["show"],
            "matches": {k: v for k, v in buckets["matches"].items()},
            "moments": buckets["moments"],
        }
    json.dump(out_map, open(os.path.join(HERE, "media_map.json"), "w"), indent=1)

    with open(os.path.join(HERE, "reports/ambiguous.tsv"), "w") as f:
        f.write("source\treason\ttitle\n")
        for r in ambiguous:
            f.write("\t".join(r) + "\n")
    with open(os.path.join(HERE, "reports/unmatched.tsv"), "w") as f:
        f.write("source\treason\ttitle\n")
        for r in unmatched:
            f.write("\t".join(r) + "\n")

    # coverage report
    ev_with_show = sum(1 for b in media.values() if b["show"])
    ev_with_any = len(media)
    n_match_links = sum(len(v) for b in media.values() for v in b["matches"].values())
    n_matches_covered = sum(len(b["matches"]) for b in media.values())
    n_moments = sum(len(b["moments"]) for b in media.values())
    per_year = defaultdict(lambda: [0, 0, 0])
    for eid, b in media.items():
        y = int(events[eid]["air_date"][:4])
        if b["show"]:
            per_year[y][0] += 1
        per_year[y][1] += len(b["matches"])
        per_year[y][2] += len(b["moments"])
    total_events_by_year = defaultdict(int)
    for e in events.values():
        total_events_by_year[int(e["air_date"][:4])] += 1

    L = ["# Media coverage report", ""]
    L.append(f"Corpus: {len(events)} events, {sum(len(m) for m in matches.values())} matches")
    L.append(f"Events with a full-show video: {ev_with_show}")
    L.append(f"Distinct matches with a video: {n_matches_covered} ({n_match_links} links)")
    L.append(f"Moments attached to events: {n_moments}")
    L.append(f"Events touched by any video: {ev_with_any}")
    L.append("")
    L.append("| Year | Events | Full shows | Matches w/ video | Moments |")
    L.append("|---|---|---|---|---|")
    for y in sorted(per_year):
        s, m, mo = per_year[y]
        L.append(f"| {y} | {total_events_by_year[y]} | {s} | {m} | {mo} |")
    L.append("")
    for sid in stats:
        L.append(f"## {sid}")
        for k in sorted(stats[sid]):
            L.append(f"- {k}: {stats[sid][k]}")
        L.append("")
    open(os.path.join(HERE, "reports/coverage.md"), "w").write("\n".join(L))
    print("\n".join(L[:20]))
    print(f"\nfull report: reports/coverage.md | ambiguous: {len(ambiguous)} | unmatched: {len(unmatched)}")

if __name__ == "__main__":
    main()
