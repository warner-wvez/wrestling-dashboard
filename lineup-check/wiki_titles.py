#!/usr/bin/env python3
"""Wikipedia title histories, fetched once and cached in wiki-cache/.

fetch() follows redirects ("List of WWE Universal Champions" is a section of
the championship's article). reigns() reads the two formats the lists use:
{{PWtitlereign}} templates and plain wikitable rows.
"""
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CACHE = HERE / "wiki-cache"
API = "https://en.wikipedia.org/w/api.php"
UA = {"User-Agent": "wrestling-dashboard title audit (personal research)"}


def fetch(title):
    f = CACHE / ("api_" + re.sub(r"[^A-Za-z0-9_.()-]", "_", title) + ".json")
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    r = requests.get(API, params={"action": "query", "prop": "revisions", "rvprop": "content",
                                  "rvslots": "main", "redirects": 1, "titles": title,
                                  "format": "json", "formatversion": 2}, headers=UA, timeout=60)
    page = r.json()["query"]["pages"][0]
    out = {"title": page["title"], "text": page["revisions"][0]["slots"]["main"]["content"]}
    CACHE.mkdir(exist_ok=True)
    f.write_text(json.dumps(out), encoding="utf-8")
    return out


def _unlink(s):
    s = re.sub(r"<ref[^>]*/>|<ref.*?</ref>|<ref[^>]*>.*$", "", s or "", flags=re.S)
    s = re.sub(r"\{\{(?:sortname|Sortname)\|([^|}]*)\|([^|}]*)(?:\|[^}]*)?\}\}", r"\1 \2", s)
    s = re.sub(r"\{\{sort\|[^|}]*\|([^}]*)\}\}", r"\1", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    return re.sub(r"\s+", " ", s.replace("''", "")).strip(" |")


def _date(s):
    m = re.search(r"\{\{(?:dts|Dts|DTS)\|(\d{4})\|(\d{1,2})\|(\d{1,2})", s or "")
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"\{\{(?:dts|Dts)\|([A-Za-z]+ \d{1,2}, \d{4})", s or "")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(m.group(1), fmt).date().isoformat() if m else None
        except ValueError:
            pass
    return None


def reigns(text):
    out = []
    for b in re.split(r"\{\{\s*PWtitlereign", text)[1:]:
        # Citations first: a cite's own "|date=" must not pass for the reign's.
        b = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", b, flags=re.S)
        # A template on one line runs its fields together ("|champion = X |date
        # = ..."), so each field ends where the next "|name =" begins.
        # Only marks at the template's own level count: "{{sortname||Edge|dab=
        # wrestler}}" has a "|dab=" of its own.
        depth, level = 0, []
        for i, ch in enumerate(b):
            if b.startswith("{{", i) or b.startswith("[[", i):
                depth += 1
            elif b.startswith("}}", i) or b.startswith("]]", i):
                depth -= 1
            level.append(depth)
        marks = [mk for mk in re.finditer(r"\|\s*(\w+)\s*=", b) if level[mk.start()] == 0]
        f = {}
        for n, mk in enumerate(marks):
            end = marks[n + 1].start() if n + 1 < len(marks) else len(b)
            f.setdefault(mk.group(1), b[mk.end():end].split("\n|")[0].strip())
        d = _date(f.get("date", ""))
        if d:
            out.append({"date": d, "champion": _unlink(f.get("champion", "")), "event": _unlink(f.get("event", "")),
                        "location": _unlink(f.get("location", "")), "notes": _unlink(f.get("notes", ""))})
    return out


if __name__ == "__main__":
    for t in sys.argv[1:]:
        p = fetch(t)
        rs = reigns(p["text"])
        print(p["title"], len(p["text"]), "templates:", len(rs))
        for r in rs[:3] + rs[-3:]:
            print("   ", r["date"], r["champion"][:50], "|", r["event"][:30])
