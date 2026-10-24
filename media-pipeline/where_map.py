#!/usr/bin/env python3
"""Where to watch each show: build shards/where.json.

Two inputs, joined to our shows by show type and air date:

  watch-feed.csv   archive.org items, one per show type and year (Warner's
                   "WWE watch feed" sheet). Each item holds full-show files
                   named by date, by PPV name, or by episode number.
  official.json    Peacock and Netflix playback pages (Warner's "WWE Network
                   Peacock" sheet), exported once with --sheet.

Output, one row per show that has something:

  {"<event id>": {"archive": {"item", "file", "min", "how"},
                  "official": {"platform", "url"}}}

"how" says how the archive file was tied to the show: "date" (same day),
"near-3" (one file that week, one show that week, three days apart),
"name" (PPV name plus year), "ordinal" (episode number walked over the
year's weeks). Everything else is left out: recap specials with no show,
kickoff shows, files that share a week with another file.

Usage:
  where_map.py --sheet "~/Downloads/WWE Network Peacock.xlsx"   # refresh official.json
  where_map.py                                                  # build shards/where.json
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FEED = os.path.join(HERE, "watch-feed.csv")
OFFICIAL = os.path.join(HERE, "official.json")
CACHE = os.path.join(HERE, "cache", "archive")
OUT = os.path.join(REPO, "shards", "where.json")

COL2TYPE = {"RAW": "Raw", "Smackdown": "SmackDown", "PPV": "PPV", "Extras?": "PPV"}
VIDEO = (".mp4", ".mkv", ".avi", ".m4v", ".webm", ".ts", ".mpg", ".mov")
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
ORDERS = ("mon", "ymd", "mdy", "dmy", "ydm")

P_MON = re.compile(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?[ .]+(\d{1,2}),?[ .]+(\d{4})", re.I)
P_YMD = re.compile(r"(?<!\d)(\d{4})[-._ ](\d{1,2})[-._ ](\d{1,2})(?!\d)")
P_XY = re.compile(r"(?<!\d)(\d{1,2})[-._ ](\d{1,2})[-._ ](\d{4})(?!\d)")
P_YEAR = re.compile(r"(?:^|[\s(._-])((?:19|20)\d\d)(?=$|[\s)._-])")
P_EP = re.compile(r"\bE(\d{1,3})\b")

# The feed writes WrestleMania with a number; our PPV names carry the roman
# numerals WWE used that year.
WM_ROMAN = {"17": "x seven", "18": "x8", "19": "xix", "20": "xx", "24": "xxiv",
            "26": "xxvi", "27": "xxvii", "28": "xxviii"}
NOISE = {"wwe", "wwf", "720p", "1080p", "aac", "web", "h264", "h265", "x264", "heel",
         "multi", "bdrip", "fog", "mkv", "mp4", "avi"}
KICKOFF = ("kickoff show", "kickoff", "pre show", "preshow", "pre-show", "press conference")


def _safe_date(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def date_candidates(name):
    """Every date the file name could mean, keyed by the order it was read in."""
    m = P_MON.search(name)
    if m:
        month = next(i + 1 for i, full in enumerate(MONTHS) if full.startswith(m.group(1).lower()))
        d = _safe_date(int(m.group(3)), month, int(m.group(2)))
        return {"mon": d} if d else {}
    out = {}
    m = P_YMD.search(name)
    if m:
        y, a, b = (int(x) for x in m.groups())
        for key, (mo, da) in (("ymd", (a, b)), ("ydm", (b, a))):
            d = _safe_date(y, mo, da)
            if d:
                out[key] = d
        return out
    m = P_XY.search(name)
    if m:
        a, b, y = (int(x) for x in m.groups())
        for key, (mo, da) in (("mdy", (a, b)), ("dmy", (b, a))):
            d = _safe_date(y, mo, da)
            if d:
                out[key] = d
    return out


def pick_order(names, show_dates):
    """The date order under which the most file names land on one of our shows."""
    hits = Counter()
    for n in names:
        for key, d in date_candidates(n).items():
            if d.isoformat() in show_dates:
                hits[key] += 1
    return max(ORDERS, key=lambda k: (hits[k], -ORDERS.index(k)))


def _norm(s):
    s = re.sub(r"[^a-z0-9]+", " ", str(s).lower()).replace("judgement", "judgment")
    return re.sub(r"\s+", " ", s).strip()


def ppv_key(name):
    """(normalised PPV name, year, is a kickoff show) from an archive file name,
    or None when the name carries no standalone year."""
    m = P_YEAR.search(name)
    if not m:
        return None
    year = int(m.group(1))
    s = _norm(re.sub(r"\.[a-z0-9]{2,4}$", "", name, flags=re.I))
    kickoff = any(k in s for k in KICKOFF)
    for k in KICKOFF:
        s = s.replace(k, " ")
    words = [w for w in s.split() if w not in NOISE and w != str(year)]
    s = " ".join(words)
    m = re.match(r"^wrestlemania (\d+)$", s)
    if m and m.group(1) in WM_ROMAN:
        s = "wrestlemania " + WM_ROMAN[m.group(1)]
    return (s, year, kickoff)


def _our_ppv_key(ev):
    s = _norm(re.split(r"\s+-\s+|:", str(ev.get("ppv_name") or ev.get("title") or ""))[0])
    year = ev["air_date"][:4]
    return " ".join(w for w in s.split() if w not in NOISE and w != year)


# Under 40 minutes is not trusted as a full show: the shortest 1993 Raw (an
# hour on air, about 40 minutes without breaks) runs 40, and one file of 36
# (1993-03-22) may be missing a segment. An item that lists no length passes.
MIN_FULL_SHOW = 40


def _video_files(files):
    return [f for f in files if f.get("name", "").lower().endswith(VIDEO) and not f["name"].endswith(".ia.mp4")
            and not (0 < float(f.get("length") or 0) / 60 < MIN_FULL_SHOW - 0.5)]


def _rec(item, f, how):
    return {"item": item, "file": f["name"], "min": round(float(f.get("length") or 0) / 60), "how": how}


def _better(a, b):
    """Prefer the mp4 (it plays in the browser), then the larger file."""
    ka = (a["file"].lower().endswith(".mp4"), a["_size"])
    kb = (b["file"].lower().endswith(".mp4"), b["_size"])
    return a if ka >= kb else b


def join_items(items, events):
    """One archive file per show. items: [{col, id, files}], events: our shows."""
    by_day = defaultdict(list)
    ppv_by_year = defaultdict(list)
    for e in events:
        by_day[(e["show_type"], e["air_date"])].append(e)
        if e["show_type"] == "PPV":
            ppv_by_year[int(e["air_date"][:4])].append(e)
    found = {}

    def offer(e, item, f, how):
        rec = {**_rec(item, f, how), "_size": int(f.get("size") or 0)}
        key = str(e["id"])
        found[key] = _better(found[key], rec) if key in found else rec

    for it in items:
        st = COL2TYPE.get(it["col"])
        if not st:
            continue
        files = _video_files(it["files"])
        show_dates = {d for (t, d) in by_day if t == st}
        order = pick_order([f["name"] for f in files], show_dates)
        dated = [(f, date_candidates(f["name"]).get(order)) for f in files]
        near_wanted = []
        for f, d in dated:
            if d is None:
                if st == "PPV":
                    k = ppv_key(f["name"])
                    if k and not k[2]:
                        name, year, _ = k
                        best = None
                        for e in ppv_by_year.get(year, []):
                            ours = _our_ppv_key(e)
                            if name == ours or (len(name) > 3 and (name in ours or ours in name)):
                                if best is None or len(ours) > len(_our_ppv_key(best)):
                                    best = e
                        if best:
                            offer(best, it["id"], f, "name")
                continue
            exact = by_day.get((st, d.isoformat()))
            if exact:
                offer(exact[0], it["id"], f, "date")
                continue
            for delta in (-1, 1, -2, 2, -3, 3):
                e = by_day.get((st, (d + timedelta(days=delta)).isoformat()))
                if e:
                    near_wanted.append((f, d, delta, e[0]))
                    break
        # A near miss is trusted only when it is the one file within three days
        # of that show, and the show has no exact file.
        for f, d, delta, e in near_wanted:
            ed = date.fromisoformat(e["air_date"])
            week = [g for g, gd in dated if gd and abs((gd - ed).days) <= 3]
            if len(week) == 1 and str(e["id"]) not in found:
                offer(e, it["id"], f, f"near{(d - ed).days:+d}")  # file day minus air day
    return {k: {kk: v for kk, v in rec.items() if kk != "_size"} for k, rec in found.items()}


def ordinal_join(item, files, events, show_type, year):
    """Files named E01..E52 walked over the weeks of that year's shows. Refuses
    unless the file count equals the week count, so one skipped upload cannot
    shift every show after it."""
    numbered = []
    for f in _video_files(files):
        m = P_EP.search(f["name"])
        if m:
            numbered.append((int(m.group(1)), f))
    numbered.sort()
    ours = sorted((e for e in events if e["show_type"] == show_type and e["air_date"].startswith(str(year))),
                  key=lambda e: e["air_date"])
    if not numbered or not ours:
        return {}
    first, last = date.fromisoformat(ours[0]["air_date"]), date.fromisoformat(ours[-1]["air_date"])
    weeks = []
    d = first
    while d <= last:
        weeks.append(d.isoformat())
        d += timedelta(days=7)
    if len(weeks) != len(numbered) or [n for n, _ in numbered] != list(range(1, len(numbered) + 1)):
        return {}
    by_day = {e["air_date"]: e for e in ours}
    out = {}
    for (n, f), day in zip(numbered, weeks):
        e = by_day.get(day)
        if e:
            out[str(e["id"])] = _rec(item, f, "ordinal")
    return out


def official_links(rows, events):
    """Peacock/Netflix pages keyed by our show id. rows: (class, name, link, date)."""
    by_day = defaultdict(list)
    for e in events:
        by_day[(e["show_type"], e["air_date"])].append(e)
    out = {}
    for cls, _name, link, d in rows:
        if not isinstance(link, str) or not link.startswith("http") or not hasattr(d, "isoformat"):
            continue
        c = str(cls).lower()
        st = "SmackDown" if "smackdown" in c else "Raw" if "raw" in c else "PPV"
        hit = by_day.get((st, d.isoformat()))
        if not hit:
            continue
        if "netflix.com" in link:
            platform, url = "netflix", link.split("?")[0]
        elif "peacocktv.com" in link:
            platform, url = "peacock", link
        else:
            continue
        out[str(hit[0]["id"])] = {"platform": platform, "url": url}
    return out


# ---------------------------------------------------------------- inputs --

def load_events():
    html = open(os.path.join(REPO, "index.html"), encoding="utf-8").read()
    m = re.search(r'<script id="wrestling-data"[^>]*>(.*?)</script>', html, re.S)
    return list(json.loads(m.group(1))["events"].values())


def read_feed(path=FEED):
    with open(path, newline="") as f:
        return [(r["column"], r["identifier"]) for r in csv.DictReader(f)]


def fetch_item(identifier, cache=CACHE, refresh=False):
    os.makedirs(cache, exist_ok=True)
    p = os.path.join(cache, identifier + ".json")
    if os.path.exists(p) and not refresh:
        return json.load(open(p))
    req = urllib.request.Request(f"https://archive.org/metadata/{identifier}",
                                 headers={"User-Agent": "wvez-wrestling-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=60) as u:
        d = json.load(u)
    if d.get("files"):
        json.dump(d, open(p, "w"))
    time.sleep(0.4)
    return d


def export_official(xlsx, out=OFFICIAL):
    """Flatten the Peacock/Netflix sheet to rows we can commit."""
    import openpyxl  # only needed for this one-off export
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    rows = []
    for ws in wb.worksheets:
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0 or len(row) < 4:
                continue
            cls, name, link, d = row[:4]
            if hasattr(d, "isoformat") and d.year >= 2001 and isinstance(link, str) and link.startswith("http"):
                rows.append([str(cls), str(name) if name is not None else "", link, d.date().isoformat()])
    json.dump(rows, open(out, "w"), indent=0)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", help="Peacock/Netflix xlsx: export it to official.json and stop")
    ap.add_argument("--refresh", action="store_true", help="re-fetch archive.org metadata")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    if args.sheet:
        rows = export_official(os.path.expanduser(args.sheet))
        print(f"official.json: {len(rows)} rows")
        return 0
    events = load_events()
    items = []
    ordinal = {}
    for col, identifier in read_feed():
        if col not in COL2TYPE:
            continue
        try:
            d = fetch_item(identifier, refresh=args.refresh)
        except Exception as e:  # one dead item must not stop the build
            print(f"skip {identifier}: {e}", file=sys.stderr)
            continue
        files = d.get("files", [])
        if any(P_EP.search(f.get("name", "")) and not date_candidates(f["name"]) for f in _video_files(files)):
            m = re.search(r"(20\d\d)", identifier)
            if m:
                ordinal.update(ordinal_join(identifier, files, events, COL2TYPE[col], int(m.group(1))))
        items.append({"col": col, "id": identifier, "files": files})
    archive = join_items(items, events)
    for k, v in ordinal.items():
        archive.setdefault(k, v)
    official = {}
    if os.path.exists(OFFICIAL):
        rows = [(c, n, l, date.fromisoformat(d)) for c, n, l, d in json.load(open(OFFICIAL))]
        official = official_links(rows, events)
    out = {}
    for k in sorted(set(archive) | set(official), key=int):
        row = {}
        if k in archive:
            row["archive"] = archive[k]
        if k in official:
            row["official"] = official[k]
        out[k] = row
    json.dump(out, open(args.out, "w"), separators=(",", ":"))
    years = Counter()
    for e in events:
        years[(e["show_type"], e["air_date"][:4], str(e["id"]) in archive)] += 1
    print(f"where.json: {len(out)} shows; archive {len(archive)}, official {len(official)}")
    print("how:", dict(Counter(v["how"] for v in archive.values())))
    for st in ("Raw", "SmackDown", "PPV"):
        print(st, " ".join(f"{y}:{years[(st, str(y), True)]}/{years[(st, str(y), True)] + years[(st, str(y), False)]}"
                           for y in range(2001, 2027)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
